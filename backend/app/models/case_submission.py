"""Private request receipts, committed atomically with a created case."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class CaseSubmissionReceipt(Base):
    __tablename__ = "case_submission_receipts"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_case_submission_user_key"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    request_sha256 = Column(String(64), nullable=False)
    # A deleted case does not free its key for accidentally recreating the case.
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
