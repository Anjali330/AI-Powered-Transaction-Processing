import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobSummary(Base):
    __tablename__ = "job_summaries"
    __table_args__ = (UniqueConstraint("job_id", name="uq_job_summaries_job_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    total_spend_inr: Mapped[str | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_spend_usd: Mapped[str | None] = mapped_column(Numeric(14, 2), nullable=True)
    top_merchants: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    anomaly_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    job: Mapped["Job"] = relationship("Job", back_populates="summary")  # noqa: F821
