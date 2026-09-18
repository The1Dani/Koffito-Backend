# Architecture

## Layers

Requests flow strictly downward. A layer never reaches past the one below it.

```
HTTP request
    │
    ▼
api/routes/*.py        FastAPI routers. Parse/validate input via Pydantic schemas,
    │                  translate service exceptions into HTTPException.
    ▼
api/deps.py            Dependency wiring: get_db → Session → Service.
    │
    ▼
services/*.py          Business rules. Raise domain exceptions (e.g. VenueNotFound).
    │                  "Routers call this, never the repository directly."
    ▼
repositories/*.py      Raw DB access. No validation, no business rules.
    │
    ▼
models/*.py            SQLAlchemy declarative models on the shared `Base`.
    │
    ▼
PostgreSQL / SQLite
```

`schemas/*.py` (Pydantic) sits beside the routes and defines the wire format. It is
deliberately separate from `models/*.py` (SQLAlchemy), which defines the table format.
`VenueOut` uses `ConfigDict(from_attributes=True)` so a route can return an ORM object
directly and FastAPI serialises it through the schema.

## Package layout

```
src/koffito/
├── __init__.py            exports `app`; `main()` runs uvicorn with reload (the
│                          `koffito` console script from pyproject.toml)
├── main.py                builds the FastAPI app, includes routers
├── db.py                  engine, SessionLocal, Base, get_db() dependency
├── api/
│   ├── deps.py            get_venue_service(db = Depends(get_db))
│   └── routes/
│       ├── root.py        GET /
│       └── venues.py      /venues router
├── models/                one module per table + enums.py
├── schemas/               Pydantic request/response models
├── services/              business logic + domain exceptions
└── repositories/          SQLAlchemy query code

alembic/
├── env.py                 wires DATABASE_URL + Base.metadata, auto-emits RLS ops
├── rls.py                 enable_rls() helper and the EnableRLS autogenerate op
└── versions/              migration scripts
```

## Database session handling

`db.py` builds one module-level `engine` from `DATABASE_URL` and a `sessionmaker`
bound to it. `get_db()` is a generator dependency: FastAPI opens a `Session` per
request and closes it in the `finally` block. Commits happen in the repository
(`self.db.commit()` followed by `refresh`), not at request teardown.

```python
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./koffito.db")
```

There is a `TODO` on that line — configuration is read straight from the environment
with no settings object, and how this should be handled is still open.

## Adding a new resource

To add, say, `events`, mirror the venue slice end to end:

1. `models/event.py` — already exists; the model is registered in `models/__init__.py`.
2. `schemas/event.py` — `EventCreate`, `EventOut`; export from `schemas/__init__.py`.
3. `repositories/event.py` — `EventRepository` with the queries; export it.
4. `services/event.py` — `EventService` + `EventNotFound`; export both.
5. `api/deps.py` — add `get_event_service`.
6. `api/routes/events.py` — the router, with `prefix="/events"` and `tags=["events"]`.
7. `main.py` — `app.include_router(events.router)`.

Each `__init__.py` re-exports its public names and keeps `__all__` sorted, so imports
elsewhere read `from ..services import EventService` rather than reaching into modules.
