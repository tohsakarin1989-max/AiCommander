from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import cases
from app.database import Base, get_db
from app.models.case import Case, CaseVehicle
from app.models.preprocess_job import PreprocessJob


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


def _seed(db: Session) -> list[Case]:
    complete = Case(
        case_number="BATCH-001",
        occurred_time=datetime(2026, 3, 1, 1, 20),
        location="萨中作业区",
        latitude=46.6,
        longitude=125.1,
        case_type="涉油盗窃",
        description="夜间井场便道发现涉案车辆和油桶。",
        oil_type="原油",
        oil_volume=1.0,
        oil_nature="被盗原油",
        oil_handling="检斤入库",
        vehicle_handling="扣押停放",
        status="pending",
    )
    missing_geo = Case(
        case_number="BATCH-002",
        occurred_time=datetime(2026, 3, 2, 3, 40),
        location="未知地点",
        case_type="涉油盗窃",
        description="线索描述较少，缺少坐标。",
        status="pending",
    )
    db.add_all([complete, missing_geo])
    db.commit()
    db.refresh(complete)
    db.refresh(missing_geo)
    db.add(
        CaseVehicle(
            case_id=complete.id,
            vehicle_type="皮卡",
            plate_number="黑A00002",
            handling_status="扣押停放",
        )
    )
    db.commit()
    return [complete, missing_geo]


def test_batch_review_runs_with_deterministic_fallback_and_exposes_progress():
    db = _session()
    client = _client(db)
    _seed(db)

    created = client.post(
        "/api/cases/batch-review",
        json={"limit": 10, "use_llm": False},
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["job_id"]
    assert payload["status"] == "completed"
    assert payload["progress"] == 100
    assert payload["processed"] == 2
    assert payload["failed"] == 0
    assert payload["issues"]
    assert any(issue["type"] in {"data_quality", "experience", "bonus"} for issue in payload["issues"])
    routed_issues = [issue for issue in payload["issues"] if issue.get("case_id")]
    assert routed_issues
    assert routed_issues[0]["target_type"] == "case"
    assert routed_issues[0]["target_id"] == routed_issues[0]["case_id"]
    assert payload["preprocess"]["success"] == 2

    fetched = client.get(f"/api/cases/batch-review/{payload['job_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["job_id"] == payload["job_id"]


def test_batch_review_allows_empty_body_and_rejects_non_positive_limit():
    db = _session()
    client = _client(db)
    _seed(db)

    created = client.post("/api/cases/batch-review")
    assert created.status_code == 200
    assert created.json()["processed"] == 2

    empty_selection = client.post("/api/cases/batch-review", json={"case_ids": []})
    assert empty_selection.status_code == 200
    assert empty_selection.json()["processed"] == 0
    assert empty_selection.json()["skipped"] == 0

    rejected = client.post("/api/cases/batch-review", json={"limit": 0})
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "limit 必须大于 0"

    too_large = client.post("/api/cases/batch-review", json={"limit": 201})
    assert too_large.status_code == 400
    assert too_large.json()["detail"] == "limit 不能超过 200"


def test_batch_review_only_missing_preprocess_does_not_skip_review_chain():
    db = _session()
    client = _client(db)
    seeded = _seed(db)
    seeded[0].features = {"existing": True}
    db.commit()

    reviewed = client.post(
        "/api/cases/batch-review",
        json={
            "case_ids": [case.id for case in seeded],
            "only_missing": True,
            "use_llm": False,
        },
    )

    assert reviewed.status_code == 200
    payload = reviewed.json()
    assert payload["processed"] == 2
    assert payload["preprocess"]["success"] == 1
    assert payload["preprocess"]["skipped"] == 1
    assert db.query(PreprocessJob).count() == 1


def test_batch_review_does_not_reopen_confirmed_experience_card():
    db = _session()
    client = _client(db)
    seeded = _seed(db)
    confirmed = seeded[0]
    confirmed.features = {
        "intelligence": {
            "experience_card": {
                "manual_review_status": "confirmed",
            },
        },
    }
    db.commit()

    reviewed = client.post(
        "/api/cases/batch-review",
        json={"case_ids": [confirmed.id], "only_missing": True, "use_llm": False},
    )

    assert reviewed.status_code == 200
    issues = reviewed.json()["issues"]
    assert not [
        issue
        for issue in issues
        if issue["type"] == "experience" and issue.get("case_id") == confirmed.id
    ]
