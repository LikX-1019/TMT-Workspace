# TMT Workspace

TMT Workspace is the company-internal enterprise workstation monorepo. It starts with a FastAPI modular monolith and a Vue 3 console foundation around identity, organization, RBAC, workspace navigation, announcements, audit, and platform infrastructure. Department-specific business systems will be added as decoupled workspace modules later.

Phase 0 establishes the repository contract and engineering foundation. It does not implement user, role, workspace, or announcement CRUD.

## Product Stack

- Python 3.12+
- FastAPI
- SQLAlchemy 2.x (async)
- Pydantic v2
- Alembic
- PostgreSQL 16
- Redis 7
- Ruff, MyPy, Pytest
- Vue 3, TypeScript, Vite, Pinia, Vue Router, Element Plus

## Repository Layout

```text
frontend/          # Vue 3 + TypeScript workstation console
backend/           # FastAPI + SQLAlchemy modular monolith
docs/              # Product, architecture, security, database, API, development docs
infra/             # Nginx and operational assets
.github/           # CI
```

## Configuration Contract

Backend environment variables use the `TMT_` prefix (`TMT_DATABASE_URL`, `TMT_REDIS_URL`, `TMT_SECRET_KEY`). Local and testing environments may use the development fallback secret. `development` and `production` require an explicit `TMT_SECRET_KEY`; placeholder values fail closed.

The Docker Compose backend runs with `TMT_ENVIRONMENT=development`, so it requires a real non-placeholder `TMT_SECRET_KEY` in the root environment before startup.

## Quick Start

### 1. Create dependencies

```bash
make install
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

### 2. Start local dependencies

```bash
make compose-up
```

### 3. Apply migrations

After the first model migration is introduced:

```bash
make migrate
```

### 4. Run services

```bash
make api
```

In another terminal:

```bash
make web
```

Useful URLs:

- API root health: http://localhost:8000/api/v1/health
- Readiness: http://localhost:8000/api/v1/health/ready
- OpenAPI: http://localhost:8000/api/openapi.json
- Swagger UI: http://localhost:8000/api/docs
- Console: http://localhost:5173

## Validation

```bash
make check
```

## Repository Contract

Read [AGENTS.md](AGENTS.md) before changing source code. It defines module boundaries, dependency direction, FastAPI/SQLAlchemy conventions, security rules, and the validation required from every contributor.

Phase 0 documentation lives under [docs](docs/README.md).
