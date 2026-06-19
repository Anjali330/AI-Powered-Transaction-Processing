import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.transaction import AnomalyOut, TransactionOut

__all__ = [
    "AnomalyOut",
    "TransactionOut",
    "JobUploadResponse",
    "JobStatusSummary",
    "JobStatusResponse",
    "JobResultsPending",
    "JobResultsResponse",
    "JobListItem",
    "JobListResponse",
    "SummaryOut",
    "TopMerchantOut",
]


# ── Upload response ──────────────────────────────────────────────────────────

class JobUploadResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    filename: str


# ── Status response ──────────────────────────────────────────────────────────

class JobStatusSummary(BaseModel):
    anomaly_count: int | None
    llm_failed_count: int | None
    risk_level: str | None


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    status: str
    filename: str
    row_count_raw: int | None
    row_count_clean: int | None
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
    summary: JobStatusSummary | None = None


# ── Results response ─────────────────────────────────────────────────────────

class JobResultsPending(BaseModel):
    job_id: uuid.UUID
    status: str


class TopMerchantOut(BaseModel):
    merchant: str
    total_amount: Any
    txn_count: int


class SummaryOut(BaseModel):
    total_spend_inr: Any
    total_spend_usd: Any
    total_spend: Any
    top_merchants: list[Any] | None
    category_breakdown: dict[str, Any] | None
    anomaly_count: int | None
    ai_summary: str | None
    risk_level: str | None


class JobResultsResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    original_rows: int | None
    cleaned_rows: int | None
    duplicates_removed: int | None
    transactions: list[TransactionOut]
    anomalies: list[AnomalyOut]
    summary: SummaryOut | None


# ── List response ────────────────────────────────────────────────────────────

class JobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    filename: str
    status: str
    row_count_raw: int | None
    row_count_clean: int | None
    created_at: datetime


class JobListResponse(BaseModel):
    jobs: list[JobListItem]
    count: int
