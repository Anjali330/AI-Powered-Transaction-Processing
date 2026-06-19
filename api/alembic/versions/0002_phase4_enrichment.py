"""add phase4 enrichment columns

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── transactions: new enrichment columns ─────────────────────────────────
    op.add_column("transactions", sa.Column("llm_subcategory", sa.Text, nullable=True))
    op.add_column("transactions", sa.Column("llm_risk_level", sa.Text, nullable=True))
    op.add_column("transactions", sa.Column("llm_merchant_type", sa.Text, nullable=True))
    op.add_column("transactions", sa.Column("llm_confidence", sa.Numeric(4, 3), nullable=True))

    # ── job_summaries: category breakdown + ai narrative ─────────────────────
    op.add_column("job_summaries", sa.Column("category_breakdown", postgresql.JSONB, nullable=True))
    op.add_column("job_summaries", sa.Column("ai_summary", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("job_summaries", "ai_summary")
    op.drop_column("job_summaries", "category_breakdown")
    op.drop_column("transactions", "llm_confidence")
    op.drop_column("transactions", "llm_merchant_type")
    op.drop_column("transactions", "llm_risk_level")
    op.drop_column("transactions", "llm_subcategory")
