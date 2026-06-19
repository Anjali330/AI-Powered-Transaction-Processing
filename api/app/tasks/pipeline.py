import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.job import Job
from app.models.job_summary import JobSummary
from app.models.transaction import Transaction
from app.services.anomaly import detect_anomalies
from app.services.cleaning import clean_csv
from app.services.llm_client import enrich_batch, generate_summary

logger = logging.getLogger(__name__)


def _set_status(db: Session, job: Job, status: str) -> None:
    job.status = status
    job.updated_at = datetime.now(timezone.utc)
    db.commit()


@celery_app.task(name="app.tasks.pipeline.process_job", bind=True)
def process_job(self, job_id: str) -> None:
    """
    Full pipeline:
      1. Mark job → processing
      2. Clean CSV
      3. Rule-based anomaly detection
      4. LLM enrichment (batched, graceful degradation)
      5. Bulk-insert / update Transaction rows
      6. Generate & persist JobSummary
      7. Mark job → completed
    """
    jid = uuid.UUID(job_id)
    db = SessionLocal()
    try:
        job = db.get(Job, jid)
        if job is None:
            logger.error("process_job: unknown job_id=%s", job_id)
            return

        # ── 1. processing ────────────────────────────────────────────────────
        _set_status(db, job, "processing")
        logger.info("job_id=%s status=processing", job_id)

        # ── 2. clean CSV ─────────────────────────────────────────────────────
        result = clean_csv(job.file_path, jid)
        logger.info(
            "job_id=%s raw=%d cleaned=%d dupes=%d invalid=%d",
            job_id, result.original_row_count, result.cleaned_row_count,
            result.duplicates_removed, result.invalid_rows,
        )

        rows = result.rows
        if not rows:
            logger.warning("job_id=%s no valid rows after cleaning", job_id)

        # ── 3. anomaly detection ─────────────────────────────────────────────
        rows = detect_anomalies(rows)

        # ── 4. LLM enrichment ────────────────────────────────────────────────
        rows = enrich_batch(rows)

        # ── 5. idempotent bulk insert ────────────────────────────────────────
        db.execute(delete(Transaction).where(Transaction.job_id == jid))
        db.commit()

        if rows:
            # Filter each dict to only keys that exist on the Transaction model
            _txn_cols = {c.key for c in Transaction.__table__.columns}
            db.bulk_insert_mappings(
                Transaction,
                [{k: v for k, v in r.items() if k in _txn_cols} for r in rows],
            )
            db.commit()

        # ── 6. generate & persist summary ────────────────────────────────────
        summary_data = generate_summary(rows)

        # Upsert JobSummary (delete-then-insert for idempotency)
        db.execute(delete(JobSummary).where(JobSummary.job_id == jid))
        db.commit()

        job_summary = JobSummary(
            job_id=jid,
            total_spend_inr=_spend_by_currency(rows, "INR"),
            total_spend_usd=_spend_by_currency(rows, "USD"),
            top_merchants=summary_data.get("top_merchants"),
            anomaly_count=summary_data.get("anomaly_count", 0),
            narrative=summary_data.get("ai_summary"),
            risk_level=summary_data.get("risk_level"),
            category_breakdown=summary_data.get("category_breakdown"),
            ai_summary=summary_data.get("ai_summary"),
            llm_raw_response=summary_data.get("llm_raw_response"),
        )
        db.add(job_summary)

        # ── 7. update metrics & complete ─────────────────────────────────────
        job.row_count_raw = result.original_row_count
        job.row_count_clean = result.cleaned_row_count
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("job_id=%s status=completed", job_id)

    except Exception as exc:
        db.rollback()
        logger.exception("job_id=%s pipeline failed", job_id)
        try:
            job = db.get(Job, jid)
            if job:
                job.status = "failed"
                job.error_message = str(exc)
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            logger.exception("job_id=%s could not write failed status", job_id)
    finally:
        db.close()


def _spend_by_currency(rows: list[dict], currency: str):
    from decimal import Decimal
    total = sum(
        Decimal(str(r.get("amount", 0)))
        for r in rows
        if (r.get("currency") or "").upper() == currency
    )
    return total if total else None
