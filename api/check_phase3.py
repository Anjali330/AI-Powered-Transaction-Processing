import os
os.environ.setdefault("DATABASE_URL", "postgresql://app:app@localhost:5432/transactions")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

from app.services.cleaning import clean_csv, CleaningResult
print("cleaning service OK")

from app.tasks.pipeline import process_job
print("pipeline task OK")

from app.routers.jobs import router
print("router OK")

from app.schemas.job import JobResultsResponse
import inspect
fields = list(JobResultsResponse.model_fields.keys())
print(f"JobResultsResponse fields: {fields}")
assert "original_rows" in fields
assert "cleaned_rows" in fields
assert "duplicates_removed" in fields
print("\nAll Phase 3 imports and schema checks passed.")
