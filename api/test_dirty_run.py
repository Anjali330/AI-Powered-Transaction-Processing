import os, uuid
os.environ.setdefault("DATABASE_URL", "postgresql://app:app@localhost:5432/transactions")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

from app.services.cleaning import clean_csv

result = clean_csv("test_dirty.csv", uuid.uuid4())
print(f"original_row_count : {result.original_row_count}")
print(f"cleaned_row_count  : {result.cleaned_row_count}")
print(f"duplicates_removed : {result.duplicates_removed}")
print(f"invalid_rows       : {result.invalid_rows}")
print()
for r in result.rows:
    print(f"  {r['txn_id']:8} | {r['date']} | {r['merchant']:20} | {r['amount']:>10} | {r['currency']} | {r['status']}")
