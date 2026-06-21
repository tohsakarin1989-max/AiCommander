from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ChainLink(Base):
    __tablename__ = "chain_links"
    __table_args__ = (
        UniqueConstraint("case_id_a", "case_id_b", "link_type", name="uq_chain_links_pair_type"),
        Index("ix_chain_links_case_a", "case_id_a"),
        Index("ix_chain_links_case_b", "case_id_b"),
        Index("ix_chain_links_status", "status"),
        Index("ix_chain_links_type_status", "link_type", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_id_a = Column(Integer, ForeignKey("cases.id"), nullable=False)
    case_id_b = Column(Integer, ForeignKey("cases.id"), nullable=False)
    link_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="inferred")
    confidence = Column(Float, nullable=False, default=0.0)
    distance_km = Column(Float, nullable=False, default=0.0)
    time_diff_days = Column(Integer, nullable=False, default=0)
    reasoning = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    confirmed_by = Column(String(100), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)

    from_case = relationship("Case", foreign_keys=[case_id_a])
    to_case = relationship("Case", foreign_keys=[case_id_b])
