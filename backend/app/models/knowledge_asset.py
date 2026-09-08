"""可复核的案件知识资产与历史经验复用轨迹。"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class KnowledgeAsset(Base):
    __tablename__ = "knowledge_assets"
    __table_args__ = (
        UniqueConstraint(
            "asset_type",
            "source_case_id",
            "version",
            name="uq_knowledge_asset_case_version",
        ),
        Index("ix_knowledge_assets_case_type", "source_case_id", "asset_type"),
        Index("ix_knowledge_assets_type_status", "asset_type", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    asset_type = Column(String(30), nullable=False)
    source_case_id = Column(
        Integer,
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(JSON, nullable=False, default=dict)
    evidence_refs = Column(JSON, nullable=False, default=list)
    source_signature = Column(String(64), nullable=False)
    source_data_version = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="draft")
    generated_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewer_label = Column(String(100), nullable=True)
    review_note = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    source_case = relationship("Case")
    reuse_records = relationship(
        "KnowledgeReuseRecord",
        foreign_keys="KnowledgeReuseRecord.source_asset_id",
        back_populates="source_asset",
        cascade="all, delete-orphan",
    )


class KnowledgeReuseRecord(Base):
    __tablename__ = "knowledge_reuse_records"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_knowledge_reuse_idempotency"),
        Index("ix_knowledge_reuse_target_created", "target_case_id", "created_at"),
        Index("ix_knowledge_reuse_source_created", "source_asset_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    source_asset_id = Column(
        Integer,
        ForeignKey("knowledge_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_case_id = Column(
        Integer,
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_asset_id = Column(
        Integer,
        ForeignKey("knowledge_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision = Column(String(20), nullable=False)
    purpose = Column(String(200), nullable=False)
    applicability = Column(JSON, nullable=False, default=dict)
    note = Column(Text, nullable=True)
    idempotency_key = Column(String(64), nullable=False)
    created_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    source_asset = relationship(
        "KnowledgeAsset",
        foreign_keys=[source_asset_id],
        back_populates="reuse_records",
    )
    target_asset = relationship("KnowledgeAsset", foreign_keys=[target_asset_id])
    target_case = relationship("Case")
