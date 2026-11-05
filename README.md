# URL Shortener Microservice

A small REST API that turns long URLs into short codes and redirects short codes back to the original URL.

It is built with **FastAPI**, stores data in **Redis**, and runs with **Docker Compose**. Interactive **Swagger** documentation is generated automatically.

```
POST /api/shorten   {"url": "https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702"}
  → 201  {"short_code": "aB3xY9", "short_url": "http://127.0.0.1:8000/api/aB3xY9", ...}

GET  /api/aB3xY9
  → 302  redirect to https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702
```

---

## Contents

1. [Tech stack](#tech-stack)
2. [Why FastAPI instead of Flask](#why-fastapi-instead-of-flask)
3. [Architecture](#architecture)
4. [Project structure](#project-structure)
5. [Configuration](#configuration)
6. [Running the project](#running-the-project)
7. [API reference](#api-reference)
8. [Demo walkthrough](#demo-walkthrough)
9. [Design decisions](#design-decisions)

---

## Tech stack

| Tool | Purpose |
|---|---|
| Python 3.14 | Language (the lab requires 3.11+) |
| FastAPI | Web framework, validation, OpenAPI docs |
| Pydantic | Request and response validation |
| Redis | Stores `short code → long URL` |
| python-decouple | Reads configuration from environment variables / `.env` |
| Gunicorn + Uvicorn workers | Production server with several worker processes |
| Docker + Docker Compose | Containers for the app and Redis |

---

## Why FastAPI instead of Flask

The lab is written for Flask. This project uses FastAPI, and every Flask requirement has a direct FastAPI equivalent:

| Lab requirement (Flask) | This project (FastAPI) | Where |
|---|---|---|
| Application factory | `create_app()` | [app/main.py](app/main.py) |
| Blueprints | `APIRouter` with the `/api` prefix | [app/routes.py](app/routes.py) |
| Flask-Injector | FastAPI's built-in `Depends()` | [app/dependencies.py](app/dependencies.py) |
| Flask-RESTX + Swagger | FastAPI's built-in OpenAPI + Swagger UI at `/docs` | automatic |
| Pydantic / Marshmallow validation | Pydantic models | [app/schemas.py](app/schemas.py) |
| Global exception handler | `app.add_exception_handler(...)` | [app/errors.py](app/errors.py) |
| Request logging middleware | `BaseHTTPMiddleware` | [app/middleware.py](app/middleware.py) |
| WSGI server (Gunicorn) | Gunicorn managing ASGI Uvicorn workers | [Dockerfile](Dockerfile) |
| python-decouple config | python-decouple | [app/config.py](app/config.py) |
| Application / request context | The `Request` object and `Depends()` are passed into functions directly | routes, middleware, error handlers |

**About OpenAPI:** the lab asks for OpenAPI 3.0. FastAPI generates **OpenAPI 3.1**, the newer version of the same standard. Swagger UI fully supports it.

---

## Architecture

### Request flow

```
                Client (browser / Swagger UI / curl)
                              │
                              ▼
            ┌──────────────────────────────────────┐
            │  Logging middleware                  │  logs method, path, status, time
            │  ┌────────────────────────────────┐  │
            │  │  Exception handlers            │  │  turn errors into JSON
            │  │  ┌──────────────────────────┐  │  │
            │  │  │  Routes (APIRouter /api) │  │  │  validate input with Pydantic
            │  │  └────────────┬─────────────┘  │  │
            │  └───────────────┼────────────────┘  │
            └──────────────────┼───────────────────┘
                               │  Depends(get_shortener_service)
                               ▼
                    UrlShortenerService               generates unique codes
                               │
                               ▼
                         RedisStorage                 save / get / exists
                               │
                               ▼
                             Redis
```

### Layers

| Layer | File | Responsibility |
|---|---|---|
| App factory | `main.py` | Builds the app and plugs in routes, middleware and error handlers |
| Routes | `routes.py` | HTTP only: read the request, call the service, return the response |
| Schemas | `schemas.py` | The shape of requests, responses and errors (and their Swagger examples) |
| Service | `services.py` | Business logic: create a random 6-character code that isn't taken yet |
| Storage | `storage.py` | Where data lives. `RedisStorage` (used) and `InMemoryStorage` (simple dict, for experiments) have the same methods |
| Dependencies | `dependencies.py` | Builds the service and injects it into routes |
| Config | `config.py` | All settings, read from environment variables |

Each layer only talks to the one below it. To switch storage, you change one line in `dependencies.py`. Nothing else changes.

### Docker setup

```
docker-compose.yml
 ├── api    (built from Dockerfile)   port 8000 → your PC
 │     └── connects to redis://redis:6379 (password protected)
 └── redis  (redis:8-alpine)          not exposed to your PC
       └── named volume "redis-data"  data survives restarts
```

---

## Project structure

```
url-shortener-microservice/
├── app/
│   ├── __init__.py
│   ├── main.py             # create_app() factory
│   ├── config.py           # settings from environment variables
│   ├── routes.py           # POST /api/shorten, GET /api/{code}
│   ├── schemas.py          # Pydantic request / response / error models
│   ├── services.py         # UrlShortenerService
│   ├── storage.py          # RedisStorage, InMemoryStorage
│   ├── dependencies.py     # dependency injection provider
│   ├── errors.py           # global exception handlers
│   └── middleware.py       # request logging middleware
├── Dockerfile              # multi-stage production image
├── docker-compose.yml      # development: app + Redis + hot reload
├── docker-compose.prod.yml # production overrides: Gunicorn, 4 workers, no debug
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
| `BASE_URL` | `http://127.0.0.1:8000` | Used to build the full short link. Set it to your real domain when deployed |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis address for **local** runs. Docker Compose overrides it |
| `REDIS_PASSWORD` | `change-me` | Password for the Redis container (Docker only) |

`.env` is listed in `.gitignore`, so real secrets are never committed. Only `.env.example` is in the repository.

**Profiles**

| | Development | Production |
|---|---|---|
| Server | `fastapi dev`, auto-reload | Gunicorn + 4 Uvicorn workers (`WEB_CONCURRENCY`) |
| `DEBUG` | `True` | `False` |
| Code | mounted as a volume (hot reload) | baked into the image |
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
Then open `.env` and set a real `REDIS_PASSWORD`.

### 2. Development (hot reload)
```bash
docker compose up --build
```
Expected at the end of the logs:
```
redis-1  | Ready to accept connections tcp
api-1    | INFO     Application startup complete.
```
- Swagger UI: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health → `{"status":"ok","env":"development"}`

Edit any file in `app/` and save. The logs show `Reloading...` and the change is live, with no rebuild needed.

Stop with `Ctrl+C`, or `docker compose down`.

### 3. Production profile
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build
```
Expected:
```
api-1  | [INFO] Starting gunicorn 26.2.0
api-1  | [INFO] Using worker: uvicorn_worker.UvicornWorker
api-1  | [INFO] Booting worker with pid: 7     (×4)
```
`/health` now returns `{"status":"ok","env":"production"}`.

### 4. Without Docker (optional)
Needs Python 3.11+ and a Redis server on `127.0.0.1:6379`. On Windows, Redis can run through [Memurai](https://www.memurai.com/) or `docker run -p 6379:6379 redis:8-alpine`.
```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
fastapi dev app/main.py
```

### Looking inside Redis (Docker)
```bash
docker compose exec redis redis-cli -a <your REDIS_PASSWORD> KEYS '*'
docker compose exec redis redis-cli -a <your REDIS_PASSWORD> GET <short_code>
```

---

## API reference

Interactive version: **http://127.0.0.1:8000/docs**. Raw OpenAPI schema: `/openapi.json`.

### `POST /api/shorten`: create a short URL

Request:
```json
{ "url": "https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702" }
```

| Status | When | Body |
|---|---|---|
| **201 Created** | Success | `{"short_code": "aB3xY9", "short_url": "http://127.0.0.1:8000/api/aB3xY9", "original_url": "https://www.amazon.com/..."}` |
| **422** | `url` missing, or not a valid `http(s)` URL | see [Error format](#error-format) |

### `GET /api/{code}`: redirect to the original URL

| Status | When | Body |
|---|---|---|
| **302 Found** | Code exists | Redirect. The `Location` header holds the original URL |
| **404 Not Found** | Unknown code | `{"status_code": 404, "message": "Short URL not found"}` |

### `GET /health`: health check

| Status | Body |
|---|---|
| **200** | `{"status": "ok", "env": "development"}` |

### Error format

Every error has the same JSON shape, produced by the global exception handlers in [app/errors.py](app/errors.py):

```json
{ "status_code": 404, "message": "Short URL not found" }
```

Validation errors (422) also list each problem:
```json
{
  "status_code": 422,
  "message": "Invalid input",
  "errors": [
    { "field": "url", "message": "Input should be a valid URL, relative URL without a base" }
  ]
}
```

Unexpected errors return `500` with `"Something went wrong on our side"`. The full error is written to the logs, never sent to the client. (When `DEBUG=True`, the detailed debug page is shown instead.)

### Request logs

Every request is logged by the middleware in [app/middleware.py](app/middleware.py):
```
2026-11-05 16:30:04,513 INFO app.middleware: POST /api/shorten -> 201 (23.4 ms)
2026-11-05 16:30:04,523 INFO app.middleware: GET /api/aB3xY9 -> 302 (2.5 ms)
```

---

## Demo walkthrough

A step-by-step script that shows every feature. It's also the outline of the Loom video.

### Step 1: Start the system
```bash
docker compose up --build
```
**Show:** Redis becomes `Healthy` first, then the API starts. `depends_on` with a health check makes the API wait for Redis.

### Step 2: Open the documentation
Go to **http://127.0.0.1:8000/docs**.

**Show:**
- The title, version `1.0.0` and description at the top
- Two sections: **shortener** and **health**
- The **Schemas** section at the bottom: `ShortenRequest`, `ShortenResponse`, `ErrorResponse`, `ValidationErrorResponse`

### Step 3: Health check
Open **GET /health → Try it out → Execute**.

**Expected:** `200` and `{"status": "ok", "env": "development"}`

### Step 4: Shorten a URL (201)
Open **POST /api/shorten → Try it out**. The body is already filled in with the example URL. Click **Execute**.

**Expected:** `201 Created`
```json
{
  "short_code": "aB3xY9",
  "short_url": "http://127.0.0.1:8000/api/aB3xY9",
  "original_url": "https://www.amazon.com/Python-Crash-Course-3rd-Edition/dp/1718502702"
}
```
**Show:** the terminal logs `POST /api/shorten -> 201 (... ms)` from the logging middleware.

### Step 5: Follow the short link (302)
Copy `short_url` and paste it into a **new browser tab's address bar**.

**Expected:** the browser lands on the Amazon page.

> Test redirects in the address bar, not with Swagger's *Try it out*. Browsers block Swagger from following a redirect to another website, and it would show "Failed to fetch". That's a browser security rule, not an API bug.

**Show:** the terminal logs `GET /api/aB3xY9 -> 302`.

### Step 6: Unknown code (404)
Open **GET /api/{code} → Try it out**, enter `nope12` and click **Execute**.

**Expected:** `404` and `{"status_code": 404, "message": "Short URL not found"}`

### Step 7: Invalid URL (422)
In **POST /api/shorten**, send:
```json
{ "url": "hello" }
```
**Expected:** `422`
```json
{
  "status_code": 422,
  "message": "Invalid input",
  "errors": [{ "field": "url", "message": "Input should be a valid URL, relative URL without a base" }]
}
```
Also try `{"url": "ftp://example.com"}`. It's rejected with `URL scheme should be 'http' or 'https'`.

### Step 8: Data lives in Redis
```bash
docker compose exec redis redis-cli -a <your REDIS_PASSWORD> KEYS '*'
```
**Expected:** the code from step 4, e.g. `1) "aB3xY9"`.

Then restart everything:
```bash
docker compose restart
```
Paste the short link from step 5 again. **It still redirects**, because the data survived the restart.

### Step 9: Hot reload
With `docker compose up` running, open [app/main.py](app/main.py) and change `"ok"` in the `/health` route to `"OK!"`. Save.

**Expected:** the logs show `WatchFiles detected changes in 'app/main.py'. Reloading...`, and `/health` returns `"OK!"` without a rebuild. Change it back afterwards.

### Step 10: Production profile
```bash
docker compose down
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build
```
**Show:**
- The logs: `Starting gunicorn` and **4×** `Booting worker`
- `/health` → `{"status": "ok", "env": "production"}`
- Shorten a URL and open the link several times. Every request works, whichever of the 4 workers handles it, because all workers share Redis.

---

## Design decisions

**Dependency injection with `Depends`.**
Routes never create their own service. `get_shortener_service()` in [app/dependencies.py](app/dependencies.py) builds it with the shared storage, and FastAPI passes it in. The service also *receives* its storage instead of creating it. That means the storage backend can be swapped (Redis ↔ in-memory) in one place.

**Redis instead of an in-memory dictionary.**
A Python dict lives inside one process. It's lost on restart, and each Gunicorn worker would have its own copy, so a link created on worker 1 would give 404 on worker 3. Redis lives outside the app, so the data survives restarts and is shared by all workers.

**Random codes with a collision check.**
Codes are 6 characters from `a-z`, `A-Z` and `0-9` (62⁶ ≈ 56 billion combinations), generated with the `secrets` module. Before saving, the service checks the code isn't already taken and generates a new one if needed.

**Multi-stage Dockerfile.**
Stage 1 (`builder`) installs the packages into a virtual environment. Stage 2 (`runtime`) starts from a clean `python:3.14-slim` and copies only that virtual environment and the `app/` folder. The final image contains no pip cache or build leftovers, and it runs as a non-root user (`appuser`).

**Secrets.**
`REDIS_PASSWORD` lives only in `.env`, which is git-ignored. Docker Compose substitutes it into both the Redis server (`--requirepass`) and the API's `REDIS_URL`. Redis isn't exposed to the host at all. Only the API container can reach it.

**One error format.**
Three handlers in [app/errors.py](app/errors.py) cover HTTP errors (404, and unknown routes), validation errors (422) and unexpected crashes (500). Clients always get `status_code` + `message`, and internal details are never leaked.
