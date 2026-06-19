from app.config import settings
from app.services.cleaning import clean_csv
from app.services.anomaly import detect_anomalies
from app.services.llm_client import enrich_batch, generate_summary, _local_summary
import uuid, json

job_id = uuid.uuid4()
result = clean_csv("test_dirty.csv", job_id)
rows = detect_anomalies(result.rows)
rows = enrich_batch(rows)

print("=== Enriched rows ===")
for r in rows:
    print(f"  {r['txn_id']:8} | category={r.get('llm_category'):12} | "
          f"subcategory={r.get('llm_subcategory'):15} | "
          f"risk={r.get('llm_risk_level'):6} | "
          f"merchant_type={r.get('llm_merchant_type'):20} | "
          f"confidence={r.get('llm_confidence')}")

print("\n=== Summary (Groq) ===")
summary = generate_summary(rows)
print(json.dumps(summary, indent=2, default=str))
