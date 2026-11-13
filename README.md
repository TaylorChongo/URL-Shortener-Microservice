# URL Shortener Microservice

A REST API that turns long URLs into short codes and redirects short codes back to the original URL. Each user has an account and manages **only their own** links: list, view, update, delete, tag them, and see click statistics.

It is built with **FastAPI**, stores data in **PostgreSQL** through the **SQLAlchemy 2.x ORM**, manages the schema with **Alembic** migrations, and runs with **Docker Compose**. Interactive **Swagger** documentation is generated automatically.

```
POST /auth/register   {"email": "ama@mail.com", "password": "secret123"}           → 201
POST /api/shorten     {"url": "https://www.python.org", "tags": ["learning"]}     → 201  {"short_code": "aB3xY9", ...}
GET  /api/aB3xY9                                                                  → 302  redirect (click recorded)
GET  /api/urls/stats                                                              → 200  totals, top links, clicks per day
```

---

## Contents

1. [Tech stack](#tech-stack)
2. [Why FastAPI instead of Flask](#why-fastapi-instead-of-flask)
3. [Architecture](#architecture)
4. [Database and ORM](#database-and-orm)
5. [Project structure](#project-structure)
6. [Configuration](#configuration)
7. [Running the project](#running-the-project)
8. [API reference](#api-reference)
9. [Demo walkthrough](#demo-walkthrough)
10. [Design decisions](#design-decisions)
11. [Known limitations](#known-limitations)

---

## Tech stack

| Tool | Purpose |
|---|---|
| Python 3.14 | Language (the lab requires 3.11+) |
| FastAPI | Web framework, validation, OpenAPI docs, HTTP Basic auth |
| Pydantic | Request and response validation |
| PostgreSQL 18 | Database |
| SQLAlchemy 2.1 | ORM: models, relationships, queries (no raw SQL in the app) |
| Alembic | Database migrations |
| psycopg 3 | PostgreSQL driver |
| pwdlib + bcrypt | Password hashing |
| python-decouple | Reads configuration from environment variables / `.env` |
| Gunicorn + Uvicorn workers | Production server with several worker processes |
| Docker + Docker Compose | Containers for the app and PostgreSQL |

---

## Why FastAPI instead of Flask

The lab is written for Flask. This project uses FastAPI, and every Flask requirement has a direct FastAPI equivalent:

| Lab requirement (Flask) | This project (FastAPI) | Where |
|---|---|---|
| Application factory | `create_app()` | [app/main.py](app/main.py) |
| Blueprints | `APIRouter` groups: `/auth`, `/api/urls`, `/api` | [app/routes.py](app/routes.py) |
| Flask-Injector | FastAPI's built-in `Depends()` | [app/dependencies.py](app/dependencies.py) |
| Flask-RESTX + Swagger | FastAPI's built-in OpenAPI + Swagger UI at `/docs` | automatic |
| Pydantic / Marshmallow validation | Pydantic models | [app/schemas.py](app/schemas.py) |
| Flask-SQLAlchemy | SQLAlchemy 2.x directly (engine, session per request) | [app/database.py](app/database.py) |
| Flask-Migrate | Alembic (which Flask-Migrate wraps) | [alembic/](alembic/) |
| Django model managers | Repository classes, one per model | [app/repositories.py](app/repositories.py) |
| Django custom user model | `User` SQLAlchemy model, created before the first migration | [app/models.py](app/models.py) |
| Global exception handler | `app.add_exception_handler(...)` | [app/errors.py](app/errors.py) |
| Request logging middleware | `BaseHTTPMiddleware` | [app/middleware.py](app/middleware.py) |
| WSGI server (Gunicorn) | Gunicorn managing ASGI Uvicorn workers | [Dockerfile](Dockerfile) |
| python-decouple config | python-decouple | [app/config.py](app/config.py) |

**About OpenAPI:** FastAPI generates **OpenAPI 3.1**, the newer version of the 3.0 standard the lab mentions. Swagger UI fully supports it.

---

## Architecture

### Request flow

```
                Client (browser / Swagger UI / curl)
                              │
                              ▼
            ┌──────────────────────────────────────────┐
            │  Logging middleware                      │  logs method, path, status, time
            │  ┌────────────────────────────────────┐  │
            │  │  Exception handlers                │  │  turn errors into JSON
            │  │  ┌──────────────────────────────┐  │  │
            │  │  │  Routes (APIRouter)          │  │  │  validate input with Pydantic
            │  │  └──────────────┬───────────────┘  │  │
            │  └─────────────────┼──────────────────┘  │
            └────────────────────┼─────────────────────┘
                                 │  Depends(get_current_user)   ← HTTP Basic: email + password
                                 │  Depends(get_url_repository) ← one DB session per request
                                 ▼
          UrlShortenerService (code generation)   /   Repositories (all ORM queries)
                                 │
                                 ▼
                     SQLAlchemy Session → PostgreSQL
```

### Layers

| Layer | File | Responsibility |
|---|---|---|
| App factory | `main.py` | Builds the app and plugs in routers, middleware and error handlers |
| Routes | `routes.py` | HTTP only: read the request, call a repository or service, return the response |
| Schemas | `schemas.py` | The shape of requests, responses and errors (and their Swagger examples) |
| Service | `services.py` | Business logic: create a unique 6-character code, record clicks on redirect |
| Repositories | `repositories.py` | **Every database query**, one class per model (the "managers") |
| Models | `models.py` | Tables, columns, constraints, indexes and relationships |
| Database | `database.py` | Engine (connection pool), session factory, `Base`, `get_db()` |
| Security | `security.py` | Password hashing and verification |
| Dependencies | `dependencies.py` | Builds repositories and the service, and checks the logged-in user |
| Config | `config.py` | All settings, read from environment variables |

Routes never write queries. They ask a repository, so every query lives in one place where it can be reviewed and optimized.

### Docker setup

```
docker-compose.yml
 ├── api  (built from Dockerfile)    port 8000 → your PC
 │     └── connects to postgresql://db:5432
 └── db   (postgres:18-alpine)       port 5433 → your PC (development only, hidden in production)
       └── named volume "postgres-data"   data survives restarts
```

Port **5433** is used on the host so it doesn't clash with a PostgreSQL installed directly on the machine (which uses 5432).

---

## Database and ORM

### Tables and relationships

```
users ──< urls ──< clicks                 one-to-many (twice)
            │
            └──< url_tags >── tags        many-to-many through a linking table
```

| Table | Columns | Constraints and indexes |
|---|---|---|
| `users` | `id`, `email`, `hashed_password`, `is_active`, `created_at` | PK `id` · **unique index** `ix_users_email` |
| `urls` | `id`, `short_code`, `original_url`, `created_at`, `user_id` | PK `id` · **unique index** `ix_urls_short_code` · FK `user_id → users.id ON DELETE CASCADE` · **composite index** `ix_urls_user_id_id (user_id, id)` |
| `clicks` | `id`, `url_id`, `clicked_at` | PK `id` · FK `url_id → urls.id ON DELETE CASCADE` · **composite index** `ix_clicks_url_id_clicked_at (url_id, clicked_at)` |
| `tags` | `id`, `name` | PK `id` · **unique index** `ix_tags_name` |
| `url_tags` | `url_id`, `tag_id` | **Composite PK** `(url_id, tag_id)` (a tag can't be added twice to a link) · FKs to both sides `ON DELETE CASCADE` · index `ix_url_tags_tag_id` |

- **Custom user model.** FastAPI has no built-in user, so `User` is our own model. It was written **before the first migration**, so `urls.user_id` could reference it from the start (the same reason Django recommends a custom user model before `migrate`).
- **Database-side defaults.** `created_at` and `clicked_at` use `server_default=now()`, so every row uses the database clock.
- **Rules live in the database**, not only in Python: `NOT NULL`, `UNIQUE`, foreign keys and `CASCADE` are enforced by PostgreSQL. For example, two people registering the same email at the same moment can't both succeed: the unique index rejects the second insert, and the API answers `409`.
- **Relationships** (`user.urls`, `url.owner`, `url.clicks`, `url.tags`, `tag.urls`) use `back_populates`, so both sides stay in sync. `passive_deletes=True` lets PostgreSQL's `ON DELETE CASCADE` remove children instead of the ORM loading and deleting them one by one.

### Migrations (Alembic)

| # | Revision | What it does |
|---|---|---|
| 1 | `e6e9665c32e0` | Create `users` and its unique email index |
| 2 | `2f758049b7ce` | Create `urls` with the foreign key to `users` and its indexes |
| 3 | `d258882cd189` | Create `clicks`, `tags` and the `url_tags` linking table |
| 4 | `ed410620164d` | Replace two single-column indexes with composite ones that match the real queries (see below) |

Each migration was autogenerated from the models, **reviewed**, then applied. Every migration has a working `downgrade()`. Migration 4 was tested by running `upgrade → downgrade → upgrade`.

`alembic/env.py` reads the database URL from the environment (never from `alembic.ini`, which is committed) and uses `Base.metadata` as the target for autogenerate.

### Repositories (the "managers")

FastAPI has no equivalent of Django's `Model.objects` manager, so each model gets a repository class in [app/repositories.py](app/repositories.py). It receives the request's session and holds every query for that model.

| Repository | Methods |
|---|---|
| `UserRepository` | `get_by_email`, `get_by_id`, `create` |
| `TagRepository` | `get_or_create(names)`: cleans names, then finds the existing ones in **one** `IN (...)` query and creates the rest |
| `URLRepository` | `code_exists`, `create`, `get_by_code`, `get_for_user`, `list_for_user`, `update`, `delete`, `add_click`, `click_counts`, plus the stats queries |

**Ownership is part of every query.** `get_for_user` filters on **both** `URL.id` and `URL.user_id`. Another user's link is simply "not found" (`404`), so the API never reveals that it exists.

### Query optimization

**No N+1 queries.** Listing links with their tags and click counts uses a **constant number of queries**, whatever the page size:

| Route | Queries | How |
|---|---|---|
| `GET /api/urls` | 3 | the page of links · `selectinload(URL.tags)` loads all their tags in one query · one `COUNT ... GROUP BY url_id` for all their click counts |
| `GET /api/urls/{id}` | 3 | same, for one link |
| `GET /api/urls/stats` | 5 | one aggregate query per figure |

These counts exclude the login check. Measured with SQLAlchemy's `before_cursor_execute` event: without `selectinload`, the same list made `1 + N` queries (measured: 4 queries for 3 links, so a 100-link page would need 101).

Other details:
- `code_exists` selects only `URL.id`, not the whole row.
- Saving a user is a single `INSERT ... RETURNING id, created_at`, with no extra reload query.
- Pagination (`limit` 1–100, `offset`) keeps responses small.

### Indexes, and how they were checked

Indexes exist for the columns the app actually **searches by**: email at login, `short_code` on every redirect, owner on every list, `url_id` when counting clicks, and tag name.

Migration 4 reshaped two of them to fit the real queries. They were measured with `EXPLAIN ANALYZE` on generated test data, comparing the old and new indexes:

| Query | Old index | New index | Result |
|---|---|---|---|
| A user's 20 newest links (`WHERE user_id = ? ORDER BY id DESC LIMIT 20`): small user, 100,000 other rows in the table | `ix_urls_user_id (user_id)` | `ix_urls_user_id_id (user_id, id)` | Old plan walked the primary key backwards and **discarded 100,000 rows**. New plan reads the user's rows already in order: **0 discarded**. |
| One link's clicks in the last 7 days (`WHERE url_id = ? AND clicked_at >= ?`) | `ix_clicks_url_id (url_id)` | `ix_clicks_url_id_clicked_at (url_id, clicked_at)` | Old plan read all 20 clicks and **filtered out 18**. New plan reads only the 2 matching rows (2 heap blocks instead of 20). |

A composite index still serves queries on its **first** column alone (like a phone book sorted by surname then first name), so the old single-column indexes were removed instead of kept alongside.

### Aggregations (`GET /api/urls/stats`)

| Figure | ORM query |
|---|---|
| `total_urls` | `func.count(URL.id)` filtered by owner |
| `total_clicks` | `func.count(Click.id)` with a `join` to `URL`, filtered by owner |
| `top_urls` | `outerjoin` clicks, `group_by(URL.id)`, `order_by(count desc)`, `limit(5)`. Links with 0 clicks are included. |
| `clicks_last_7_days` | `group_by(func.date(Click.clicked_at))` over the last 7 days |
| `urls_per_tag` | `join` through `url_tags`, `group_by(Tag.name)` |

Per-link click counts are **computed** from the `clicks` table, not stored in a counter column. There is one source of truth, so a stored count can never disagree with the real clicks.

---

## Project structure

```
url-shortener-microservice/
├── app/
│   ├── __init__.py
│   ├── main.py             # create_app() factory, routers
│   ├── config.py           # settings from environment variables
│   ├── database.py         # engine, SessionLocal, Base, get_db()
│   ├── models.py           # User, URL, Click, Tag, url_tags
│   ├── repositories.py     # UserRepository, TagRepository, URLRepository
│   ├── security.py         # hash_password, verify_password
│   ├── services.py         # UrlShortenerService (codes, clicks)
│   ├── schemas.py          # Pydantic request / response / error models
│   ├── dependencies.py     # get_db wiring, repositories, get_current_user
│   ├── routes.py           # /auth, /api/urls, /api routes
│   ├── errors.py           # global exception handlers
│   └── middleware.py       # request logging middleware
├── alembic/
│   ├── env.py              # reads DATABASE_URL, targets Base.metadata
│   └── versions/           # the 4 migrations
├── alembic.ini
├── Dockerfile              # multi-stage production image (includes alembic)
├── docker-compose.yml      # development: app + PostgreSQL + hot reload
├── docker-compose.prod.yml # production overrides: Gunicorn, 4 workers, no debug, DB not exposed
├── .dockerignore
├── .env.example            # template for .env
└── requirements.txt
```

---

## Configuration

All settings come from environment variables. Locally they are read from a `.env` file (copy it from `.env.example`).

| Variable | Example | Meaning |
|---|---|---|
| `APP_ENV` | `development` | Environment name, shown on `/health` |
| `DEBUG` | `True` | Detailed error pages. Always `False` in production |
| `BASE_URL` | `http://127.0.0.1:8000` | Used to build the full short link |
| `POSTGRES_USER` | `shortener` | Database user created by the Postgres container on first start |
| `POSTGRES_PASSWORD` | `change-me` | Its password |
| `POSTGRES_DB` | `shortener` | Database created on first start |
| `DATABASE_URL` | `postgresql+psycopg://shortener:change-me@127.0.0.1:5433/shortener` | Used by **local** tools (Alembic, scripts). Docker Compose builds its own URL for the API (`@db:5432`). Required: the app refuses to start without it. |

`.env` is listed in `.gitignore`, so real secrets are never committed. Only `.env.example` is in the repository.

> Postgres reads `POSTGRES_USER` / `POSTGRES_DB` only the **first** time its volume is empty. If you change them later, `DATABASE_URL` must still match the original values (or remove the volume with `docker compose down -v`, which deletes the data).

**Profiles**

| | Development | Production |
|---|---|---|
| Server | `fastapi dev`, auto-reload | Gunicorn + 4 Uvicorn workers (`WEB_CONCURRENCY`) |
| `DEBUG` | `True` | `False` |
| Code | mounted as a volume (hot reload) | baked into the image |
| Database port on host | `5433` | not exposed |
| Restart policy | none | `unless-stopped` |

---

## Running the project

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Git
- Python 3.11+ (to run Alembic from your machine in development)

### 1. Clone and configure
```bash
git clone <your-repo-url>
cd url-shortener-microservice
cp .env.example .env          # on Windows PowerShell: copy .env.example .env
```
Open `.env` and set a real `POSTGRES_PASSWORD`, using the same value inside `DATABASE_URL`.

### 2. Start the containers (development)
```bash
docker compose up --build -d
docker compose ps
```
Expected: `db` is `(healthy)` and `api` is `Up`.

### 3. Create the tables (run the migrations)
From your machine:
```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
```
Or from inside the API container, without a local Python:
```bash
docker compose exec api alembic upgrade head
```
Expected last line:
```
INFO  [alembic.runtime.migration] Running upgrade d258882cd189 -> ed410620164d, use composite indexes for url list and clicks
```
Check with `alembic current`, which should print `ed410620164d (head)`.

- Swagger UI: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health → `{"status":"ok","env":"development"}`

Edit any file in `app/` and save. The logs show `Reloading...` and the change is live, with no rebuild needed.

### 4. Production profile
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
docker compose exec api alembic upgrade head
```
In production the database port is not exposed, so migrations run inside the `api` container. The image includes `alembic.ini` and `alembic/` for this reason.

### Looking inside the database
```bash
docker compose exec db psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c "\dt"
docker compose exec db psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c "\d urls"
```
Or connect pgAdmin to host `127.0.0.1`, port **5433**.

### Migration commands
```bash
alembic revision --autogenerate -m "describe the change"   # write a migration from model changes (then read it!)
alembic upgrade head                                       # apply all pending migrations
alembic downgrade -1                                       # roll back the last one
alembic current                                            # which migration the database is on
```
On Windows, if `alembic` is blocked by an application-control policy, use `python -m alembic ...` instead.

---

## API reference

Interactive version: **http://127.0.0.1:8000/docs**. Raw OpenAPI schema: `/openapi.json`.

### Authentication: HTTP Basic

Protected routes need the email and password with each request (`Authorization: Basic ...`). In Swagger, click **Authorize** and enter your **email as the username**. Wrong email and wrong password give the same `401` message, so the API never reveals which emails have an account.

Basic auth sends credentials with every request, so it must be used over HTTPS outside local development. Token-based auth (JWT) is planned for the next module.

### Auth (`/auth`)

| Method and path | Auth | Success | Errors |
|---|---|---|---|
| `POST /auth/register` `{"email", "password"}` | – | **201** `{"id", "email", "is_active", "created_at"}` | **409** email already registered · **422** invalid email or password not 8–72 characters |
| `POST /auth/login` | Basic | **200** the user | **401** incorrect email or password · **403** account disabled |

Emails are stored in lowercase. Passwords are stored only as bcrypt hashes and are never returned.

### Short links (`/api`)

| Method and path | Auth | Success | Errors |
|---|---|---|---|
| `POST /api/shorten` `{"url", "tags"?}` | Basic | **201** a link (see below) | **401** · **422** invalid URL, more than 10 tags, or a tag longer than 50 characters |
| `GET /api/{code}` | – (public) | **302** redirect, and **one click is recorded** | **404** unknown code |

### Your links (`/api/urls`)

| Method and path | Auth | Success | Errors |
|---|---|---|---|
| `GET /api/urls?limit=20&offset=0` | Basic | **200** your links, newest first (`limit` 1–100) | **401** · **422** bad `limit` / `offset` |
| `GET /api/urls/stats` | Basic | **200** stats (see below) | **401** |
| `GET /api/urls/{id}` | Basic | **200** one link | **401** · **404** not found or not yours |
| `PATCH /api/urls/{id}` `{"url"?, "tags"?}` | Basic | **200** the updated link | **401** · **404** · **422** |
| `DELETE /api/urls/{id}` | Basic | **204** (its clicks and tag links are deleted too) | **401** · **404** |

For `PATCH`, leave a field out to keep it unchanged. `"tags": []` removes all tags, and a new list replaces the old one.

A link looks like:
```json
{
  "id": 1,
  "short_code": "aB3xY9",
  "short_url": "http://127.0.0.1:8000/api/aB3xY9",
  "original_url": "https://www.python.org/",
  "tags": ["learning"],
  "click_count": 3,
  "created_at": "2026-11-13T15:20:22.740332Z"
}
```

Stats look like:
```json
{
  "total_urls": 4,
  "total_clicks": 8,
  "top_urls": [{"short_code": "aB3xY9", "original_url": "https://a.com/", "clicks": 5}],
  "clicks_last_7_days": [{"day": "2026-11-13", "clicks": 8}],
  "urls_per_tag": [{"tag": "shopping", "urls": 2}, {"tag": "books", "urls": 1}]
}
```

Tags are trimmed, lowercased and de-duplicated (`[" Shopping", "shopping"]` → `["shopping"]`). Tag names are shared between users: there is one `shopping` row in `tags`.

### `GET /health`

| Status | Body |
|---|---|
| **200** | `{"status": "ok", "env": "development"}` |

### Error format

Every error has the same JSON shape, produced by the global exception handlers in [app/errors.py](app/errors.py):

```json
{ "status_code": 404, "message": "URL not found" }
```

Validation errors (422) also list each problem:
```json
{
  "status_code": 422,
  "message": "Invalid input",
  "errors": [{ "field": "password", "message": "String should have at least 8 characters" }]
}
```

Unexpected errors return `500` with `"Something went wrong on our side"`. The full error is written to the logs, never sent to the client.

### Request logs

Every request is logged by the middleware in [app/middleware.py](app/middleware.py):
```
2026-11-13 16:30:04,513 INFO app.middleware: POST /api/shorten -> 201 (23.4 ms)
2026-11-13 16:30:04,523 INFO app.middleware: GET /api/aB3xY9 -> 302 (2.5 ms)
```

---

## Demo walkthrough

### 1. Start and migrate
```bash
docker compose up --build -d
alembic upgrade head
```
**Show:** in pgAdmin (`127.0.0.1:5433`) or with `\dt`, the tables `users`, `urls`, `clicks`, `tags`, `url_tags` and `alembic_version`.

### 2. Register two users
In Swagger (**http://127.0.0.1:8000/docs**), use **POST /auth/register** twice: `ama@mail.com` and `kofi@mail.com`, both with `secret123` → **201**.
Register `Ama@Mail.com` again → **409** (emails are compared in lowercase).

**Show:** `users` stores `$2b$12$...` hashes, never the password.

### 3. Log in as Ama
Click **Authorize** and enter `ama@mail.com` / `secret123`. Call **POST /auth/login** → **200**.

### 4. Create links with tags
**POST /api/shorten**:
```json
{ "url": "https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702", "tags": ["shopping", "books"] }
```
```json
{ "url": "https://www.python.org", "tags": ["learning"] }
```
→ **201** each time. Log out of Swagger and try again → **401**.

### 5. Open a short link a few times
Paste a `short_url` into the **browser's address bar** (Swagger cannot follow redirects to other websites) → it redirects.
**Show:** each visit adds a row to `clicks`.

### 6. Manage the links
- **GET /api/urls**: both links, newest first, with `tags` and `click_count`.
- **PATCH /api/urls/{id}** with `{"tags": ["work"]}`: only the tags change.
- **GET /api/urls/stats**: totals, top links, clicks per day, links per tag.

### 7. Ownership
Authorize as `kofi@mail.com`. **GET /api/urls** → `[]`. **GET**, **PATCH** or **DELETE** one of Ama's ids → **404**.

### 8. Delete
As Ama, **DELETE /api/urls/{id}** → **204**. **Show:** its rows in `clicks` and `url_tags` are gone too (`ON DELETE CASCADE`), and the tags themselves stay.

### 9. Migrations
```bash
alembic downgrade -1    # composite indexes → back to single-column indexes
alembic upgrade head    # and forward again
alembic current         # ed410620164d (head)
```

### 10. Production profile
```bash
docker compose down
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
docker compose exec api alembic upgrade head
```
**Show:** `Starting gunicorn` and **4×** `Booting worker`. `/health` → `{"status": "ok", "env": "production"}`. All workers share the same PostgreSQL database.

---

## Design decisions

**ORM only, no raw SQL in the application.**
Every query is built with SQLAlchemy (`select`, `where`, `join`, `group_by`, `func.count`) inside a repository. SQL text appears only in the generated migrations and in manual `EXPLAIN` checks.

**One session per request.**
`get_db()` opens a session, lends it to the request, and always closes it in `finally`. Anything not committed is rolled back. FastAPI caches `get_db` within a request, so the user, URL and tag repositories in the same request share one session and one transaction. For example, creating a link with new tags is a single `commit()`.

**Session settings.**
`expire_on_commit=False` lets a route return an object after `commit()` without another query. `autoflush=False` means nothing is sent to the database before we commit. `pool_pre_ping=True` replaces dead connections, for example after a database restart.

**HTTP Basic auth for this module.**
It's the simplest correct option: no extra package, no extra table. All authorization goes through one dependency, `get_current_user`, so switching to JWT next module changes only that function. The routes stay the same.

**bcrypt for passwords.**
Hashing goes through `pwdlib`. Argon2 was the first choice, but its compiled module was blocked by Windows application control on the development machine, so bcrypt (also a slow, salted password hash) is used. bcrypt reads at most 72 bytes, so passwords are limited to 8–72 characters, and longer ones get a clear 422 instead of a server error.

**404 instead of 403 for other users' links.**
The ownership filter is part of the query, so another user's link is indistinguishable from a link that doesn't exist.

**Random codes with a collision check.**
Codes are 6 characters from `a-z`, `A-Z` and `0-9` (62⁶ ≈ 56 billion combinations), generated with the `secrets` module. The service checks `code_exists` before saving, and the unique index on `short_code` is the final guarantee.

**Multi-stage Dockerfile.**
Stage 1 installs the packages into a virtual environment. Stage 2 copies only that environment, `app/` and the Alembic files into a clean `python:3.14-slim` image that runs as a non-root user.

**One error format.**
Three handlers in [app/errors.py](app/errors.py) cover HTTP errors, validation errors and unexpected crashes. Clients always get `status_code` + `message`. The handler keeps response headers such as `WWW-Authenticate: Basic`.

---

## Known limitations

- **Basic auth** sends the password on every request and checks it with bcrypt each time (slow on purpose). It's fine for this module, and it's replaced by JWT in the next one.
- **New tag race:** if two requests create the same **new** tag name at exactly the same moment, the second one can fail on the unique index. PostgreSQL's `INSERT ... ON CONFLICT DO NOTHING` would remove this.
- **Clicks are written synchronously** on each redirect. At very high traffic, they could be buffered (for example in a queue) and written in batches.
- **`offset` pagination** gets slower for very deep pages. Keyset pagination (`WHERE id < last_seen_id`) would keep it constant, and the `(user_id, id)` index already supports it.
