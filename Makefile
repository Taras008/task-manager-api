.PHONY: up down logs migrate revision test lint

COMPOSE ?= docker compose

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f api

migrate:
	$(COMPOSE) run --rm migrate

revision:
	$(COMPOSE) run --rm migrate alembic revision --autogenerate -m "$(m)"

test:
	$(COMPOSE) up -d --wait db_test
	TEST_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/app_test uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
