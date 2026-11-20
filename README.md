# Task Management API

REST API для керування задачами: реєстрація й JWT-авторизація, CRUD задач, призначення виконавців,
зміна статусів за правилами, коментарі, пошук/фільтри/сортування/пагінація, список прострочених
задач, статистика та фонове автоскасування прострочених задач.

**Стек:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + asyncpg, PostgreSQL 16,
Alembic, PyJWT, argon2 (pwdlib), pytest, Docker Compose, uv, ruff, mypy (strict).

## Зміст

- [Швидкий старт](#швидкий-старт)
- [Змінні оточення](#змінні-оточення)
- [API](#api)
- [Життєвий цикл задачі](#життєвий-цикл-задачі)
- [Бізнес-правила](#бізнес-правила)
- [Фонові задачі](#фонові-задачі)
- [Ухвалені рішення](#ухвалені-рішення)
- [Припущення (відповіді ментора ще немає)](#припущення-відповіді-ментора-ще-немає)
- [Розробка й тести](#розробка-й-тести)

## Швидкий старт

Потрібні лише Docker та Docker Compose.

```bash
cp .env.example .env     # за потреби змініть значення (див. нижче)
make up                  # збирає образ і піднімає db, migrate (one-shot), api, scheduler
```

Після `make up` API готовий: таблиці вже створені сервісом `migrate`.

- Swagger UI: http://localhost:8000/docs
- Healthcheck: `GET http://localhost:8000/health`

```bash
make logs      # логи api
make down      # зупинити стек (дані БД зберігаються)
make clean     # зупинити стек І видалити томи (docker compose down -v) — БД буде порожня
```

> `make down -v` не працює: `-v` перехоплює сам make. Для видалення томів використовуйте `make clean`.

### Якщо порт 8000 зайнятий

Порт API на хості задається змінною `API_PORT` (за замовчуванням 8000):

```bash
API_PORT=8001 make up          # API на http://localhost:8001
```

Або постійно — у `.env` поруч із `docker-compose.yml`:

```
API_PORT=8001
```

Усередині контейнера API завжди слухає 8000; змінюється лише порт на хості.

### Сервіси Docker Compose

| Сервіс      | Призначення                                                                      |
|-------------|----------------------------------------------------------------------------------|
| `db`        | PostgreSQL 16 із healthcheck                                                     |
| `migrate`   | one-shot: `alembic upgrade head`; `api` і `scheduler` чекають його завершення    |
| `api`       | FastAPI (uvicorn)                                                                |
| `scheduler` | фоновий воркер автоскасування прострочених задач (той самий образ), має healthcheck |
| `db_test`   | окрема БД для тестів (порт 5433); профіль `test`: `make up` її не запускає, `make test` — так |

### Приклад сценарію (curl)

```bash
B=http://localhost:8000/api/v1

# реєстрація й логін (login — форма OAuth2: username = email)
curl -s -X POST $B/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"author@example.com","password":"Passw0rd!long"}'
TOKEN=$(curl -s -X POST $B/auth/login -d 'username=author@example.com&password=Passw0rd!long' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# створити задачу
curl -s -X POST $B/tasks -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"First task","deadline":"2030-01-01T12:00:00Z","priority":"high"}'
```

У Swagger достатньо натиснути **Authorize** і ввести email та пароль.

## Змінні оточення

Шаблон — `.env.example`. У Docker Compose хост БД — `db`; `DATABASE_URL` для контейнерів
задається в `docker-compose.yml`.

| Змінна                        | За замовчуванням                                        | Опис                                                                 |
|-------------------------------|---------------------------------------------------------|----------------------------------------------------------------------|
| `DATABASE_URL`                | `postgresql+asyncpg://app:app@localhost:5432/app`       | БД застосунку                                                        |
| `TEST_DATABASE_URL`           | `postgresql+asyncpg://app:app@localhost:5433/app_test`  | БД для тестів                                                        |
| `ENVIRONMENT`                 | `dev`                                                   | `dev` / `test` / `prod`. У `prod` слабкий `JWT_SECRET` не дає застосунку стартувати |
| `JWT_SECRET`                  | плейсхолдер                                             | Секрет підпису JWT; у `prod` — унікальний, ≥ 32 символи              |
| `JWT_ALGORITHM`               | `HS256`                                                 | Алгоритм підпису                                                     |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60`                                                    | Час життя токена                                                     |
| `OVERDUE_INTERVAL_SECONDS`    | `60`                                                    | Інтервал тіку воркера автоскасування                                 |
| `SCHEDULER_HEARTBEAT_PATH`    | `/tmp/scheduler-heartbeat`                              | Heartbeat-файл воркера (для healthcheck)                             |
| `API_PORT`                    | `8000`                                                  | Порт API на хості (лише docker-compose)                              |
| `TEST_DB_PORT`                | `5433`                                                  | Порт тестової БД на хості: `TEST_DB_PORT=5434 make test`             |

> **Безпека за замовчуванням.** `JWT_SECRET` у `.env.example` і `docker-compose.yml` — публічний
> плейсхолдер, а `ENVIRONMENT=dev`, тож перевірка секрету для `prod` не активна. Перед розгортанням
> поза локальною машиною задайте `ENVIRONMENT=prod` і унікальний `JWT_SECRET` (≥ 32 символи).

## API

Префікс `/api/v1`. Усі ендпоінти, крім `register`, `login` і `/health`, потребують
`Authorization: Bearer <token>`.

| Метод і шлях                         | Опис                                                              |
|--------------------------------------|-------------------------------------------------------------------|
| `POST /auth/register`                | Реєстрація (JSON: `email`, `password` ≥ 8 символів)               |
| `POST /auth/login`                   | Логін (`OAuth2PasswordRequestForm`), повертає JWT                 |
| `GET /users/me`                      | Поточний користувач                                               |
| `POST /tasks`                        | Створити задачу                                                   |
| `GET /tasks`                         | Список: пошук, фільтри, сортування, пагінація                     |
| `GET /tasks/overdue`                 | Прострочені нетермінальні задачі (пагінація як у списку)          |
| `GET /tasks/stats`                   | Глобальна статистика                                              |
| `GET /tasks/{id}`                    | Задача                                                            |
| `PATCH /tasks/{id}`                  | Часткове редагування (лише автор; PUT немає, поля `status` немає) |
| `PATCH /tasks/{id}/status`           | Зміна статусу (автор або виконавець)                              |
| `DELETE /tasks/{id}`                 | Видалення (лише автор; hard delete, коментарі каскадно)           |
| `POST /tasks/{id}/comments`          | Додати коментар (будь-який автентифікований користувач)           |
| `GET /tasks/{id}/comments`           | Коментарі задачі (хронологічно, з пагінацією)                     |
| `GET /health`                        | Healthcheck (без автентифікації, поза префіксом)                  |

### Список задач

- `search` — за `title` і `description` (ILIKE + `pg_trgm`, `%` та `_` екрануються)
- фільтри: `status`, `priority` (`low|medium|high`), `assignee_id`, `deadline_from`, `deadline_to` (межі включні)
- `sort_by` (`created_at|deadline|priority`) і `order` (`asc|desc`); за замовчуванням —
  пріоритет ↓, дедлайн ↑, `id`
- `page` (≥ 1) і `size` (1–100, за замовчуванням 20)

Відповідь: `{"items": [...], "total": N, "page": 1, "size": 20, "pages": M}`.

`GET /tasks/stats` повертає `total`, `by_status`, `by_priority`, `overdue`, `active`
(`active` = backlog / in_progress / review).

### Формат помилок

Усі помилки мають однаковий вигляд:

```json
{"error": {"code": "invalid_status_transition", "message": "...", "details": {"from": "done", "to": "review"}}}
```

| HTTP | Коли                                                                       | `code` (приклади)                              |
|------|----------------------------------------------------------------------------|------------------------------------------------|
| 401  | немає/недійсний токен, невірний логін                                      | `unauthorized`                                 |
| 403  | немає прав на дію                                                          | `permission_denied`                            |
| 404  | задачу не знайдено                                                         | `not_found`                                    |
| 422  | невалідний запит або доменна валідація (дедлайн у минулому, naive datetime)| `validation_error`                             |
| 409  | порушено правило стану/бізнес-правило, зайнятий email                      | `invalid_status_transition`, `business_rule_violation`, `email_already_registered` |

Порядок перевірок: 401 → 404 → 403 → 422 → 409. Схемна валідація FastAPI виконується до
хендлера, тому схемний 422 передує 404; наведений порядок стосується доменних помилок у сервісі.

Усі datetime — timezone-aware UTC; naive datetime від клієнта відхиляється (422).

## Життєвий цикл задачі

Статуси: `backlog`, `in_progress`, `review`, `done`, `cancelled`. Пріоритети: `low`, `medium`, `high`.

```mermaid
stateDiagram-v2
    [*] --> backlog
    backlog --> in_progress
    backlog --> cancelled
    in_progress --> review
    in_progress --> cancelled
    review --> done
    done --> [*]
    cancelled --> [*]

    note right of cancelled
        Також у cancelled задачу переводить
        scheduler, якщо минув дедлайн
        (з backlog, in_progress і review)
    end note
```

Список дозволених переходів вичерпний (`app/domain/transitions.py`). Будь-який інший перехід,
зокрема назад, — `409 invalid_status_transition`. `done` і `cancelled` — термінальні.

## Бізнес-правила

Правила реалізовано чистими функціями в `app/domain/rules.py` (тестуються без БД); сервіс лише
завантажує дані, викликає правила й пише через репозиторій.

1. Статус змінюється **лише** через `PATCH /tasks/{id}/status`; редагування — лише `PATCH`.
2. `→ in_progress` і `→ review` заборонено без виконавця; `→ done` заборонено, якщо немає виконавця або дедлайн минув.
3. Дедлайн обов'язковий (`NOT NULL`), не може бути в минулому (відносно `core/clock.py`). Перевіряється
   при створенні та лише коли поле дедлайну змінюється в `PATCH`; обнулити його не можна.
4. У статусах `review` і `done` виконавця змінювати не можна.
5. `done` і `cancelled` — read-only (будь-яке редагування → 409). Коментувати можна в будь-якому статусі;
   редагування й видалення коментарів не підтримується.
6. Видалення заборонено в `in_progress` і `review`. Видалення — hard delete, коментарі видаляються каскадно.
7. Виконавець не може мати понад 10 активних задач (backlog / in_progress / review): 10-та дозволена,
   11-та → 409. Перевіряється при створенні з виконавцем і при зміні виконавця під
   `SELECT ... FOR UPDATE` рядка виконавця (без race condition).

## Фонові задачі

**Автоскасування прострочених.** Окремий сервіс `scheduler` (`python -m app.workers.overdue`, той самий
образ) кожні `OVERDUE_INTERVAL_SECONDS` одним bulk `UPDATE` переводить прострочені нетермінальні задачі
в `cancelled` (з явним `updated_at`, часом з `clock.now()`) і повертає через `RETURNING` id та виконавців.

- Захищено `pg_try_advisory_xact_lock` у тій самій транзакції, що й `UPDATE`: дві репліки не скасовують
  одне й те саме; якщо lock зайнятий, тік пропускається (`lock_not_acquired`).
- Логи тіку структуровані: `cancelled=N duration_ms=M`.
- Тік має тайм-аут (30 с); збій тіку не зупиняє воркер.
- **Graceful shutdown:** SIGTERM лише ставить прапорець — поточний тік (UPDATE і нотифікації) завершується.
- **Healthcheck:** після кожного успішного тіку оновлюється heartbeat-файл; контейнер вважається
  `healthy`, якщо файл свіжіший за 3 інтервали. Збійний тік heartbeat не оновлює.
- Docker Compose лише позначає контейнер `unhealthy` і **не перезапускає його автоматично**
  (`restart: unless-stopped` реагує на падіння процесу, а не на healthcheck). Якщо scheduler завис:
  `docker compose restart scheduler`. В оркестраторі (Kubernetes/Swarm) цю перевірку варто
  підключити як liveness-probe.
- Наслідок: `/tasks/overdue` і лічильник `overdue` у stats показують лише задачі у вікні між дедлайном і
  наступним тіком воркера (до `OVERDUE_INTERVAL_SECONDS`). Це очікувано.

**Нотифікації.** Інтерфейс `Notifier` (зараз — `LoggingNotifier`, структурований лог) викликається через
FastAPI `BackgroundTasks` після відповіді: виконавцю при призначенні та при зміні статусу іншою людиною.
Воркер сповіщає виконавців автоскасованих задач після commit; збій однієї нотифікації не ламає тік.
Сервіс збирає доменні події (`TaskService.events`), а роутер лише планує їх відправлення.

## Ухвалені рішення

Нестандартне рішення → чому.

**База даних**
- **VARCHAR + CHECK замість PG ENUM для статусу** — `ALTER TYPE ... ADD VALUE` не транзакційний,
  downgrade складний; CHECK міняється звичайною міграцією.
- **Пріоритет — `SMALLINT` + CHECK** (low=1, medium=2, high=3) — сортування за числом не залежить від
  порядку оголошення значень. В API пріоритет — рядок `low|medium|high`.
- **BIGINT identity** — простий монотонний id, стабільне сортування.
- **`pg_trgm` + екранування `%`/`_`** — швидкий ILIKE (два GIN-індекси) і коректний пошук спецсимволів.
- **Hard delete + каскад коментарів** — у ТЗ немає історії чи відновлення; простіша модель.
- **Дедлайн `NOT NULL`, перевірка «не в минулому» лише при зміні поля** — ТЗ вимагає дедлайн у кожній
  задачі; редагування прострочених задач іншими полями не ламається.

**Архітектура**
- **Правила як чисті функції в `domain/`** — тестуються без БД; сервіс лише оркеструє.
- **Commit у сервісі** — межа транзакції збігається з бізнес-операцією, репозиторії прості (без commit).
- **Єдиний `clock.now()`, без SQL `now()` і time-machine** — один механізм часу, який можна мокати в
  тестах і передавати в SQL та воркер.
- **`DomainValidationError` + перевизначені хендлери** — немає плутанини з pydantic `ValidationError`,
  один формат помилки для всіх випадків (включно з 401/404/422 від FastAPI).
- **Лише PATCH, без PUT** — статус не входить до оновлення, часткове оновлення достатнє.
- **Логін через `OAuth2PasswordRequestForm`** — працює кнопка Authorize у Swagger.

**Конкурентність і фон**
- **`FOR UPDATE` на задачі** — захист від гонок між паралельними PATCH і воркером; для ліміту №7 —
  `FOR NO KEY UPDATE` на рядку (нового) виконавця: звичайний `FOR UPDATE` конфліктує з `FOR KEY SHARE`,
  який `INSERT` задачі бере для FK-перевірки, і зустрічні створення (A→B та B→A) давали deadlock.
  Порядок блокувань: задача, потім користувач.
- **`FOR SHARE` на задачі при коментуванні** — паралельне видалення не дасть FK-помилки (500).
- **Ліміт: 10-та дозволена, 11-та → 409** — буквально «не більше десяти».
- **`pg_try_advisory_xact_lock`** — lock живе рівно в транзакції `UPDATE`; session-level lock міг би
  лишитись на іншому з'єднанні пулу.
- **Окремий сервіс `scheduler`** — не дублюється при кількох репліках `api`; піднімається тим самим
  `docker compose up`.
- **Нотифікації автоскасування через `UPDATE ... RETURNING`** — один запит повертає id та виконавців.
- **Heartbeat-файл + healthcheck** — воркер не слухає порт, тож «здоров'я» = свіжий mtime файлу.
- **Не сповіщаємо автора дії** — виконавець, який сам змінив статус (або сам собі призначив задачу), не
  отримує нотифікацію про власну дію.
- **`migrate` як one-shot сервіс** — `docker compose up` працює без ручних кроків.

**Безпека**
- **409 на `register` для зайнятого email** — свідомий компроміс: дає змогу перебирати email. Логін
  захищений (однакова відповідь + фіктивний хеш), але для register UX важливіший; rate limit поза
  скоупом тестового завдання.
- **Email учасників видимий (`UserBrief` з email)** — усі автентифіковані користувачі — одна команда
  (як у Jira/Linear). У мультитенантній версії видимість обмежувалась би workspace.
- **`ENVIRONMENT=prod` відхиляє слабкий `JWT_SECRET`** — плейсхолдер або < 32 символів не дає
  застосунку стартувати; dev/test лишаються зручними.
- **`verify_and_update` відкладено** — оновлення параметрів argon2 у хешах існуючих користувачів не
  потрібне, поки параметри не змінювались; зламаний хеш при логіні = 401, а не 500.
- **Порожній `/overdue` після автоскасування** — наслідок вимог ТЗ (див. «Фонові задачі»).

## Припущення (відповіді ментора ще немає)

Відповіді на ці питання від ментора немає, тому прийнято такі припущення. Кожне ізольоване в одному
місці коду, тож змінюється дешево.

| Питання | Прийняте рішення | Чому | Де змінити |
|---------|------------------|------|------------|
| Що таке «Todo» у правилі про ліміт 10 задач | `Todo` = `backlog`; активні = backlog / in_progress / review; ліміт рахується по виконавцю | У ТЗ немає статусу Todo; backlog — його єдиний аналог. «Один користувач» у контексті «активних задач» — це той, на кого задачі призначено | `ACTIVE_STATUSES` у `domain/transitions.py`, `count_active_for_assignee` |
| Чи автоскасування зачіпає `review` | Так: скасовуються всі нетермінальні прострочені, включно з `review` | Це системна дія, а не ручний перехід (вручну `review → cancelled` заборонено). Інакше прострочена задача в `review` висіла б вічно: `done` після дедлайну заборонено | `_overdue_clause` у `repositories/task.py` |
| Права доступу | Усі автентифіковані бачать усі задачі; редагувати й видаляти — автор; змінювати статус — автор або виконавець; коментувати — будь-хто | ТЗ не описує ролей; це мінімальна модель «одна команда», у якій виконавець може рухати власну задачу, а чужі правки обмежені автором | `services/task.py`, `services/comment.py` |
| Виконавець обов'язковий для `→ in_progress` і `→ review` | Так (розширення правила №2 про `done`) | Інакше задача могла б дійти до `review` без виконавця (зокрема зняттям виконавця в `in_progress`) і застрягти: `done` без виконавця заборонено, а виконавця в `review` змінювати не можна | `ensure_can_enter_status` у `domain/rules.py` |

## Розробка й тести

```bash
make migrate               # alembic upgrade head
make revision m="message"  # нова міграція (autogenerate + ручна перевірка)
make test                  # піднімає db_test (профіль test) і запускає pytest
TEST_DB_PORT=5434 make test  # якщо 5433 зайнятий
make lint                  # ruff check + ruff format --check + mypy (strict)
```

Для локальної розробки без Docker для застосунку потрібні [uv](https://docs.astral.sh/uv/) і запущена
`db_test` (`docker compose up -d --wait db_test`).

- Тестова БД будується **міграціями** (`alembic upgrade head`), а не `metadata.create_all`.
- Тести конкурентності (ліміт №7, паралельні зміни статусу, коментар проти видалення задачі) працюють
  з реальним commit і `TRUNCATE` між тестами, а не з rollback-на-тест.
- Час мокається **лише** через `core/clock.py`.
- Структура тестів: `tests/api` (HTTP), `tests/services`, `tests/domain` (чисті правила), `tests/workers`.
- CI (GitHub Actions): ruff → ruff format → mypy → `alembic upgrade head` + `alembic check` → pytest.
- Коміти — за Conventional Commits; pre-commit запускає ruff і mypy.

### Архітектура

```
app/
  api/            # роутери (тонкі), deps, диспетчеризація нотифікацій
  schemas/        # Pydantic: *Create, *Update, *Read, Page[T]
  services/       # оркестрація бізнес-логіки: завантаження, блокування, commit
  repositories/   # лише SQL-запити, без бізнес-правил і commit
  models/         # SQLAlchemy ORM
  domain/         # enums, transitions, rules, exceptions, events (без БД)
  core/           # config, security, logging, clock
  db/             # engine, session factory, base
  workers/        # scheduler: автоскасування, heartbeat
migrations/       # Alembic
tests/
```

Залежності йдуть лише зверху вниз: роутер не містить бізнес-`if`, сервіс не знає про HTTP.
