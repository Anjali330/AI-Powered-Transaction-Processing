import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.job import Job

logger = logging.getLogger(__name__)


def _get_job(db: Session, job_id: uuid.UUID) -> Job | None:
    return db.get(Job, job_id)


@celery_app.task(name="app.tasks.pipeline.process_job", bind=True)
def process_job(self, job_id: str) -> None:
    """
    Placeholder pipeline task.

    Phase 2 behaviour:
      1. Set status → processing
      2. Sleep 5 s  (simulates real work)
      3. Set status → completed + completed_at

    Steps 5–9 (cleaning, anomaly, LLM, summary) are added in later phases.
    """
    jid = uuid.UUID(job_id)
    db = SessionLocal()
    try:
        job = _get_job(db, jid)
        if job is None:
            logger.error("process_job called with unknown job_id=%s", job_id)
            return

        # ── Step 1: mark processing ──────────────────────────────────────────
        job.status = "processing"
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("job_id=%s status=processing", job_id)

        # ── Step 2: placeholder work ─────────────────────────────────────────
        time.sleep(5)

        # ── Step 3: mark completed ───────────────────────────────────────────
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("job_id=%s status=completed", job_id)

    except Exception as exc:
        db.rollback()
        try:
            job = _get_job(db, jid)
            if job:
                job.status = "failed"
                job.error_message = str(exc)
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
        logger.exception("job_id=%s unhandled error, marked failed", job_id)
        raise
    finally:
        db.close()
