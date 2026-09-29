.PHONY: install install-backend install-frontend api web lint lint-backend lint-frontend typecheck test test-db test-integration check compose-up compose-down revision migrate

install: install-backend install-frontend

install-backend:
	uv sync --project backend --group dev

install-frontend:
	npm --prefix frontend install

api:
	uv run --directory backend uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

web:
	npm --prefix frontend run dev

lint: lint-backend lint-frontend

lint-backend:
	uv run --directory backend ruff format --check .
	uv run --directory backend ruff check .

lint-frontend:
	npm --prefix frontend run build

typecheck:
	uv run --directory backend mypy

test:
	uv run --directory backend pytest

test-db:
	TMT_SECRET_KEY=$${TMT_SECRET_KEY:-local-compose-only} bash infra/scripts/create-postgres-test-db.sh

test-integration: test-db
	TMT_ENVIRONMENT=testing \
	TMT_DATABASE_URL=postgresql+asyncpg://tmt:tmt_change_me@localhost:5432/tmt_workspace_test \
	TMT_TEST_DATABASE_URL=postgresql+asyncpg://tmt:tmt_change_me@localhost:5432/tmt_workspace_test \
	uv run --directory backend pytest -m postgres

check: lint-backend typecheck test lint-frontend

compose-up:
	docker compose up -d

compose-down:
	docker compose down

revision:
	uv run --directory backend alembic revision --autogenerate -m "$(m)"

migrate:
	uv run --directory backend alembic upgrade head
