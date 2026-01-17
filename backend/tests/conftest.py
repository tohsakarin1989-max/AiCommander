"""
pytest 配置和通用 fixtures
"""
import os
import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# 设置测试环境变量
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing")
os.environ.setdefault("ENABLE_VECTOR_DB", "false")

from app.database import Base
from app.models.case import Case
from app.models.ai_model import AIModel


@pytest.fixture(scope="function")
def db_session() -> Session:
    """
    创建内存数据库会话（每个测试函数独立）
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_case(db_session: Session) -> Case:
    """
    创建示例案件
    """
    case = Case(
        case_number="TEST-20250101-001",
        occurred_time=datetime(2025, 1, 1, 10, 0, 0),
        location="测试地点",
        latitude=39.9042,
        longitude=116.4074,
        case_type="盗窃",
        description="测试案件描述",
        status="pending",
    )
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)
    return case


@pytest.fixture
def sample_cases_with_geo(db_session: Session) -> list[Case]:
    """
    创建多个带地理坐标的案件（用于地理分析测试）
    """
    cases = [
        Case(
            case_number=f"GEO-20250101-{i:03d}",
            occurred_time=datetime(2025, 1, i + 1, 10, 0, 0),
            location=f"地点{i}",
            latitude=39.9 + i * 0.001,  # 小范围聚集
            longitude=116.4 + i * 0.001,
            case_type="盗窃",
            status="pending",
        )
        for i in range(5)
    ]
    # 添加一个远离的案件
    cases.append(
        Case(
            case_number="GEO-20250101-099",
            occurred_time=datetime(2025, 1, 10, 10, 0, 0),
            location="远离地点",
            latitude=40.5,  # 远离其他案件
            longitude=117.0,
            case_type="盗窃",
            status="pending",
        )
    )
    for case in cases:
        db_session.add(case)
    db_session.commit()
    return cases


@pytest.fixture
def sample_ai_model(db_session: Session) -> AIModel:
    """
    创建示例 AI 模型
    """
    model = AIModel(
        name="测试模型",
        provider="openai",
        model_name="gpt-4",
        api_key_encrypted="test-encrypted-key",
        role="analyst",
        is_active=True,
        is_default=False,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model
