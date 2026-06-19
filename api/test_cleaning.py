import os, uuid
os.environ.setdefault("DATABASE_URL", "postgresql://app:app@localhost:5432/transactions")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

from app.services.cleaning import clean_csv

result = clean_csv("test.csv", uuid.uuid4())
print(f"original_row_count : {result.original_row_count}")
print(f"cleaned_row_count  : {result.cleaned_row_count}")
print(f"duplicates_removed : {result.duplicates_removed}")
print(f"invalid_rows       : {result.invalid_rows}")
print(f"rows inserted      : {len(result.rows)}")
if result.rows:
    print("\nFirst row:")
    for k, v in result.rows[0].items():
        if k not in ("id", "job_id"):
            print(f"  {k}: {v!r}")
