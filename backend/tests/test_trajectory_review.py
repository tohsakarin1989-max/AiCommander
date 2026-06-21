from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import cases
from app.database import Base, get_db
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return session_local()


def _client(db_session: Session) -> TestClient:
    app = FastAPI()
    app.include_router(cases.router, prefix="/api/cases")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _add_case(db: Session, number: str, index: int) -> Case:
    case = Case(
        case_number=number,
        occurred_time=datetime(2026, 1, 2, 1, 30) + timedelta(hours=index * 3),
        location=f"萨中北线{index}号点",
        case_type="涉油盗窃",
        description="夜间靠近井场便道，发现油桶和软管。",
        latitude=46.60 + index * 0.01,
        longitude=125.10 + index * 0.012,
        status="closed",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _seed(db: Session) -> list[Case]:
    cases_ = [_add_case(db, f"TRJ-{idx}", idx) for idx in range(1, 4)]
    db.add(
        JurisdictionAsset(
            name="萨中北线井点",
            asset_type="well",
            geometry_type="point",
            latitude=46.615,
            longitude=125.115,
            status="active",
            source="test",
            verified=True,
        )
    )
    db.add(
        JurisdictionAsset(
            name="北线监控盲区",
            asset_type="camera",
            geometry_type="point",
            latitude=46.66,
            longitude=125.18,
            status="inactive",
            source="test",
            verified=True,
        )
    )
    db.commit()
    return cases_


def test_trajectory_review_returns_six_section_retrospective_not_prediction():
    db = _session()
    client = _client(db)
    case_ids = ",".join(str(case.id) for case in _seed(db))

    response = client.get(f"/api/cases/trajectory/{case_ids}/review")

    assert response.status_code == 200
    payload = response.json()
    assert set(
        [
            "facts",
            "path_conditions",
            "inferences",
            "information_gaps",
            "reusable_suggestions",
            "boundary",
        ]
    ).issubset(payload.keys())
    assert payload["facts"]
    assert payload["path_conditions"]
    assert "prediction" not in payload
    assert "不做犯罪预测" in payload["boundary"]
    assert not any("下一个可能位置" in str(value) for value in payload.values())


def test_legacy_predict_route_is_deprecated_review_compatibility_entry():
    db = _session()
    client = _client(db)
    case_ids = ",".join(str(case.id) for case in _seed(db))

    response = client.get(f"/api/cases/trajectory/{case_ids}/predict")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deprecated"] is True
    assert payload["method"] == "path_condition_review"
    assert "prediction" not in payload
    assert "不做犯罪预测" in payload["boundary"]
