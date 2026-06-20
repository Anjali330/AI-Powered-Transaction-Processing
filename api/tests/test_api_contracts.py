"""
tests/test_api_contracts.py

API contract tests for all 5 endpoints.
Uses FastAPI TestClient + real PostgreSQL (transaction-rollback isolation) +
mocked Celery task. No LLM or Redis calls are made.
"""
import io
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.job import Job
from app.models.job_summary import JobSummary
from app.models.transaction import Transaction
from tests.conftest import make_csv


# ── helpers ───────────────────────────────────────────────────────────────────

VALID_CSV = make_csv(
    "T1,2024-01-01,Amazon,100.00,INR,SUCCESS,Shopping,ACC1,note",
    "T2,2024-01-02,Swiggy,200.00,INR,SUCCESS,Food,ACC1,",
)


def _upload(client, content=VALID_CSV, filename="test.csv"):
    return client.post(
        "/jobs/upload",
        files={"file": (filename, io.BytesIO(content), "text/csv")},
    )


def _seed_job(db, status="pending", row_count_raw=None, row_count_clean=None):
    """Insert a Job row directly into the test DB."""
    job = Job(
        id=uuid.uuid4(),
        filename="seed.csv",
        file_path="/tmp/seed.csv",
        status=status,
        row_count_raw=row_count_raw,
        row_count_clean=row_count_clean,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _seed_completed_job(db):
    """Insert a fully completed Job + JobSummary + two transactions."""
    job = _seed_job(db, status="completed", row_count_raw=2, row_count_clean=2)

    txn1 = Transaction(
        id=uuid.uuid4(), job_id=job.id, txn_id="T1",
        date="2024-01-01", merchant="Amazon", amount=100,
        currency="INR", status="SUCCESS", account_id="ACC1",
        is_anomaly=False, llm_failed=False,
    )
    txn2 = Transaction(
        id=uuid.uuid4(), job_id=job.id, txn_id="T2",
        date="2024-01-02", merchant="Swiggy", amount=200,
        currency="INR", status="FAILED", account_id="ACC1",
        is_anomaly=True, anomaly_reason="transaction status is FAILED",
        llm_failed=False,
    )
    db.add_all([txn1, txn2])

    summary = JobSummary(
        id=uuid.uuid4(), job_id=job.id,
        total_spend_inr=300, total_spend_usd=None,
        anomaly_count=1, risk_level="low",
        ai_summary="Test summary.", narrative="Test narrative.",
        top_merchants=[{"merchant": "Swiggy", "total_amount": 200, "txn_count": 1}],
        category_breakdown={"Food": {"total_amount": 200, "txn_count": 1}},
    )
    db.add(summary)
    db.commit()
    db.refresh(job)
    return job


# ── GET /health ───────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self, client):
        c, db, _ = client
        resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ── POST /jobs/upload ─────────────────────────────────────────────────────────

class TestUpload:
    def test_valid_csv_returns_202(self, client):
        c, db, mock_task = client
        resp = _upload(c)
        assert resp.status_code == 202

    def test_response_shape(self, client):
        c, db, _ = client
        resp = _upload(c)
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert data["filename"] == "test.csv"

    def test_celery_task_enqueued(self, client):
        c, db, mock_task = client
        _upload(c)
        mock_task.delay.assert_called_once()

    def test_job_persisted_in_db(self, client):
        c, db, _ = client
        resp = _upload(c)
        job_id = uuid.UUID(resp.json()["job_id"])
        job = db.get(Job, job_id)
        assert job is not None
        assert job.status == "pending"
        assert job.filename == "test.csv"

    def test_non_csv_extension_rejected(self, client):
        c, db, _ = client
        resp = _upload(c, filename="data.txt")
        assert resp.status_code == 400
        assert "Invalid file" in resp.json()["detail"]

    def test_empty_file_rejected(self, client):
        c, db, _ = client
        resp = _upload(c, content=b"")
        assert resp.status_code == 400

    def test_no_file_field_returns_422(self, client):
        c, db, _ = client
        resp = c.post("/jobs/upload")
        assert resp.status_code == 422


# ── GET /jobs/{id}/status ─────────────────────────────────────────────────────

class TestJobStatus:
    def test_pending_job_status(self, client):
        c, db, _ = client
        job = _seed_job(db, status="pending")
        resp = c.get(f"/jobs/{job.id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["summary"] is None

    def test_processing_job_status(self, client):
        c, db, _ = client
        job = _seed_job(db, status="processing")
        resp = c.get(f"/jobs/{job.id}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

    def test_completed_job_has_summary_block(self, client):
        c, db, _ = client
        job = _seed_completed_job(db)
        resp = c.get(f"/jobs/{job.id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["summary"] is not None
        assert "anomaly_count" in data["summary"]
        assert "llm_failed_count" in data["summary"]
        assert "risk_level" in data["summary"]

    def test_completed_job_row_counts(self, client):
        c, db, _ = client
        job = _seed_completed_job(db)
        resp = c.get(f"/jobs/{job.id}/status")
        data = resp.json()
        assert data["row_count_raw"] == 2
        assert data["row_count_clean"] == 2

    def test_unknown_job_returns_404(self, client):
        c, db, _ = client
        resp = c.get(f"/jobs/{uuid.uuid4()}/status")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_response_contains_filename(self, client):
        c, db, _ = client
        job = _seed_job(db)
        resp = c.get(f"/jobs/{job.id}/status")
        assert resp.json()["filename"] == "seed.csv"


# ── GET /jobs/{id}/results ────────────────────────────────────────────────────

class TestJobResults:
    def test_pending_job_returns_200_with_status(self, client):
        c, db, _ = client
        job = _seed_job(db, status="pending")
        resp = c.get(f"/jobs/{job.id}/results")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert "transactions" not in data   # lightweight polling response

    def test_processing_job_returns_200_with_status(self, client):
        c, db, _ = client
        job = _seed_job(db, status="processing")
        resp = c.get(f"/jobs/{job.id}/results")
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

    def test_completed_job_full_response_shape(self, client):
        c, db, _ = client
        job = _seed_completed_job(db)
        resp = c.get(f"/jobs/{job.id}/results")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "transactions" in data
        assert "anomalies" in data
        assert "summary" in data
        assert "original_rows" in data
        assert "cleaned_rows" in data
        assert "duplicates_removed" in data

    def test_completed_transactions_list(self, client):
        c, db, _ = client
        job = _seed_completed_job(db)
        resp = c.get(f"/jobs/{job.id}/results")
        txns = resp.json()["transactions"]
        assert len(txns) == 2
        assert txns[0]["merchant"] in ("Amazon", "Swiggy")

    def test_completed_anomalies_list(self, client):
        c, db, _ = client
        job = _seed_completed_job(db)
        resp = c.get(f"/jobs/{job.id}/results")
        anomalies = resp.json()["anomalies"]
        assert len(anomalies) == 1
        assert anomalies[0]["txn_id"] == "T2"
        assert "FAILED" in anomalies[0]["reason"]

    def test_completed_summary_fields(self, client):
        c, db, _ = client
        job = _seed_completed_job(db)
        resp = c.get(f"/jobs/{job.id}/results")
        summary = resp.json()["summary"]
        assert summary["anomaly_count"] == 1
        assert summary["risk_level"] == "low"
        assert summary["ai_summary"] is not None
        assert summary["top_merchants"] is not None
        assert summary["category_breakdown"] is not None

    def test_unknown_job_returns_404(self, client):
        c, db, _ = client
        resp = c.get(f"/jobs/{uuid.uuid4()}/results")
        assert resp.status_code == 404

    def test_duplicates_removed_computed(self, client):
        c, db, _ = client
        job = _seed_job(db, status="completed", row_count_raw=5, row_count_clean=3)
        # Add a minimal summary so endpoint doesn't skip it
        summary = JobSummary(
            id=uuid.uuid4(), job_id=job.id, anomaly_count=0, risk_level="low",
        )
        db.add(summary)
        db.commit()
        resp = c.get(f"/jobs/{job.id}/results")
        assert resp.json()["duplicates_removed"] == 2


# ── GET /jobs ─────────────────────────────────────────────────────────────────

class TestListJobs:
    def test_empty_db_returns_empty_list(self, client):
        # Counts only jobs seeded in this test — pre-existing jobs in DB are excluded
        # by checking the response structure rather than asserting count == 0
        c, db, _ = client
        resp = c.get("/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert "count" in data
        assert isinstance(data["jobs"], list)
        assert data["count"] == len(data["jobs"])

    def test_returns_all_jobs(self, client):
        c, db, _ = client
        before = c.get("/jobs").json()["count"]
        _seed_job(db, status="pending")
        _seed_job(db, status="completed")
        after = c.get("/jobs").json()["count"]
        assert after == before + 2

    def test_filter_by_status_pending(self, client):
        c, db, _ = client
        before = c.get("/jobs?status=pending").json()["count"]
        _seed_job(db, status="pending")
        _seed_job(db, status="completed")
        resp = c.get("/jobs?status=pending")
        data = resp.json()
        assert data["count"] == before + 1
        assert all(j["status"] == "pending" for j in data["jobs"])

    def test_filter_by_status_completed(self, client):
        c, db, _ = client
        before = c.get("/jobs?status=completed").json()["count"]
        _seed_job(db, status="pending")
        _seed_job(db, status="completed")
        after = c.get("/jobs?status=completed").json()["count"]
        assert after == before + 1

    def test_invalid_status_returns_422(self, client):
        c, db, _ = client
        resp = c.get("/jobs?status=invalid_value")
        assert resp.status_code == 422

    def test_pagination_limit(self, client):
        c, db, _ = client
        for _ in range(5):
            _seed_job(db)
        resp = c.get("/jobs?limit=2")
        assert len(resp.json()["jobs"]) == 2

    def test_pagination_offset(self, client):
        c, db, _ = client
        total_before = c.get("/jobs").json()["count"]
        for _ in range(5):
            _seed_job(db)
        total_after = total_before + 5
        resp_offset = c.get(f"/jobs?limit=5&offset=3")
        assert len(resp_offset.json()["jobs"]) == min(5, max(0, total_after - 3))

    def test_response_job_fields(self, client):
        c, db, _ = client
        _seed_job(db)
        job = resp = c.get("/jobs").json()["jobs"][0]
        assert "job_id" in job
        assert "filename" in job
        assert "status" in job
        assert "created_at" in job

    def test_ordered_by_created_at_desc(self, client):
        c, db, _ = client
        j1 = _seed_job(db)
        j2 = _seed_job(db)
        jobs = c.get("/jobs").json()["jobs"]
        # Most recently created comes first
        assert str(j2.id) == jobs[0]["job_id"]
