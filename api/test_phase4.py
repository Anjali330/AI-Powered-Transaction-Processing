"""
Phase 4 integration test.
Runs clean → anomaly → enrich → summary against test_dirty.csv.
"""
import os
# Do NOT use setdefault — let config.py read the real .env for GEMINI_API_KEY
from app.config import settings
from app.services.cleaning import clean_csv
from app.services.anomaly import detect_anomalies
from app.services.llm_client import enrich_batch, generate_summary
import uuid

job_id = uuid.uuid4()

# ── 1. clean ──────────────────────────────────────────────────────────────────
result = clean_csv("test_dirty.csv", job_id)
print(f"[clean]   raw={result.original_row_count}  clean={result.cleaned_row_count}"
      f"  dupes={result.duplicates_removed}  invalid={result.invalid_rows}")

# ── 2. anomaly detection ──────────────────────────────────────────────────────
rows = detect_anomalies(result.rows)
flagged = sum(1 for r in rows if r.get("is_anomaly"))
print(f"[anomaly] {flagged}/{len(rows)} rows flagged")
for r in rows:
    if r.get("is_anomaly"):
        print(f"          txn_id={r['txn_id']}  reason={r['anomaly_reason']}")

# ── 3. LLM enrichment (no key → graceful skip) ────────────────────────────────
rows = enrich_batch(rows)
enriched = sum(1 for r in rows if r.get("llm_category"))
failed   = sum(1 for r in rows if r.get("llm_failed"))
print(f"[enrich]  enriched={enriched}  llm_failed={failed}")

# ── 4. summary ────────────────────────────────────────────────────────────────
summary = generate_summary(rows)
print(f"[summary] total_spend={summary['total_spend']:.2f}")
print(f"          anomaly_count={summary['anomaly_count']}")
print(f"          risk_level={summary['risk_level']}")
print(f"          ai_summary={summary['ai_summary']}")
print(f"          top_merchants={summary['top_merchants']}")
print(f"          categories={list(summary['category_breakdown'].keys())}")
print("\nPhase 4 pipeline test passed.")
