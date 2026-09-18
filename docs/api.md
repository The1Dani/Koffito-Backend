# HTTP API

Base URL in local development: `http://127.0.0.1:8000`
Base URL under Docker Compose: `http://localhost:8000`

FastAPI serves interactive docs generated from the same route definitions:

- Swagger UI — `/docs`
- ReDoc — `/redoc`
- OpenAPI JSON — `/openapi.json`

There is **no authentication** on any endpoint yet. Every route below is open.

## Routers

| Router | Prefix | Tag | Source |
| --- | --- | --- | --- |
| root | — | — | `src/koffito/api/routes/root.py` |
| venues | `/venues` | `venues` | `src/koffito/api/routes/venues.py` |

---

## `GET /`

Health/liveness ping.

**Response `200`**

```json
{ "Hello": "Koffito" }
```

---

## `POST /venues`

Create a venue.

> Note the path has no trailing slash — the router uses `@router.post("")`, so the
> endpoint is exactly `/venues`. `POST /venues/` will redirect.

**Request body** — `VenueCreate`

| Field | Type | Required | Validation |
| --- | --- | --- | --- |
| `name` | string | yes | |
| `address` | string | yes | |
| `maps_url` | string \| null | no (default `null`) | |
| `capacity` | integer | yes | must be `> 0` |

```json
{
  "name": "Café Central",
  "address": "Str. Ismail 33, Chișinău",
  "maps_url": "https://maps.google.com/?q=...",
  "capacity": 24
}
```

**Response `200`** — `VenueOut`

```json
{
  "id": "0f6a2c3e-5b41-4e9a-9d6e-3f1b2c4d5e6f",
  "name": "Café Central",
  "address": "Str. Ismail 33, Chișinău",
  "maps_url": "https://maps.google.com/?q=...",
  "capacity": 24,
  "is_active": true,
  "created_at": "2026-09-18T09:31:04.512Z"
}
```

`is_active` and `created_at` are set by the database, not by the request.

**Response `422`** — Pydantic validation error (missing field, `capacity <= 0`, …).

---

## `GET /venues`

List **active** venues only — the repository filters on `is_active`, so soft-disabled
venues never appear here and there is currently no way to list them over HTTP.

No query parameters: no pagination, filtering or sorting.

**Response `200`** — `list[VenueOut]`

```json
[
  {
    "id": "0f6a2c3e-5b41-4e9a-9d6e-3f1b2c4d5e6f",
    "name": "Café Central",
    "address": "Str. Ismail 33, Chișinău",
    "maps_url": null,
    "capacity": 24,
    "is_active": true,
    "created_at": "2026-09-18T09:31:04.512Z"
  }
]
```

---

## `GET /venues/{venue_id}`

Fetch a single venue by id. Unlike the list endpoint this returns inactive venues too.

**Path parameter**

| Name | Type | Notes |
| --- | --- | --- |
| `venue_id` | UUID | malformed UUIDs are rejected with `422` before the handler runs |

**Response `200`** — `VenueOut`

**Response `404`**

```json
{ "detail": "Venue not found" }
```

The service raises the domain exception `VenueNotFound`; the route catches it and
converts it to the `HTTPException`. Domain exceptions never leak past the route layer.

> The `404` is raised at runtime but is not declared on the route, so it does not
> appear in `/openapi.json` — the generated schema lists only `200` and `422`. Passing
> `responses={404: ...}` to the decorator would document it for clients.

---

## Not yet exposed

The schema covers profiles, events, groups, event participants, surveys, reports and
admins ([database.md](database.md)), but none of them have routes, schemas, services or
repositories yet. `src/koffito/api/deps.py` wires exactly one service,
`get_venue_service`. See [architecture.md](architecture.md#adding-a-new-resource) for
the slice to replicate when adding one.
