import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# ── Upload response ──────────────────────────────────────────────────────────

class JobUploadResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    filename: str


# ── Status response ──────────────────────────────────────────────────────────

class JobStatusSummary(BaseModel):
    anomaly_count: int | None
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


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    txn_id: str | None
    date: Any
    merchant: str
    amount: Any
    currency: str
    status: str
    category: str | None
    account_id: str
    is_anomaly: bool
    anomaly_reason: str | None
    llm_category: str | None
    llm_failed: bool


class AnomalyOut(BaseModel):
    txn_id: str | None
    reason: str | None


class CategoryBreakdownOut(BaseModel):
    category: str | None
    total_amount: Any
    txn_count: int


class TopMerchantOut(BaseModel):
    merchant: str
    total_amount: Any


class SummaryOut(BaseModel):
    total_spend_inr: Any
    total_spend_usd: Any
    top_merchants: list[Any] | None
    anomaly_count: int | None
    narrative: str | None
    risk_level: str | None


class JobResultsResponse(BaseModel):
    job_id: uuid.UUID
    status: str
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
