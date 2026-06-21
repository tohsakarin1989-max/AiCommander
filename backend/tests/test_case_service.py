import os
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ENABLE_VECTOR_DB", "false")

from app.database import Base
from app.services.case_service import CaseService


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def test_case_number_generation_increments():
    db = _session()
    occurred_time = datetime(2025, 1, 1, 12, 0, 0)

    case1 = CaseService.create_case(
        db=db,
        case_number=None,
        occurred_time=occurred_time,
        description="first",
    )
    case2 = CaseService.create_case(
        db=db,
        case_number=None,
        occurred_time=occurred_time,
        description="second",
    )

    assert case1.case_number.endswith("-001")
    assert case2.case_number.endswith("-002")
