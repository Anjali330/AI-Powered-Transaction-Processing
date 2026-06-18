"""initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: create the enum type explicitly via raw DDL (transactional in PG)
    op.execute("CREATE TYPE job_status AS ENUM ('pending', 'processing', 'completed', 'failed')")

    # Step 2: create tables using sa.Text for the status column to avoid
    # SQLAlchemy 2.x _on_table_create firing a second CREATE TYPE automatically
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("row_count_raw", sa.Integer, nullable=True),
        sa.Column("row_count_clean", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Step 3: alter the status column to the native enum type
    # DROP DEFAULT first — PG cannot auto-cast a text default when changing type
    op.execute("ALTER TABLE jobs ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE jobs ALTER COLUMN status TYPE job_status USING status::job_status")
    op.execute("ALTER TABLE jobs ALTER COLUMN status SET DEFAULT 'pending'::job_status")

    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])

    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("txn_id", sa.Text, nullable=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("merchant", sa.Text, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("account_id", sa.Text, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_anomaly", sa.Boolean, server_default="false", nullable=False),
        sa.Column("anomaly_reason", sa.Text, nullable=True),
        sa.Column("llm_category", sa.Text, nullable=True),
        sa.Column("llm_raw_response", postgresql.JSONB, nullable=True),
        sa.Column("llm_failed", sa.Boolean, server_default="false", nullable=False),
    )
    op.create_index("ix_transactions_job_id", "transactions", ["job_id"])
    op.create_index("ix_transactions_job_account", "transactions", ["job_id", "account_id"])

    op.create_table(
        "job_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_spend_inr", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_spend_usd", sa.Numeric(14, 2), nullable=True),
        sa.Column("top_merchants", postgresql.JSONB, nullable=True),
        sa.Column("anomaly_count", sa.Integer, nullable=True),
        sa.Column("narrative", sa.Text, nullable=True),
        sa.Column("risk_level", sa.Text, nullable=True),
        sa.Column("llm_raw_response", postgresql.JSONB, nullable=True),
        sa.UniqueConstraint("job_id", name="uq_job_summaries_job_id"),
    )


def downgrade() -> None:
    op.drop_table("job_summaries")
    op.drop_index("ix_transactions_job_account", table_name="transactions")
    op.drop_index("ix_transactions_job_id", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")
    op.execute("DROP TYPE job_status")
