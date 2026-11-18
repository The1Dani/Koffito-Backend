"""Postgres access for the whole backend (replaces the old Supabase/PostgREST client).

The method names (`rpc`, `select`, `insert`, `update`, `delete`) and the small filter syntax
(`("column", "op.value")`) are the ones the repositories, services and jobs already used, so
they did not have to change. Underneath, everything is plain SQL with bound parameters:

* identifiers (tables, columns, functions) must match a strict pattern and are quoted with
  `psycopg.sql.Identifier`, so they can never carry SQL;
* every value is sent as a parameter, never formatted into the query.

Each call runs in its own transaction. `UserAuth(user_id)` sets `app.user_id` for that
transaction, which the SQL functions read via `app.uid()` to decide what the user may see/do.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .errors import DatabaseError, DatabaseUnavailable


@dataclass(frozen=True, slots=True)
class UserAuth:
    """Act as the signed-in user: SQL functions see their id through `app.uid()`."""

    user_id: UUID


@dataclass(frozen=True, slots=True)
class ServiceAuth:
    """Act as the backend itself (background jobs, auth bookkeeping): no user."""


Auth = UserAuth | ServiceAuth
Filter = tuple[str, str]  # ("column", "op.value"), e.g. ("id", "eq.<uuid>")


@dataclass(frozen=True, slots=True)
class Page:
    items: list[dict[str, Any]]
    total: int


_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_OPS = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _ident(name: str) -> sql.Identifier:
    if not _IDENT.match(name):
        raise ValueError(f"invalid identifier: {name!r}")
    return sql.Identifier(name)


def _columns(columns: str | None) -> sql.Composable:
    if not columns or columns.strip() == "*":
        return sql.SQL("*")
    return sql.SQL(", ").join(_ident(c.strip()) for c in columns.split(","))


def _where(filters: Sequence[Filter]) -> tuple[sql.Composable, list[Any]]:
    """PostgREST-style filters → `where` clause + params. Supports eq/neq/gt/gte/lt/lte,
    in.(a,b) and is.null / is.true / is.false — everything the codebase uses."""
    parts: list[sql.Composable] = []
    params: list[Any] = []
    for column, expr in filters:
        col = _ident(column)
        op, _, value = expr.partition(".")
        if op in _OPS:
            parts.append(sql.SQL("{} {} %s").format(col, sql.SQL(_OPS[op])))
            params.append(_coerce(value))
        elif op == "in":
            items = [v.strip() for v in value.strip("()").split(",") if v.strip()]
            parts.append(sql.SQL("{}::text = any(%s)").format(col))
            params.append(items)
        elif op == "is" and value in ("null", "true", "false"):
            parts.append(sql.SQL("{} is {}").format(col, sql.SQL(value)))
        else:
            raise ValueError(f"unsupported filter: {column}={expr}")
    if not parts:
        return sql.SQL(""), params
    return sql.SQL(" where ") + sql.SQL(" and ").join(parts), params


def _coerce(value: str) -> Any:
    if value in ("true", "false"):
        return value == "true"
    return value


def _order(order: str | None) -> sql.Composable:
    if not order:
        return sql.SQL("")
    parts = []
    for item in order.split(","):
        column, _, direction = item.strip().partition(".")
        direction = direction or "asc"
        if direction not in ("asc", "desc"):
            raise ValueError(f"invalid order: {order!r}")
        parts.append(sql.SQL("{} {}").format(_ident(column), sql.SQL(direction)))
    return sql.SQL(" order by ") + sql.SQL(", ").join(parts)


def _page(limit: int | None, offset: int | None) -> tuple[sql.Composable, list[Any]]:
    clause, params = sql.SQL(""), []
    if limit is not None:
        clause += sql.SQL(" limit %s")
        params.append(int(limit))
    if offset is not None:
        clause += sql.SQL(" offset %s")
        params.append(int(offset))
    return clause, params


def _adapt(value: Any) -> Any:
    """Objects (and lists of objects) go to Postgres as jsonb; plain lists stay arrays
    (`text[]` languages, `smallint[]` popular times)."""
    if isinstance(value, dict) or (
        isinstance(value, list) and any(isinstance(v, dict) for v in value)
    ):
        return Jsonb(value)
    return value


def _plain(value: Any) -> Any:
    """Rows come back as JSON-friendly values, like they did from the REST API."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: _plain(v) for k, v in row.items()}


class Database:
    """Async connection pool + the handful of operations the app needs."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 10, timeout: float = 10.0):
        self._pool = AsyncConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            open=False,
            kwargs={"row_factory": dict_row, "autocommit": False},
        )
        self._fn_cache: dict[str, tuple[bool, str]] = {}

    async def open(self) -> None:
        await self._pool.open(wait=True)

    async def close(self) -> None:
        await self._pool.close()

    # --- raw SQL (fixed statements only; values always as parameters) -------------------------

    async def fetch(
        self,
        query: str | sql.Composable,
        params: Sequence[Any] | Mapping[str, Any] = (),
        *,
        auth: Auth,
    ) -> list[dict[str, Any]]:
        async with self._tx(auth) as cur:
            await cur.execute(query, params)  # type: ignore[arg-type]
            return [_row(r) for r in await cur.fetchall()] if cur.description else []

    async def fetchrow(
        self,
        query: str | sql.Composable,
        params: Sequence[Any] | Mapping[str, Any] = (),
        *,
        auth: Auth,
    ) -> dict[str, Any] | None:
        rows = await self.fetch(query, params, auth=auth)
        return rows[0] if rows else None

    # --- the old client's API ------------------------------------------------------------------

    async def rpc(
        self,
        fn: str,
        params: Mapping[str, Any] | None = None,
        *,
        auth: Auth,
        filters: Sequence[Filter] = (),
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        count: bool = False,
        single: bool = False,
    ) -> Any:
        params = dict(params or {})
        args = sql.SQL(", ").join(sql.SQL("{} => %s").format(_ident(name)) for name in params)
        values = [_adapt(v) for v in params.values()]
        returns_set, kind = await self._function_kind(fn)
        call = sql.SQL("public.{}({})").format(_ident(fn), args)

        if not returns_set:
            row = await self.fetchrow(
                sql.SQL("select {} as result").format(call), values, auth=auth
            )
            result = None if row is None else row["result"]
            if single and result is None:
                raise DatabaseError(404, "not_found", "no rows")
            return result

        where, wparams = _where(filters)
        page, pparams = _page(limit, offset)
        source = (
            sql.SQL("select t.* from {} as t").format(call)
            if kind == "record"
            else sql.SQL("select t as value from {} as t").format(call)
        )
        query = sql.SQL("select * from ({}) as q{}{}{}").format(source, where, _order(order), page)
        rows = await self.fetch(query, [*values, *wparams, *pparams], auth=auth)
        items = self._shape(rows, kind, single=single)
        if not count:
            return items
        counted = sql.SQL("select count(*) as n from ({}) as q{}").format(source, where)
        total = await self.fetchrow(counted, [*values, *wparams], auth=auth)
        return Page(items, total["n"] if total else 0)

    async def select(
        self,
        table: str,
        *,
        auth: Auth,
        columns: str = "*",
        filters: Sequence[Filter] = (),
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        single: bool = False,
        count: bool = False,
    ) -> Any:
        where, wparams = _where(filters)
        page, pparams = _page(limit, offset)
        query = sql.SQL("select {} from public.{}{}{}{}").format(
            _columns(columns), _ident(table), where, _order(order), page
        )
        rows = await self.fetch(query, [*wparams, *pparams], auth=auth)
        items = self._shape(rows, "record", single=single)
        if not count:
            return items
        # Counted separately: a page past the end still reports the real total.
        counted = sql.SQL("select count(*) as n from public.{}{}").format(_ident(table), where)
        total = await self.fetchrow(counted, wparams, auth=auth)
        return Page(items, total["n"] if total else 0)

    async def insert(
        self,
        table: str,
        rows: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        auth: Auth,
        columns: str | None = None,
        upsert_on: str | None = None,
        returning: bool = True,
    ) -> Any:
        batch = [dict(rows)] if isinstance(rows, Mapping) else [dict(r) for r in rows]
        if not batch:
            return []
        keys = list(batch[0])
        values = sql.SQL(", ").join(
            sql.SQL("({})").format(sql.SQL(", ").join(sql.Placeholder() for _ in keys))
            for _ in batch
        )
        query = sql.SQL("insert into public.{} ({}) values {}").format(
            _ident(table), sql.SQL(", ").join(_ident(k) for k in keys), values
        )
        if upsert_on:
            conflict = [c.strip() for c in upsert_on.split(",")]
            updates = [k for k in keys if k not in conflict]
            query += sql.SQL(" on conflict ({}) do update set {}").format(
                sql.SQL(", ").join(_ident(c) for c in conflict),
                sql.SQL(", ").join(
                    sql.SQL("{} = excluded.{}").format(_ident(k), _ident(k)) for k in updates
                ),
            )
        if returning:
            query += sql.SQL(" returning {}").format(_columns(columns))
        params = [_adapt(row[k]) for row in batch for k in keys]
        result = await self.fetch(query, params, auth=auth)
        return result if returning else None

    async def update(
        self,
        table: str,
        values: Mapping[str, Any],
        *,
        auth: Auth,
        filters: Sequence[Filter],
        columns: str | None = None,
        returning: bool = True,
    ) -> Any:
        if not filters:
            raise ValueError("update requires at least one filter")
        sets = sql.SQL(", ").join(sql.SQL("{} = %s").format(_ident(k)) for k in values)
        where, wparams = _where(filters)
        query = sql.SQL("update public.{} set {}{}").format(_ident(table), sets, where)
        if returning:
            query += sql.SQL(" returning {}").format(_columns(columns))
        result = await self.fetch(
            query, [*(_adapt(v) for v in values.values()), *wparams], auth=auth
        )
        return result if returning else None

    # --- internals -----------------------------------------------------------------------------

    def _tx(self, auth: Auth):
        return _Transaction(self._pool, auth)

    async def _function_kind(self, fn: str) -> tuple[bool, str]:
        """(returns a set?, 'record' for table rows | 'scalar') — looked up once per function."""
        if fn not in self._fn_cache:
            row = await self.fetchrow(
                """
                select p.proretset as returns_set,
                       (t.typtype = 'c' or p.prorettype = 'record'::regtype) as is_record
                from pg_proc p
                join pg_namespace n on n.oid = p.pronamespace
                join pg_type t on t.oid = p.prorettype
                where n.nspname = 'public' and p.proname = %s
                limit 1
                """,
                [fn],
                auth=ServiceAuth(),
            )
            if row is None:
                raise DatabaseError(404, "42883", f"function {fn} does not exist")
            self._fn_cache[fn] = (row["returns_set"], "record" if row["is_record"] else "scalar")
        return self._fn_cache[fn]

    @staticmethod
    def _shape(rows: list[dict[str, Any]], kind: str, *, single: bool) -> Any:
        items = rows if kind == "record" else [r["value"] for r in rows]
        if single:
            if len(items) != 1:
                raise DatabaseError(404, "not_found", "expected exactly one row")
            return items[0]
        return items


class _Transaction:
    """`async with` → a cursor inside a transaction with `app.user_id` set (or cleared)."""

    def __init__(self, pool: AsyncConnectionPool, auth: Auth) -> None:
        self._pool = pool
        self._auth = auth
        self._ctx: Any = None

    async def __aenter__(self) -> psycopg.AsyncCursor[Any]:
        try:
            self._ctx = self._pool.connection()
            conn = await self._ctx.__aenter__()
        except psycopg.OperationalError as exc:
            raise DatabaseUnavailable(str(exc)) from exc
        except Exception as exc:  # pool timeout
            if type(exc).__name__ == "PoolTimeout":
                raise DatabaseUnavailable(str(exc)) from exc
            raise
        self._cur = conn.cursor()
        user_id = str(self._auth.user_id) if isinstance(self._auth, UserAuth) else ""
        # `true` = local to this transaction, so it can never leak to the next request.
        await self._cur.execute("select set_config('app.user_id', %s, true)", [user_id])
        return self._cur

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            await self._ctx.__aexit__(exc_type, exc, tb)  # commits, or rolls back on error
        finally:
            if isinstance(exc, psycopg.Error) and not isinstance(exc, psycopg.OperationalError):
                raise DatabaseError.from_psycopg(exc) from exc
            if isinstance(exc, psycopg.OperationalError):
                raise DatabaseUnavailable(str(exc)) from exc
