import uuid
from enum import Enum
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.job import Job
from app.models.job_summary import JobSummary
from app.models.transaction import Transaction
from app.schemas.job import (
    AnomalyOut,
    JobListItem,
    JobListResponse,
    JobResultsPending,
    JobResultsResponse,
    JobStatusResponse,
    JobStatusSummary,
    JobUploadResponse,
    SummaryOut,
    TransactionOut,
)
from app.tasks.pipeline import process_job

router = APIRouter(prefix="/jobs", tags=["jobs"])

UPLOAD_DIR = Path("uploaded_csvs")


class JobStatusFilter(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


# ── POST /jobs/upload ────────────────────────────────────────────────────────

@router.post("/upload", status_code=status.HTTP_202_ACCEPTED, response_model=JobUploadResponse)
def upload_job(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> JobUploadResponse:
    # Validate extension
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file: expected a non-empty CSV with the required columns.",
        )

    # Validate size (read up to max+1 bytes to detect oversize without loading all)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    contents = file.file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum allowed size of {settings.max_upload_mb} MB.",
        )
    if len(contents) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file: expected a non-empty CSV with the required columns.",
        )

    # Persist file
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4()
    file_path = UPLOAD_DIR / f"{job_id}.csv"
    file_path.write_bytes(contents)

    # Insert Job row
    job = Job(
        id=job_id,
        filename=file.filename,
        file_path=str(file_path),
        status="pending",
    )
    db.add(job)
    db.commit()

    # Enqueue task
    process_job.delay(str(job_id))

    return JobUploadResponse(job_id=job_id, status="pending", filename=file.filename)


# ── GET /jobs/{job_id}/status ────────────────────────────────────────────────

@router.get("/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobStatusResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    summary_out: JobStatusSummary | None = None
    if job.status == "completed" and job.summary:
        summary_out = JobStatusSummary(
            anomaly_count=job.summary.anomaly_count,
            risk_level=job.summary.risk_level,
        )

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        summary=summary_out,
    )


# ── GET /jobs/{job_id}/results ───────────────────────────────────────────────

@router.get("/{job_id}/results")
def get_job_results(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    # Not ready yet — return lightweight polling response (200, not 4xx)
    if job.status != "completed":
        return JobResultsPending(job_id=job.id, status=job.status)

    # Fetch transactions
    txns = db.scalars(
        select(Transaction).where(Transaction.job_id == job_id)
    ).all()

    anomalies = [
        AnomalyOut(txn_id=t.txn_id, reason=t.anomaly_reason)
        for t in txns
        if t.is_anomaly
    ]

    summary_row: JobSummary | None = job.summary
    summary_out: SummaryOut | None = None
    if summary_row:
        summary_out = SummaryOut(
            total_spend_inr=summary_row.total_spend_inr,
            total_spend_usd=summary_row.total_spend_usd,
            top_merchants=summary_row.top_merchants,
            anomaly_count=summary_row.anomaly_count,
            narrative=summary_row.narrative,
            risk_level=summary_row.risk_level,
        )

    return JobResultsResponse(
        job_id=job.id,
        status=job.status,
        transactions=[TransactionOut.model_validate(t) for t in txns],
        anomalies=anomalies,
        summary=summary_out,
    )


# ── GET /jobs ────────────────────────────────────────────────────────────────

@router.get("", response_model=JobListResponse)
def list_jobs(
    status: JobStatusFilter | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> JobListResponse:
    stmt = select(Job).order_by(Job.created_at.desc())
    if status is not None:
        stmt = stmt.where(Job.status == status.value)
    stmt = stmt.limit(limit).offset(offset)

    jobs = db.scalars(stmt).all()
    return JobListResponse(
        jobs=[
            JobListItem(
                job_id=j.id,
                filename=j.filename,
                status=j.status,
                row_count_raw=j.row_count_raw,
                row_count_clean=j.row_count_clean,
                created_at=j.created_at,
            )
            for j in jobs
        ],
        count=len(jobs),
    )
