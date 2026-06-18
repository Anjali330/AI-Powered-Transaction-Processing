import os
os.environ.setdefault("DATABASE_URL", "postgresql://app:app@localhost:5432/transactions")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

from app.main import app
print("app import OK")
from app.celery_app import celery_app
print("celery_app import OK")
from app.tasks.pipeline import process_job
print("tasks import OK")
from app.schemas.job import JobUploadResponse, JobStatusResponse, JobListResponse
print("schemas import OK")
print("\nAll Phase 2 imports successful.")
