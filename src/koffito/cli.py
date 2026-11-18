"""Admin tasks that are deliberately not in the API.

python -m koffito.cli make-admin <email>     give an account admin rights
python -m koffito.cli revoke-admin <email>   take them away
python -m koffito.cli seed                   cafés + upcoming coffee talks for a fresh database
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from .core.config import Settings

SEED = Path(__file__).resolve().parents[2] / "db" / "seed"

# Upcoming coffee talks the seed creates: (days from today, hour, minute).
SEED_EVENTS = [(1, 18, 0), (2, 11, 0), (3, 15, 0), (5, 17, 0), (6, 10, 0), (8, 18, 30), (10, 12, 0)]


def _set_admin(dsn: str, email: str, value: bool) -> int:
    with psycopg.connect(dsn) as conn:
        cur = conn.execute(
            """
            update public.profiles p set is_admin = %s
            from public.users u where u.id = p.id and u.email = %s
            """,
            [value, email.strip().lower()],
        )
        if cur.rowcount == 0:
            print(f"no account for {email}")
            return 1
    print(f"{email}: admin = {value}")
    return 0


def _seed(dsn: str) -> int:
    venues = json.loads((SEED / "venues.json").read_text(encoding="utf-8"))
    with psycopg.connect(dsn) as conn:
        if conn.execute("select exists (select 1 from public.venues)").fetchone()[0]:  # type: ignore[index]
            print("venues already present; skipping seed")
            return 0
        ids = []
        for v in venues:
            row = conn.execute(
                """
                insert into public.venues
                  (name, description, photo_url, address, website, phone, rating, popular_times)
                values (%s, %s, %s, %s, %s, %s, %s, %s) returning id
                """,
                [
                    v["name"],
                    v["description"],
                    v["photo_url"],
                    v["address"],
                    v["website"],
                    v["phone"],
                    v["rating"],
                    v["popular_times"],
                ],
            ).fetchone()
            ids.append(row[0])  # type: ignore[index]
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        for index, (days, hour, minute) in enumerate(SEED_EVENTS):
            # Times are Chișinău local (UTC+2); the café stays hidden until 24h before.
            event_at = today + timedelta(days=days, hours=hour - 2, minutes=minute)
            conn.execute(
                """
                insert into public.events (event_at, default_venue_id, status, target_group_size)
                values (%s, %s, 'open', 4)
                """,
                [event_at, ids[index % len(ids)]],
            )
    print(f"seeded {len(venues)} venues and {len(SEED_EVENTS)} events")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    dsn = Settings().database_url.get_secret_value()
    if len(args) == 2 and args[0] in ("make-admin", "revoke-admin"):
        return _set_admin(dsn, args[1], args[0] == "make-admin")
    if args == ["seed"]:
        return _seed(dsn)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
