# AI-Powered Transaction Processing

A production-grade asynchronous backend that ingests raw bank transaction CSVs, cleans and validates them, runs rule-based anomaly detection, enriches each row with an LLM (Groq-hosted Llama 3.3 70B), and produces a portfolio-level risk summary — all behind a small, well-documented REST API.

The system is designed to be **resilient, idempotent, and LLM-tolerant**: an outage, rate-limit, or missing API key never breaks a job. The local fallback path always produces a meaningful summary.

---

## Quick Start

Get the full stack running locally in under two minutes. The fastest path uses Docker Compose — no Python setup required.

### Prerequisites

- [Docker](https://www.docker.com/get-started) and [Docker Compose](https://docs.docker.com/compose/install/) (v2+)
- A Groq API key from [console.groq.com](https://console.groq.com/) — *optional*, the system works without it (enrichment is skipped, local fallback summary is used)

### One-command startup

```bash
# 1. Clone the repository
git clone https://github.com/Anjali330/AI-Powered-Transaction-Processing.git
cd AI-Powered-Transaction-Processing

# 2. (Optional) paste your Groq API key
#    On Windows (PowerShell):  copy .env.example .env  then edit .env
#    On macOS/Linux:           cp .env.example .env     then edit .env
#    Replace <your-groq-api-key> with your real key from console.groq.com

# 3. Build and start the full stack
docker compose up --build
```

On first run you will see five services start in order: `db` (Postgres) → `redis` → `migrate` (runs Alembic) → `api` (FastAPI) → `worker` (Celery). Wait until you see:

```
api-1       | Application startup complete.
api-1       | Uvicorn running on http://0.0.0.0:8000
```

### Verify it's working

```bash
# Health check
curl http://localhost:8000/health
# → {"status":"ok"}

# Open interactive API docs in your browser
# → http://localhost:8000/docs
```

### Upload a test CSV

A sample CSV is provided at `api/test.csv`. You can also build one inline:

```csv
txn_id,date,merchant,amount,currency,status,category,account_id,notes
T1,2024-01-15,Amazon,1500.00,INR,SUCCESS,Shopping,ACC1,new year sale
T2,2024-01-16,Swiggy,420.50,INR,SUCCESS,Food,ACC1,
T3,2024-01-17,Uber,25.00,USD,FAILED,Travel,ACC2,driver cancelled
T4,2024-01-18,Flipkart,9999.00,INR,SUCCESS,Shopping,ACC1,
T5,2024-01-19,Netflix,649.00,INR,SUCCESS,Entertainment,ACC1,
```

```bash
# Save the CSV above as sample.csv, then upload it
curl -F "file=@sample.csv" http://localhost:8000/jobs/upload
# → {"job_id":"<uuid>","status":"pending","filename":"sample.csv"}

# Poll status (replace <uuid> with the job_id from the response above)
curl http://localhost:8000/jobs/<uuid>/status

# Once status == "completed", fetch full results
curl http://localhost:8000/jobs/<uuid>/results | python -m json.tool
```

### Run the test suite

```bash
docker compose exec api pytest -v
```

### Tear down

```bash
# Stop services, keep database volume
docker compose down

# Stop services AND wipe the database volume
docker compose down -v
```

---

## Highlights

- **Asynchronous, scalable pipeline** — CSV uploads are accepted synchronously over HTTP, then a Celery worker drains the queue.
- **Resilient by design** — Tenacity-backed exponential retry, batched LLM calls, graceful degradation when the Groq key is missing.
- **Strict schema enforcement** — Pydantic request/response models across all five endpoints, OpenAPI docs auto-generated.
- **Rule-based + AI anomaly detection** — four deterministic rules (large transaction, one-off merchant, failed status, currency mismatch) combined with LLM-derived per-row risk levels.
- **PostgreSQL persistence with Alembic migrations** — versioned schema, UUIDs everywhere, JSONB columns for LLM raw responses.
- **Structured JSON logging** — single-line JSON log records with `job_id` correlation across HTTP and worker processes.
- **Comprehensive test suite** — pure unit tests for cleaning and anomaly logic, transactional API contract tests against a real PostgreSQL database.

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Repository Layout](#repository-layout)
- [Data Flow](#data-flow)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Configuration](#configuration)
- [Local Development Setup](#local-development-setup)
- [Running with Docker Compose](#running-with-docker-compose)
- [Database Migrations](#database-migrations)
- [Running the Test Suite](#running-the-test-suite)
- [CSV Format](#csv-format)
- [Anomaly Detection Rules](#anomaly-detection-rules)
- [LLM Enrichment & Fallback](#llm-enrichment--fallback)
- [Logging](#logging)
- [Operational Notes](#operational-notes)
- [Roadmap / Future Work](#roadmap--future-work)
- [License](#license)

---

## Architecture

The system is split into three independently-scalable services plus a thin migration job, all orchestrated by `docker-compose.yml`.

```
                    ┌────────────────────────┐
                    │       Client           │
                    │  (curl / frontend)     │
                    └────────────┬───────────┘
                                 │  HTTP (FastAPI)
                                 ▼
        ┌─────────────────────────────────────────────────┐
        │                  api  (uvicorn)                  │
        │  POST /jobs/upload → persist file + insert Job   │
        │                    → enqueue Celery task         │
        │  GET  /jobs/{id}/status | /results               │
        │  GET  /jobs                                        │
        └────────────────┬─────────────────────────────────┘
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
        ▼                ▼                 ▼
 ┌─────────────┐  ┌─────────────┐   ┌──────────────┐
 │ PostgreSQL  │  │   Redis     │   │  uploaded    │
 │   (jobs,    │  │  (broker +  │   │   _csvs/     │
 │ transactions│  │   result    │   │ (shared vol) │
 │  summaries) │  │  backend)   │   └──────┬───────┘
 └──────┬──────┘  └──────┬──────┘          │
        │                │                 │
        │                ▼                 │
        │       ┌──────────────────┐       │
        └──────►│  worker (Celery) │◄──────┘
                │  app.tasks.      │
                │   pipeline       │
                │                  │
                │ 1. clean_csv     │
                │ 2. detect_anomaly│
                │ 3. enrich_batch  │──► Groq API (Llama 3.3 70B)
                │ 4. bulk insert   │
                │ 5. summary       │
                └──────────────────┘
```

### Why this shape?

- **HTTP layer stays thin.** The upload endpoint only validates, persists the file, inserts a `Job` row, and queues a Celery task. It returns `202 Accepted` immediately with the new `job_id`.
- **Heavy work happens off the request path.** Cleaning (pandas), anomaly detection (pure Python), LLM calls (network), and bulk inserts all happen in a Celery worker. The API thread is never blocked.
- **Idempotent re-runs.** The pipeline deletes prior `Transaction` and `JobSummary` rows for the job before inserting, so a Celery retry never leaves duplicate state.
- **Graceful degradation.** If the Groq API key is missing or every retry is exhausted, `llm_failed=True` is set on affected rows and the summary is computed locally. The job still completes successfully.

---

## Tech Stack

| Layer            | Choice                                            |
|------------------|---------------------------------------------------|
| Web framework    | FastAPI + Uvicorn                                 |
| Async worker     | Celery 5 (Redis broker, Redis result backend)     |
| Database          | PostgreSQL 16                                     |
| ORM              | SQLAlchemy 2.x (typed `Mapped[...]` models)       |
| Migrations       | Alembic                                           |
| LLM provider     | Groq — `llama-3.3-70b-versatile`                  |
| LLM SDK          | `groq`                                            |
| Resilience        | `tenacity` (exponential backoff + jitter)         |
| Data handling    | pandas                                            |
| Settings         | pydantic-settings                                 |
| Logging          | Custom JSON formatter on the root logger          |
| Tests            | pytest + FastAPI TestClient + real PostgreSQL     |
| Containerisation | Docker, docker-compose                            |
| Python           | 3.11                                              |

---

## Repository Layout

```
AI-Powered Transaction Processing/
├── docker-compose.yml          # db, redis, migrate, api, worker
├── .env / .env.docker / .env.example
├── Architecture_Roadmap.md     # internal planning notes
└── api/
    ├── Dockerfile              # python:3.11-slim, non-root user
    ├── requirements.txt
    ├── alembic.ini
    ├── alembic/
    │   ├── env.py
    │   ├── script.py.mako
    │   └── versions/
    │       ├── 0001_initial_schema.py
    │       └── 0002_phase4_enrichment.py
    ├── app/
    │   ├── main.py             # FastAPI app + /health
    │   ├── config.py           # pydantic-settings, .env loader
    │   ├── database.py         # SQLAlchemy engine, get_db()
    │   ├── celery_app.py       # Celery instance, JSON serializer
    │   ├── core/
    │   │   └── logging.py      # JSONFormatter + setup_logging()
    │   ├── models/             # Job, Transaction, JobSummary
    │   ├── schemas/            # Pydantic request/response models
    │   ├── routers/
    │   │   └── jobs.py         # All 4 /jobs/* endpoints
    │   ├── services/
    │   │   ├── cleaning.py     # Pure CSV cleaning pipeline
    │   │   ├── anomaly.py      # 4 rule-based detectors
    │   │   └── llm_client.py   # Groq wrapper + local fallback
    │   └── tasks/
    │       └── pipeline.py     # Celery task orchestration
    ├── tests/
    │   ├── conftest.py         # DB rollback fixture + TestClient
    │   ├── test_cleaning.py    # ~20 unit tests
    │   ├── test_anomaly.py     # ~20 unit tests
    │   └── test_api_contracts.py  # ~30 contract tests
    └── uploaded_csvs/          # Volume-mounted shared upload dir
```

---

## Data Flow

A complete request travels through six stages:

1. **Upload** — Client `POST`s a CSV to `/jobs/upload`. The server validates the extension (`.csv`) and size (`MAX_UPLOAD_MB`), writes the file to `uploaded_csvs/{job_id}.csv`, inserts a `Job` row with `status='pending'`, and calls `process_job.delay(job_id)`. Response is `202 Accepted` with the new `job_id`.

2. **Pickup** — A Celery worker on the `worker` service claims the task, opens its own SQLAlchemy session, and flips the `Job` row to `status='processing'`.

3. **Cleaning** — `services/cleaning.py` loads the CSV with pandas, normalises column casing, drops duplicate rows, parses and validates every column (amount → `Decimal`, date → ISO-8601, currency → 3-char uppercase, merchant → title-case). Rows that fail any required-field check are counted as `invalid_rows` and dropped.

4. **Anomaly detection** — `services/anomaly.py` evaluates four rules in a single pass. Pre-computed per-account amount medians and merchant frequency tables keep the loop O(n).

5. **LLM enrichment** — `services/llm_client.enrich_batch` slices the cleaned rows into `LLM_BATCH_SIZE` (default 20) chunks and calls Groq once per chunk. Each call is wrapped with Tenacity (exponential backoff 2–60 s + jitter, `LLM_MAX_RETRIES` attempts). On final failure the batch is marked `llm_failed=True` and the pipeline continues.

6. **Persistence + summary** — The worker deletes any prior `Transaction` and `JobSummary` rows for the job (idempotent re-run), bulk-inserts the cleaned/enriched rows, then calls `generate_summary`. The LLM-derived summary is merged with a locally-computed fallback so the job always completes with a `JobSummary` row.

The job is then flipped to `status='completed'` and `completed_at` is set. Any unhandled exception inside the task body is caught, the transaction is rolled back, and the job is marked `failed` with the exception message persisted in `error_message`.

---

## API Reference

Interactive OpenAPI docs are served at **`/docs`** (Swagger UI) and **`/redoc`** when the API is running.

### `GET /health`

Lightweight liveness probe used by the Docker healthcheck.

```json
{ "status": "ok" }
```

### `POST /jobs/upload`

Accepts a CSV upload (`multipart/form-data`, field name `file`). Returns `202 Accepted`.

- **Constraints:** `.csv` extension only, ≤ `MAX_UPLOAD_MB` (default 10 MB), non-empty.
- **Side effects:** writes file to `uploaded_csvs/{job_id}.csv`, inserts `Job(status='pending')`, enqueues `process_job` task.
- **Response 202:**
  ```json
  {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "pending",
    "filename": "march-statement.csv"
  }
  ```
- **Errors:** `400` for invalid extension, empty file, or oversize file. `422` if no `file` field is sent.

### `GET /jobs/{job_id}/status`

Returns the current lifecycle status plus summary metrics when complete.

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "filename": "march-statement.csv",
  "row_count_raw": 312,
  "row_count_clean": 308,
  "created_at": "2025-04-12T10:00:00+00:00",
  "completed_at": "2025-04-12T10:00:14+00:00",
  "error_message": null,
  "summary": {
    "anomaly_count": 4,
    "llm_failed_count": 0,
    "risk_level": "low"
  }
}
```

`summary` is `null` until the job completes. `404` if the `job_id` is unknown.

### `GET /jobs/{job_id}/results`

While the job is not yet `completed`, returns a lightweight polling response (`200`):

```json
{ "job_id": "...", "status": "processing" }
```

Once complete, returns the full payload:

```json
{
  "job_id": "...",
  "status": "completed",
  "original_rows": 312,
  "cleaned_rows": 308,
  "duplicates_removed": 4,
  "transactions": [ { "txn_id": "T1", "merchant": "Amazon", "amount": "1500.00",
                       "currency": "INR", "is_anomaly": false,
                       "llm_category": "Shopping", "llm_subcategory": "Ecommerce",
                       "llm_risk_level": "low", "llm_confidence": 0.92,
                       "llm_failed": false, "...": "..." } ],
  "anomalies": [ { "txn_id": "T42", "reason": "amount 5.2x account ACC1 median" } ],
  "summary": {
    "total_spend_inr": "84210.50",
    "total_spend_usd": null,
    "total_spend": "84210.50",
    "top_merchants": [ { "merchant": "Amazon", "total_amount": 18230.0, "txn_count": 12 } ],
    "category_breakdown": { "Shopping": { "total_amount": 18230.0, "txn_count": 12 } },
    "anomaly_count": 4,
    "ai_summary": "Across 308 transactions totalling ₹84,210.50, ...",
    "risk_level": "low"
  }
}
```

### `GET /jobs`

Lists jobs newest-first. Supports:

- `status` — one of `pending`, `processing`, `completed`, `failed` (Pydantic-validated enum; bad values return `422`).
- `limit` — 1–200, default 20.
- `offset` — ≥ 0, default 0.

```json
{
  "jobs": [
    { "job_id": "...", "filename": "...", "status": "completed",
      "row_count_raw": 312, "row_count_clean": 308,
      "created_at": "2025-04-12T10:00:00+00:00" }
  ],
  "count": 1
}
```

---

## Database Schema

Three tables, all keyed by UUID with cascading deletes from `jobs`.

### `jobs`
| Column            | Type                            | Notes                              |
|-------------------|---------------------------------|------------------------------------|
| `id`              | `UUID PK`                       |                                    |
| `filename`        | `TEXT NOT NULL`                 | Original filename from the upload  |
| `file_path`       | `TEXT NOT NULL`                 | On-disk path inside `uploaded_csvs`|
| `status`          | `job_status ENUM NOT NULL`      | `pending` / `processing` / `completed` / `failed` |
| `row_count_raw`   | `INTEGER`                       | Set when cleaning finishes         |
| `row_count_clean` | `INTEGER`                       | Set when cleaning finishes         |
| `error_message`   | `TEXT`                          | Populated on failure               |
| `created_at`      | `TIMESTAMPTZ NOT NULL`          | Default `now()`                    |
| `updated_at`      | `TIMESTAMPTZ NOT NULL`          | Default `now()`, auto on update    |
| `completed_at`    | `TIMESTAMPTZ`                   | Set on completion or failure       |

Indexes: `(status)`, `(created_at)`.

### `transactions`
One row per cleaned transaction. All currency-bearing amounts are stored as `Numeric(12, 2)` to avoid floating-point drift.

| Column               | Type                            | Notes                                    |
|----------------------|---------------------------------|------------------------------------------|
| `id`                 | `UUID PK`                       |                                          |
| `job_id`             | `UUID FK → jobs.id CASCADE`     |                                          |
| `txn_id`             | `TEXT`                          | Original CSV `txn_id` (may be null)      |
| `date`               | `DATE NOT NULL`                 | Normalised to ISO `YYYY-MM-DD`           |
| `merchant`           | `TEXT NOT NULL`                 | Title-cased                              |
| `amount`             | `NUMERIC(12, 2) NOT NULL`       |                                          |
| `currency`           | `VARCHAR(3) NOT NULL`           | Uppercase                                |
| `status`             | `TEXT NOT NULL`                 | Uppercase                                |
| `category`           | `TEXT`                          | Original CSV value                       |
| `account_id`         | `TEXT NOT NULL`                 |                                          |
| `notes`              | `TEXT`                          |                                          |
| `is_anomaly`         | `BOOLEAN NOT NULL`              | Set by anomaly detector                  |
| `anomaly_reason`     | `TEXT`                          | Semicolon-joined reasons                 |
| `llm_category`       | `TEXT`                          | LLM-assigned category                    |
| `llm_subcategory`    | `TEXT`                          | LLM-assigned subcategory                 |
| `llm_risk_level`     | `TEXT`                          | `low` / `medium` / `high`                |
| `llm_merchant_type`  | `TEXT`                          | e.g. "Online Retailer"                   |
| `llm_confidence`     | `NUMERIC(4, 3)`                 | 0.000–1.000                              |
| `llm_raw_response`   | `JSONB`                         | Full structured LLM response             |
| `llm_failed`         | `BOOLEAN NOT NULL`              | True if enrichment retry exhausted       |

Indexes: `(job_id)`, `(job_id, account_id)`.

### `job_summaries`
One row per job. Enforced unique on `job_id` so re-running the pipeline is safe.

| Column              | Type                          | Notes                                     |
|---------------------|-------------------------------|-------------------------------------------|
| `id`                | `UUID PK`                     |                                           |
| `job_id`            | `UUID FK UNIQUE CASCADE`      | One summary per job                       |
| `total_spend_inr`   | `NUMERIC(14, 2)`              |                                           |
| `total_spend_usd`   | `NUMERIC(14, 2)`              |                                           |
| `top_merchants`     | `JSONB`                       | Top 3 `{merchant, total_amount, txn_count}`|
| `anomaly_count`     | `INTEGER`                     |                                           |
| `category_breakdown`| `JSONB`                       | `{category: {total_amount, txn_count}}`   |
| `narrative`         | `TEXT`                        | Older narrative field                     |
| `ai_summary`        | `TEXT`                        | LLM narrative                             |
| `risk_level`        | `TEXT`                        | `low` / `medium` / `high`                 |
| `llm_raw_response`  | `JSONB`                       | Raw LLM response for traceability         |

---

## Configuration

All configuration is sourced from environment variables via `pydantic-settings` (`app/config.py`). A `.env` file at the project root is loaded automatically when present.

| Variable                 | Required | Default                       | Description                                      |
|--------------------------|----------|-------------------------------|--------------------------------------------------|
| `DATABASE_URL`           | yes      | —                             | SQLAlchemy URL, e.g. `postgresql://app:app@db:5432/transactions` |
| `REDIS_URL`              | yes      | —                             | e.g. `redis://redis:6379/0`                      |
| `CELERY_BROKER_URL`      | yes      | —                             | Same as `REDIS_URL` in this stack                |
| `CELERY_RESULT_BACKEND`  | yes      | —                             | e.g. `redis://redis:6379/1`                      |
| `GROQ_API_KEY`           | no       | empty                         | If missing or `<your-key>`, enrichment is skipped and the local fallback summary is used |
| `GROQ_MODEL`             | no       | `llama-3.3-70b-versatile`     | Any Groq-hosted chat model                       |
| `LLM_BATCH_SIZE`         | no       | `20`                          | Transactions per LLM call                        |
| `LLM_MAX_RETRIES`        | no       | `3`                           | Tenacity stop-after-attempt count                |
| `MAX_UPLOAD_MB`          | no       | `10`                          | Server-side upload cap                           |
| `LOG_LEVEL`              | no       | `INFO`                        | Standard Python log level                        |
| `ENV`                    | no       | `development`                 | Enables verbose debug logging when set to `development` |

When running inside Docker, hostnames must match the Compose service names (`db`, `redis`). See `.env.docker` for the in-container values and `.env.example` for a template.

---

## Local Development Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ running locally (or use the Compose stack for the DB only)
- Redis 7+
- (Optional) A Groq API key from [console.groq.com](https://console.groq.com/)

### Steps

```bash
# 1. Clone and enter the project
git clone <repo-url> "ai-tx-processing"
cd "ai-tx-processing"

# 2. Create and activate a virtualenv
python -m venv api/.venv
source api/.venv/bin/activate          # Windows: api\.venv\Scripts\activate

# 3. Install dependencies
pip install -r api/requirements.txt

# 4. Copy the env template and edit it for your local services
cp .env.example .env
#  - Point DATABASE_URL at your local Postgres
#  - Point REDIS_URL / CELERY_* at your local Redis
#  - Optionally paste a real GROQ_API_KEY

# 5. Run migrations
cd api && alembic upgrade head && cd ..

# 6. Start the API
cd api && uvicorn app.main:app --reload --port 8000

# 7. In a second terminal, start a Celery worker
cd api && celery -A app.celery_app worker --loglevel=info --concurrency=2 -P prefork
```

The API is then reachable at `http://localhost:8000`, Swagger UI at `http://localhost:8000/docs`.

---

## Running with Docker Compose

The compose file at the repository root brings up the full stack with one command.

```bash
# Build images and start all services
docker compose up --build

# In a separate shell, sanity-check the stack
curl http://localhost:8000/health
# → {"status":"ok"}
```

Services started:

| Service     | Port  | Purpose                                                    |
|-------------|-------|------------------------------------------------------------|
| `db`        | 5432  | PostgreSQL 16 with a persistent named volume               |
| `redis`     | —     | Redis 7 (internal only, not published)                     |
| `migrate`   | —     | One-shot job that runs `alembic upgrade head`              |
| `api`       | 8000  | FastAPI on `0.0.0.0:8000` with a `/health` healthcheck    |
| `worker`    | —     | Celery worker with concurrency 2 (prefork pool)            |

The `migrate` service blocks `api` and `worker` from starting via `depends_on: { condition: service_completed_successfully }`, guaranteeing the schema exists before either process opens a DB connection.

Shared `uploaded_csvs` volume is mounted on both `api` and `worker` so the worker can read files the API wrote.

To tear down (keeping volumes):

```bash
docker compose down
```

To tear down including the Postgres volume:

```bash
docker compose down -v
```

---

## Database Migrations

Schema is managed by Alembic. Two revisions are present:

- `0001_initial_schema.py` — creates the `job_status` enum and all three base tables.
- `0002_phase4_enrichment.py` — adds `llm_subcategory`, `llm_risk_level`, `llm_merchant_type`, `llm_confidence` to `transactions` and `category_breakdown`, `ai_summary` to `job_summaries`.

Common operations:

```bash
cd api

# Apply all pending migrations
alembic upgrade head

# Show current revision
alembic current

# Roll back one step
alembic downgrade -1

# After changing models, autogenerate a new revision
alembic revision --autogenerate -m "describe change"
```

The compose `migrate` service runs `alembic upgrade head` automatically on each `docker compose up`.

---

## Running the Test Suite

The suite has three layers:

1. **`tests/test_cleaning.py`** — pure-Python unit tests for `services/cleaning.py`. No DB, no Celery, no network. ~20 cases cover amount parsing (dollar/₹/European decimals), date normalisation, duplicate removal, and required-field validation.
2. **`tests/test_anomaly.py`** — pure-Python unit tests for `services/anomaly.py`. ~20 cases cover each of the four anomaly rules, edge cases (exactly at multiplier, insufficient sample size, case-insensitivity, currency ties), and combined-rule scenarios.
3. **`tests/test_api_contracts.py`** — API contract tests using FastAPI's `TestClient` against a real PostgreSQL database with transactional rollback isolation. Celery's `process_job.delay` is patched out. ~30 cases cover every endpoint, every status code path, and every documented response field.

```bash
cd api
pytest -v
```

`tests/conftest.py` provides:

- `db_session` — opens a connection, starts a transaction, yields a session, rolls back at teardown. Tests never persist data.
- `client` — a FastAPI `TestClient` wired to the rollback session with the Celery task mocked.
- `make_csv(*rows)` — helper to build a valid CSV from raw row strings.

The contract tests require `DATABASE_URL` in the environment pointing at a real PostgreSQL instance with the schema already migrated.

---

## CSV Format

Uploads must be UTF-8 encoded, comma-separated, and contain a header row with exactly these column names (case-insensitive after whitespace trim):

```
txn_id, date, merchant, amount, currency, status, category, account_id, notes
```

| Column      | Required | Notes                                                                  |
|-------------|----------|------------------------------------------------------------------------|
| `txn_id`    | no       | Original transaction ID; preserved as-is                               |
| `date`      | yes      | Accepts `YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`, `DD-MM-YYYY`, `YYYY/MM/DD`, or any pandas-parseable format |
| `merchant`  | yes      | Normalised to title-case, internal whitespace collapsed                |
| `amount`    | yes      | `$1,234.56`, `₹9999.00`, `1.234,56` (European), `-200.5` all accepted  |
| `currency`  | yes      | Normalised to 3-character uppercase; `inr` → `INR`                     |
| `status`    | yes      | Uppercased; defaults to `UNKNOWN` if blank                             |
| `category`  | no       | Original user-supplied category (overridden by LLM enrichment)         |
| `account_id`| yes      | Used by the large-transaction rule                                     |
| `notes`     | no       | Free text                                                              |

Rows missing any required column, or with an unparseable amount/date, are dropped and counted in `invalid_rows`.

A minimal valid example:

```csv
txn_id,date,merchant,amount,currency,status,category,account_id,notes
T1,2024-01-15,Amazon,1500.00,INR,SUCCESS,Shopping,ACC1,new year sale
T2,2024-01-16,Swiggy,₹420.50,INR,SUCCESS,Food,ACC1,
T3,2024-01-17,Uber,$25.00,USD,FAILED,Travel,ACC2,driver cancelled
```

---

## Anomaly Detection Rules

All four rules run in a single pass over the cleaned rows. Multiple rules can fire on the same row — reasons are joined with `"; "`.

| # | Rule              | Fires when…                                                                                              |
|---|-------------------|----------------------------------------------------------------------------------------------------------|
| 1 | Large transaction | `amount > 3.0 × median(account_id.amounts)`, **and** the account has ≥ 3 prior transactions.             |
| 2 | One-off merchant  | `merchant` (case-insensitive) appears exactly once across the whole dataset.                              |
| 3 | Failed status     | `status == "FAILED"` (case-insensitive).                                                                  |
| 4 | Currency mismatch | `currency` differs from the majority currency across the whole dataset.                                  |

Rules 1, 3, and 4 are intentionally simple and explainable. Rule 2 acts as a lightweight outlier detector without statistical machinery. The LLM-derived `llm_risk_level` is stored separately and surfaced via `/results` for richer context.

---

## LLM Enrichment & Fallback

### What the LLM does

Two prompts are sent to Groq (`llama-3.3-70b-versatile` by default):

- **Per-row enrichment** (`enrich_batch`) — given a JSON array of up to `LLM_BATCH_SIZE` (20) transactions, the model returns a same-length JSON array with `category`, `subcategory`, `merchant_type`, `risk_level`, and `confidence` for each row. `response_format={"type": "json_object"}` is enforced.
- **Portfolio summary** (`generate_summary`) — given the full set of cleaned transactions, the model returns a JSON object with `top_merchants`, `category_breakdown`, `ai_summary`, `risk_level`, etc.

### How failures are handled

- **Missing key.** If `GROQ_API_KEY` is empty or the literal placeholder `<your-key>`, both calls are skipped: enrichment is a no-op (`llm_failed=False` on rows), and the summary is computed locally.
- **Per-batch retry.** Each Groq call is decorated with Tenacity: exponential backoff (`min=2 s`, `max=60 s`) plus random jitter (`0–2 s`), up to `LLM_MAX_RETRIES` (3) attempts. Each attempt is logged at WARNING before sleep.
- **Batch-level fallback.** If a batch's retries are exhausted, every row in that batch gets `llm_failed=True`. Subsequent batches are still attempted.
- **Summary fallback.** If the summary call fails entirely, a locally-computed summary is used. The local summary always reflects the true local `anomaly_count` and includes a deterministic narrative string.

The net effect: **the job never fails because of an LLM issue.**

---

## Logging

Logging is configured in `app/core/logging.py` via `setup_logging(LOG_LEVEL)` (called from `app/main.py`). Every record is emitted as a single-line JSON object to stdout:

```json
{"time": "2025-04-12T10:00:14.231Z", "level": "INFO", "logger": "app.tasks.pipeline",
 "message": "job_id=... status=completed", "job_id": "550e8400-..."}
```

- `job_id` correlation — pass it explicitly via `logger.info("...", extra={"job_id": job_id})` and it propagates through both the API and worker processes.
- Exception info — `logger.exception(...)` automatically attaches a formatted traceback under `exc_info`.
- Uvicorn and Celery loggers are wired into the same root handler so log output stays consistent across the API and worker processes.

---

## Operational Notes

- **Idempotent re-runs.** Each Celery task deletes any existing `Transaction` and `JobSummary` rows for the job before inserting new ones, so re-running a task (manually or via Celery retry) never leaves duplicates.
- **Shared upload volume.** Both `api` and `worker` mount the same `uploaded_csvs` named volume so the worker can read files written by the API.
- **Health checks.** The Postgres container uses `pg_isready`; Redis uses `redis-cli ping`; the API uses `curl http://localhost:8000/health`. All have retry-on-failure policies in Compose.
- **Non-root container.** The Dockerfile creates a system user `app` and switches to it before `CMD`. No root processes inside the API container.
- **Decimal arithmetic.** Money is handled via Python's `Decimal` end-to-end (cleaning → anomaly detection → DB persistence via `Numeric`). Floating-point drift is avoided.
- **Graceful LLM outage.** Set `GROQ_API_KEY=` (empty) to disable enrichment entirely; the system runs in deterministic local mode.

---

## Roadmap / Future Work

See `Architecture_Roadmap.md` for the full plan. Highlights:

- Front-end dashboard with upload progress and anomaly drill-down.
- Per-account profile baselines (rolling 30/90-day medians) for stronger large-transaction detection.
- Optional plug-in for OpenAI / Anthropic backends alongside Groq.
- Token-based authentication and per-user quota tracking.
- Prometheus metrics endpoint (`/metrics`) for job counts, latency histograms, LLM failure rate.

---

## License

This project does not currently declare an open-source license. All rights reserved by the repository owner unless a `LICENSE` file is added.
