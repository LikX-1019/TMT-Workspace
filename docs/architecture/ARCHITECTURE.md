# Architecture

## Architectural Style

TMT Workspace is a monorepo containing a Vue 3 console, a FastAPI modular monolith, durable architecture documents, and deployment assets. One deployable backend owns shared infrastructure and platform modules. Internal boundaries are designed so a future business capability can become a service only if measured load, ownership, or release independence actually requires it.

This is not a layered monolith where every table shares one giant service. Each business module owns its models, DTOs, services, repository logic, permissions, tests, and documentation. Cross-module calls are explicit public contracts.

## Runtime Overview

```text
Web / Mobile / Automation / Future AI
          |
          v
Vue 3 console
          |
          v
FastAPI ASGI application
          |
          v
Versioned API layer (/api/v1)
          |
          v
Application service layer
          |
          v
Domain rules + typed DTO/domain objects
          |
          v
Repository layer
          |
          v
SQLAlchemy 2.x AsyncSession
          |
          v
PostgreSQL
```

Redis is a supporting infrastructure component, not a second source of truth. It is reserved for cache, refresh-token/session revocation state, rate-limit/brute-force counters, distributed locks, and future task coordination after those features are introduced.

## Source Layout

```text
frontend/
  src/api/         # Typed HTTP contracts
  src/layouts/     # Application shell
  src/router/      # Static shell routes; protected routes remain contract-driven
  src/stores/      # Pinia state
  src/modules/     # System/public modules
  src/workspaces/  # Future department workspaces

backend/
  app/api/         # Versioned router composition only
  app/common/      # Response envelope and pagination
  app/core/        # Settings, security, logging, exceptions
  app/db/          # Declarative base, engine, session, model registry
  app/modules/     # Platform and business modules
  app/integrations/
  migrations/
  tests/

infra/             # Nginx and operational assets
docs/              # Architecture and policy documents
```

Future module template:

```text
backend/app/modules/<module>/
  __init__.py
  api.py
  schemas.py
  service.py
  models.py
  repository.py
  dependencies.py      # Only when reusable auth/permission dependencies are needed
  tests/               # Or mirrored under /tests
```

## Layer Contracts

### API layer

- Defines HTTP routes, status codes, and Pydantic request/response models.
- Injects current user, database session, service, and permission dependencies.
- Does not query the database or contain business policy.

### Service layer

- Owns application rules and transaction intent.
- Calls repositories and public contracts exposed by other modules.
- Enforces invariants and decides when an operation is auditable.
- Does not depend on FastAPI `Request` or render HTTP responses.

### Repository layer

- Owns SQLAlchemy query construction and persistence details.
- Accepts an `AsyncSession`.
- Returns ORM entities or typed projection rows.
- Encapsulates required tenant/workspace/data-scope query conditions.

### Domain

The project does not create a speculative rich domain-model layer. SQLAlchemy entities plus explicit service rules are sufficient until a behavior becomes complex enough to deserve independent domain objects.

## API Composition

Versioned routers are composed in `backend/app/api/v1/router.py`:

```python
api_router = APIRouter()
api_router.include_router(health_router)
```

The application mounts this under `/api/v1`. Adding a module router must not alter an existing route's meaning or response envelope.

## Configuration And Environments

Configuration is loaded through Pydantic Settings using the `TMT_` prefix. `.env` is for local developer convenience only; real secrets are supplied by the deployment environment.

Supported logical environments:

- `local`: developer workstation, permissive defaults allowed;
- `development`: shared development environment;
- `testing`: automated tests, isolated database/Redis state;
- `production`: hardened secrets, logging, CORS, and credential policy.

Phase 0 uses one settings class with environment differentiation rather than duplicate config modules.

## Data Ownership

Each module owns its tables. Foreign keys may reference another module's stable identifier, but the owning module is responsible for its table constraints and lifecycle. Cross-module reads should use a public service method or explicitly designed read model rather than reaching into private ORM internals.

For example, a future procurement module may reference `users.id` and `workspaces.id`, but it must not mutate user rows directly to express procurement state.

## Extension Points

### Business workspace modules

Future modules such as `backend/app/modules/operation` or `warehouse` register routes, permissions, and workspace/menu metadata through the same platform contracts as the system management area.

### Integrations

External systems (Amazon, Walmart, TikTok Shop, Shopify, ERP, OMS, WMS, enterprise messaging, calendars) belong under `backend/app/integrations/<provider>`. Integration credentials are configuration/platform-managed. Core identity and RBAC must not depend on any provider.

### AI and automation

Future `modules/ai` and `modules/automation` must consume the same authenticated API and permission layer as any other module. Model providers, prompt stores, vector stores, or agent frameworks must not leak into the RBAC or workspace core.

## Scalability Direction

The first scaling controls are:

- indexed PostgreSQL queries and explicit transaction scope;
- stateless API processes;
- Redis for volatile shared state;
- pagination on list endpoints;
- module-level ownership boundaries;
- audit and migration discipline.

Horizontal scaling of the FastAPI process is expected. Premature service extraction is not.
