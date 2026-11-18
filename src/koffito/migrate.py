"""Apply `db/migrations/*.sql` in name order, once each: `python -m koffito.migrate`.

Applied files are recorded (with their SHA-256) in `public.schema_migrations`; a file that
changed after it was applied is an error — add a new migration instead of editing an old one.
"""

import hashlib
import sys
from pathlib import Path

import psycopg

from .core.config import Settings

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"


def migrate(dsn: str, directory: Path = MIGRATIONS) -> list[str]:
    applied_now: list[str] = []
    with psycopg.connect(dsn, autocommit=False) as conn:
        conn.execute(
            """
            create table if not exists public.schema_migrations (
              name text primary key,
              sha256 text not null,
              applied_at timestamptz not null default now()
            )
            """
        )
        # One migrator at a time (two app containers starting together).
        conn.execute("select pg_advisory_xact_lock(hashtext('koffito.migrate'))")
        done = dict(conn.execute("select name, sha256 from public.schema_migrations").fetchall())
        for path in sorted(directory.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if path.name in done:
                if done[path.name] != digest:
                    raise RuntimeError(f"{path.name} changed after it was applied")
                continue
            conn.execute(sql)  # type: ignore[arg-type]
            conn.execute(
                "insert into public.schema_migrations (name, sha256) values (%s, %s)",
                [path.name, digest],
            )
            applied_now.append(path.name)
        conn.commit()
    return applied_now


def main() -> int:
    applied = migrate(Settings().database_url.get_secret_value())
    print("applied: " + (", ".join(applied) if applied else "nothing new"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
