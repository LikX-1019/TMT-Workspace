# Backend Architecture

## Application Shape

The backend is a modular monolith under `backend/app`. It is one deployable unit, but each platform/business module owns its HTTP interface, DTOs, service rules, persistence model, repository queries, permission dependencies, and tests. First-party imports always start with `app`.

In Phase 1A, `departments`, `positions`, and `users` intentionally implement models, schemas, repositories, and services without `api.py` files or management routes. There is no authenticated administrator yet; exposing organization mutation routes before Phase 1B would violate the platform security boundary. Health routes remain the only public API surface.

```text
app/api/v1/router.py       # Router composition only
app/common/                # Response envelope, pagination, shared DTOs
app/core/                  # Settings, logging, exceptions, future security dependencies
app/db/                    # Engine, session, Base, mixins, model registry
app/modules/<module>/      # Vertical business/platform modules
app/integrations/<provider>/ # Isolated external adapters
backend/migrations/        # Alembic revisions
backend/tests/             # Backend test suite
```

## Request Flow

```text
FastAPI dependency graph
  -> API route
  -> authentication / workspace / action permission dependencies
  -> typed request schema
  -> application service
  -> repository and scoped SQLAlchemy query
  -> typed response schema
```

The API layer does not execute queries. Services do not depend on FastAPI request/response types. Repositories do not own other aggregates. Shared transaction behavior commits in `app.db.session.get_db_session` after successful request handling and rolls back on exceptions.

## Module Contract

A new backend module should expose:

```text
__init__.py
api.py          # Routes, status codes, dependency wiring
schemas.py      # Pydantic request/response DTOs
service.py      # Application rules and transaction intent
models.py       # SQLAlchemy tables
repository.py   # Persistence/query boundary
dependencies.py # Only when the module has reusable route dependencies
tests.py        # Or a mirror under backend/tests
```

Register a module router only when the module has an authenticated API contract; register model modules in `app/db/models.py`. Never wire one module directly to another module's private internals.

## Infrastructure Responsibilities

- **PostgreSQL** is the authoritative data store.
- **Redis** is reserved for cache, refresh-token/session revocation, rate limiting, locks, and future task coordination.
- **Alembic** owns all schema changes.
- **Ruff/MyPy/Pytest** are the backend correctness gate.
- **Docker Compose** supports local dependencies and integrated startup; it does not imply a production orchestration decision.

## Stability Rules

- Keep `/api/v1` contracts backward compatible.
- Keep permission checks and data scope in backend dependencies/services/repositories.
- Keep every module independently understandable.
- Keep configuration in `app.core.config`; do not scatter environment reads.
- Make new infrastructure optional until a phase requires it.
