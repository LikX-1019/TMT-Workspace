.PHONY: install dev lint typecheck test check run compose-up compose-down revision migrate

install:
	uv sync --group dev

dev:
	uv run uvicorn tmt_workspace.main:app --reload --host 0.0.0.0 --port 8000

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy

test:
	uv run pytest

check: lint typecheck test

compose-up:
	docker compose up -d

compose-down:
	docker compose down

revision:
	uv run alembic revision --autogenerate -m "$(m)"

migrate:
	uv run alembic upgrade head

