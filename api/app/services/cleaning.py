"""
services/cleaning.py

Pure data-cleaning pipeline.  No DB, no Celery — only pandas in, dataclass out.
Called by tasks/pipeline.py which handles all DB writes.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Columns the CSV must contain (case-insensitive match after strip)
REQUIRED_COLUMNS = {
    "txn_id", "date", "merchant", "amount",
    "currency", "status", "category", "account_id", "notes",
}

# Strips everything except digits, dot, comma, and leading minus.
# The \u0000-\u002F range covers $, and the broad unicode range covers ₹, €, £ etc.
_AMOUNT_STRIP = re.compile(r"[^\d.,-]")


@dataclass
class CleaningResult:
    original_row_count: int = 0
    cleaned_row_count: int = 0
    duplicates_removed: int = 0
    invalid_rows: int = 0
    # Each element is a dict ready for bulk-inserting into Transaction
    rows: list[dict] = field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────────────

def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case and strip column names so uploads with varied casing work."""
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def _clean_amount(raw) -> Decimal | None:
    """
    Convert anything like '$1,234.56', '1.234,56', '1500', '-200.5' to Decimal.
    Returns None for blanks / unparseable values.
    """
    if pd.isna(raw):
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = _AMOUNT_STRIP.sub("", s)
    # Handle European comma-as-decimal: '1.234,56' → '1234.56'
    if s.count(",") == 1 and s.count(".") >= 1:
        # e.g. 1.234,56 — period is thousands separator
        s = s.replace(".", "").replace(",", ".")
    else:
        # Remove thousands-separator commas: '1,234.56' → '1234.56'
        s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _clean_date(raw) -> str | None:
    """
    Parse any recognisable date string and return ISO 8601 YYYY-MM-DD.
    Returns None for unparseable values.
    """
    if pd.isna(raw):
        return None
    s = str(raw).strip()
    # Try common explicit formats first to avoid pandas ambiguity warnings
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # Fall back to pandas inference for less common formats
    try:
        return pd.to_datetime(s, infer_datetime_format=True, errors="raise").strftime("%Y-%m-%d")
    except Exception:
        return None


def _clean_str(raw, *, upper: bool = False) -> str | None:
    """Trim whitespace; optionally uppercase; return None for blank/NaN."""
    if pd.isna(raw):
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s.upper() if upper else s


def _standardise_merchant(name: str | None) -> str | None:
    """Title-case and collapse internal whitespace."""
    if not name:
        return None
    return " ".join(name.title().split())


# ── public entry point ────────────────────────────────────────────────────────

def clean_csv(file_path: str | Path, job_id: uuid.UUID) -> CleaningResult:
    """
    Load, clean, and validate a CSV file.

    Returns a CleaningResult with .rows ready for bulk DB insert and
    .original_row_count / .cleaned_row_count / .duplicates_removed / .invalid_rows
    populated.

    Raises ValueError if the file is missing required columns.
    """
    result = CleaningResult()

    df = pd.read_csv(file_path, dtype=str, keep_default_na=False, na_values=["", "NA", "N/A", "null", "NULL", "none", "None"])
    df = _normalise_columns(df)

    # ── validate required columns ────────────────────────────────────────────
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    result.original_row_count = len(df)

    # ── 1. trim all string columns ───────────────────────────────────────────
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    # ── 2. remove duplicate rows (all columns considered) ───────────────────
    before_dedup = len(df)
    df = df.drop_duplicates()
    result.duplicates_removed = before_dedup - len(df)

    # ── 3. parse & validate each row ────────────────────────────────────────
    rows: list[dict] = []
    invalid = 0

    for _, row in df.iterrows():
        # Amount — required, must be parseable
        amount = _clean_amount(row.get("amount"))
        if amount is None:
            logger.warning("job_id=%s dropping row with invalid amount: %s", job_id, row.get("amount"))
            invalid += 1
            continue

        # Date — required, must be parseable
        date_str = _clean_date(row.get("date"))
        if date_str is None:
            logger.warning("job_id=%s dropping row with invalid date: %s", job_id, row.get("date"))
            invalid += 1
            continue

        # Currency — required, normalise to 3-char uppercase
        currency = _clean_str(row.get("currency"), upper=True)
        if not currency:
            logger.warning("job_id=%s dropping row with missing currency", job_id)
            invalid += 1
            continue
        currency = currency[:3]

        # Merchant — required
        merchant = _standardise_merchant(_clean_str(row.get("merchant")))
        if not merchant:
            logger.warning("job_id=%s dropping row with missing merchant", job_id)
            invalid += 1
            continue

        # Account ID — required
        account_id = _clean_str(row.get("account_id"))
        if not account_id:
            logger.warning("job_id=%s dropping row with missing account_id", job_id)
            invalid += 1
            continue

        # Status — normalise to uppercase
        txn_status = _clean_str(row.get("status"), upper=True) or "UNKNOWN"

        rows.append({
            "id": uuid.uuid4(),
            "job_id": job_id,
            "txn_id": _clean_str(row.get("txn_id")),
            "date": date_str,
            "merchant": merchant,
            "amount": amount,
            "currency": currency,
            "status": txn_status,
            "category": _clean_str(row.get("category")),
            "account_id": account_id,
            "notes": _clean_str(row.get("notes")),
            "is_anomaly": False,
            "anomaly_reason": None,
            "llm_category": None,
            "llm_raw_response": None,
            "llm_failed": False,
        })

    result.invalid_rows = invalid
    result.cleaned_row_count = len(rows)
    result.rows = rows
    return result
