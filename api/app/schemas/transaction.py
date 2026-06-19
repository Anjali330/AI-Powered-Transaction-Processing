from typing import Any

from pydantic import BaseModel, ConfigDict


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    txn_id: str | None
    date: Any
    merchant: str
    amount: Any
    currency: str
    status: str
    category: str | None
    account_id: str
    is_anomaly: bool
    anomaly_reason: str | None
    llm_category: str | None
    llm_subcategory: str | None
    llm_risk_level: str | None
    llm_merchant_type: str | None
    llm_confidence: Any
    llm_failed: bool


class AnomalyOut(BaseModel):
    txn_id: str | None
    reason: str | None
