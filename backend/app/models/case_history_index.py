"""可重建的历史检索派生索引，不持有业务事实或授权副本。"""
from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.sql import func

from app.database import Base


class CaseHistoryIndex(Base):
    __tablename__ = "case_history_indexes"

    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True)
    source_type = Column(String(40), primary_key=True)
    source_id = Column(String(64), primary_key=True)
    source_hash = Column(String(64), nullable=False)
    rule_version = Column(String(80), nullable=False)
    payload = Column(JSON, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CaseHistoryIndexCursor(Base):
    """后台全库轮询断点，与本批索引更新同事务提交。"""
    __tablename__ = "case_history_index_cursors"

    name = Column(String(40), primary_key=True)
    after_case_id = Column(Integer, nullable=False, default=0)
    completed_passes = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CaseHistoryEmbedding(Base):
    """同一检索索引的可重建向量侧表；PostgreSQL 原生 vector，SQLite 仅测试回退。"""
    __tablename__ = "case_history_embeddings"
    __table_args__ = (ForeignKeyConstraint(
        ['case_id', 'source_type', 'source_id'],
        ['case_history_indexes.case_id', 'case_history_indexes.source_type', 'case_history_indexes.source_id'],
        ondelete='CASCADE'),)

    case_id = Column(Integer, primary_key=True)
    source_type = Column(String(40), primary_key=True)
    source_id = Column(String(64), primary_key=True)
    model_version = Column(String(100), primary_key=True)
    source_hash = Column(String(64), nullable=False)
    dimension = Column(Integer, nullable=False)
    embedding = Column(VECTOR().with_variant(JSON(), 'sqlite'), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
