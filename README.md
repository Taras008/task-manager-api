# Task Management API

FastAPI + PostgreSQL 16 + SQLAlchemy 2.0 (async) + Alembic. Повний опис, ендпоінти й діаграма
статусів з'являться в фінальному етапі; нижче — запуск і довідка по командах.

## Запуск

```bash
make up        # збирає образ, піднімає db, migrate (one-shot), api, scheduler
make logs      # логи api
make down      # зупинити стек (дані БД зберігаються)
make clean     # зупинити стек І видалити томи (docker compose down -v) — БД буде порожня
```

API: http://localhost:8000 (Swagger: `/docs`), healthcheck: `GET /health`.

> Увага: `make down -v` не працює — `-v` перехоплює сам make. Для видалення томів
> використовуйте `make clean`.

### Якщо порт 8000 зайнятий

Порт API на хості задається змінною `API_PORT` (за замовчуванням 8000):

```bash
API_PORT=8001 make up          # API на http://localhost:8001
```

Або постійно — у файлі `.env` поруч із `docker-compose.yml`:

```
API_PORT=8001
```

Усередині контейнера API завжди слухає 8000; змінюється лише порт на хості.

## Scheduler

Окремий сервіс `scheduler` (той самий образ) кожні `OVERDUE_INTERVAL_SECONDS` (за замовчуванням 60)
скасовує прострочені задачі й сповіщає їхніх виконавців. Його healthcheck перевіряє heartbeat-файл:
якщо він старший за 3 інтервали, контейнер стає `unhealthy`.

Docker Compose лише позначає контейнер як `unhealthy` і **не перезапускає його автоматично**
(`restart: unless-stopped` реагує на падіння процесу, а не на статус healthcheck). Якщо scheduler
завис, перезапустіть його вручну: `docker compose restart scheduler`. В оркестраторі
(Kubernetes/Swarm) цю перевірку варто підключити як liveness-probe.

## Розробка

```bash
make migrate               # alembic upgrade head
make revision m="message"  # нова міграція (autogenerate)
make test                  # pytest проти db_test
make lint                  # ruff check + ruff format --check + mypy
```
