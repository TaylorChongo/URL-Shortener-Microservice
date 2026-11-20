# URL Shortener Microservice

A REST API that turns long URLs into short codes and redirects short codes back to the original URL. Each user has an account and manages **only their own** links: list, view, update, delete, tag them, give them a custom alias or an expiry date, switch them off, and see click statistics. Every visit is recorded with the visitor's IP address, browser, referrer, country and city, and the statistics break visits down by each of these. A user can shorten a given URL only once.

It is built with **FastAPI**, stores data in **PostgreSQL** through the **SQLAlchemy 2.x ORM**, manages the schema with **Alembic** migrations, and runs with **Docker Compose**. Interactive **Swagger** documentation is generated automatically.

```
POST /auth/register   {"email": "ama@mail.com", "password": "secret123"}                          → 201
POST /api/shorten     {"url": "https://www.python.org", "custom_alias": "my-cv", "tags": ["cv"]}  → 201  {"short_code": "aB3xY9", ...}
GET  /api/aB3xY9      (or /api/my-cv)                                                            → 302  redirect, visit recorded
GET  /api/urls/stats                                                                             → 200  totals, top links, clicks per day
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
| maxminddb + DB-IP City Lite | Offline IP → country and city lookup for visits |
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
| Django custom user model (`AbstractUser`) | `User` SQLAlchemy model, created before the first migration | [app/models.py](app/models.py) |
| Django field `choices` / `PositiveIntegerField` | `CHECK` constraints enforced by PostgreSQL | [app/models.py](app/models.py) |
| Django `GenericIPAddressField` | PostgreSQL's native `INET` type | [app/models.py](app/models.py) |
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
     UrlShortenerService (codes, aliases, visits)   /   Repositories (all ORM queries)
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
| Service | `services.py` | Business logic: unique 6-character codes, custom alias and duplicate URL checks, recording visits |
| Location | `geoip.py` | Looks up an IP's country and city in the offline location file |
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
 │     ├── connects to postgresql://db:5432
 │     ├── ./data is shared read-only (the IP location file), in development and production
 │     └── development: ./app, ./alembic and alembic.ini are shared with the container
 └── db   (postgres:18-alpine)       port 5433 → your PC (development only, hidden in production)
       └── named volume "postgres-data"   data survives restarts
```

Port **5433** is used on the host so it doesn't clash with a PostgreSQL installed directly on the machine (which uses 5432).

---

## Database and ORM

### Tables and relationships (ERD)

```mermaid
erDiagram
    users ||--o{ urls : "owns"
    urls ||--o{ clicks : "receives"
    urls ||--o{ url_tags : "is tagged"
    tags ||--o{ url_tags : "labels"

    users {
        int id PK
        varchar email UK "max 255, unique index"
        varchar hashed_password "bcrypt hash, max 255"
        boolean is_active "default true"
        boolean is_premium "default false"
        varchar tier "free | premium | admin (CHECK), default free"
        timestamptz created_at "default now()"
    }

    urls {
        int id PK
        varchar short_code UK "max 10, unique index"
        varchar custom_alias UK "max 10, nullable, unique index"
        text original_url
        varchar title "max 255, nullable"
        varchar description "max 500, nullable"
        varchar favicon "max 2048, nullable"
        boolean is_active "default true"
        timestamptz expires_at "nullable"
        int click_count "stored counter, default 0, CHECK >= 0"
        timestamptz created_at "default now()"
        int user_id FK "users.id, on delete cascade"
    }

    clicks {
        int id PK
        int url_id FK "urls.id, on delete cascade"
        timestamptz clicked_at "default now()"
        inet ip_address "IPv4 or IPv6"
        text user_agent "browser or app"
        text referrer "nullable"
        varchar city "max 100, nullable"
        varchar country "max 100, nullable"
    }

    tags {
        int id PK
        varchar name UK "max 50, unique index"
    }

    url_tags {
        int url_id PK, FK "urls.id, on delete cascade"
        int tag_id PK, FK "tags.id, on delete cascade"
    }
```

How to read it:
- `||--o{` means **one to many**. One user owns zero or more URLs, and one URL receives zero or more clicks.
- `urls` ↔ `tags` is **many-to-many**: a link can have many tags, and a tag can be on many links. The `url_tags` table in the middle holds one row per link–tag pair.
- `PK` primary key · `FK` foreign key · `UK` unique.
- Composite indexes, which the diagram can't show: `urls (user_id, id)` and `clicks (url_id, clicked_at)`. See [Indexes](#indexes-and-how-they-were-checked).

| Table | Constraints and indexes |
|---|---|
| `users` | PK `id` · **unique index** `ix_users_email` · **CHECK** `ck_users_tier` (`tier IN ('free', 'premium', 'admin')`) |
| `urls` | PK `id` · **unique indexes** `ix_urls_short_code`, `ix_urls_custom_alias` · **unique expression index** `uq_urls_user_id_original_url (user_id, md5(original_url))`: one link per URL per user · FK `user_id → users.id ON DELETE CASCADE` · **composite index** `ix_urls_user_id_id (user_id, id)` · **CHECK** `ck_urls_click_count_not_negative` (`click_count >= 0`) |
| `clicks` | PK `id` · FK `url_id → urls.id ON DELETE CASCADE` · **composite index** `ix_clicks_url_id_clicked_at (url_id, clicked_at)` · `ip_address` uses PostgreSQL's `INET` type, which rejects anything that isn't an IP address |
| `tags` | PK `id` · **unique index** `ix_tags_name` |
| `url_tags` | **Composite PK** `(url_id, tag_id)` (a tag can't be added twice to a link) · FKs to both sides `ON DELETE CASCADE` · index `ix_url_tags_tag_id` |

- **Custom user model.** FastAPI has no built-in user, so `User` is our own model (the equivalent of a Django custom user extending `AbstractUser`). It was written **before the first migration**, so `urls.user_id` could reference it from the start. Of `AbstractUser`'s fields, it keeps what the app needs: `email`, `is_active`, `created_at` (≈ `date_joined`), plus `is_premium` and `tier`.
- **Database-side defaults.** `created_at`, `clicked_at`, `is_active`, `is_premium`, `tier` and `click_count` use `server_default`, so the rule lives in the table itself and also applies to rows inserted outside the app.
- **Rules live in the database**, not only in Python: `NOT NULL`, `UNIQUE`, foreign keys, `CASCADE`, `CHECK` and the `INET` type are enforced by PostgreSQL. For example, two people registering the same email at the same moment can't both succeed, and `tier = 'gold'` is refused even when typed directly in pgAdmin.
- **Relationships** (`user.urls`, `url.owner`, `url.clicks`, `url.tags`, `tag.urls`) use `back_populates`, so both sides stay in sync. `passive_deletes=True` lets PostgreSQL's `ON DELETE CASCADE` remove children instead of the ORM loading and deleting them one by one.

### Migrations (Alembic)

| # | Revision | What it does | Adjusted by hand |
|---|---|---|---|
| 1 | `e6e9665c32e0` | Create `users` and its unique email index | – |
| 2 | `2f758049b7ce` | Create `urls` with the foreign key to `users` and its indexes | – |
| 3 | `d258882cd189` | Create `clicks`, `tags` and the `url_tags` linking table | – |
| 4 | `ed410620164d` | Replace two single-column indexes with composite ones that match the real queries (see below) | – |
| 5 | `b2489dff4602` | Add `is_premium` and `tier` to `users` | added the `tier` CHECK constraint |
| 6 | `0c6a9ac83683` | Add `custom_alias`, `title`, `description`, `favicon`, `is_active`, `expires_at` and `click_count` to `urls` | added the `click_count >= 0` CHECK, and a **data step** that fills `click_count` from the clicks already recorded |
| 7 | `6c4844556bc0` | Add `ip_address`, `user_agent`, `referrer`, `city`, `country` to `clicks` | required columns on a table with existing rows: added **temporary defaults** (`0.0.0.0`, empty) for old rows, then removed them so new clicks must provide real values |
| 8 | `81f75907bc05` | One link per URL per user: unique index on `(user_id, md5(original_url))` | a **data step first merges existing duplicates** (see below), otherwise the index can't be created |

Each migration was autogenerated from the models, **reviewed**, corrected where needed, then applied. Autogenerate doesn't detect `CHECK` constraints or data changes, which is why migrations 5–8 needed manual additions. Every migration has a working `downgrade()`, and migrations 4–8 were tested by running `upgrade → downgrade → upgrade`.

**Merging duplicates (migration 8).** Before the unique rule existed, a user could shorten the same URL several times. For each such group, the migration keeps the **most-clicked** link (the oldest if tied), so a link that was already shared keeps working. It moves the others' clicks and tags onto it, adds their click counts to its `click_count`, keeps an alias if only a removed copy had one, then deletes the other copies. It was first run on a **copy of the database** with harder cases (tied clicks, different tags, an alias on a copy being removed) before the real data. Its `downgrade()` removes the rule only: merged links can't be split apart again.

The data step in migration 6 is written with SQLAlchemy Core, not raw SQL:
```python
number_of_clicks = select(func.count()).select_from(clicks).where(clicks.c.url_id == urls.c.id).scalar_subquery()
op.execute(urls.update().values(click_count=number_of_clicks))
```

`alembic/env.py` reads the database URL from the environment (never from `alembic.ini`, which is committed) and uses `Base.metadata` as the target for autogenerate.

### Repositories (the "managers")

FastAPI has no equivalent of Django's `Model.objects` manager, so each model gets a repository class in [app/repositories.py](app/repositories.py). It receives the request's session and holds every query for that model.

| Repository | Methods |
|---|---|
| `UserRepository` | `get_by_email`, `get_by_id`, `create` |
| `TagRepository` | `get_or_create(names)`: cleans names (`clean_tag_names`: trimmed, lowercase, no repeats), then finds the existing ones in **one** `IN (...)` query and creates the rest |
| `URLRepository` | `code_exists` (short code **or** alias), `get_user_link_for_url` (duplicate check), `create`, `get_by_code` (short code **or** alias), `get_for_user`, `list_for_user`, `update` (only the fields that changed), `delete`, `add_click`, plus the stats queries, including the reusable `clicks_grouped_by(user_id, column, limit)` |

**Ownership is part of every query.** `get_for_user` filters on **both** `URL.id` and `URL.user_id`. Another user's link is simply "not found" (`404`), so the API never reveals that it exists. The owner is always taken from the login, never from the request body.

### Stored click counter (from code review)

At first, a link's click count was **computed** by counting its rows in `clicks` each time it was shown. A reviewer pointed out that reading a count this way gets slower as visits grow, and suggested storing the count on the link itself. `urls.click_count` now does that (a deliberate **denormalization**):

| | Counting rows (before) | Stored counter (now) |
|---|---|---|
| Reading a link's clicks | `COUNT(*)` over its rows in `clicks` | read one column |
| Each visit | 1 insert into `clicks` | 1 insert into `clicks` + `UPDATE urls SET click_count = click_count + 1` |

How it stays correct:
- The **+1 is done by PostgreSQL** (`URL.click_count + 1`), not by reading the value in Python and writing it back, so simultaneous visits are all counted. Tested with **20 parallel requests**: counter and click rows both went up by exactly 20.
- The click row and the counter update are saved in **one commit**, so they can't drift apart.
- `CHECK (click_count >= 0)` guards against bad writes.
- Migration 6 filled the counter for existing links from their recorded clicks.

The `clicks` table is kept: it holds *when* and *from where* (IP, browser, referrer), which the per-day statistics need.

### Query optimization

**No N+1 queries.** Listing links with their tags uses a **constant number of queries**, whatever the page size:

| Route | Queries | How |
|---|---|---|
| `GET /api/urls` | 2 | the page of links (with their stored `click_count`) · `selectinload(URL.tags)` loads all their tags in one query |
| `GET /api/urls/{id}` | 2 | same, for one link |
| `GET /api/urls/stats` | 10 | one aggregate query per figure |

These counts exclude the login check. Measured with SQLAlchemy's `before_cursor_execute` event. Without `selectinload`, the list made `1 + N` queries (measured: 4 queries for 3 links, so a 100-link page would need 101). Before the stored counter, the list needed a third query to count clicks.

Other details:
- `code_exists` selects only `URL.id`, not the whole row.
- Saving a user is a single `INSERT ... RETURNING id, created_at`, with no extra reload query.
- Pagination (`limit` 1–100, `offset`) keeps responses small.
- Looking up a link by short code **or** alias uses the two unique indexes.
- The duplicate check compares `md5(original_url)`, so it can use the `(user_id, md5(original_url))` index; it also compares the full text to be certain.

### Indexes, and how they were checked

Indexes exist for the columns the app actually **searches by**: email at login, `short_code` and `custom_alias` on every redirect, owner on every list, `url_id` + date when counting clicks per day, tag name, and owner + URL when checking for duplicates.

The duplicate rule indexes `md5(original_url)` (a 32-character fingerprint) instead of the URL itself, so the index stays small however long the URLs are.

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
| `total_clicks` | `func.sum(URL.click_count)` filtered by owner (`coalesce` → 0 when there are no links) |
| `top_urls` | links ordered by the stored `click_count`, `limit(5)` |
| `clicks_last_7_days` | `group_by(func.date(Click.clicked_at))` over the last 7 days, joined to the owner's links |
| `urls_per_tag` | `join` through `url_tags`, `group_by(Tag.name)` |
| `clicks_per_ip_address` | `clicks_grouped_by(Click.ip_address)`, top 10; the last part of each IP is hidden before it is returned |
| `clicks_per_user_agent` | `clicks_grouped_by(Click.user_agent)`, top 10 |
| `clicks_per_country` | `clicks_grouped_by(Click.country)`, top 10 |
| `clicks_per_city` | `group_by(Click.city, Click.country)`, top 10 (so two towns with the same name stay apart) |
| `clicks_per_referrer` | `clicks_grouped_by(Click.referrer)`, top 10 |

`clicks_grouped_by` is one reusable query, "count this user's clicks per value of a column, most first, top N": `select(column, count(Click.id)).join(Click.url).where(URL.user_id == ...).group_by(column).order_by(count desc).limit(N)`. Empty values come back as one group and are shown as "Unknown" (or "Direct" for the referrer).

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
│   ├── services.py         # UrlShortenerService (codes, aliases, duplicates, visits)
│   ├── geoip.py            # find_location(ip) → (country, city)
│   ├── schemas.py          # Pydantic request / response / error models
│   ├── dependencies.py     # get_db wiring, repositories, get_current_user
│   ├── routes.py           # /auth, /api/urls, /api routes
│   ├── errors.py           # global exception handlers
│   └── middleware.py       # request logging middleware
├── alembic/
│   ├── env.py              # reads DATABASE_URL, targets Base.metadata
│   └── versions/           # the 8 migrations
├── scripts/
│   └── download_location_file.py   # downloads the IP location file into data/
├── data/                   # IP location file (not in Git, see "Running the project")
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
| `GEOIP_DATABASE_PATH` | `data/dbip-city-lite.mmdb` | Optional. Where the IP location file is. If the file is missing, the app still runs and logs a warning; country and city stay empty. |

`.env` is listed in `.gitignore`, so real secrets are never committed. Only `.env.example` is in the repository.

> Postgres reads `POSTGRES_USER` / `POSTGRES_DB` only the **first** time its volume is empty. If you change them later, `DATABASE_URL` must still match the original values (or remove the volume with `docker compose down -v`, which deletes the data).

**Profiles**

| | Development | Production |
|---|---|---|
| Server | `fastapi dev`, auto-reload | Gunicorn + 4 Uvicorn workers (`WEB_CONCURRENCY`) |
| `DEBUG` | `True` | `False` |
| Code and migrations | shared with the container (hot reload, new migration files appear in the project) | baked into the image |
| Database port on host | `5433` | not exposed |
| Restart policy | none | `unless-stopped` |

---

## Running the project

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Git

### 1. Clone and configure
```bash
git clone <your-repo-url>
cd url-shortener-microservice
cp .env.example .env          # on Windows PowerShell: copy .env.example .env
```
Open `.env` and set a real `POSTGRES_PASSWORD`, using the same value inside `DATABASE_URL`.

### 2. Download the IP location file
```bash
python scripts/download_location_file.py
```
Expected:
```
Downloading https://download.db-ip.com/free/dbip-city-lite-2026-11.mmdb.gz ...
Unpacking ...
Saved data/dbip-city-lite.mmdb (121 MB, edition 2026-11)
```
The file (about 120 MB) is not in Git: GitHub refuses files over 100 MB, and a new edition comes out every month. The script needs only Python's built-in modules. Run it again later to refresh the data, then `docker compose restart api`. Without the file, everything still works, but visits have no country or city.

IP Geolocation by [DB-IP](https://db-ip.com), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

### 3. Start the containers (development)
```bash
docker compose up --build -d
docker compose ps
```
Expected: `db` is `(healthy)` and `api` is `Up`.

### 4. Create the tables (run the migrations)
```bash
docker compose exec api alembic upgrade head
```
Expected last line:
```
INFO  [alembic.runtime.migration] Running upgrade 6c4844556bc0 -> 81f75907bc05, one link per url per user
```
Check with `docker compose exec api alembic current`, which should print `81f75907bc05 (head)`.

- Swagger UI: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health → `{"status":"ok","env":"development"}`

Edit any file in `app/` and save. The logs show `Reloading...` and the change is live, with no rebuild needed.

### 5. Production profile
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
Run Alembic inside the `api` container. In development, `./alembic` is shared with the container, so a migration file generated there appears in the project folder.
```bash
docker compose exec api alembic revision --autogenerate -m "describe the change"   # write a migration (then read it!)
docker compose exec api alembic upgrade head                                       # apply all pending migrations
docker compose exec api alembic downgrade -1                                       # roll back the last one
docker compose exec api alembic current                                            # which migration the database is on
```
Alembic can also run from a local virtual environment (`pip install -r requirements.txt`, then `python -m alembic ...`). On the development machine, Windows application control blocked `alembic.exe` and one of SQLAlchemy's compiled modules, which is why the commands above run in Docker.

---

## API reference

Interactive version: **http://127.0.0.1:8000/docs**. Raw OpenAPI schema: `/openapi.json`.

### Authentication: HTTP Basic

Protected routes need the email and password with each request (`Authorization: Basic ...`). In Swagger, click **Authorize** and enter your **email as the username**. Wrong email and wrong password give the same `401` message, so the API never reveals which emails have an account.

Basic auth sends credentials with every request, so it must be used over HTTPS outside local development. Token-based auth (JWT) is planned for the next module.

### Auth (`/auth`)

| Method and path | Auth | Success | Errors |
|---|---|---|---|
| `POST /auth/register` `{"email", "password"}` | – | **201** `{"id", "email", "is_active", "is_premium", "tier", "created_at"}` | **409** email already registered · **422** invalid email or password not 8–72 characters |
| `POST /auth/login` | Basic | **200** the user | **401** incorrect email or password · **403** account disabled |

Emails are stored in lowercase. Passwords are stored only as bcrypt hashes and are never returned. New users are always `tier: "free"`, `is_premium: false`: these fields can't be set at registration.

### Short links (`/api`)

| Method and path | Auth | Success | Errors |
|---|---|---|---|
| `POST /api/shorten` | Basic | **201** a link (see below) | **401** · **409** you already shortened this URL (the answer names your existing link), or custom alias already used · **422** invalid field |
| `GET /api/{code}` (short code **or** custom alias) | – (public) | **302** redirect; the visit is recorded and `click_count` goes up by 1 | **404** unknown code · **410** link switched off or expired (no visit recorded) |

`POST /api/shorten` body:

| Field | Required | Rules |
|---|---|---|
| `url` | yes | valid `http(s)` URL; you can't shorten the same URL twice (other users can) |
| `tags` | no | up to 10, each 1–50 characters |
| `custom_alias` | no | 3–10 letters, digits, `-` or `_`; must not match any short code or alias; `urls` and `shorten` are reserved |
| `title` / `description` / `favicon` | no | max 255 / 500 / 2048 characters |
| `expires_at` | no | date and time **in the future** |

### Your links (`/api/urls`)

| Method and path | Auth | Success | Errors |
|---|---|---|---|
| `GET /api/urls?limit=20&offset=0` | Basic | **200** your links, newest first (`limit` 1–100) | **401** · **422** bad `limit` / `offset` |
| `GET /api/urls/stats` | Basic | **200** stats (see below) | **401** |
| `GET /api/urls/{id}` | Basic | **200** one link | **401** · **404** not found or not yours |
| `PATCH /api/urls/{id}` | Basic | **200** the updated link | **400** nothing sent, or nothing would change · **401** · **404** · **409** alias taken, or you already have a link for the new URL · **422** |
| `DELETE /api/urls/{id}` | Basic | **204** (its clicks and tag links are deleted too) | **401** · **404** |

`PATCH` only changes the fields you send:
- **leave a field out** to keep it,
- send **`null`** to clear an optional field (`custom_alias`, `title`, `description`, `favicon`, `expires_at`),
- `url`, `tags` and `is_active` can't be `null`; `"tags": []` removes all tags, and a new list replaces the old one,
- `"is_active": false` switches the link off (it answers **410**); `true` switches it back on,
- only fields whose value really differs are saved. An empty body `{}` answers **400** "Send at least one field to update", and a body whose values all equal the current ones answers **400** "Nothing to update". Tags are compared after tidying, in any order.

A link looks like:
```json
{
  "id": 1,
  "short_code": "aB3xY9",
  "short_url": "http://127.0.0.1:8000/api/aB3xY9",
  "original_url": "https://www.python.org/",
  "custom_alias": "my-cv",
  "alias_url": "http://127.0.0.1:8000/api/my-cv",
  "title": "Python",
  "description": "Docs",
  "favicon": "https://www.python.org/favicon.ico",
  "tags": ["learning"],
  "click_count": 3,
  "is_active": true,
  "expires_at": "2026-12-19T13:00:00Z",
  "created_at": "2026-11-19T13:00:00Z"
}
```

Stats look like this (lists shortened):
```json
{
  "total_urls": 2,
  "total_clicks": 7,
  "top_urls": [{"short_code": "GoDhSr", "original_url": "https://a.com/", "clicks": 4}],
  "clicks_last_7_days": [{"day": "2026-11-20", "clicks": 7}],
  "urls_per_tag": [{"tag": "work", "urls": 1}],
  "clicks_per_ip_address": [{"ip_address": "196.216.180.xxx", "clicks": 2}, {"ip_address": "102.176.65.xxx", "clicks": 1}],
  "clicks_per_user_agent": [{"user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/142.0 ...", "clicks": 4}],
  "clicks_per_country": [{"country": "Ghana", "clicks": 4}, {"country": "Unknown", "clicks": 1}],
  "clicks_per_city": [{"city": "Accra (Osu Klottey)", "country": "Ghana", "clicks": 3}, {"city": "Kumasi", "country": "Ghana", "clicks": 1}],
  "clicks_per_referrer": [{"referrer": "Direct", "clicks": 3}, {"referrer": "https://twitter.com/ama/status/1", "clicks": 2}]
}
```
- The five `clicks_per_...` lists show the **top 10**, most visits first, for **your links only**.
- **IP addresses are partly hidden** in stats (`196.216.180.xxx`, or the second half of an IPv6 address) to protect visitors; the full address stays in the database. Two different visitors on the same network can therefore appear as two rows with the same hidden address.
- Empty values are grouped as **"Unknown"** (user agent, country, city) or **"Direct"** (referrer: the link was typed or pasted).

Tags are trimmed, lowercased and de-duplicated (`[" Shopping", "shopping"]` → `["shopping"]`). Tag names are shared between users: there is one `shopping` row in `tags`.

### What a visit records

Each successful redirect saves one row in `clicks`:

| Column | Taken from |
|---|---|
| `ip_address` | the connection (`request.client.host`); anything that isn't a valid IP is saved as `0.0.0.0` |
| `user_agent` | the `User-Agent` header (empty if missing) |
| `referrer` | the `Referer` header (null if missing) |
| `city`, `country` | looked up from the IP in the offline DB-IP City Lite file ([app/geoip.py](app/geoip.py)); empty when the IP isn't in it |

**Why local tests show "Unknown" for country and city.** When you test from Swagger on your own machine, the request never goes over the internet: Docker forwards it to the API, so the API sees Docker's own **private** address (e.g. `172.18.0.1`). Private addresses are used by millions of networks and belong to no place, so no location file can place them. Real countries and cities appear once the app runs on a server and visitors arrive from **public** IPs. The lookup itself was checked with public IPs (e.g. `102.176.65.1` → Ghana, Kumasi; `8.8.8.8` → United States, Mountain View). City-level results are approximate.

### `GET /health`

| Status | Body |
|---|---|
| **200** | `{"status": "ok", "env": "development"}` |

### Error format

Every error has the same JSON shape, produced by the global exception handlers in [app/errors.py](app/errors.py):

```json
{ "status_code": 410, "message": "This short link has expired" }
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
2026-11-19 16:30:04,513 INFO app.middleware: POST /api/shorten -> 201 (23.4 ms)
2026-11-19 16:30:04,523 INFO app.middleware: GET /api/aB3xY9 -> 302 (2.5 ms)
```

---

## Demo walkthrough

### 1. Start and migrate
```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
```
**Show:** in pgAdmin (`127.0.0.1:5433`) or with `\dt`, the tables `users`, `urls`, `clicks`, `tags`, `url_tags` and `alembic_version`.

### 2. Register two users
In Swagger (**http://127.0.0.1:8000/docs**), use **POST /auth/register** twice: `ama@mail.com` and `kofi@mail.com`, both with `secret123` → **201**, with `tier: "free"`.
Register `Ama@Mail.com` again → **409** (emails are compared in lowercase).

**Show:** `users` stores `$2b$12$...` hashes, never the password.

### 3. Log in as Ama
Click **Authorize** and enter `ama@mail.com` / `secret123`. Call **POST /auth/login** → **200**.

### 4. Create links
**POST /api/shorten**:
```json
{ "url": "https://www.python.org", "custom_alias": "my-cv", "title": "Python", "tags": ["learning"] }
```
```json
{ "url": "https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702", "tags": ["shopping", "books"] }
```
→ **201** each time. Try the alias `my-cv` again → **409**. Shorten `https://www.python.org` again → **409** "You already shortened this URL: …". Log out of Swagger and try again → **401**.

### 5. Open the links
Paste a `short_url` **and** the `alias_url` into the **browser's address bar** (Swagger cannot follow redirects to other websites). Both redirect.
**Show:** each visit adds a row to `clicks` (IP, browser, referrer, country, city), and `click_count` on the link goes up. Locally, country and city are empty: see [why](#what-a-visit-records).

### 6. Manage the links
- **GET /api/urls**: both links, newest first, with `tags` and `click_count`.
- **PATCH /api/urls/{id}** with `{"tags": ["work"]}`: only the tags change. Send the same body again → **400** "Nothing to update". Send `{}` → **400** "Send at least one field to update".
- **GET /api/urls/stats**: totals, top links, clicks per day, links per tag, and the top IPs (partly hidden), browsers, countries, cities and referrers.

### 7. Switch off and expire
- **PATCH** `{"is_active": false}` → opening the link gives **410**, and `click_count` doesn't change. **PATCH** `{"is_active": true}` → it works again.
- **PATCH** `{"expires_at": null}` removes an expiry date. An expiry in the past is refused with **422**.

### 8. Ownership
Authorize as `kofi@mail.com`. **GET /api/urls** → `[]`. **GET**, **PATCH** or **DELETE** one of Ama's ids → **404**.

### 9. Delete
As Ama, **DELETE /api/urls/{id}** → **204**. **Show:** its rows in `clicks` and `url_tags` are gone too (`ON DELETE CASCADE`), and the tags themselves stay.

### 10. Migrations
```bash
docker compose exec api alembic downgrade -1    # removes the one-link-per-URL rule
docker compose exec api alembic upgrade head    # and adds it back
docker compose exec api alembic current         # 81f75907bc05 (head)
```

### 11. Production profile
```bash
docker compose down
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
docker compose exec api alembic upgrade head
```
**Show:** `Starting gunicorn` and **4×** `Booting worker`. `/health` → `{"status": "ok", "env": "production"}`. All workers share the same PostgreSQL database.

---

## Design decisions

**ORM only, no raw SQL in the application.**
Every query is built with SQLAlchemy (`select`, `where`, `join`, `group_by`, `func.count`, `func.sum`, `update`) inside a repository. SQL text appears only in `CHECK` constraint expressions, in the migrations, and in manual `EXPLAIN` checks.

**One session per request.**
`get_db()` opens a session, lends it to the request, and always closes it in `finally`. Anything not committed is rolled back. FastAPI caches `get_db` within a request, so the user, URL and tag repositories in the same request share one session and one transaction. For example, creating a link with new tags is a single `commit()`, and so is recording a visit together with its counter update.

**Session settings.**
`expire_on_commit=False` lets a route return an object after `commit()` without another query. `autoflush=False` means nothing is sent to the database before we commit. `pool_pre_ping=True` replaces dead connections, for example after a database restart.

**Stored click counter.**
Suggested in code review; see [Stored click counter](#stored-click-counter-from-code-review). Reads are frequent and cheap, and the small extra write per visit is atomic.

**Rules in the database.**
Django's `choices` and `PositiveIntegerField` become `CHECK` constraints, and `GenericIPAddressField` becomes PostgreSQL's `INET` type, so invalid values are rejected by the database, not only by Python.

**404 vs 410 on redirect.**
`404` means the code was never known. `410 Gone` means the link exists but is switched off or expired. Neither records a visit.

**Updates that tell "left out" from "null", and say when nothing changes.**
`PATCH` uses Pydantic's `exclude_unset`, so a field that isn't sent is kept, while `null` clears it. This is needed to remove an alias or an expiry date. The sent values are then compared with the stored ones, and only real differences are saved. If there are none, the answer is **400** instead of a misleading **200**.

**One link per URL per user.**
Shortening a URL you already have answers **409** and names your existing link, instead of creating a second code for the same page. The app checks first, and the unique index on `(user_id, md5(original_url))` is the final guarantee: tested with 5 identical requests at once, one link was created and four got **409**. When the database refuses a save, the app reads which rule refused it, so a duplicate URL and a taken alias get the right message.

**Offline location lookup.**
Country and city come from a local file (DB-IP City Lite, read with `maxminddb`), not from an online service: visitors' IPs never leave the server, there's no rate limit, and a lookup takes about 0.02 ms. The file is opened once at startup and refreshed monthly with `scripts/download_location_file.py`.

**IP addresses partly hidden in stats.**
An IP address is personal data about the **visitor**, and the stats are read by the **link owner**, a different person. Following least privilege and data minimisation, stats show `196.216.180.xxx`, which is enough to spot repeated visits from one network. The full address stays stored for the service itself.

**HTTP Basic auth for this module.**
It's the simplest correct option: no extra package, no extra table. All authorization goes through one dependency, `get_current_user`, so switching to JWT next module changes only that function. The routes stay the same.

**bcrypt for passwords.**
Hashing goes through `pwdlib`. Argon2 was the first choice, but its compiled module was blocked by Windows application control on the development machine, so bcrypt (also a slow, salted password hash; cost 12 ≈ 0.25 s per hash) is used. bcrypt reads at most 72 bytes, so passwords are limited to 8–72 characters, and longer ones get a clear 422 instead of a server error.

**404 instead of 403 for other users' links.**
The ownership filter is part of the query, so another user's link is indistinguishable from a link that doesn't exist.

**Random codes with a collision check.**
Codes are 6 characters from `a-z`, `A-Z` and `0-9` (62⁶ ≈ 56 billion combinations), generated with the `secrets` module. The service checks that the code isn't used as a short code **or** an alias, and the unique index on `short_code` is the final guarantee.

**Multi-stage Dockerfile.**
Stage 1 installs the packages into a virtual environment. Stage 2 copies only that environment, `app/` and the Alembic files into a clean `python:3.14-slim` image that runs as a non-root user.

**One error format.**
Three handlers in [app/errors.py](app/errors.py) cover HTTP errors, validation errors and unexpected crashes. Clients always get `status_code` + `message`. The handler keeps response headers such as `WWW-Authenticate: Basic`.

---

## Known limitations

- **Basic auth** sends the password on every request and checks it with bcrypt each time (slow on purpose). It's fine for this module, and it's replaced by JWT in the next one.
- **Visitor IP behind Docker or a proxy:** the app sees the address of whatever is directly in front of it. In local Docker that is the Docker network gateway (e.g. `172.18.0.1`), not the real visitor. Behind a trusted reverse proxy, the real IP would be read from `X-Forwarded-For`.
- **Location data:** the IP location file must be downloaded separately and refreshed monthly; city results are approximate, and private IPs (all local tests) are "Unknown".
- **Not filled automatically:** `title`, `description` and `favicon` would need the target page to be fetched; the owner can set them.
- **URL spelling:** duplicates are detected on the URL as normalised by Pydantic (for example `https://python.org` and `https://python.org/` are the same), but not across other spellings such as `http://` vs `https://`, `www.` or extra query parameters. The database rule compares an `md5` fingerprint; two different URLs with the same fingerprint are practically impossible, but would be treated as duplicates.
- **`tier` and `is_premium`** are stored and returned, but no feature depends on them yet (for example, custom aliases for premium users only).
- **Alias vs short code at the same instant:** aliases are unique among aliases, and codes among codes (unique indexes). An alias matching another link's **short code** is checked by the app, so two requests at exactly the same moment could in theory get past that check.
- **New tag race:** if two requests create the same **new** tag name at exactly the same moment, the second one can fail on the unique index. PostgreSQL's `INSERT ... ON CONFLICT DO NOTHING` would remove this.
- **Visits are written synchronously** on each redirect (a click row and a counter update). At very high traffic, they could be buffered (for example in a queue) and written in batches.
- **`offset` pagination** gets slower for very deep pages. Keyset pagination (`WHERE id < last_seen_id`) would keep it constant, and the `(user_id, id)` index already supports it.
