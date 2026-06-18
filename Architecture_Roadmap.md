# AI-Powered Transaction Processing Pipeline — Design Review Roadmap

**Assignment:** Backend + DevOps Intern, AI-Powered Transaction Processing Pipeline
**Stack:** FastAPI · PostgreSQL · Redis · Celery · Docker Compose · Gemini API · SQLAlchemy · Alembic
**Reviewer stance:** Staff Engineer design review — architecture finalized before a single line of application code is written.

This document is the complete roadmap. It is scoped tightly to what the assignment PDF actually asks for (4 endpoints, 5 pipeline steps, 3 tables) and then layered with the production hardening a Staff Engineer would push back on in review. Build in the order given in Phase 2 — each step is independently testable before the next begins.

---

## PHASE 1 — Architecture, Lifecycle, Schema, Folder Structure

### 1.1 High-Level Architecture (ASCII)

```
                                   ┌─────────────────────────┐
                                   │        Client            │
                                   │ (curl / Postman / video) │
                                   └────────────┬─────────────┘
                                                 │ HTTP
                                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          DOCKER COMPOSE NETWORK                          │
│                                                                            │
│   ┌──────────────────┐        ┌──────────────────────────────────┐      │
│   │   api (FastAPI)   │        │            worker (Celery)         │      │
│   │  uvicorn :8000     │        │   celery -A app.celery_app worker  │      │
│   │                    │        │                                    │      │
│   │ POST /jobs/upload  │──┐     │  1. clean_transactions             │      │
│   │ GET  /jobs/{id}/   │  │     │  2. detect_anomalies               │      │
│   │      status        │  │     │  3. llm_categorize_batch           │      │
│   │ GET  /jobs/{id}/   │  │     │  4. llm_generate_summary           │      │
│   │      results       │  │     │  5. finalize_job                   │      │
│   │ GET  /jobs          │  │     │                                    │      │
│   └─────────┬──────────┘  │     └───────────┬───────────────┬────────┘      │
│             │             │                 │               │               │
│             │ writes Job  │ enqueues task    │ reads/writes  │ calls         │
│             │ row, file   │ (job_id)         │ Transaction/  │               │
│             ▼             ▼                 │ JobSummary    │               │
│   ┌──────────────────────────────┐          ▼               ▼               │
│   │     PostgreSQL (db)            │◄────────────┐   ┌──────────────────┐    │
│   │  jobs / transactions /         │             │   │   Gemini API      │    │
│   │  job_summaries                 │             │   │ (external, free  │    │
│   └──────────────────────────────┘             │   │  tier, batched)   │    │
│                                                   │   └──────────────────┘    │
│   ┌──────────────────────────────┐               │                          │
│   │      Redis (broker + backend)  │◄──────────────┘                          │
│   │  task queue, result store      │                                         │
│   └──────────────────────────────┘                                         │
│                                                                            │
│   ┌──────────────────────────────┐                                         │
│   │   volume: uploaded_csvs/        │  (local disk in this assignment;        │
│   │   (mounted into api + worker)   │   becomes S3 in Phase 6)                │
│   └──────────────────────────────┘                                         │
└────────────────────────────────────────────────────────────────────────┘
```

**Why this shape:** the API process never touches pandas, the Gemini SDK, or anomaly math — it only validates the upload, writes one `Job` row, drops the file on a shared volume, and enqueues a task ID. Every CPU/IO-heavy and flaky-external-dependency step lives in the worker, which is the only thing allowed to fail and retry without taking the API down. This is the single most important decision in the whole design and it's worth saying explicitly in the video review.

### 1.2 Request Lifecycle (trace per endpoint)

**Upload — `POST /jobs/upload`**
1. FastAPI receives multipart upload, streams it to disk under `uploaded_csvs/{uuid}.csv` (never fully loaded into memory at the route level).
2. A lightweight synchronous check runs: file extension, max size, and a 1-row header sanity check (do the 9 expected columns exist). This is the *only* validation done inline — anything dirtier than that is the worker's job.
3. A `Job` row is inserted with `status=pending`, `filename`, `row_count_raw=NULL` (unknown until the worker actually parses it).
4. `clean_transactions.delay(job_id)` is enqueued to Celery via Redis.
5. API returns `202 Accepted` with `{job_id, status: "pending"}` immediately — the HTTP request never waits on parsing, cleaning, or any LLM call.

**Status poll — `GET /jobs/{job_id}/status`**
1. Single indexed `SELECT` on `jobs.id`.
2. If `status == completed`, a second cheap query pulls the lightweight `summary` fields (row counts, anomaly count) — not the full transaction list.
3. Returns `404` if the job doesn't exist, otherwise `200` with status + optional summary.

**Results poll — `GET /jobs/{job_id}/results`**
1. If job isn't `completed`, return `200` with a `status` field telling the client to keep polling (or `409` — see API contract in Phase 3 for the exact choice and why).
2. If completed: one query joins `Job` → `Transaction` (all rows) → `JobSummary` (one row), assembled into the response shape.

**List — `GET /jobs`**
1. `SELECT` with optional `WHERE status = :status`, ordered by `created_at DESC`, paginated (assignment doesn't ask for pagination, but a Staff Engineer review will dock points if 10,000 jobs returns 10,000 rows unpaginated — add `limit`/`offset` with sane defaults even though the assignment didn't ask).

**Worker pipeline — triggered by the upload, invisible to the client until it polls**
1. `clean_transactions(job_id)` reads the CSV path from the `Job` row, parses with pandas, applies all cleaning rules, bulk-inserts `Transaction` rows, updates `row_count_raw` / `row_count_clean`, sets `status=processing`.
2. `detect_anomalies(job_id)` runs the median/domestic-brand rules per `account_id`, updates `is_anomaly` / `anomaly_reason` on existing rows (bulk update, not row-by-row ORM writes).
3. `llm_categorize_batch(job_id)` collects all rows where `category` is null/empty, batches them into one (or a handful of) Gemini calls, writes `llm_category` back.
4. `llm_generate_summary(job_id)` makes one Gemini call with the cleaned+flagged dataset, parses the JSON response, writes a `JobSummary` row.
5. `finalize_job(job_id)` sets `status=completed`, `completed_at=now()` (or `status=failed` + `error_message` if any step raised unrecoverably).

### 1.3 Database Schema

Three tables as suggested by the assignment, with the additions a review would expect (timestamps, indexes, idempotency hooks) called out explicitly as **[added]**.

**`jobs`**

| Column | Type | Notes |
|---|---|---|
| id | UUID, PK | use UUID not serial int — job IDs are returned to external clients, shouldn't leak sequential info |
| filename | text | original upload filename |
| file_path | text **[added]** | path/object-key on the shared volume, needed by the worker to read the file |
| status | enum(`pending`,`processing`,`completed`,`failed`) | indexed — `GET /jobs?status=` filters on this |
| row_count_raw | int, nullable | filled after parsing |
| row_count_clean | int, nullable | filled after dedup |
| error_message | text, nullable | populated on `failed` |
| created_at | timestamptz | indexed, default now() |
| updated_at | timestamptz **[added]** | bump on every status transition — useful for stuck-job alerting later |
| completed_at | timestamptz, nullable | |

**`transactions`**

| Column | Type | Notes |
|---|---|---|
| id | UUID, PK | |
| job_id | UUID, FK → jobs.id, **indexed** | every query filters by job_id — this index is mandatory, not optional |
| txn_id | text, nullable | original CSV value, can be blank |
| date | date | normalized to ISO 8601 by the cleaning step; original raw string discarded (not needed downstream) |
| merchant | text | |
| amount | numeric(12,2) | stored as numeric, never float — money math |
| currency | text(3) | normalized uppercase |
| status | text | normalized uppercase (SUCCESS/FAILED/PENDING) |
| category | text, nullable | original CSV category, post-cleaning |
| account_id | text, **indexed alongside job_id** | composite index `(job_id, account_id)` — the anomaly step's median calculation groups by exactly this pair |
| notes | text, nullable | raw free text |
| is_anomaly | boolean, default false | |
| anomaly_reason | text, nullable | e.g. `"amount 4.2x account median"` or `"USD currency on domestic-only merchant Swiggy"` |
| llm_category | text, nullable | only populated when original `category` was blank |
| llm_raw_response | jsonb, nullable | raw Gemini response for that row's batch — keep for debuggability, never re-parse it live |
| llm_failed | boolean, default false | true if this row's batch exhausted retries |

**`job_summaries`**

| Column | Type | Notes |
|---|---|---|
| id | UUID, PK | |
| job_id | UUID, FK → jobs.id, **unique** | one summary per job — unique constraint, not just an index |
| total_spend_inr | numeric(14,2) | |
| total_spend_usd | numeric(14,2) | |
| top_merchants | jsonb | `[{merchant, total_amount, txn_count}, ...]` top 3 |
| anomaly_count | int | |
| narrative | text | the 2-3 sentence LLM narrative |
| risk_level | text | `low` / `medium` / `high` |
| llm_raw_response | jsonb **[added]** | full raw Gemini summary response, for audit/debugging |

**Why a separate `job_summaries` table instead of JSON columns on `jobs`:** keeps `jobs` lean for the high-frequency `GET /jobs` list query, and means a re-run of just the summary step (if you want that as a retry/admin endpoint later) doesn't touch the job row at all.

### 1.4 Folder Structure

```
.
├── docker-compose.yml
├── .env.example
├── .dockerignore
├── README.md
├── diagram.drawio                  # the visual diagram for submission
│
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   │       └── 0001_initial_schema.py
│   │
│   └── app/
│       ├── main.py                 # FastAPI app factory, router registration
│       ├── config.py               # pydantic-settings, reads .env
│       ├── database.py             # engine, SessionLocal, get_db dependency
│       ├── celery_app.py           # Celery() instance, broker/backend config
│       │
│       ├── models/
│       │   ├── job.py
│       │   ├── transaction.py
│       │   └── job_summary.py
│       │
│       ├── schemas/                # Pydantic request/response models
│       │   ├── job.py
│       │   └── transaction.py
│       │
│       ├── routers/
│       │   └── jobs.py             # all 4 endpoints
│       │
│       ├── services/                # pure, unit-testable, no Celery/FastAPI imports
│       │   ├── cleaning.py          # data cleaning pipeline (step a)
│       │   ├── anomaly.py           # anomaly detection rules (step b)
│       │   └── llm_client.py        # Gemini wrapper: categorize_batch(), generate_summary()
│       │
│       ├── tasks/
│       │   └── pipeline.py          # the 5 Celery tasks, orchestration only — calls into services/
│       │
│       └── core/
│           └── logging.py           # structured logging setup
│
└── tests/
    ├── test_cleaning.py
    ├── test_anomaly.py
    └── test_api_contracts.py
```

**Why `services/` is separated from `tasks/`:** the cleaning and anomaly logic are pure functions (CSV in, DataFrame out) with zero dependency on Celery or the DB session. That means they can be unit tested directly against `transactions.csv` without spinning up Redis or Postgres — which matters a lot given the 4-day deadline. `tasks/pipeline.py` is intentionally thin: it just wires `services/` functions to DB writes and status transitions.

---

## PHASE 2 — Implementation Order, Dependencies, Environment

### 2.1 Build Order (do not skip ahead — each step should run/test before the next)

| Step | File(s) | Why this order |
|---|---|---|
| 1 | `docker-compose.yml` (postgres + redis only), `.env.example` | Get the two stateful services up first (`docker compose up postgres redis`) so everything after this has something real to connect to — no mocking infra. |
| 2 | `config.py`, `database.py` | Confirms the app can read env vars and open a DB connection before any business logic exists. |
| 3 | `models/job.py`, `models/transaction.py`, `models/job_summary.py` | ORM models are the contract everything else depends on. |
| 4 | Alembic init + `0001_initial_schema.py` | Generate and apply the first migration. Verify with `psql` that the 3 tables + indexes exist exactly as designed in Phase 1.3. |
| 5 | `services/cleaning.py` | Pure function, testable immediately against the real `transactions.csv` with zero infra. This is where 90% of the assignment's "dirty data" requirements get satisfied — get it right before touching Celery. |
| 6 | `services/anomaly.py` | Same — pure function, unit test against the cleaned DataFrame. |
| 7 | `services/llm_client.py` | Wrap Gemini behind two functions: `categorize_batch(rows) -> dict[txn_id, category]` and `generate_summary(df) -> dict`. Build this with retry/backoff logic in isolation (mock the API in tests) before Celery ever calls it. |
| 8 | `celery_app.py`, `tasks/pipeline.py` | Now wire the tested pure functions into the 5-task chain. This is where job `status` transitions and DB writes happen. |
| 9 | `schemas/job.py`, `schemas/transaction.py` | Pydantic response models, written against what `tasks/pipeline.py` actually produces. |
| 10 | `routers/jobs.py`, `main.py` | The 4 endpoints. By this point the worker pipeline is fully tested in isolation, so the API layer is just plumbing: validate upload → insert Job → enqueue → return. |
| 11 | `docker-compose.yml` (add `api` + `worker` services) | Now bring up the full stack with one command and run an end-to-end curl test against the real `transactions.csv`. |
| 12 | `core/logging.py`, retry/error-handling polish | Phase 4 concerns — added once the happy path works end-to-end. |
| 13 | `tests/`, `README.md`, `diagram.drawio` | Last, but don't leave it for the last hour — the README + diagram are explicitly graded deliverables. |

### 2.2 Dependency List (`api/requirements.txt`)

| Package | Purpose |
|---|---|
| `fastapi` | API framework |
| `uvicorn[standard]` | ASGI server |
| `python-multipart` | required by FastAPI for `UploadFile` form parsing |
| `sqlalchemy>=2.0` | ORM |
| `alembic` | migrations |
| `psycopg2-binary` | Postgres driver (sync — simplest for a Celery-worker-driven pipeline; no need for asyncpg since the heavy work happens in Celery, not in async route handlers) |
| `celery[redis]` | task queue, with Redis transport extras |
| `redis` | direct Redis client (used by Celery under the hood, and optionally for a status cache later) |
| `pydantic-settings` | typed `.env` loading |
| `pandas` | CSV parsing + cleaning + median/groupby logic — far less error-prone than hand-rolled parsing for this dataset's specific dirtiness (mixed date formats, `$` prefixes, casing) |
| `google-genai` | official Gemini SDK |
| `tenacity` | declarative retry/backoff for the LLM client (cleaner than hand-rolled `try/except` loops) |
| `python-dotenv` | local dev convenience, loading `.env` outside Docker |
| `pytest` | tests |

### 2.3 Environment Variables (`.env.example`)

| Variable | Example | Notes |
|---|---|---|
| `POSTGRES_USER` | `app` | |
| `POSTGRES_PASSWORD` | `app` | dev only — never commit a real prod password |
| `POSTGRES_DB` | `transactions` | |
| `DATABASE_URL` | `postgresql://app:app@db:5432/transactions` | host is the Compose service name `db`, not `localhost` |
| `REDIS_URL` | `redis://redis:6379/0` | |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | can share the DB index with result backend for this scale; split in Phase 6 |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` | |
| `GEMINI_API_KEY` | `<your-key>` | free tier |
| `GEMINI_MODEL` | `gemini-1.5-flash` | |
| `LLM_BATCH_SIZE` | `20` | rows per categorization call |
| `LLM_MAX_RETRIES` | `3` | matches assignment spec exactly |
| `MAX_UPLOAD_MB` | `10` | inline validation limit at the route |
| `LOG_LEVEL` | `INFO` | |
| `ENV` | `development` | toggles debug logging of raw LLM payloads |

---

## PHASE 3 — API Contracts & Database Models

### 3.1 `POST /jobs/upload`

Request: `multipart/form-data`, field name `file`, content-type `text/csv`.

```
curl -X POST http://localhost:8000/jobs/upload \
  -F "file=@transactions.csv"
```

Response `202 Accepted`:
```json
{
  "job_id": "b2f8c1d4-...",
  "status": "pending",
  "filename": "transactions.csv"
}
```

Error `400` (wrong extension, empty file, missing required headers):
```json
{ "detail": "Invalid file: expected a non-empty CSV with the required columns." }
```

### 3.2 `GET /jobs/{job_id}/status`

```
curl http://localhost:8000/jobs/b2f8c1d4-.../status
```

While processing — `200`:
```json
{
  "job_id": "b2f8c1d4-...",
  "status": "processing",
  "filename": "transactions.csv",
  "row_count_raw": 95,
  "row_count_clean": null,
  "created_at": "2026-06-18T09:00:00Z"
}
```

Once completed — `200`, with the `summary` field the assignment explicitly asks for:
```json
{
  "job_id": "b2f8c1d4-...",
  "status": "completed",
  "filename": "transactions.csv",
  "row_count_raw": 95,
  "row_count_clean": 89,
  "created_at": "2026-06-18T09:00:00Z",
  "completed_at": "2026-06-18T09:00:42Z",
  "summary": {
    "anomaly_count": 6,
    "llm_failed_count": 0,
    "risk_level": "medium"
  }
}
```

`404` if `job_id` doesn't exist.

### 3.3 `GET /jobs/{job_id}/results`

Design decision worth stating in the review video: if the job isn't done yet, this endpoint returns `200` (not `409`/`425`) with just `{job_id, status}` — polling clients shouldn't have to special-case error codes for "not ready yet," that's a normal, expected state, not an error.

```
curl http://localhost:8000/jobs/b2f8c1d4-.../results
```

Not ready — `200`:
```json
{ "job_id": "b2f8c1d4-...", "status": "processing" }
```

Completed — `200`:
```json
{
  "job_id": "b2f8c1d4-...",
  "status": "completed",
  "transactions": [
    {
      "txn_id": "TXN1054",
      "date": "2024-02-05",
      "merchant": "Swiggy",
      "amount": 11325.79,
      "currency": "INR",
      "status": "SUCCESS",
      "category": "Food",
      "account_id": "ACC004",
      "is_anomaly": true,
      "anomaly_reason": "amount 4.1x account ACC004 median",
      "llm_category": null,
      "llm_failed": false
    }
  ],
  "anomalies": [
    { "txn_id": "TXN1054", "reason": "amount 4.1x account ACC004 median" },
    { "txn_id": "TXN1009", "reason": "USD currency on domestic-only merchant MakeMyTrip" }
  ],
  "category_breakdown": [
    { "category": "Food", "total_amount": 38250.10, "txn_count": 14 },
    { "category": "Shopping", "total_amount": 51120.40, "txn_count": 22 }
  ],
  "summary": {
    "total_spend_inr": 412300.55,
    "total_spend_usd": 9100.20,
    "top_merchants": [
      { "merchant": "Amazon", "total_amount": 88210.40 },
      { "merchant": "Swiggy", "total_amount": 41200.10 },
      { "merchant": "Flipkart", "total_amount": 35900.00 }
    ],
    "anomaly_count": 6,
    "narrative": "Spending is concentrated in shopping and food delivery, with a small cluster of unusually large transactions on account ACC004. Two cross-border charges on domestic-only merchants warrant review.",
    "risk_level": "medium"
  }
}
```

`404` if job doesn't exist.

### 3.4 `GET /jobs`

```
curl "http://localhost:8000/jobs?status=completed"
```

`200`:
```json
{
  "jobs": [
    {
      "job_id": "b2f8c1d4-...",
      "filename": "transactions.csv",
      "status": "completed",
      "row_count_raw": 95,
      "row_count_clean": 89,
      "created_at": "2026-06-18T09:00:00Z"
    }
  ],
  "count": 1
}
```

Invalid `status` value → `422` (FastAPI's native enum validation on the query param — don't hand-roll this check).

### 3.5 Database Models (field-level spec, implement as SQLAlchemy `declarative_base` classes)

This is the schema from 1.3 expressed as the model layer contract — each class below maps 1:1 to the table already designed, so there's no new information here, just pinned down as the implementation target:

- **`Job`**: `id: UUID (pk)`, `filename: str`, `file_path: str`, `status: Enum`, `row_count_raw: int | None`, `row_count_clean: int | None`, `error_message: str | None`, `created_at: datetime`, `updated_at: datetime`, `completed_at: datetime | None`. Relationship: `transactions: list[Transaction]` (one-to-many, `cascade="all, delete-orphan"`), `summary: JobSummary | None` (one-to-one).
- **`Transaction`**: all fields from 1.3, `job_id: UUID (fk)`. Relationship: `job: Job` (back-reference).
- **`JobSummary`**: all fields from 1.3, `job_id: UUID (fk, unique)`. Relationship: `job: Job` (back-reference, one-to-one via `uselist=False`).

Indexes to declare explicitly in the model `__table_args__` (don't rely on Alembic autogenerate catching all of these — it sometimes misses composite indexes):
`Index("ix_transactions_job_id", "job_id")`, `Index("ix_transactions_job_account", "job_id", "account_id")`, `Index("ix_jobs_status", "status")`, `Index("ix_jobs_created_at", "created_at")`.

---

## PHASE 4 — Celery Workflow, Retry, Error Handling, Logging

### 4.1 Celery Workflow

A strict **chain** (not a chord/group) — each step depends on the previous one's DB state, so there's no parallelism opportunity within a single job at this scale:

```
upload (API) → clean_transactions(job_id)
                    │ sets status=processing, bulk-inserts Transaction rows
                    ▼
            detect_anomalies(job_id)
                    │ bulk-updates is_anomaly / anomaly_reason
                    ▼
            llm_categorize_batch(job_id)
                    │ batched Gemini calls, writes llm_category
                    ▼
            llm_generate_summary(job_id)
                    │ one Gemini call, inserts JobSummary
                    ▼
            finalize_job(job_id)
                    │ sets status=completed / completed_at
```

Use Celery's `chain()` primitive explicitly (`chain(clean_transactions.s(job_id), detect_anomalies.s(), ...).apply_async()`) rather than having each task call the next one manually — this keeps retry/failure semantics native to Celery instead of hand-rolled, and makes the pipeline visible in Flower/monitoring as a single traceable chain.

Within `llm_categorize_batch`, the **batching** the assignment explicitly requires: group all rows with blank `category` into chunks of `LLM_BATCH_SIZE` (20), one prompt per chunk listing `txn_id, merchant, amount, notes` and asking for a JSON map back. This turns ~90 rows into ~5 Gemini calls instead of 90.

### 4.2 Retry Strategy

Exactly as specified: **3 retries, exponential backoff**, applied only to the two LLM-calling tasks (the cleaning/anomaly steps are deterministic local computation — retrying them on failure would just reproduce the same bug, so they fail fast instead).

```
@celery_app.task(
    bind=True,
    autoretry_for=(GeminiRateLimitError, GeminiTimeoutError),
    retry_backoff=True,       # exponential: 1s, 2s, 4s...
    retry_backoff_max=60,
    retry_jitter=True,        # avoid thundering herd if many jobs hit Gemini at once
    max_retries=3,
)
def llm_categorize_batch(self, job_id): ...
```

Critically: retries apply **per batch**, not per row and not per job. If batch 3 of 5 exhausts its retries, batches 1, 2, 4, 5 are unaffected — only the rows in batch 3 get `llm_failed=True`, and the pipeline moves on to `llm_generate_summary` regardless. This is the exact behavior the assignment spec calls for in step (e).

### 4.3 Error Handling Strategy

Two distinct failure tiers, handled differently:

**Row/batch-level failures (expected, recoverable):** a single Gemini batch failing after 3 retries does **not** fail the job. The affected rows get `llm_failed=True`, `llm_category=NULL`, and the job continues. The final `JobSummary` should reflect this honestly — if `llm_failed_count > 0`, note it rather than silently presenting incomplete data as complete.

**Job-level failures (unexpected, terminal):** anything else unhandled — a malformed CSV that pandas can't parse at all, a DB connection failure, an unhandled exception in the cleaning/anomaly logic — bubbles up, the task catches it at the top level, sets `Job.status=failed`, `Job.error_message=str(exc)`, and does **not** retry (retrying a parse error on the same malformed file just wastes a retry budget reproducing the same failure). `GET /jobs/{id}/status` then surfaces `status=failed` + the message directly so the client knows not to keep polling.

Idempotency: every task is written so re-running it on the same `job_id` is safe (e.g., `clean_transactions` deletes any existing `Transaction` rows for that `job_id` before bulk-inserting, rather than appending) — this matters because Celery's own retry/redelivery semantics can re-invoke a task that partially completed.

### 4.4 Logging Strategy

Structured JSON logs (not free-text), with `job_id` as the correlation ID threaded through every log line from upload to finalization — this is what makes a 4-day-old job's failure debuggable from `docker compose logs worker` alone.

| Level | When |
|---|---|
| `INFO` | task start/end, status transitions, batch counts (`"categorized 4/5 batches successfully"`) |
| `WARNING` | a batch hit `llm_failed` after exhausting retries, a row had unparseable date/amount and was dropped |
| `ERROR` | unhandled exception, job marked `failed` |
| `DEBUG` | raw Gemini request/response payloads — gated behind `ENV=development`, **never** logged in a way that could leak the API key |

Both `api` and `worker` log to stdout (12-factor style) so `docker compose logs` is sufficient for local dev and review; Phase 6 covers where this goes in production.

---

## PHASE 5 — Docker Architecture

### 5.1 Services

| Service | Image/Build | Port | Depends On | Healthcheck |
|---|---|---|---|---|
| `db` | `postgres:16-alpine` | internal only (5432) | — | `pg_isready -U app` |
| `redis` | `redis:7-alpine` | internal only (6379) | — | `redis-cli ping` |
| `api` | build `./api/Dockerfile` | `8000:8000` | `db` (healthy), `redis` (healthy) | `curl -f http://localhost:8000/health` |
| `worker` | build `./api/Dockerfile` (same image, different command: `celery -A app.celery_app worker --loglevel=info`) | none exposed | `db` (healthy), `redis` (healthy) | Celery's `inspect ping` via `celery -A app.celery_app inspect ping` |
| `migrate` *(one-off)* | same image, `alembic upgrade head`, `restart: "no"` | none | `db` (healthy) | runs once on `docker compose up`, exits 0 |

Add a trivial `GET /health` route to the FastAPI app (separate from the `/jobs` routes) purely so Compose's healthcheck has something to poll — this is what unblocks "single `docker compose up`, no manual steps."

**Why `api` and `worker` share one Docker image:** they need the exact same dependencies and application code (`services/`, `models/`) — building two separate images would double the build time and risk version drift between what the API validates and what the worker processes. Differentiate only by the `command:` override in `docker-compose.yml`.

### 5.2 Volumes & Networking

- `postgres_data` named volume → `/var/lib/postgresql/data` (persists across `docker compose down`, lost only on `down -v`).
- `uploaded_csvs` named volume, mounted into both `api` and `worker` at the same path — this is how the worker reads a file the API wrote, without a shared filesystem assumption breaking the moment either service scales past 1 replica (flagged again in Phase 6, where this volume gets replaced by S3).
- Single bridge network (Compose's default) — only `api`'s port is published to the host; `db` and `redis` are reachable by service name only, never exposed externally, even in dev.

### 5.3 Production Considerations (beyond what the assignment requires, but worth one line each in the video)

- Multi-stage `Dockerfile`: a `builder` stage installs dependencies into a venv, a slim `runtime` stage copies just the venv + app code — keeps the final image small and avoids shipping build toolchains.
- Run as a non-root user inside the container.
- `.env` is git-ignored; `.env.example` is committed with placeholder values — secrets never enter the image or the repo.
- `restart: unless-stopped` on `api`/`worker`/`db`/`redis` in a prod compose override, so a crashed worker comes back without manual intervention.
- The `migrate` one-off service pattern means schema changes are applied automatically and exactly once per deploy, never relying on a developer remembering to run `alembic upgrade head` by hand.

---

## PHASE 6 — Scaling to 100× Traffic

This section directly answers the video's "Bottlenecks & Scale" segment — structured the same way: where it breaks first, then what changes, then the trade-off.

### 6.1 Where It Breaks First (in order of how soon you'd hit each ceiling)

1. **Redis as a single broker + result backend.** At 100×, Redis is both the task queue and the Celery result store, on a single instance with no persistence guarantees configured. It's a single point of failure and, under high task throughput, the broker and backend workloads compete for the same memory and connection slots.
2. **Gemini free-tier rate limits.** This breaks first in practice, not last — free-tier RPM/TPM caps are low, and 100× job volume means 100× the categorization batches and summary calls hitting the same external limit from every worker process concurrently. You'll get 429s long before Postgres or Redis notice the load.
3. **Postgres connection pool exhaustion.** Each `api` and `worker` process opens its own SQLAlchemy connection pool; at 100× concurrent uploads plus N worker replicas, the default pool sizes multiply past Postgres's `max_connections` ceiling fast.
4. **Local-disk shared volume for uploaded CSVs.** The moment `api` or `worker` scales beyond a single replica on more than one host, the `uploaded_csvs` volume assumption (both containers see the same file) breaks — this only worked because Compose ran everything on one machine.
5. **Polling load on `GET /status` and `GET /results`.** 100× more jobs means 100× more clients polling every few seconds; this is pure read load on Postgres with no caching layer in front of it.
6. **Single uvicorn process handling uploads synchronously.** Large CSVs at high concurrency block on disk I/O in the request path even before the worker ever sees them.

### 6.2 The Next Iteration — Specific Changes

- **Split broker and result backend**, and move both to managed/clustered services: Redis Cluster (or Amazon ElastiCache/MemoryDB) for the broker, with the result backend either on a separate Redis instance or moved to Postgres entirely (Celery supports a DB result backend) so a broker outage doesn't also wipe result visibility.
- **Put a rate-limiting gateway in front of the LLM calls** — a Redis-backed token bucket shared across all worker processes, so the system self-throttles to Gemini's actual quota instead of every worker independently hammering the API and all getting 429s simultaneously. Pair with a cache (hash of merchant+notes → category) so repeat patterns across jobs skip the LLM call entirely.
- **PgBouncer in front of Postgres** for connection pooling/multiplexing, plus a **read replica** dedicated to the polling endpoints (`GET /status`, `GET /results`, `GET /jobs`) so read-heavy polling traffic never competes with the worker's writes on the primary.
- **Move uploaded files to S3 (or equivalent object storage)**, with the API issuing pre-signed upload URLs where possible so large files don't even transit the API process. Workers read directly from S3 by key.
- **Cache job status** in Redis with a short TTL (a few seconds), invalidated on status transition — turns the hottest read path into a cache hit instead of a DB round-trip for the common case of a client polling every 2 seconds against a job that hasn't changed state since the last poll.
- **Split Celery queues by workload type** — a `cpu` queue for cleaning/anomaly detection and an `llm` queue for the Gemini-calling tasks, each with its own worker pool sized to its bottleneck (CPU-bound vs IO/rate-limit-bound), and autoscaled independently (e.g., via KEDA on queue depth in Kubernetes) rather than one undifferentiated worker pool.
- **Horizontal autoscaling for `api` and `worker`** behind a load balancer / Kubernetes Deployment with HPA, replacing the single Compose replica of each.
- **Observability**: OpenTelemetry tracing keyed on `job_id` end-to-end (API → broker → worker → Gemini → DB), Prometheus metrics on queue depth and task latency, centralized log aggregation (Loki/ELK) — without this, debugging a stuck job across 50 worker replicas is close to impossible.

### 6.3 Trade-offs (worth saying out loud in the video, not just listing the upgrade)

- **PgBouncer** solves connection exhaustion but adds a network hop and a class of subtle bugs around session-mode vs transaction-mode pooling (e.g., session-level features like advisory locks behave differently) — pick transaction pooling deliberately, not by default.
- **Caching job status** reduces DB load but introduces a few seconds of staleness; acceptable for a polling UI, not acceptable if a downstream system needs to react to `completed` the instant it happens (in which case the actual fix is moving off polling entirely toward webhooks/SSE — a bigger change than caching, and worth naming as the "real" fix even if caching is the pragmatic interim step).
- **S3 for uploads** removes the shared-filesystem assumption and enables true horizontal scaling, at the cost of added latency per file read/write and a new external dependency to manage (IAM, retries, eventual consistency on some object stores).
- **Splitting Celery queues** gives independent scaling and isolates the rate-limited LLM workload from the CPU-bound one, but adds operational complexity — now there are two worker fleets to monitor, deploy, and right-size instead of one.
- **A local/self-hosted model (Ollama) instead of Gemini** removes the external rate-limit ceiling entirely, at the cost of needing real compute infrastructure (GPU or beefy CPU instances) and very likely a drop in categorization/summary quality compared to a hosted frontier-adjacent model — a real trade-off between throughput ceiling and output quality, not a free upgrade.

---

## Submission Checklist Mapping

For reference, here's how this roadmap maps to what's actually graded:

| Requirement | Where it's covered |
|---|---|
| GitHub repo, single `docker compose up` | Phase 5 |
| README + curl examples | Phase 3.1–3.4 (use these examples directly in the README) |
| Visual diagram (draw.io) | Phase 1.1 — redraw the ASCII diagram in draw.io for submission, same structure |
| Video: System Design & Data Flow (~1 min) | Phase 1.1 (the "why" of API/worker split) + Phase 1.2 (request lifecycle trace) |
| Video: Bottlenecks & Scale (~2 min) | Phase 6.1 (breaking points) + Phase 6.2 (next iteration) + Phase 6.3 (trade-offs) — this is almost a direct script |
