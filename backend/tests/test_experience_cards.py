from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import case_intelligence, knowledge
from app.database import Base, get_db
from app.models.case import Case, CaseEvidence
from app.services.case_pipeline_service import CasePipelineService


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
    app.include_router(case_intelligence.router, prefix="/api/case-intelligence")
    app.include_router(knowledge.router, prefix="/api/knowledge")

    def override_get_db():
        db_session.info["authorized_area_ids"] = None  # Isolated legacy API fixture only.
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_experience_card_is_persisted_as_reviewable_case_asset():
    db = _session()
    client = _client(db)
    case = Case(
        case_number="EXP-001",
        occurred_time=datetime(2026, 2, 1, 2, 10),
        location="萨中作业区井场",
        latitude=46.61,
        longitude=125.12,
        case_type="涉油盗窃",
        description="夜间在井场便道发现油桶、软管和抽油泵，周边照明不足。",
        source_type="技防预警",
        status="closed",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    db.add(
        CaseEvidence(
            case_id=case.id,
            evidence_type="photo",
            title="现场照片",
            requirement_key="scene_photo",
        )
    )
    db.commit()

    response = client.get(f"/api/case-intelligence/cases/{case.id}/experience-card")

    assert response.status_code == 200
    card = response.json()
    assert card["source_case_id"] == case.id
    assert card["manual_review_status"] == "pending"
    assert card["operation_conditions"]
    assert card["discovery_method"]
    assert card["protection_shortcomings"]
    assert card["evidence_gaps"] is not None
    assert card["reusable_suggestions"] is not None
    assert "事实" in card["boundary"]
    db.refresh(case)
    assert case.features is None

    saved = client.post(f"/api/knowledge/cases/{case.id}/experience-assets")
    assert saved.status_code == 409  # This operation cannot create a missing analysis.
    event = CasePipelineService.enqueue_case_change(db, case)
    db.commit()
    assert event is not None
    assert CasePipelineService.process_event(db, event.id)['status'] == 'completed'
    saved = client.post(f"/api/knowledge/cases/{case.id}/experience-assets")
    assert saved.status_code == 201, saved.text
    assert saved.json()["source_case_id"] == case.id
    assert saved.json()["content"]["frozen_result"]["id"]
    assert saved.json()["status"] == "draft"
    refreshed = db.query(Case).filter(Case.id == case.id).first()
    # New versioned assets do not overwrite the legacy card stored on the case.
    assert refreshed.features is None
    history = client.get("/api/knowledge/assets", params={"case_id": case.id})
    assert history.status_code == 200
    assert any(item["id"] == saved.json()["id"] for item in history.json()["items"])
