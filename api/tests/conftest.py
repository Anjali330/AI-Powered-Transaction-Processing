"""
conftest.py — shared fixtures for the test suite.

Uses the real PostgreSQL database from DATABASE_URL.
Each test runs inside a transaction that is rolled back after the test
completes — no data persists between tests, no schema modifications needed.
"""
import io
import uuid
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.config import settings
from app.database import get_db
from app.models.job import Job
from app.models.transaction import Transaction
from app.models.job_summary import JobSummary


# ── Postgres engine (reuses DATABASE_URL from .env) ──────────────────────────

engine = create_engine(settings.database_url, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(scope="function")
def db_session():
    """
    Yields a Session that runs inside a transaction which is rolled back
    after the test. The outer connection is never committed so the DB
    stays clean between tests without dropping or recreating tables.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
def client(db_session):
    """TestClient wired to the rollback session; Celery task mocked out."""

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db

    with patch("app.routers.jobs.process_job") as mock_task:
        mock_task.delay = MagicMock()
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, db_session, mock_task

    app.dependency_overrides.clear()


# ── CSV helpers ───────────────────────────────────────────────────────────────

VALID_CSV_HEADER = "txn_id,date,merchant,amount,currency,status,category,account_id,notes\n"


def make_csv(*rows: str) -> bytes:
    """Build a minimal valid CSV from header + supplied data rows."""
    return (VALID_CSV_HEADER + "\n".join(rows) + "\n").encode()
