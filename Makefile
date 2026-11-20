.PHONY: up down clean logs migrate revision test lint

COMPOSE ?= docker compose
# Порт тестової БД на хості (змініть, якщо 5433 зайнятий): TEST_DB_PORT=5434 make test
TEST_DB_PORT ?= 5433
export TEST_DB_PORT

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) --profile test down

# Зупиняє стек і видаляє томи (БД). Лише для цього compose-проєкту.
clean:
	$(COMPOSE) --profile test down -v

logs:
	$(COMPOSE) logs -f api

migrate:
	$(COMPOSE) run --rm migrate

revision:
	$(COMPOSE) run --rm migrate alembic revision --autogenerate -m "$(m)"

test:
	$(COMPOSE) up -d --wait db_test
	TEST_DATABASE_URL=postgresql+asyncpg://app:app@localhost:$(TEST_DB_PORT)/app_test uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
