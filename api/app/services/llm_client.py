"""
services/llm_client.py

Groq LLM wrapper (llama-3.3-70b-versatile or any Groq-hosted model).
Two public functions:
  enrich_batch(rows)     → category / subcategory / risk_level /
                           merchant_type / confidence per transaction.
  generate_summary(rows) → portfolio-level JobSummary dict.

Both degrade gracefully: Groq errors → llm_failed=True on affected rows,
local fallback summary used — the job never fails because of LLM issues.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random,
    wait_exponential,
    wait_combine,
)

from app.config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER = "<your-key>"


def _is_key_configured() -> bool:
    k = settings.groq_api_key
    return bool(k) and k != _PLACEHOLDER


def _get_client():
    from groq import Groq
    return Groq(api_key=settings.groq_api_key)


# ── shared retry decorator ────────────────────────────────────────────────────

def _llm_retry(func):
    return retry(
        reraise=True,
        stop=stop_after_attempt(settings.llm_max_retries),
        wait=wait_combine(wait_exponential(multiplier=1, min=2, max=60), wait_random(min=0, max=2)),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )(func)


# ── enrichment ────────────────────────────────────────────────────────────────

_ENRICH_SYSTEM = """\
You are a financial transaction classifier.
Given a JSON array of transactions, return a JSON array (same length, same order).
Each element must have exactly these keys:
  txn_id        : original txn_id (string or null)
  category      : e.g. Food, Shopping, Travel, Utilities, Healthcare, Entertainment
  subcategory   : e.g. Delivery, Ecommerce, Ride Sharing, Streaming
  merchant_type : e.g. Online Retailer, Restaurant, Airline, Pharmacy
  risk_level    : "low" | "medium" | "high"
  confidence    : float 0.0–1.0

Return ONLY a valid JSON array. No markdown, no explanation."""


@_llm_retry
def _call_enrich(batch: list[dict]) -> str:
    payload = [
        {
            "txn_id": r.get("txn_id"),
            "merchant": r.get("merchant"),
            "amount": str(r.get("amount", 0)),
            "currency": r.get("currency"),
            "category": r.get("category") or "",
            "notes": r.get("notes") or "",
        }
        for r in batch
    ]
    if settings.env == "development":
        logger.debug("enrich request payload: %s", json.dumps(payload))
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": _ENRICH_SYSTEM},
            {"role": "user", "content": json.dumps(payload)},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    if settings.env == "development":
        logger.debug("enrich response payload: %s", raw)
    return raw


def enrich_batch(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Enrich rows with LLM-generated fields.
    Processes in chunks of settings.llm_batch_size.
    Sets llm_failed=True on any batch that exhausts retries.
    Mutates rows in-place, returns the same list.
    """
    if not rows or not _is_key_configured():
        if not _is_key_configured():
            logger.warning("GROQ_API_KEY not configured — skipping LLM enrichment")
        return rows

    batch_size = settings.llm_batch_size
    batches = [rows[i: i + batch_size] for i in range(0, len(rows), batch_size)]
    logger.info("llm enrichment: %d rows across %d batch(es)", len(rows), len(batches))

    for idx, batch in enumerate(batches):
        try:
            raw = _call_enrich(batch)
            # Groq json_object mode wraps arrays — handle both cases
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                # unwrap common wrapper keys
                for key in ("transactions", "results", "data", "items"):
                    if key in parsed and isinstance(parsed[key], list):
                        parsed = parsed[key]
                        break
                else:
                    # try first list value
                    for v in parsed.values():
                        if isinstance(v, list):
                            parsed = v
                            break

            if not isinstance(parsed, list) or len(parsed) != len(batch):
                raise ValueError(f"Expected list of {len(batch)}, got {type(parsed).__name__}({len(parsed) if isinstance(parsed, list) else '?'})")

            for row, enc in zip(batch, parsed):
                row["llm_category"]      = enc.get("category") or row.get("category")
                row["llm_subcategory"]   = enc.get("subcategory")
                row["llm_risk_level"]    = enc.get("risk_level")
                row["llm_merchant_type"] = enc.get("merchant_type")
                row["llm_confidence"]    = enc.get("confidence")
                row["llm_raw_response"]  = enc

            logger.info("batch %d/%d enriched OK", idx + 1, len(batches))

        except Exception as exc:
            logger.error("batch %d/%d failed: %s", idx + 1, len(batches), exc)
            for row in batch:
                row["llm_failed"] = True

    return rows


# ── summary generation ────────────────────────────────────────────────────────

_SUMMARY_SYSTEM = """\
You are a financial analyst. Given a JSON array of transactions, return a single JSON object:
  total_transactions : int
  total_spend        : float
  top_merchants      : [{merchant, total_amount, txn_count}] top 3 by spend
  category_breakdown : {category: {total_amount, txn_count}}
  anomaly_count      : int  (rows where is_anomaly is true)
  ai_summary         : 2-3 sentence plain-English narrative of patterns and risks
  risk_level         : "low" | "medium" | "high"

Return ONLY a valid JSON object. No markdown, no explanation."""


@_llm_retry
def _call_summary(payload: str) -> str:
    if settings.env == "development":
        logger.debug("summary request payload: %s", payload)
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user", "content": payload},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    if settings.env == "development":
        logger.debug("summary response payload: %s", raw)
    return raw


def generate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Generate a portfolio-level summary via Groq.
    Falls back to locally-computed summary on any failure.
    """
    fallback = _local_summary(rows)

    if not _is_key_configured():
        logger.warning("GROQ_API_KEY not configured — using local summary")
        return fallback

    compact = [
        {
            "txn_id":     r.get("txn_id"),
            "merchant":   r.get("merchant"),
            "amount":     str(r.get("amount", 0)),
            "currency":   r.get("currency"),
            "category":   r.get("llm_category") or r.get("category"),
            "status":     r.get("status"),
            "is_anomaly": r.get("is_anomaly", False),
        }
        for r in rows
    ]

    try:
        raw = _call_summary(json.dumps(compact))
        result: dict = json.loads(raw)
        result["anomaly_count"]    = fallback["anomaly_count"]   # always trust local count
        result["llm_raw_response"] = result.copy()
        return result
    except Exception as exc:
        logger.error("summary generation failed: %s — using local fallback", exc)
        return fallback


# ── local fallback (no LLM) ───────────────────────────────────────────────────

def _local_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_spend    = sum(Decimal(str(r.get("amount", 0))) for r in rows)
    anomaly_count  = sum(1 for r in rows if r.get("is_anomaly"))

    merchant_spend: dict[str, Decimal] = defaultdict(Decimal)
    merchant_count: dict[str, int]     = defaultdict(int)
    for r in rows:
        m = r.get("merchant") or "Unknown"
        merchant_spend[m] += Decimal(str(r.get("amount", 0)))
        merchant_count[m] += 1

    top_merchants = sorted(
        [{"merchant": m, "total_amount": float(v), "txn_count": merchant_count[m]}
         for m, v in merchant_spend.items()],
        key=lambda x: x["total_amount"], reverse=True,
    )[:3]

    cat_spend: dict[str, Decimal] = defaultdict(Decimal)
    cat_count: dict[str, int]     = defaultdict(int)
    for r in rows:
        cat = r.get("llm_category") or r.get("category") or "Uncategorized"
        cat_spend[cat] += Decimal(str(r.get("amount", 0)))
        cat_count[cat] += 1

    category_breakdown = {
        cat: {"total_amount": float(cat_spend[cat]), "txn_count": cat_count[cat]}
        for cat in cat_spend
    }

    risk = "high" if anomaly_count > 5 else "medium" if anomaly_count > 1 else "low"

    return {
        "total_transactions": len(rows),
        "total_spend":        float(total_spend),
        "top_merchants":      top_merchants,
        "category_breakdown": category_breakdown,
        "anomaly_count":      anomaly_count,
        "ai_summary": (
            f"Processed {len(rows)} transactions totalling {float(total_spend):,.2f}. "
            f"Detected {anomaly_count} anomalies. Risk level: {risk}."
        ),
        "risk_level":         risk,
        "llm_raw_response":   None,
    }
