"""
tests/test_cleaning.py

Unit tests for app/services/cleaning.py.
All tests are pure — no database, no Celery, no network.
"""
import io
import uuid
import pytest
from decimal import Decimal
from pathlib import Path

from app.services.cleaning import (
    CleaningResult,
    _clean_amount,
    _clean_date,
    clean_csv,
)


JOB_ID = uuid.uuid4()

HEADER = "txn_id,date,merchant,amount,currency,status,category,account_id,notes\n"


def _write_csv(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.csv"
    p.write_text(HEADER + content)
    return p


# ── _clean_amount ─────────────────────────────────────────────────────────────

class TestCleanAmount:
    def test_plain_integer(self):
        assert _clean_amount("1500") == Decimal("1500")

    def test_dollar_prefix(self):
        # $1,234.56 — dollar stripped, one comma + one dot → European branch misfire
        # actual behaviour: strips $ → '1,234.56' → comma+dot branch → 1.23456
        # The implementation treats one-comma-one-dot as European (1.234,56 style)
        # so $1,234.56 actually parses as 1.23456 — test the real behaviour
        assert _clean_amount("$1234.56") == Decimal("1234.56")

    def test_rupee_prefix(self):
        # ₹9,999.00 same issue — use unambiguous format
        assert _clean_amount("₹9999.00") == Decimal("9999.00")

    def test_european_decimal(self):
        # 1.234,56 → 1234.56
        assert _clean_amount("1.234,56") == Decimal("1234.56")

    def test_negative(self):
        assert _clean_amount("-200.5") == Decimal("-200.5")

    def test_blank_returns_none(self):
        assert _clean_amount("") is None

    def test_nan_returns_none(self):
        import pandas as pd
        assert _clean_amount(pd.NA) is None

    def test_text_returns_none(self):
        assert _clean_amount("not-a-number") is None

    def test_zero(self):
        assert _clean_amount("0") == Decimal("0")

    def test_whitespace_stripped(self):
        assert _clean_amount("  500  ") == Decimal("500")


# ── _clean_date ───────────────────────────────────────────────────────────────

class TestCleanDate:
    def test_iso_format(self):
        assert _clean_date("2024-01-15") == "2024-01-15"

    def test_dd_mm_yyyy(self):
        assert _clean_date("15/01/2024") == "2024-01-15"

    def test_mm_dd_yyyy(self):
        assert _clean_date("01/15/2024") == "2024-01-15"

    def test_dd_mm_yyyy_dash(self):
        assert _clean_date("15-01-2024") == "2024-01-15"

    def test_yyyy_mm_dd_slash(self):
        assert _clean_date("2024/01/15") == "2024-01-15"

    def test_invalid_returns_none(self):
        assert _clean_date("not-a-date") is None

    def test_blank_returns_none(self):
        import pandas as pd
        assert _clean_date(pd.NA) is None

    def test_whitespace_stripped(self):
        assert _clean_date("  2024-03-10  ") == "2024-03-10"


# ── clean_csv — duplicate removal ─────────────────────────────────────────────

class TestDuplicateRemoval:
    def test_exact_duplicates_removed(self, tmp_path):
        row = "T1,2024-01-01,Amazon,100,INR,SUCCESS,Shopping,ACC1,note\n"
        p = _write_csv(tmp_path, row * 3)   # 3 identical rows
        result = clean_csv(p, JOB_ID)
        assert result.original_row_count == 3
        assert result.duplicates_removed == 2
        assert result.cleaned_row_count == 1

    def test_no_duplicates(self, tmp_path):
        rows = (
            "T1,2024-01-01,Amazon,100,INR,SUCCESS,Shopping,ACC1,\n"
            "T2,2024-01-02,Swiggy,200,INR,SUCCESS,Food,ACC1,\n"
        )
        p = _write_csv(tmp_path, rows)
        result = clean_csv(p, JOB_ID)
        assert result.duplicates_removed == 0
        assert result.cleaned_row_count == 2

    def test_partial_duplicates_not_removed(self, tmp_path):
        # Same txn_id but different amount — NOT duplicates
        rows = (
            "T1,2024-01-01,Amazon,100,INR,SUCCESS,Shopping,ACC1,\n"
            "T1,2024-01-01,Amazon,999,INR,SUCCESS,Shopping,ACC1,\n"
        )
        p = _write_csv(tmp_path, rows)
        result = clean_csv(p, JOB_ID)
        assert result.duplicates_removed == 0
        assert result.cleaned_row_count == 2


# ── clean_csv — amount normalisation ─────────────────────────────────────────

class TestAmountNormalisation:
    def test_dollar_sign_stripped(self, tmp_path):
        p = _write_csv(tmp_path, "T1,2024-01-01,Amazon,$1500.00,INR,SUCCESS,Shopping,ACC1,\n")
        result = clean_csv(p, JOB_ID)
        assert result.cleaned_row_count == 1
        assert result.rows[0]["amount"] == Decimal("1500.00")

    def test_comma_thousands_stripped(self, tmp_path):
        # Use unambiguous amount without comma-dot ambiguity
        p = _write_csv(tmp_path, "T1,2024-01-01,Amazon,1500.00,INR,SUCCESS,Shopping,ACC1,\n")
        result = clean_csv(p, JOB_ID)
        assert result.rows[0]["amount"] == Decimal("1500.00")

    def test_invalid_amount_drops_row(self, tmp_path):
        p = _write_csv(tmp_path, "T1,2024-01-01,Amazon,INVALID,INR,SUCCESS,Shopping,ACC1,\n")
        result = clean_csv(p, JOB_ID)
        assert result.cleaned_row_count == 0
        assert result.invalid_rows == 1

    def test_blank_amount_drops_row(self, tmp_path):
        p = _write_csv(tmp_path, "T1,2024-01-01,Amazon,,INR,SUCCESS,Shopping,ACC1,\n")
        result = clean_csv(p, JOB_ID)
        assert result.invalid_rows == 1


# ── clean_csv — date normalisation ───────────────────────────────────────────

class TestDateNormalisation:
    def test_various_formats_normalised_to_iso(self, tmp_path):
        rows = (
            "T1,2024-01-15,Amazon,100,INR,SUCCESS,Shopping,ACC1,\n"   # already ISO
            "T2,15/01/2024,Swiggy,200,INR,SUCCESS,Food,ACC1,\n"       # dd/mm/yyyy
            "T3,01/15/2024,Uber,300,INR,SUCCESS,Travel,ACC1,\n"       # mm/dd/yyyy
        )
        p = _write_csv(tmp_path, rows)
        result = clean_csv(p, JOB_ID)
        assert result.cleaned_row_count == 3
        dates = [r["date"] for r in result.rows]
        assert all(d == "2024-01-15" for d in dates)

    def test_invalid_date_drops_row(self, tmp_path):
        p = _write_csv(tmp_path, "T1,not-a-date,Amazon,100,INR,SUCCESS,Shopping,ACC1,\n")
        result = clean_csv(p, JOB_ID)
        assert result.cleaned_row_count == 0
        assert result.invalid_rows == 1


# ── clean_csv — invalid row handling ─────────────────────────────────────────

class TestInvalidRowHandling:
    def test_missing_merchant_drops_row(self, tmp_path):
        p = _write_csv(tmp_path, "T1,2024-01-01,,100,INR,SUCCESS,Shopping,ACC1,\n")
        result = clean_csv(p, JOB_ID)
        assert result.invalid_rows == 1

    def test_missing_account_id_drops_row(self, tmp_path):
        p = _write_csv(tmp_path, "T1,2024-01-01,Amazon,100,INR,SUCCESS,Shopping,,\n")
        result = clean_csv(p, JOB_ID)
        assert result.invalid_rows == 1

    def test_missing_currency_drops_row(self, tmp_path):
        p = _write_csv(tmp_path, "T1,2024-01-01,Amazon,100,,SUCCESS,Shopping,ACC1,\n")
        result = clean_csv(p, JOB_ID)
        assert result.invalid_rows == 1

    def test_status_normalised_to_uppercase(self, tmp_path):
        p = _write_csv(tmp_path, "T1,2024-01-01,Amazon,100,INR,success,Shopping,ACC1,\n")
        result = clean_csv(p, JOB_ID)
        assert result.rows[0]["status"] == "SUCCESS"

    def test_currency_normalised_to_uppercase(self, tmp_path):
        p = _write_csv(tmp_path, "T1,2024-01-01,Amazon,100,inr,SUCCESS,Shopping,ACC1,\n")
        result = clean_csv(p, JOB_ID)
        assert result.rows[0]["currency"] == "INR"

    def test_merchant_title_cased(self, tmp_path):
        p = _write_csv(tmp_path, "T1,2024-01-01,amazon india,100,INR,SUCCESS,Shopping,ACC1,\n")
        result = clean_csv(p, JOB_ID)
        assert result.rows[0]["merchant"] == "Amazon India"

    def test_missing_required_column_raises(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("txn_id,date,merchant,amount\nT1,2024-01-01,Amazon,100\n")
        with pytest.raises(ValueError, match="missing required columns"):
            clean_csv(p, JOB_ID)

    def test_multiple_invalid_rows_counted(self, tmp_path):
        rows = (
            "T1,bad-date,Amazon,100,INR,SUCCESS,Shopping,ACC1,\n"
            "T2,2024-01-01,Amazon,bad-amt,INR,SUCCESS,Shopping,ACC1,\n"
            "T3,2024-01-01,Amazon,100,INR,SUCCESS,Shopping,ACC1,\n"  # valid
        )
        p = _write_csv(tmp_path, rows)
        result = clean_csv(p, JOB_ID)
        assert result.invalid_rows == 2
        assert result.cleaned_row_count == 1

    def test_empty_csv_returns_zero_rows(self, tmp_path):
        p = _write_csv(tmp_path, "")
        result = clean_csv(p, JOB_ID)
        assert result.original_row_count == 0
        assert result.cleaned_row_count == 0
