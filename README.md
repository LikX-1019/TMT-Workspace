# TMT Workspace

TMT Workspace is the company-internal enterprise workstation foundation. It intentionally starts as a modular monolith built around identity, organization, RBAC, workspace navigation, announcements, audit, and platform infrastructure. Department-specific business systems will be added as decoupled workspace modules later.

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

## Quick Start

### 1. Create dependencies

```bash
make install
cp .env.example .env
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

### 4. Run the API

```bash
make dev
```

Useful URLs:

- API root health: http://localhost:8000/api/v1/health
- Readiness: http://localhost:8000/api/v1/health/ready
- OpenAPI: http://localhost:8000/api/openapi.json
- Swagger UI: http://localhost:8000/api/docs

## Validation

```bash
make check
```

## Repository Contract

Read [AGENTS.md](AGENTS.md) before changing source code. It defines module boundaries, dependency direction, FastAPI/SQLAlchemy conventions, security rules, and the validation required from every contributor.

Phase 0 documentation lives under [docs](docs/README.md).

