from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'analyst', 'viewer')", name="ck_users_role"),
    )

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    password_hash = Column(String(512), nullable=False)
    role = Column(String(20), nullable=False, default="viewer")
    is_active = Column(Boolean, nullable=False, default=True)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=False))
    session_version = Column(Integer, nullable=False, default=1)
    last_login_at = Column(DateTime(timezone=False))
    password_changed_at = Column(DateTime(timezone=False), nullable=False, default=func.now())
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=False), onupdate=func.now())


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=False), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=False))
    last_seen_at = Column(DateTime(timezone=False), nullable=False)
    client_ip = Column(String(64))
    user_agent = Column(String(512))
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    username = Column(String(64))
    action = Column(String(120), nullable=False, index=True)
    method = Column(String(10))
    path = Column(String(500))
    status_code = Column(Integer)
    client_ip = Column(String(64))
    request_id = Column(String(100), index=True)
    detail = Column(JSON)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=func.now(), index=True)
