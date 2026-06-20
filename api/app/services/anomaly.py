"""
services/anomaly.py

Pure rule-based anomaly detection.
Input : list of transaction dicts (as produced by clean_csv).
Output: same list with is_anomaly / anomaly_reason fields updated in-place.
No DB, no Celery, fully unit-testable.
"""
from __future__ import annotations

import logging
from collections import Counter
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

# Amount is flagged if it exceeds this multiple of the per-account median
AMOUNT_MEDIAN_MULTIPLIER = 3.0

# Minimum transactions an account must have before median comparison is meaningful
MIN_ACCOUNT_TXN_FOR_MEDIAN = 3

# Merchants considered India-only — flagged when paired with a non-INR currency.
# Comparisons are case-insensitive and whitespace-tolerant.
DOMESTIC_ONLY_MERCHANTS: frozenset[str] = frozenset({
    "swiggy",
    "zomato",
    "ola",
    "irctc",
    "paytm",
    "make my trip",
})


def detect_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Run all anomaly rules against cleaned transaction rows.
    Mutates is_anomaly and anomaly_reason in-place, returns the same list.

    Rules:
      1. Large transaction  — amount > AMOUNT_MEDIAN_MULTIPLIER × account median
         (only when account has >= MIN_ACCOUNT_TXN_FOR_MEDIAN transactions)
      2. One-off merchant   — merchant appears exactly once across all transactions
      3. Failed transaction — status == FAILED
      4. Currency mismatch  — currency differs from the majority currency in the dataset
      5. Domestic-only USD  — currency is USD and merchant is in DOMESTIC_ONLY_MERCHANTS
    """
    if not rows:
        return rows

    # ── pre-compute per-account medians ─────────────────────────────────────
    account_amounts: dict[str, list[Decimal]] = {}
    for r in rows:
        acc = r.get("account_id") or ""
        amt = r.get("amount")
        if amt is not None and acc:
            account_amounts.setdefault(acc, []).append(Decimal(str(amt)))

    account_median: dict[str, Decimal] = {}
    for acc, amounts in account_amounts.items():
        if len(amounts) >= MIN_ACCOUNT_TXN_FOR_MEDIAN:
            sorted_a = sorted(amounts)
            n = len(sorted_a)
            mid = n // 2
            median = sorted_a[mid] if n % 2 else (sorted_a[mid - 1] + sorted_a[mid]) / 2
            account_median[acc] = median

    # ── pre-compute merchant frequency ──────────────────────────────────────
    merchant_counts: Counter = Counter(
        r.get("merchant", "").lower() for r in rows if r.get("merchant")
    )

    # ── majority currency ────────────────────────────────────────────────────
    currency_counts: Counter = Counter(
        r.get("currency", "") for r in rows if r.get("currency")
    )
    majority_currency = currency_counts.most_common(1)[0][0] if currency_counts else None

    # ── apply rules to each row ──────────────────────────────────────────────
    for row in rows:
        reasons: list[str] = []
        amt = row.get("amount")
        acc = row.get("account_id") or ""
        merchant = row.get("merchant") or ""
        currency = row.get("currency") or ""
        txn_status = row.get("status") or ""

        # Rule 1 — large transaction
        if amt is not None and acc in account_median:
            median = account_median[acc]
            if median > 0 and Decimal(str(amt)) > Decimal(str(AMOUNT_MEDIAN_MULTIPLIER)) * median:
                ratio = float(Decimal(str(amt)) / median)
                reasons.append(f"amount {ratio:.1f}x account {acc} median")

        # Rule 2 — one-off merchant
        if merchant and merchant_counts[merchant.lower()] == 1:
            reasons.append(f"merchant '{merchant}' appears only once")

        # Rule 3 — failed transaction
        if txn_status.upper() == "FAILED":
            reasons.append("transaction status is FAILED")

        # Rule 4 — currency mismatch
        if majority_currency and currency and currency != majority_currency:
            reasons.append(f"currency {currency} differs from majority {majority_currency}")

        # Rule 5 — USD with domestic-only merchant
        if currency == "USD" and merchant and merchant.lower().strip() in DOMESTIC_ONLY_MERCHANTS:
            reasons.append("USD currency used with domestic-only merchant")

        if reasons:
            row["is_anomaly"] = True
            row["anomaly_reason"] = "; ".join(reasons)
            logger.debug("anomaly txn_id=%s reasons=%s", row.get("txn_id"), row["anomaly_reason"])

    flagged = sum(1 for r in rows if r.get("is_anomaly"))
    logger.info("anomaly detection complete: %d/%d flagged", flagged, len(rows))
    return rows
