from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from .errors import SupabaseError, SupabaseUnavailable


@dataclass(frozen=True, slots=True)
class UserAuth:
    """Act as the signed-in user: their JWT goes to PostgREST, so RLS applies."""

    token: str


@dataclass(frozen=True, slots=True)
class ServiceAuth:
    """Act as the backend itself (system jobs only): service-role key, bypasses RLS."""


Auth = UserAuth | ServiceAuth
Filter = tuple[str, str]  # ("column", "op.value"), e.g. ("id", "eq.<uuid>")


@dataclass(frozen=True, slots=True)
class Page:
    items: list[dict[str, Any]]
    total: int


class SupabaseRest:
    """Thin PostgREST client over one shared `httpx.AsyncClient`.

    Every call names its `auth`: `UserAuth(token)` for anything done on behalf of a user,
    `ServiceAuth()` for background jobs. The backend gate header is always attached; user
    requests use the publishable key, service requests the service-role key.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        rest_url: str,
        publishable_key: str,
        service_key: str | None,
        backend_key: str,
    ) -> None:
        self._http = http
        self._rest_url = rest_url.rstrip("/")
        self._publishable_key = publishable_key
        self._service_key = service_key
        self._backend_key = backend_key

    # --- public API -----------------------------------------------------------------------

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
        query = self._query(None, filters, order, limit, offset)
        return await self._request(
            "POST",
            f"/rpc/{fn}",
            auth=auth,
            params=query,
            json=dict(params or {}),
            prefer=["count=exact"] if count else [],
            single=single,
            count=count,
        )

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
        query = self._query(columns, filters, order, limit, offset)
        return await self._request(
            "GET",
            f"/{table}",
            auth=auth,
            params=query,
            json=None,
            prefer=["count=exact"] if count else [],
            single=single,
            count=count,
        )

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
        query = self._query(columns, (), None, None, None)
        prefer: list[str] = []
        if upsert_on:
            prefer.append("resolution=merge-duplicates")
            query.append(("on_conflict", upsert_on))
        prefer.append("return=representation" if returning else "return=minimal")
        body = dict(rows) if isinstance(rows, Mapping) else [dict(r) for r in rows]
        return await self._request(
            "POST", f"/{table}", auth=auth, params=query, json=body, prefer=prefer
        )

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
        self._require_filters(filters)
        query = self._query(columns, filters, None, None, None)
        prefer = ["return=representation" if returning else "return=minimal"]
        return await self._request(
            "PATCH", f"/{table}", auth=auth, params=query, json=dict(values), prefer=prefer
        )

    async def delete(
        self,
        table: str,
        *,
        auth: Auth,
        filters: Sequence[Filter],
        returning: bool = False,
    ) -> Any:
        self._require_filters(filters)
        query = self._query(None, filters, None, None, None)
        prefer = ["return=representation" if returning else "return=minimal"]
        return await self._request(
            "DELETE", f"/{table}", auth=auth, params=query, json=None, prefer=prefer
        )

    # --- internals ------------------------------------------------------------------------

    @staticmethod
    def _require_filters(filters: Sequence[Filter]) -> None:
        if not filters:
            # PostgREST (safeupdate) would refuse too; fail here with a clearer message.
            raise ValueError("update/delete require at least one entry in filters")

    @staticmethod
    def _query(
        columns: str | None,
        filters: Sequence[Filter],
        order: str | None,
        limit: int | None,
        offset: int | None,
    ) -> list[tuple[str, str]]:
        query: list[tuple[str, str]] = []
        if columns:
            query.append(("select", columns))
        query.extend(filters)
        if order:
            query.append(("order", order))
        if limit is not None:
            query.append(("limit", str(limit)))
        if offset is not None:
            query.append(("offset", str(offset)))
        return query

    def _headers(self, auth: Auth, prefer: Sequence[str], single: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.pgrst.object+json" if single else "application/json",
            "X-Koffito-Backend-Key": self._backend_key,
        }
        if isinstance(auth, UserAuth):
            headers["apikey"] = self._publishable_key
            headers["Authorization"] = f"Bearer {auth.token}"
        else:
            if not self._service_key:
                raise RuntimeError(
                    "SUPABASE_SERVICE_ROLE_KEY is not configured; service requests are disabled"
                )
            headers["apikey"] = self._service_key
            # New-style `sb_secret_...` keys are complete on their own; legacy service keys are
            # JWTs that PostgREST expects in the Authorization header as well.
            if not self._service_key.startswith("sb_secret_"):
                headers["Authorization"] = f"Bearer {self._service_key}"
        if prefer:
            headers["Prefer"] = ",".join(prefer)
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        auth: Auth,
        params: list[tuple[str, str]],
        json: Any,
        prefer: Sequence[str],
        single: bool = False,
        count: bool = False,
    ) -> Any:
        headers = self._headers(auth, prefer, single)
        try:
            response = await self._http.request(
                method,
                f"{self._rest_url}{path}",
                params=params or None,
                json=json,
                headers=headers,
            )
        except httpx.TransportError as exc:  # connection errors and timeouts
            raise SupabaseUnavailable(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code >= 400:
            raise self._error(response)
        if response.status_code == 204 or not response.content:
            return Page([], 0) if count else None
        data = response.json()
        if count:
            return Page(data, self._total(response, data))
        return data

    @staticmethod
    def _total(response: httpx.Response, data: Any) -> int:
        content_range = response.headers.get("Content-Range", "")
        _, _, total = content_range.partition("/")
        if total.isdigit():
            return int(total)
        return len(data) if isinstance(data, list) else 0

    @staticmethod
    def _error(response: httpx.Response) -> SupabaseError:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            return SupabaseError(
                response.status_code,
                payload.get("code"),
                str(payload.get("message") or response.reason_phrase),
                payload.get("details"),
                payload.get("hint"),
            )
        return SupabaseError(response.status_code, None, response.text or response.reason_phrase)
