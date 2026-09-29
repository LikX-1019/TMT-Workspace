# TMT Workspace Backend

FastAPI modular monolith for the TMT Workspace platform. See the root
[README](../README.md) and [AGENTS.md](../AGENTS.md) before changing this
directory.

```bash
uv sync --group dev
cp .env.example .env
docker compose --project-directory .. up -d postgres redis
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Validation:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

