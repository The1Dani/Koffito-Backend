# Graph Report - Koffito-Backend  (2026-11-25)

## Corpus Check
- Corpus is ~1,028 words - fits in a single context window. You may not need a graph.

## Summary
- 117 nodes · 177 edges · 10 communities (6 shown, 4 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 8 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Alembic Migrations
- Compose Services
- Schemas & Pydantic
- SQLAlchemy Models/Repos
- Item Service & Routes
- DB Session & Deps
- Compose Env & Healthcheck
- FastAPI App Root
- Community 8

## God Nodes (most connected - your core abstractions)
1. `ItemService` - 13 edges
2. `Item` - 9 edges
3. `ItemRepository` - 9 edges
4. `EnableRLS` - 6 edges
5. `db` - 6 edges
6. `healthcheck` - 6 edges
7. `db-migrate` - 6 edges
8. `ItemNotFound` - 6 edges
9. `process_revision_directives()` - 5 edges
10. `app` - 5 edges

## Surprising Connections (you probably didn't know these)
- `get_item_service()` --calls--> `ItemService`  [EXTRACTED]
  src/koffito/api/deps.py → src/koffito/services/item.py
- `create_item()` --references--> `ItemService`  [EXTRACTED]
  src/koffito/api/routes/items.py → src/koffito/services/item.py
- `Item` --inherits--> `Base`  [EXTRACTED]
  src/koffito/models/item.py → src/koffito/db.py
- `process_revision_directives()` --calls--> `EnableRLS`  [EXTRACTED]
  alembic/env.py → alembic/rls.py
- `upgrade()` --calls--> `enable_rls()`  [EXTRACTED]
  alembic/versions/f71714a4b376_creatae_items_table.py → alembic/rls.py

## Import Cycles
- None detected.

## Communities (10 total, 4 thin omitted)

### Community 0 - "Alembic Migrations"
Cohesion: 0.12
Nodes (7): process_revision_directives(), run_migrations_offline(), run_migrations_online(), enable_rls(), EnableRLS, _render_enable_rls(), upgrade()

### Community 1 - "Compose Services"
Cohesion: 0.11
Nodes (19): build, depends_on, environment, ports, condition, build, command, condition (+11 more)

### Community 2 - "Schemas & Pydantic"
Cohesion: 0.20
Nodes (5): create_item(), ItemCreate, ItemOut, Config, ItemNotFound

### Community 4 - "Item Service & Routes"
Cohesion: 0.29
Nodes (4): list_items(), read_item(), Item, ItemService

### Community 5 - "DB Session & Deps"
Cohesion: 0.20
Nodes (3): get_item_service(), Base, get_db()

### Community 6 - "Compose Env & Healthcheck"
Cohesion: 0.18
Nodes (11): env_file, healthcheck, image, ports, volumes, interval, retries, start_period (+3 more)

## Knowledge Gaps
- **1 isolated node(s):** `koffito`
  These have ≤1 connection - possible missing edges. (Counts symbols only; 52 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ItemService` connect `Item Service & Routes` to `Schemas & Pydantic`, `SQLAlchemy Models/Repos`, `DB Session & Deps`?**
  _High betweenness centrality (0.074) - this node is a cross-community bridge._
- **What connects `koffito` to the rest of the system?**
  _1 weakly-connected nodes found - possible missing edges._
- **Should `Alembic Migrations` be split into smaller, more focused modules?**
  _Cohesion score 0.11594202898550725 - nodes in this community are weakly interconnected._
- **Why does `ItemRepository` connect `SQLAlchemy Models/Repos` to `Item Service & Routes`?**
  _High betweenness centrality (0.044) - this node is a cross-community bridge._
- **Should `Compose Services` be split into smaller, more focused modules?**
  _Cohesion score 0.10526315789473684 - nodes in this community are weakly interconnected._
- **Why does `services` connect `Compose Services` to `Compose Env & Healthcheck`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._