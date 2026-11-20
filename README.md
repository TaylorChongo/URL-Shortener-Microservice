# URL Shortener Microservice

A REST API that turns long URLs into short codes and redirects short codes back to the original URL. Each user has an account and manages **only their own** links: list, search by tag, view, update, switch off or delete, give them a custom alias or an expiry date, and see click statistics. Every visit is recorded with the visitor's IP address, browser, referrer, country and city.

**Module 7** secures the platform: **JWT** login with access and refresh tokens, **role-based access control** (free, premium and admin users), **tier limits** (free accounts: 10 active links, no custom alias, no detailed analytics), **login rate limiting** and **URL input checks**.

It is built with **FastAPI**, stores data in **PostgreSQL** through the **SQLAlchemy 2.x ORM**, manages the schema with **Alembic** migrations, and runs with **Docker Compose**. Interactive **Swagger** documentation is generated automatically.

```
POST /api/v1/auth/register   {"email": "ama@mail.com", "password": "secret123"}     → 201
POST /api/v1/auth/login      username=ama@mail.com&password=secret123 (form)         → 200  {"access_token", "refresh_token", ...}
POST /api/v1/urls            {"url": "https://www.python.org", "tags": ["docs"]}      → 201  {"short_url": "http://127.0.0.1:8000/aB3xY9", ...}
GET  /aB3xY9                 (public)                                               → 302  redirect, visit recorded
GET  /api/v1/analytics/aB3xY9   (premium)                                           → 200  visits per day, countries, cities, ...
```

---

## Contents

1. [Tech stack](#tech-stack)
2. [Why FastAPI instead of Flask / Django](#why-fastapi-instead-of-flask--django)
3. [Architecture](#architecture)
4. [Security and access control (module 7)](#security-and-access-control-module-7)
5. [Database and ORM](#database-and-orm)
6. [Project structure](#project-structure)
7. [Configuration](#configuration)
8. [Running the project](#running-the-project)
9. [API reference](#api-reference)
10. [Demo walkthrough](#demo-walkthrough)
11. [Design decisions](#design-decisions)
12. [Known limitations](#known-limitations)

---

## Tech stack

| Tool | Purpose |
|---|---|
| Python 3.14 | Language (the lab requires 3.11+) |
| FastAPI | Web framework, validation, OpenAPI docs, OAuth2 password flow |
| Pydantic | Request and response validation, URL checks |
| PostgreSQL 18 | Database |
| SQLAlchemy 2.1 | ORM: models, relationships, queries (no raw SQL in the app) |
| Alembic | Database migrations |
| psycopg 3 | PostgreSQL driver |
| PyJWT | Creates and checks the JWT access and refresh tokens |
| pwdlib + bcrypt | Password hashing |
| slowapi | Rate limiting on the login endpoint |
| maxminddb + DB-IP City Lite | Offline IP → country and city lookup for visits |
| python-decouple | Reads configuration from environment variables / `.env` |
| Gunicorn + Uvicorn workers | Production server with several worker processes |
| Docker + Docker Compose | Containers for the app and PostgreSQL |

---

## Why FastAPI instead of Flask / Django

The labs are written for Flask (module 5) and Django REST Framework (modules 6–7). This project uses FastAPI throughout, and every requirement has a direct FastAPI equivalent:

| Lab requirement | This project (FastAPI) | Where |
|---|---|---|
| Application factory | `create_app()` | [app/main.py](app/main.py) |
| Blueprints / DRF routers | `APIRouter` groups under `/api/v1`: `auth`, `urls`, `analytics`, `admin`, plus the root redirect | [app/routes.py](app/routes.py) |
| Dependency injection | FastAPI's built-in `Depends()` | [app/dependencies.py](app/dependencies.py) |
| Swagger (Flask-RESTX / drf-spectacular) | FastAPI's built-in OpenAPI + Swagger UI at `/docs` | automatic |
| Serializers / Marshmallow | Pydantic models | [app/schemas.py](app/schemas.py) |
| Django ORM / Flask-SQLAlchemy | SQLAlchemy 2.x (engine, session per request) | [app/database.py](app/database.py) |
| Django migrations / Flask-Migrate | Alembic | [alembic/](alembic/) |
| Django model managers | Repository classes, one per model | [app/repositories.py](app/repositories.py) |
| Custom user model (`AbstractUser`) | `User` SQLAlchemy model, created before the first migration | [app/models.py](app/models.py) |
| Field `choices` / `PositiveIntegerField` | `CHECK` constraints enforced by PostgreSQL | [app/models.py](app/models.py) |
| `GenericIPAddressField` | PostgreSQL's native `INET` type | [app/models.py](app/models.py) |
| `djangorestframework-simplejwt` | PyJWT + FastAPI's `OAuth2PasswordBearer` / `OAuth2PasswordRequestForm` | [app/security.py](app/security.py), [app/dependencies.py](app/dependencies.py) |
| DRF permission `IsOwnerOrReadOnly` | The owner filter inside every link query (other users' links are 404) | [app/routes.py](app/routes.py) `get_own_url_or_404` |
| DRF permission classes (roles) | Dependencies `require_premium`, `require_admin` | [app/dependencies.py](app/dependencies.py) |
| DRF throttling | slowapi `@limiter.limit("5/minute")` | [app/rate_limit.py](app/rate_limit.py) |
| Django management command | `python -m app.manage set-tier ...` | [app/manage.py](app/manage.py) |
| Django password hashing | pwdlib + bcrypt | [app/security.py](app/security.py) |
| Global exception handler | `app.add_exception_handler(...)` | [app/errors.py](app/errors.py) |
| Request logging middleware | `BaseHTTPMiddleware` | [app/middleware.py](app/middleware.py) |
| WSGI server (Gunicorn) | Gunicorn managing ASGI Uvicorn workers | [Dockerfile](Dockerfile) |

**About OpenAPI:** FastAPI generates **OpenAPI 3.1**, the newer version of the 3.0 standard the labs mention. Swagger UI fully supports it.

---

## Architecture

### Overview

```mermaid
flowchart LR
    client["Client<br/>browser · Swagger UI · curl"]

    subgraph compose["Docker Compose"]
        subgraph api["api container (FastAPI)"]
            mw["Logging middleware<br/>+ error handlers"]
            authr["/api/v1/auth<br/>register · login · refresh<br/>(login: rate limited)"]
            urlsr["/api/v1/urls<br/>create · list · detail<br/>update · delete · stats"]
            anr["/api/v1/analytics<br/>(premium)"]
            admr["/api/v1/admin<br/>(admin)"]
            redir["/{short_code}<br/>public redirect"]
            guard["Dependencies<br/>get_current_user (JWT)<br/>require_premium · require_admin"]
            svc["UrlShortenerService<br/>codes · aliases · tier limits · visits"]
            repo["Repositories<br/>all ORM queries"]
            geo["geoip.py<br/>IP → country, city"]
        end
        db[("PostgreSQL 18<br/>users · urls · clicks<br/>tags · url_tags")]
    end
    file[("data/dbip-city-lite.mmdb<br/>(read-only)")]

    client --> mw
    mw --> authr & urlsr & anr & admr & redir
    urlsr & anr & admr --> guard
    authr & urlsr & anr & admr & redir --> svc
    svc --> repo
    authr & urlsr & anr & admr --> repo
    repo -->|"SQLAlchemy session<br/>(one per request)"| db
    svc --> geo
    geo --> file
```

### Request flow

```
                Client (browser / Swagger UI / curl)
                              │
                              ▼
            ┌──────────────────────────────────────────┐
            │  Logging middleware                      │  logs method, path, status, time
            │  ┌────────────────────────────────────┐  │
            │  │  Exception handlers                │  │  every error → {"status_code", "message"}
            │  │  ┌──────────────────────────────┐  │  │
            │  │  │  Routes (APIRouter)          │  │  │  validate input with Pydantic (incl. URL checks)
            │  │  └──────────────┬───────────────┘  │  │
            │  └─────────────────┼──────────────────┘  │
            └────────────────────┼─────────────────────┘
                                 │  Depends(get_current_user)   ← "Authorization: Bearer <access token>"
                                 │  Depends(require_premium / require_admin)  ← role check (403)
                                 │  Depends(get_url_repository) ← one DB session per request
                                 ▼
     UrlShortenerService (codes, aliases, tier limits, visits)   /   Repositories (all ORM queries)
                                 │
                                 ▼
                     SQLAlchemy Session → PostgreSQL
```

### Layers

| Layer | File | Responsibility |
|---|---|---|
| App factory | `main.py` | Builds the app and plugs in routers, middleware, error handlers and the rate limiter |
| Routes | `routes.py` | HTTP only: read the request, call a repository or service, return the response |
| Schemas | `schemas.py` | The shape of requests, responses and errors, plus the URL safety checks |
| Service | `services.py` | Business logic: unique codes, alias and duplicate checks, **tier limits**, recording visits |
| Security | `security.py` | Password hashing, creating and reading JWT tokens |
| Dependencies | `dependencies.py` | Builds repositories, reads the access token (`get_current_user`), role guards (`require_premium`, `require_admin`) |
| Rate limit | `rate_limit.py` | The slowapi limiter used on login |
| Location | `geoip.py` | Looks up an IP's country and city in the offline location file |
| Repositories | `repositories.py` | **Every database query**, one class per model (the "managers") |
| Models | `models.py` | Tables, columns, constraints, indexes and relationships |
| Database | `database.py` | Engine (connection pool), session factory, `Base`, `get_db()` |
| Admin command | `manage.py` | `set-tier` from the terminal (to create the first admin) |
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

## Security and access control (module 7)

### JWT authentication

Logging in once returns **two tokens**:

| Token | Lifetime | Used for |
|---|---|---|
| **Access token** | 30 minutes (`ACCESS_TOKEN_MINUTES`) | Sent with every request: `Authorization: Bearer <access_token>` |
| **Refresh token** | 7 days (`REFRESH_TOKEN_DAYS`) | Sent only to `POST /api/v1/auth/refresh` to get a new access token without the password |

Each token is a JWT signed with `JWT_SECRET_KEY` (HS256). Its content is only:
```json
{"sub": "10", "type": "access", "iat": 1795187916, "exp": 1795189716}
```
- **`sub`**: the user's id. **`exp`**: expiry, checked by PyJWT. **No password or personal data** is inside: the content is readable by anyone, only the signature is secret.
- **`type`**: `access` or `refresh`. A refresh token can't be used to call the API, and an access token can't be used to refresh.
- A **tampered** token (for example a changed user id) no longer matches its signature and is refused (401).
- `get_current_user` also reloads the user on every request, so a **disabled** account (403) or deleted account (401) stops working at once, even with a valid token.

Login follows the **OAuth2 password flow** (form fields `username` = email, `password`), so Swagger's **Authorize** button shows a login form and attaches the token to every request automatically. Because protected routes now check a token instead of a password, bcrypt runs only at login.

### Roles and tiers (RBAC)

| What | Free | Premium | Admin |
|---|---|---|---|
| Manage their own links | ✅ | ✅ | ✅ |
| **Active links** (switched on and not expired) | **max 10** | unlimited | unlimited |
| **Custom alias** | ❌ 403 | ✅ | ✅ |
| `GET /api/v1/urls/stats` | totals only (visitor lists `null`) | totals + visitor lists | totals + visitor lists |
| **`GET /api/v1/analytics/{short_code}`** | ❌ 403 | ✅ own links | ✅ any link |
| Read, update, delete **other users'** links | ❌ 404 | ❌ 404 | ✅ |
| `/api/v1/admin/...` (list users, change tier, disable account) | ❌ 403 | ❌ 403 | ✅ |

Where each rule is enforced:
- **Owner only** (the spec's `IsOwnerOrReadOnly`): `get_own_url_or_404` looks up a link with `WHERE (short_code = ? OR custom_alias = ?) AND user_id = <logged-in user>`. Someone else's link is indistinguishable from one that doesn't exist (404), so nobody can learn that it exists. Admins skip the owner filter. Short links themselves stay **public**: anyone can open them.
- **Premium features**: the `require_premium` dependency (403 for free accounts).
- **Admin endpoints**: the `require_admin` dependency on every admin route (403 otherwise).
- **Tier limits**: `check_can_add_active_link` and `check_can_use_alias` in [app/services.py](app/services.py), called when a link is created, and when an update would **bring a link back to life** (switched on again, or its expiry removed or extended) or add an alias. Removing an alias is always allowed.
- **`is_premium` follows the tier**: `premium` and `admin` → `true`, `free` → `false`, set together so they can never disagree.

How someone becomes premium or admin (there is no payment system in this project):
```bash
docker compose exec api python -m app.manage set-tier ama@mail.com admin     # terminal: creates the first admin
```
Then an admin can change other users with `PATCH /api/v1/admin/users/{user_id}` `{"tier": "premium"}`. An admin can't demote or disable their **own** account, so the system always keeps an admin.

### Rate limiting

`POST /api/v1/auth/login` accepts **5 attempts per minute** per visitor address (`LOGIN_RATE_LIMIT`). Every attempt counts, right or wrong, so a password-guessing program is stopped almost immediately. The 6th attempt gets:
```json
{"status_code": 429, "message": "Too many attempts (5 per 1 minute): try again in a minute"}
```
with a `Retry-After: 60` header. Counts are kept in memory (see [Known limitations](#known-limitations)).

### Secure password storage

Passwords are hashed with **bcrypt** (cost 12, about 0.25 s per hash, salted) and never stored or returned in plain text. Wrong email and wrong password give the **same** 401 message, so the login can't be used to find out who has an account.

### URL input checks

Every long URL, on create and on update, goes through `SafeHttpUrl` ([app/schemas.py](app/schemas.py)): trimmed, then checked. Refused URLs get **422** with a clear message:

| Refused | Example | Why |
|---|---|---|
| Not `http`/`https` | `javascript:alert(1)`, `ftp://…` | can't be a web page; `javascript:` links are an attack |
| Longer than 2048 characters | | protects the database and the app |
| Username or password inside | `https://admin:secret@site.com` | hides where a link really goes, and leaks credentials |
| One of **our own** short links | `http://127.0.0.1:8000/aB3xY9` | a short link to a short link can loop |
| Local names | `localhost`, `*.local`, `*.internal` | they point inside a network |
| Private and special IPs | `192.168.1.1`, `10.0.0.5`, `[::1]`, `169.254.169.254` | prevents using our server to reach internal machines (SSRF), which matters once module 9 fetches pages |

Disguised addresses such as `http://2130706433/` or `http://0x7f.0.0.1/` are normalised by the URL parser to `127.0.0.1` before the check, so they're refused too.

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
        boolean is_premium "default false, follows tier"
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

- **Custom user model.** FastAPI has no built-in user, so `User` is our own model (the equivalent of a Django custom user extending `AbstractUser`). It was written **before the first migration**, so `urls.user_id` could reference it from the start. Of `AbstractUser`'s fields, it keeps what the app needs: `email`, `is_active`, `created_at` (≈ `date_joined`), plus `is_premium` and `tier`, which are the roles used by module 7.
- **Database-side defaults.** `created_at`, `clicked_at`, `is_active`, `is_premium`, `tier` and `click_count` use `server_default`, so the rule lives in the table itself and also applies to rows inserted outside the app.
- **Rules live in the database**, not only in Python: `NOT NULL`, `UNIQUE`, foreign keys, `CASCADE`, `CHECK` and the `INET` type are enforced by PostgreSQL. For example, two people registering the same email at the same moment can't both succeed, and `tier = 'gold'` is refused even when typed directly in pgAdmin.
- **Relationships** (`user.urls`, `url.owner`, `url.clicks`, `url.tags`, `tag.urls`) use `back_populates`, so both sides stay in sync. `passive_deletes=True` lets PostgreSQL's `ON DELETE CASCADE` remove children instead of the ORM loading and deleting them one by one.
- Module 7 needed **no schema change**: `alembic check` reports "No new upgrade operations detected".

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
| `UserRepository` | `get_by_email`, `get_by_id`, `create`, `list_all`, `update` (keeps `is_premium` in step with `tier`) |
| `TagRepository` | `get_or_create(names)`: cleans names (`clean_tag_names`: trimmed, lowercase, no repeats), then finds the existing ones in **one** `IN (...)` query and creates the rest |
| `URLRepository` | `code_exists` (short code **or** alias), `get_user_link_for_url` (duplicate check), `create`, `get_by_code`, `get_for_user` (owner filter), `list_for_user` (pagination + tag filter), `update` (only the fields that changed), `delete`, `add_click`, `count_active_urls` (tier limit), plus the stats queries, which work for **all of a user's links or one link** (`only_these_clicks`) |

**Ownership is part of every query.** `get_for_user` filters on the code **and** `URL.user_id`. The owner is always taken from the access token, never from the request body.

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

The `clicks` table is kept: it holds *when* and *from where* (IP, browser, referrer, country, city), which the per-day and per-place statistics need.

### Query optimization

**No N+1 queries.** Every page uses a **constant number of queries**, whatever the number of links or visits:

| Route | Queries | How |
|---|---|---|
| `GET /api/v1/urls` (also with `?tag=`) | 2 | the page of links (with their stored `click_count`) · `selectinload(URL.tags)` loads all their tags in one query |
| `GET /api/v1/urls/{short_code}` | 2 | same, for one link |
| `GET /api/v1/urls/stats` | 5 (free) / 10 (premium) | one aggregate query per figure; free accounts skip the 5 visitor lists |
| `GET /api/v1/analytics/{short_code}` | 8 | the link (2) · visits per day (1) · 5 visitor lists |

These counts exclude the login check. Measured with SQLAlchemy's `before_cursor_execute` event. Without `selectinload`, the list made `1 + N` queries (measured: 4 queries for 3 links, so a 100-link page would need 101).

Other details:
- `code_exists` selects only `URL.id`, not the whole row.
- Saving a user is a single `INSERT ... RETURNING id, created_at`, with no extra reload query.
- Pagination (`limit` 1–100, `offset`) keeps responses small.
- Tag search uses `URL.tags.any(Tag.name == ...)`, which SQLAlchemy turns into `EXISTS (SELECT 1 FROM tags, url_tags WHERE ...)`, using the `url_tags` primary key.
- Looking up a link by short code **or** alias uses the two unique indexes.
- The duplicate check compares `md5(original_url)`, so it can use the `(user_id, md5(original_url))` index; it also compares the full text to be certain.
- The free-tier limit counts active links with one `COUNT` query (`count_active_urls`), using the `(user_id, id)` index.
- Per-link click statistics filter on `clicks.url_id` directly, with no join, using the `(url_id, clicked_at)` index.

### Indexes, and how they were checked

Indexes exist for the columns the app actually **searches by**: email at login, `short_code` and `custom_alias` on every redirect, owner on every list, `url_id` + date when counting clicks per day, tag name, and owner + URL when checking for duplicates.

The duplicate rule indexes `md5(original_url)` (a 32-character fingerprint) instead of the URL itself, so the index stays small however long the URLs are.

Migration 4 reshaped two of them to fit the real queries. They were measured with `EXPLAIN ANALYZE` on generated test data, comparing the old and new indexes:

| Query | Old index | New index | Result |
|---|---|---|---|
| A user's 20 newest links (`WHERE user_id = ? ORDER BY id DESC LIMIT 20`): small user, 100,000 other rows in the table | `ix_urls_user_id (user_id)` | `ix_urls_user_id_id (user_id, id)` | Old plan walked the primary key backwards and **discarded 100,000 rows**. New plan reads the user's rows already in order: **0 discarded**. |
| One link's clicks in the last 7 days (`WHERE url_id = ? AND clicked_at >= ?`) | `ix_clicks_url_id (url_id)` | `ix_clicks_url_id_clicked_at (url_id, clicked_at)` | Old plan read all 20 clicks and **filtered out 18**. New plan reads only the 2 matching rows (2 heap blocks instead of 20). |

A composite index still serves queries on its **first** column alone (like a phone book sorted by surname then first name), so the old single-column indexes were removed instead of kept alongside.

### Aggregations

`GET /api/v1/urls/stats` (all of your links):

| Figure | ORM query | Who |
|---|---|---|
| `total_urls` | `func.count(URL.id)` filtered by owner | everyone |
| `total_clicks` | `func.sum(URL.click_count)` filtered by owner (`coalesce` → 0 when there are no links) | everyone |
| `top_urls` | links ordered by the stored `click_count`, `limit(5)` | everyone |
| `clicks_last_7_days` | `group_by(func.date(Click.clicked_at))` over the last 7 days | everyone |
| `urls_per_tag` | `join` through `url_tags`, `group_by(Tag.name)` | everyone |
| `clicks_per_ip_address` · `clicks_per_user_agent` · `clicks_per_country` · `clicks_per_referrer` | `clicks_grouped_by(column)`, top 10 | premium, admin |
| `clicks_per_city` | `group_by(Click.city, Click.country)`, top 10 (so two towns with the same name stay apart) | premium, admin |

`GET /api/v1/analytics/{short_code}` (one link, premium) uses the same queries filtered on that link, plus visits per day over `?days=` (1–365, default 30), with one entry per day, including days with 0 visits, so it can be drawn as a chart.

`clicks_grouped_by` is one reusable query, "count the clicks per value of a column, most first, top N": `select(column, count(Click.id)).<only these clicks>.group_by(column).order_by(count desc).limit(N)`. Empty values come back as one group and are shown as "Unknown" (or "Direct" for the referrer).

---

## Project structure

```
url-shortener-microservice/
├── app/
│   ├── __init__.py
│   ├── main.py             # create_app() factory, routers, error handlers, rate limiter
│   ├── config.py           # settings from environment variables
│   ├── database.py         # engine, SessionLocal, Base, get_db()
│   ├── models.py           # User, URL, Click, Tag, url_tags, TIERS
│   ├── repositories.py     # UserRepository, TagRepository, URLRepository
│   ├── security.py         # password hashing, JWT create/read
│   ├── services.py         # UrlShortenerService, tier limits
│   ├── geoip.py            # find_location(ip) → (country, city)
│   ├── schemas.py          # Pydantic models, SafeHttpUrl (URL checks)
│   ├── dependencies.py     # repositories, get_current_user (JWT), require_premium, require_admin
│   ├── rate_limit.py       # slowapi limiter
│   ├── routes.py           # /api/v1/{auth,urls,analytics,admin} and the /{short_code} redirect
│   ├── manage.py           # python -m app.manage set-tier <email> <tier>
│   ├── errors.py           # global exception handlers (incl. 429)
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
| `BASE_URL` | `http://127.0.0.1:8000` | Used to build the full short link (`BASE_URL/<short_code>`), and to refuse our own short links as long URLs |
| `POSTGRES_USER` | `shortener` | Database user created by the Postgres container on first start |
| `POSTGRES_PASSWORD` | `change-me` | Its password |
| `POSTGRES_DB` | `shortener` | Database created on first start |
| `DATABASE_URL` | `postgresql+psycopg://shortener:change-me@127.0.0.1:5433/shortener` | Used by **local** tools (Alembic, scripts). Docker Compose builds its own URL for the API (`@db:5432`). Required: the app refuses to start without it. |
| `JWT_SECRET_KEY` | *(a long random string)* | **Required.** Signs the tokens. Keep it secret; anyone with it could create tokens. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(64))"`. Changing it logs everyone out. |
| `ACCESS_TOKEN_MINUTES` | `30` | Access token lifetime |
| `REFRESH_TOKEN_DAYS` | `7` | Refresh token lifetime |
| `LOGIN_RATE_LIMIT` | `5/minute` | Login attempts allowed per visitor address |
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
- Python 3.11+ (only to run the download script)

### 1. Clone and configure
```bash
git clone <your-repo-url>
cd url-shortener-microservice
cp .env.example .env          # on Windows PowerShell: copy .env.example .env
```
Open `.env` and:
- set a real `POSTGRES_PASSWORD`, using the same value inside `DATABASE_URL`,
- set `JWT_SECRET_KEY` to a long random string: `python -c "import secrets; print(secrets.token_urlsafe(64))"`.

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

### 5. Create the first admin
Register an account (`POST /api/v1/auth/register` in Swagger), then:
```bash
docker compose exec api python -m app.manage set-tier you@mail.com admin
```
Expected: `you@mail.com is now 'admin' (is_premium=True)`. Use `premium` or `free` the same way.

### 6. Production profile
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
docker compose exec api alembic check                                              # do the models need a new migration?
```
Alembic can also run from a local virtual environment (`pip install -r requirements.txt`, then `python -m alembic ...`). On the development machine, Windows application control blocked `alembic.exe` and one of SQLAlchemy's compiled modules, which is why the commands above run in Docker.

---

## API reference

Interactive version: **http://127.0.0.1:8000/docs**. Raw OpenAPI schema: `/openapi.json`.

**Using Swagger:** click **Authorize**, enter your **email** as `username` and your password, leave the other fields empty, then **Authorize**. Swagger logs in through `/api/v1/auth/login` and attaches the access token to every request. After 30 minutes, authorize again or call `/api/v1/auth/refresh`.

Protected routes need `Authorization: Bearer <access_token>`. Without a valid token they answer **401**.

### Auth (`/api/v1/auth`)

| Method and path | Auth | Success | Errors |
|---|---|---|---|
| `POST /api/v1/auth/register` `{"email", "password"}` | – | **201** `{"id", "email", "is_active", "is_premium", "tier", "created_at"}` | **409** email already registered · **422** invalid email or password not 8–72 characters |
| `POST /api/v1/auth/login` form: `username` (email), `password` | – | **200** `{"access_token", "refresh_token", "token_type": "bearer", "expires_in": 1800}` | **401** incorrect email or password · **403** account disabled · **429** more than 5 attempts per minute |
| `POST /api/v1/auth/refresh` `{"refresh_token"}` | – | **200** `{"access_token", "token_type", "expires_in"}` | **401** invalid, expired or wrong-type token · **403** account disabled |

Emails are stored in lowercase. Passwords are stored only as bcrypt hashes and are never returned. New users are always `tier: "free"`: the tier can't be set at registration.

With curl:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login -d "username=ama@mail.com&password=secret123"
curl http://127.0.0.1:8000/api/v1/urls -H "Authorization: Bearer <access_token>"
```

### Your links (`/api/v1/urls`)

A link is identified by its **short code** (or its custom alias) in the path.

| Method and path | Auth | Success | Errors |
|---|---|---|---|
| `POST /api/v1/urls` | token | **201** a link (see below) | **401** · **403** free-tier limit (10 active links, or custom alias) · **409** you already shortened this URL (the answer names your existing link), or alias already used · **422** invalid field or unsafe URL |
| `GET /api/v1/urls?limit=20&offset=0&tag=books` | token | **200** your links, newest first (`limit` 1–100); `tag` filters by tag (case-insensitive) | **401** · **422** |
| `GET /api/v1/urls/stats` | token | **200** stats (see below; visitor lists for premium/admin only) | **401** |
| `GET /api/v1/urls/{short_code}` | token | **200** one link | **401** · **404** not found or not yours |
| `PUT` or `PATCH /api/v1/urls/{short_code}` | token | **200** the updated link | **400** nothing sent, or nothing would change · **401** · **403** free-tier limit · **404** · **409** · **422** |
| `DELETE /api/v1/urls/{short_code}` | token | **204** the link is **switched off** (`is_active: false`, answers 410, history kept) | **400** already switched off · **401** · **404** |
| `DELETE /api/v1/urls/{short_code}?permanent=true` | token | **204** the link is **deleted for good**, with its clicks and tag links | **401** · **404** |

Admins can use the `{short_code}` routes on **any** user's link.

`POST /api/v1/urls` body:

| Field | Required | Rules |
|---|---|---|
| `url` | yes | safe `http(s)` URL (see [URL input checks](#url-input-checks)); you can't shorten the same URL twice (other users can) |
| `tags` | no | up to 10, each 1–50 characters; trimmed, lowercased, de-duplicated |
| `custom_alias` | no | **premium/admin only**; 3–10 letters, digits, `-` or `_`; must not match any short code or alias; `api`, `docs`, `redoc` and `health` are reserved |
| `title` / `description` / `favicon` | no | max 255 / 500 / 2048 characters |
| `expires_at` | no | date and time **in the future** |

`PUT` and `PATCH` behave the same and only change the fields you send:
- **leave a field out** to keep it,
- send **`null`** to clear an optional field (`custom_alias`, `title`, `description`, `favicon`, `expires_at`),
- `url`, `tags` and `is_active` can't be `null`; `"tags": []` removes all tags, and a new list replaces the old one,
- `"is_active": false` switches the link off; `true` switches it back on (free accounts: only if they have fewer than 10 active links),
- only fields whose value really differs are saved. `{}` answers **400** "Send at least one field to update", and a body whose values all equal the current ones answers **400** "Nothing to update".

A link looks like:
```json
{
  "id": 1,
  "short_code": "aB3xY9",
  "short_url": "http://127.0.0.1:8000/aB3xY9",
  "original_url": "https://www.python.org/",
  "custom_alias": "my-cv",
  "alias_url": "http://127.0.0.1:8000/my-cv",
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

Stats look like this (lists shortened). For free accounts, `detailed_analytics` is `false` and the five `clicks_per_...` lists are `null`:
```json
{
  "total_urls": 2,
  "total_clicks": 7,
  "top_urls": [{"short_code": "GoDhSr", "original_url": "https://a.com/", "clicks": 4}],
  "clicks_last_7_days": [{"day": "2026-11-20", "clicks": 7}],
  "urls_per_tag": [{"tag": "work", "urls": 1}],
  "detailed_analytics": true,
  "clicks_per_ip_address": [{"ip_address": "196.216.180.xxx", "clicks": 2}],
  "clicks_per_user_agent": [{"user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/142.0 ...", "clicks": 4}],
  "clicks_per_country": [{"country": "Ghana", "clicks": 4}, {"country": "Unknown", "clicks": 1}],
  "clicks_per_city": [{"city": "Accra (Osu Klottey)", "country": "Ghana", "clicks": 3}],
  "clicks_per_referrer": [{"referrer": "Direct", "clicks": 3}, {"referrer": "https://twitter.com/ama/status/1", "clicks": 2}]
}
```
- The `clicks_per_...` lists show the **top 10**, most visits first.
- **IP addresses are partly hidden** (`196.216.180.xxx`, or the second half of an IPv6 address) to protect visitors; the full address stays in the database.
- Empty values are grouped as **"Unknown"** (user agent, country, city) or **"Direct"** (referrer: the link was typed or pasted).

### Analytics (`/api/v1/analytics`, Premium)

| Method and path | Auth | Success | Errors |
|---|---|---|---|
| `GET /api/v1/analytics/{short_code}?days=30` | token, **premium or admin** | **200** analytics for one link | **401** · **403** free account · **404** not found or not yours · **422** `days` not 1–365 |

```json
{
  "short_code": "aB3xY9",
  "original_url": "https://www.python.org/",
  "total_clicks": 6,
  "days": 7,
  "clicks_per_day": [{"day": "2026-11-14", "clicks": 0}, {"day": "2026-11-15", "clicks": 3}, "...", {"day": "2026-11-20", "clicks": 2}],
  "clicks_per_country": [{"country": "Ghana", "clicks": 4}, {"country": "United States", "clicks": 1}],
  "clicks_per_city": [{"city": "Kumasi", "country": "Ghana", "clicks": 2}],
  "clicks_per_referrer": [{"referrer": "Direct", "clicks": 4}],
  "clicks_per_user_agent": [{"user_agent": "Chrome", "clicks": 3}],
  "clicks_per_ip_address": [{"ip_address": "102.176.65.xxx", "clicks": 2}]
}
```

### Admin (`/api/v1/admin`, admins only)

| Method and path | Success | Errors |
|---|---|---|
| `GET /api/v1/admin/users?limit=20&offset=0` | **200** all users | **401** · **403** not an admin |
| `PATCH /api/v1/admin/users/{user_id}` `{"tier"?, "is_active"?}` | **200** the updated user (`is_premium` follows the tier) | **400** nothing to change, or changing your own account · **401** · **403** · **404** · **422** tier not `free`/`premium`/`admin` |

### Public redirect

| Method and path | Auth | Success | Errors |
|---|---|---|---|
| `GET /{short_code}` (short code **or** custom alias) | – | **302** redirect; the visit is recorded and `click_count` goes up by 1 | **404** unknown code · **410** link switched off or expired (no visit recorded) |

Test redirects in the **browser's address bar**: Swagger's *Try it out* can't follow a redirect to another website ("Failed to fetch"), but the visit is still recorded.

### What a visit records

Each successful redirect saves one row in `clicks`:

| Column | Taken from |
|---|---|
| `ip_address` | the connection (`request.client.host`); anything that isn't a valid IP is saved as `0.0.0.0` |
| `user_agent` | the `User-Agent` header (empty if missing) |
| `referrer` | the `Referer` header (null if missing) |
| `city`, `country` | looked up from the IP in the offline DB-IP City Lite file ([app/geoip.py](app/geoip.py)); empty when the IP isn't in it |

**Why local tests show "Unknown" for country and city.** When you test from Swagger on your own machine, the request never goes over the internet: Docker forwards it to the API, so the API sees Docker's own **private** address (e.g. `172.18.0.1`). Private addresses belong to no place, so no location file can place them. Real countries and cities appear once the app runs on a server and visitors arrive from **public** IPs. The lookup itself was checked with public IPs (e.g. `102.176.65.1` → Ghana, Kumasi; `8.8.8.8` → United States, Mountain View). City-level results are approximate.

### `GET /health`

| Status | Body |
|---|---|
| **200** | `{"status": "ok", "env": "development"}` |

### Error format

Every error has the same JSON shape, produced by the global exception handlers in [app/errors.py](app/errors.py):

```json
{ "status_code": 403, "message": "Free accounts can have at most 10 active links: switch one off or upgrade to Premium" }
```

Validation errors (422) also list each problem:
```json
{
  "status_code": 422,
  "message": "Invalid input",
  "errors": [{ "field": "url", "message": "Private or local IP addresses are not allowed" }]
}
```

| Code | Meaning in this API |
|---|---|
| 400 | nothing to update / already switched off / admin changing their own account |
| 401 | no token, invalid or expired token, wrong email or password |
| 403 | disabled account, free-tier limit, premium feature, admins only |
| 404 | unknown code, or a link that isn't yours |
| 409 | email registered, alias taken, URL already shortened |
| 410 | short link switched off or expired |
| 422 | invalid input, including unsafe URLs |
| 429 | too many login attempts |

Unexpected errors return `500` with `"Something went wrong on our side"`. The full error is written to the logs, never sent to the client.

### Request logs

Every request is logged by the middleware in [app/middleware.py](app/middleware.py):
```
2026-11-20 16:30:04,513 INFO app.middleware: POST /api/v1/urls -> 201 (23.4 ms)
2026-11-20 16:30:04,523 INFO app.middleware: GET /aB3xY9 -> 302 (2.5 ms)
```

---

## Demo walkthrough

### 1. Start, migrate, create an admin
```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
```
In Swagger (**http://127.0.0.1:8000/docs**), **POST /api/v1/auth/register** three accounts with password `secret123`: `ama@mail.com`, `kofi@mail.com`, `boss@mail.com` → **201**, all `tier: "free"`. Then:
```bash
docker compose exec api python -m app.manage set-tier boss@mail.com admin
```

### 2. JWT login
Click **Authorize** → `ama@mail.com` / `secret123`. Or call **POST /api/v1/auth/login** and **show** the `access_token`, `refresh_token` and `expires_in: 1800`. Paste this test account's access token into [jwt.io](https://jwt.io) to show its content: only `sub`, `type`, `iat` and `exp`, no password. (Only do this with test tokens: a real token pasted into a website could be reused until it expires.)
**POST /api/v1/auth/refresh** with the refresh token → a new access token.

### 3. Rate limit
Call **POST /api/v1/auth/login** with a wrong password 6 times in a row → the 6th answers **429** with `Retry-After: 60`.

### 4. Links as a free user (Ama)
- **POST /api/v1/urls** `{"url": "https://www.python.org", "tags": ["learning"]}` → **201**, with a short link at the root, e.g. `http://127.0.0.1:8000/aB3xY9`.
- Same URL again → **409** "You already shortened this URL: …".
- `{"url": "https://example.com", "custom_alias": "my-cv"}` → **403** "Custom aliases are a Premium feature".
- Unsafe URLs → **422**: `http://192.168.1.1/`, `https://admin:pw@site.com`, `http://localhost/`.
- Create links until there are 10 → the 11th answers **403** "Free accounts can have at most 10 active links…". **DELETE** one (switch it off) → the 11th now fits.

### 5. Open a link
Paste a `short_url` into the **browser's address bar** → redirect. **Show:** `click_count` went up, and `clicks` has a row with IP, browser and referrer. A switched-off link answers **410**.

### 6. Manage and search
- **GET /api/v1/urls?tag=learning**: only tagged links.
- **PUT /api/v1/urls/{short_code}** `{"title": "Python docs"}` → **200**. Same body again → **400** "Nothing to update".
- **GET /api/v1/urls/stats** → totals, `detailed_analytics: false`, visitor lists `null`.
- **GET /api/v1/analytics/{short_code}** → **403** "Detailed analytics are a Premium feature".

### 7. Ownership
Authorize as `kofi@mail.com`. **GET**, **PUT** or **DELETE** one of Ama's short codes → **404**. **GET /api/v1/admin/users** → **403** "Admins only".

### 8. Admin
Authorize as `boss@mail.com`.
- **GET /api/v1/admin/users** → all users.
- **PATCH /api/v1/admin/users/{ama's id}** `{"tier": "premium"}` → `tier: premium`, `is_premium: true`.
- **GET /api/v1/urls/{one of Ama's codes}** → **200**: admins can see any link.
- **PATCH** your own user id → **400**.

### 9. Premium (Ama, logged in again)
- `{"url": "https://example.com", "custom_alias": "my-cv"}` → **201**, and `http://127.0.0.1:8000/my-cv` redirects.
- More than 10 active links → allowed.
- **GET /api/v1/urls/stats** → `detailed_analytics: true` with the visitor lists.
- **GET /api/v1/analytics/{short_code}?days=7** → 7 days of visits per day, plus countries, cities, referrers, browsers and IPs.

### 10. Delete for good
**DELETE /api/v1/urls/{short_code}?permanent=true** → **204**. **Show:** its rows in `clicks` and `url_tags` are gone (`ON DELETE CASCADE`), and the tags themselves stay.

### 11. Production profile
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
docker compose exec api alembic upgrade head
```
**Show:** `Starting gunicorn` and **4×** `Booting worker`. `/health` → `{"status": "ok", "env": "production"}`.

---

## Design decisions

**JWT with access and refresh tokens.**
Short-lived access tokens limit the damage if one leaks; the refresh token avoids asking for the password every 30 minutes. Tokens are stateless: the server checks the signature and expiry instead of looking up a session. The `type` claim stops a refresh token being used as an access token. The user is still loaded on each request, so disabling an account takes effect immediately. Login uses FastAPI's OAuth2 password flow so Swagger's Authorize button works out of the box.

**Roles as dependencies.**
`get_current_user` → `require_premium` → `require_admin` build on each other, the FastAPI way of writing DRF permission classes. Each route declares what it needs in its signature, and Swagger lists the 401/403 answers.

**Tier rules in the service layer.**
The 10-link and alias rules live in `services.py` (`check_can_add_active_link`, `check_can_use_alias`), not in the routes, so create and update apply exactly the same rules. "Active" means switched on and not expired, so a free user can make room by switching a link off or letting it expire.

**404 instead of 403 for other users' links.**
The ownership filter is part of the query, so another user's link is indistinguishable from a link that doesn't exist. This is stricter than DRF's `IsOwnerOrReadOnly` (which lets others read): link details, click counts and visitors are private, while the short link itself stays public.

**DELETE switches off by default.**
The spec says "delete or deactivate". A switched-off link answers 410, keeps its history and can be switched back on; `?permanent=true` deletes it for good.

**PUT and PATCH share one handler.**
The spec asks for `PUT`. Both methods change only the fields sent, so existing clients using `PATCH` keep working.

**Rate limiting with slowapi.**
5 login attempts per minute per address, counting every attempt so a guessing program can't tell which one would have worked. The answer uses the same error format, with `Retry-After`.

**URL checks at the edge.**
`SafeHttpUrl` validates every long URL before anything else runs, on create and update. Blocking private and local addresses now avoids SSRF problems when module 9 starts fetching pages.

**Short links at the root, under a versioned API.**
`/aB3xY9` is as short as possible; the API lives under `/api/v1` so a future `v2` can sit next to it. The redirect router is registered last, and `api`, `docs`, `redoc` and `health` are reserved, so short codes never hide the app's own pages.

**ORM only, no raw SQL in the application.**
Every query is built with SQLAlchemy (`select`, `where`, `join`, `group_by`, `func.count`, `func.sum`, `update`, `any`) inside a repository. SQL text appears only in `CHECK` constraint expressions, in the migrations, and in manual `EXPLAIN` checks.

**One session per request.**
`get_db()` opens a session, lends it to the request, and always closes it in `finally`. Anything not committed is rolled back. FastAPI caches `get_db` within a request, so all repositories in the same request share one session and one transaction. For example, recording a visit together with its counter update is a single `commit()`.

**Stored click counter.**
Suggested in code review; see [Stored click counter](#stored-click-counter-from-code-review). Reads are frequent and cheap, and the small extra write per visit is atomic.

**Rules in the database.**
Django's `choices` and `PositiveIntegerField` become `CHECK` constraints, and `GenericIPAddressField` becomes PostgreSQL's `INET` type, so invalid values are rejected by the database, not only by Python.

**One link per URL per user.**
Shortening a URL you already have answers **409** and names your existing link. The app checks first, and the unique index on `(user_id, md5(original_url))` is the final guarantee: tested with 5 identical requests at once, one link was created and four got **409**.

**Offline location lookup and partly hidden IPs.**
Visitors' IPs never leave the server for a location lookup (local DB-IP file, about 0.02 ms per lookup). Stats show IPs as `196.216.180.xxx`: the link owner is a different person from the visitor, so following least privilege they see enough to spot repeated visits, not the exact address.

**bcrypt for passwords.**
Hashing goes through `pwdlib`. Argon2 was the first choice, but its compiled module was blocked by Windows application control on the development machine, so bcrypt (also a slow, salted password hash; cost 12 ≈ 0.25 s per hash) is used. bcrypt reads at most 72 bytes, so passwords are limited to 8–72 characters.

**Multi-stage Dockerfile.**
Stage 1 installs the packages into a virtual environment. Stage 2 copies only that environment, `app/` and the Alembic files into a clean `python:3.14-slim` image that runs as a non-root user.

---

## Known limitations

- **No token revocation:** JWTs are valid until they expire. Logging out happens on the client (forget the tokens); a stolen refresh token works for up to 7 days unless the account is disabled or `JWT_SECRET_KEY` is changed (which logs everyone out). A token blocklist would need shared storage such as Redis (module 8).
- **Rate limit counts per worker:** slowapi keeps counts in each process's memory, so with 4 Gunicorn workers the effective limit is up to 5 attempts per minute **per worker**, and counts reset on restart. Module 8 adds Redis, where the limiter can share its counts (`storage_uri="redis://..."`). Locally, all requests come from Docker's address, so all local logins share one count.
- **Visitor IP behind Docker or a proxy:** the app sees the address of whatever is directly in front of it. In local Docker that is the Docker network gateway (e.g. `172.18.0.1`), not the real visitor. Behind a trusted reverse proxy, the real IP would be read from `X-Forwarded-For`. The rate limit uses the same address.
- **URL checks and DNS:** a normal domain name that points to a private address isn't caught when the link is saved (that would need a DNS lookup). Module 9's preview service should check the resolved address when it fetches a page.
- **Tier changes don't touch existing links:** a user moved from premium back to free keeps their aliases and active links; the limits only apply to new actions.
- **Location data:** the IP location file must be downloaded separately and refreshed monthly; city results are approximate, and private IPs (all local tests) are "Unknown".
- **Not filled automatically:** `title`, `description` and `favicon` would need the target page to be fetched (module 9); the owner can set them.
- **URL spelling:** duplicates are detected on the URL as normalised by Pydantic (for example `https://python.org` and `https://python.org/` are the same), but not across other spellings such as `http://` vs `https://`, `www.` or extra query parameters.
- **Alias vs short code at the same instant:** aliases are unique among aliases, and codes among codes (unique indexes). An alias matching another link's **short code** is checked by the app, so two requests at exactly the same moment could in theory get past that check.
- **New tag race:** if two requests create the same **new** tag name at exactly the same moment, the second one can fail on the unique index. PostgreSQL's `INSERT ... ON CONFLICT DO NOTHING` would remove this.
- **Visits are written synchronously** on each redirect (a click row and a counter update). Module 8 plans to move this to background tasks (Celery).
- **`offset` pagination** gets slower for very deep pages. Keyset pagination (`WHERE id < last_seen_id`) would keep it constant, and the `(user_id, id)` index already supports it.
