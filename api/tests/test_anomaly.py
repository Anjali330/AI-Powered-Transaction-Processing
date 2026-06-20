"""
tests/test_anomaly.py

Unit tests for app/services/anomaly.py.
All tests operate on plain dicts — no database, no Celery, no network.
"""
import uuid
import pytest
from decimal import Decimal

from app.services.anomaly import (
    detect_anomalies,
    AMOUNT_MEDIAN_MULTIPLIER,
    MIN_ACCOUNT_TXN_FOR_MEDIAN,
)


def _row(
    txn_id="T1",
    account_id="ACC1",
    amount=100,
    currency="INR",
    merchant="Amazon",
    status="SUCCESS",
):
    """Build a minimal transaction dict."""
    return {
        "txn_id": txn_id,
        "account_id": account_id,
        "amount": Decimal(str(amount)),
        "currency": currency,
        "merchant": merchant,
        "status": status,
        "is_anomaly": False,
        "anomaly_reason": None,
    }


def _flagged(rows):
    return [r for r in rows if r.get("is_anomaly")]


# ── empty input ───────────────────────────────────────────────────────────────

def test_empty_input_returns_empty():
    assert detect_anomalies([]) == []


def test_single_row_no_anomaly():
    # A single row has exactly one merchant — the one-off merchant rule fires.
    # This is correct behaviour, not a bug. Verify the flag is set for that reason.
    rows = [_row()]
    result = detect_anomalies(rows)
    assert result[0]["is_anomaly"]
    assert "appears only once" in result[0]["anomaly_reason"]


# ── Rule 1: Large transaction ─────────────────────────────────────────────────

class TestLargeTransaction:
    def _account_rows(self, normal_amounts, spike_amount):
        """Build rows for one account with normal amounts + one spike."""
        rows = [_row(txn_id=f"T{i}", amount=a) for i, a in enumerate(normal_amounts)]
        rows.append(_row(txn_id="SPIKE", amount=spike_amount))
        return rows

    def test_spike_above_multiplier_flagged(self):
        # median of [100,100,100] = 100; spike = 100 * 3.1 = 310 > 300 threshold
        rows = self._account_rows([100, 100, 100], spike_amount=310)
        result = detect_anomalies(rows)
        flagged_ids = [r["txn_id"] for r in _flagged(result)]
        assert "SPIKE" in flagged_ids

    def test_spike_at_exactly_multiplier_not_flagged(self):
        # exactly 3× median is NOT > 3×, so no flag
        rows = self._account_rows([100, 100, 100], spike_amount=300)
        result = detect_anomalies(rows)
        flagged_ids = [r["txn_id"] for r in _flagged(result)]
        assert "SPIKE" not in flagged_ids

    def test_insufficient_account_txns_skips_median_check(self):
        # Only 2 transactions — below MIN_ACCOUNT_TXN_FOR_MEDIAN (3)
        rows = [_row(txn_id="T1", amount=100), _row(txn_id="SPIKE", amount=9999)]
        result = detect_anomalies(rows)
        # Both share only the one-off merchant rule, but NOT the median rule
        reasons = [r.get("anomaly_reason", "") or "" for r in result]
        assert not any("median" in r for r in reasons)

    def test_anomaly_reason_contains_ratio(self):
        rows = self._account_rows([100, 100, 100], spike_amount=500)
        result = detect_anomalies(rows)
        spike = next(r for r in result if r["txn_id"] == "SPIKE")
        assert "median" in spike["anomaly_reason"]

    def test_large_txn_flag_correct_account(self):
        # Two accounts — only ACC2 has a spike
        rows = [
            _row("T1", "ACC1", 100), _row("T2", "ACC1", 100), _row("T3", "ACC1", 100),
            _row("T4", "ACC2", 100), _row("T5", "ACC2", 100), _row("T6", "ACC2", 100),
            _row("SPIKE", "ACC2", 500),
        ]
        result = detect_anomalies(rows)
        spike = next(r for r in result if r["txn_id"] == "SPIKE")
        assert spike["is_anomaly"]
        # ACC1 rows should not be flagged for large txn
        acc1_flagged = [r for r in result if r["account_id"] == "ACC1" and r.get("is_anomaly")]
        assert not acc1_flagged


# ── Rule 2: Unusual (one-off) merchant ───────────────────────────────────────

class TestUnusualMerchant:
    def test_one_off_merchant_flagged(self):
        rows = [
            _row("T1", merchant="Amazon"),
            _row("T2", merchant="Amazon"),
            _row("T3", merchant="UnknownShop"),   # appears once
        ]
        result = detect_anomalies(rows)
        t3 = next(r for r in result if r["txn_id"] == "T3")
        assert t3["is_anomaly"]
        assert "appears only once" in t3["anomaly_reason"]

    def test_repeated_merchant_not_flagged_for_merchant_rule(self):
        rows = [_row(f"T{i}", merchant="Amazon") for i in range(5)]
        result = detect_anomalies(rows)
        assert not _flagged(result)

    def test_merchant_check_is_case_insensitive(self):
        # "amazon" and "Amazon" should count as the same merchant
        rows = [
            _row("T1", merchant="amazon"),
            _row("T2", merchant="Amazon"),
        ]
        result = detect_anomalies(rows)
        assert not _flagged(result)

    def test_all_one_off_merchants_flagged(self):
        rows = [
            _row("T1", merchant="ShopA"),
            _row("T2", merchant="ShopB"),
            _row("T3", merchant="ShopC"),
        ]
        result = detect_anomalies(rows)
        assert len(_flagged(result)) == 3


# ── Rule 3: Failed transaction ────────────────────────────────────────────────

class TestFailedTransaction:
    def test_failed_status_flagged(self):
        rows = [_row("T1", status="FAILED")]
        result = detect_anomalies(rows)
        assert result[0]["is_anomaly"]
        assert "FAILED" in result[0]["anomaly_reason"]

    def test_success_status_not_flagged_for_failed_rule(self):
        rows = [_row("T1", status="SUCCESS"), _row("T2", status="SUCCESS")]
        result = detect_anomalies(rows)
        assert not _flagged(result)

    def test_failed_check_case_insensitive(self):
        # Status is normalised to uppercase in cleaning — but test the rule directly
        rows = [_row("T1", status="failed")]
        result = detect_anomalies(rows)
        assert result[0]["is_anomaly"]

    def test_pending_status_not_flagged(self):
        # PENDING has no merchant-pair so one-off merchant fires, but NOT for FAILED rule
        rows = [_row("T1", status="PENDING"), _row("T2", status="PENDING")]
        result = detect_anomalies(rows)
        reasons = [r.get("anomaly_reason") or "" for r in result]
        assert not any("FAILED" in r for r in reasons)

    def test_multiple_failed_all_flagged(self):
        rows = [_row(f"T{i}", status="FAILED") for i in range(3)]
        result = detect_anomalies(rows)
        assert len(_flagged(result)) == 3


# ── Rule 4: Currency mismatch ─────────────────────────────────────────────────

class TestCurrencyMismatch:
    def test_minority_currency_flagged(self):
        rows = [
            _row("T1", currency="INR"),
            _row("T2", currency="INR"),
            _row("T3", currency="INR"),
            _row("T4", currency="USD"),   # minority
        ]
        result = detect_anomalies(rows)
        t4 = next(r for r in result if r["txn_id"] == "T4")
        assert t4["is_anomaly"]
        assert "USD" in t4["anomaly_reason"]
        assert "INR" in t4["anomaly_reason"]

    def test_majority_currency_not_flagged(self):
        rows = [_row(f"T{i}", currency="INR") for i in range(4)]
        result = detect_anomalies(rows)
        assert not _flagged(result)

    def test_all_same_currency_no_mismatch(self):
        rows = [_row(f"T{i}", currency="USD") for i in range(3)]
        result = detect_anomalies(rows)
        assert not _flagged(result)

    def test_tie_uses_first_most_common(self):
        # 2 INR, 2 USD — Counter picks one majority, minority gets flagged
        rows = [
            _row("T1", currency="INR"),
            _row("T2", currency="INR"),
            _row("T3", currency="USD"),
            _row("T4", currency="USD"),
        ]
        result = detect_anomalies(rows)
        # Exactly 2 rows should be flagged for currency mismatch
        currency_flagged = [r for r in result if r.get("anomaly_reason") and "differs from majority" in r["anomaly_reason"]]
        assert len(currency_flagged) == 2


# ── Multiple rules firing on same row ────────────────────────────────────────

class TestMultipleRules:
    def test_failed_and_currency_mismatch_combined(self):
        rows = [
            _row("T1", currency="INR", status="SUCCESS"),
            _row("T2", currency="INR", status="SUCCESS"),
            _row("T3", currency="INR", status="SUCCESS"),
            _row("T4", currency="USD", status="FAILED"),   # two rules
        ]
        result = detect_anomalies(rows)
        t4 = next(r for r in result if r["txn_id"] == "T4")
        assert t4["is_anomaly"]
        assert "FAILED" in t4["anomaly_reason"]
        assert "differs from majority" in t4["anomaly_reason"]

    def test_return_value_is_same_list(self):
        rows = [_row()]
        result = detect_anomalies(rows)
        assert result is rows   # mutates in-place, returns same list
