from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings
from typing import Dict, Any


def _create_engine_from_settings() -> "Engine":
    """
    根据配置创建数据库引擎：
    - 默认使用 SQLite 本地文件（无需 Docker/PostgreSQL）
    - 如设置了 DATABASE_URL（PostgreSQL等），则使用对应配置
    """
    url = settings.DATABASE_URL
    connect_args: Dict[str, Any] = {}

    # SQLite 需要特殊的 connect_args 设置
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    return create_engine(url, connect_args=connect_args)


engine = _create_engine_from_settings()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

