from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.config import settings
from app.database import Base
from app.database import get_db
from app.api import case_pipeline
from app.api.cases import (
    AiIntakeApplyRequest,
    AiIntakeField,
    CaseEvidenceCreate,
    apply_ai_intake_preview,
    create_case_evidence,
)
from app.models.case import CaseVehicle
from app.models.case_pipeline import CaseAnalysisProfile, CasePipelineState, OutboxEvent
from app.services.case_pipeline_service import CasePipelineService
from app.services.outbox_claim_service import OutboxClaimLostError, OutboxClaimService
from app.services.case_service import CaseService


@pytest.fixture
def db_session(monkeypatch) -> Session:
    monkeypatch.setattr(settings, "ENABLE_VECTOR_DB", False)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = local()
    try:
        yield session
    finally:
        session.close()


def _create_case(db: Session):
    return CaseService.create_case(
        db=db,
        case_number="PIPE-001",
        occurred_time=datetime(2026, 9, 8, 1, 30),
        location="南区 12 号井附近",
        latitude=46.601,
        longitude=125.101,
        case_type="涉油盗窃",
        description="夜间发现井场原油被盗，现场留有车辆轮胎痕迹。",
        oil_type="原油",
        facility_type="井口",
        modus_operandi="车辆转运",
    )


def test_case_create_commits_outbox_without_waiting_for_pipeline(db_session: Session):
    case = _create_case(db_session)

    event = db_session.query(OutboxEvent).one()
    assert event.aggregate_id == str(case.id)
    assert event.event_type == "case.analysis.requested"
    assert event.status == "pending"
    assert db_session.query(CaseAnalysisProfile).count() == 0


@pytest.mark.parametrize("status", ["pending", "processing", "degraded"])
@pytest.mark.parametrize("version_field", ["schema_version", "dictionary_version"])
def test_rule_upgrade_does_not_discard_request_for_unchanged_case(
    db_session: Session, status: str, version_field: str,
):
    case = _create_case(db_session)
    original_description = case.description
    state = db_session.query(CasePipelineState).one()
    old_event = db_session.query(OutboxEvent).one()
    state.status = status
    setattr(state, version_field, "previous-version")
    old_event.payload = {**old_event.payload, version_field: "previous-version"}
    db_session.commit()

    new_event = CasePipelineService.enqueue_case_change(db_session, case)
    assert new_event is not None
    assert new_event.id != old_event.id
    db_session.commit()
    assert CasePipelineService.enqueue_case_change(db_session, case) is None
    assert CasePipelineService.process_event(db_session, old_event.id)["status"] == "superseded"
    assert CasePipelineService.process_event(db_session, new_event.id)["status"] == "completed"
    profile = db_session.query(CaseAnalysisProfile).one()
    assert getattr(profile, version_field) == new_event.payload[version_field]
    assert case.description == original_description


def test_expired_processing_lease_is_recovered(db_session: Session):
    _create_case(db_session)
    event = db_session.query(OutboxEvent).one()
    event.status = "processing"
    event.attempts = 1
    event.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    event.worker_id = "stopped-worker"
    db_session.commit()

    result = CasePipelineService.process_pending(db_session)

    db_session.refresh(event)
    assert result["completed"] == 1
    assert event.status == "completed"
    assert event.attempts == 2
    assert event.lease_until is None
    assert event.worker_id is None


def test_pipeline_generates_versioned_profile_without_overwriting_case(db_session: Session):
    case = _create_case(db_session)
    original = {
        "location": case.location,
        "description": case.description,
        "features": case.features,
        "latitude": case.latitude,
        "longitude": case.longitude,
    }
    event = db_session.query(OutboxEvent).one()

    result = CasePipelineService.process_event(db_session, event.id)

    assert result["status"] == "completed"
    profile = db_session.query(CaseAnalysisProfile).one()
    assert profile.case_id == case.id
    assert profile.is_current is True
    assert profile.payload["spatial_grid"] == "46.60:125.10"
    assert len(profile.payload["critical_gaps"]) <= 3
    state = db_session.query(CasePipelineState).one()
    assert state.status == "completed"
    db_session.refresh(case)
    assert {
        "location": case.location,
        "description": case.description,
        "features": case.features,
        "latitude": case.latitude,
        "longitude": case.longitude,
    } == original


def test_unchanged_case_and_rules_do_not_enqueue_or_duplicate_profile(db_session: Session):
    case = _create_case(db_session)
    first_event = db_session.query(OutboxEvent).one()
    CasePipelineService.process_event(db_session, first_event.id)

    duplicate = CasePipelineService.enqueue_case_change(db_session, case, changed_fields={"location"})
    db_session.commit()

    assert duplicate is None
    assert db_session.query(OutboxEvent).count() == 1
    assert db_session.query(CaseAnalysisProfile).count() == 1


def test_only_analysis_relevant_changes_trigger_new_profile(db_session: Session):
    case = _create_case(db_session)
    CasePipelineService.process_event(db_session, db_session.query(OutboxEvent).one().id)

    CaseService.update_case(db_session, case.id, security_level="待评估")
    assert db_session.query(OutboxEvent).count() == 1

    CaseService.update_case(db_session, case.id, location="南区 13 号井附近")

    assert db_session.query(OutboxEvent).count() == 2
    pending = db_session.query(OutboxEvent).filter(OutboxEvent.status == "pending").one()
    CasePipelineService.process_event(db_session, pending.id)
    profiles = db_session.query(CaseAnalysisProfile).order_by(CaseAnalysisProfile.created_at).all()
    assert len(profiles) == 2
    assert [item.is_current for item in profiles] == [False, True]


def test_reverting_to_a_historical_source_hash_reactivates_only_that_profile(db_session: Session):
    case = _create_case(db_session)
    original_location = case.location
    CasePipelineService.process_event(db_session, db_session.query(OutboxEvent).one().id)

    CaseService.update_case(db_session, case.id, location="南区 13 号井附近")
    changed = db_session.query(OutboxEvent).filter(OutboxEvent.status == "pending").one()
    CasePipelineService.process_event(db_session, changed.id)

    CaseService.update_case(db_session, case.id, location=original_location)
    reverted = db_session.query(OutboxEvent).filter(OutboxEvent.status == "pending").one()
    CasePipelineService.process_event(db_session, reverted.id)

    profiles = db_session.query(CaseAnalysisProfile).order_by(CaseAnalysisProfile.profile_version).all()
    assert len(profiles) == 2
    assert [item.is_current for item in profiles] == [True, False]
    assert db_session.query(CaseAnalysisProfile).filter(CaseAnalysisProfile.is_current.is_(True)).count() == 1


def test_confirmed_intake_and_evidence_changes_enqueue_fresh_analysis(db_session: Session):
    case = _create_case(db_session)
    CasePipelineService.process_event(db_session, db_session.query(OutboxEvent).one().id)

    apply_ai_intake_preview(
        case.id,
        AiIntakeApplyRequest(
            confirmed_fields=[AiIntakeField(field="oil_type", value="混合油")],
            confirmed_field_names=["oil_type"],
        ),
        db_session,
    )
    assert db_session.query(OutboxEvent).count() == 2
    pending = db_session.query(OutboxEvent).filter(OutboxEvent.status == "pending").one()
    CasePipelineService.process_event(db_session, pending.id)

    create_case_evidence(
        case.id,
        CaseEvidenceCreate(title="现场轮胎痕迹", evidence_type="现场勘验"),
        db_session,
    )

    assert db_session.query(OutboxEvent).count() == 3


def test_quality_rule_fields_enqueue_and_refresh_profile(db_session: Session):
    case = _create_case(db_session)
    CasePipelineService.process_event(db_session, db_session.query(OutboxEvent).one().id)

    CaseService.update_case(db_session, case.id, police_reported=True)
    pending = db_session.query(OutboxEvent).filter(OutboxEvent.status == "pending").one()
    CasePipelineService.process_event(db_session, pending.id)

    profiles = db_session.query(CaseAnalysisProfile).order_by(
        CaseAnalysisProfile.profile_version
    ).all()
    assert len(profiles) == 2
    assert profiles[0].is_current is False
    assert profiles[1].is_current is True
    assert {item["field"] for item in profiles[1].payload["quality"]["missing_required"]} >= {
        "police_officer",
        "police_phone",
    }


def test_vehicle_transfer_fields_are_part_of_profile_source_hash(db_session: Session):
    case = _create_case(db_session)
    vehicle = CaseVehicle(
        case_id=case.id,
        vehicle_type="皮卡",
        plate_number="TEST-001",
        transferred_to_police=False,
    )
    db_session.add(vehicle)
    db_session.commit()
    before = CasePipelineService.source_hash(db_session, case)

    vehicle.transferred_to_police = True
    vehicle.transfer_time = datetime(2026, 9, 8, 8, 0)
    vehicle.transfer_document_no = "TRANSFER-001"
    db_session.flush()

    assert CasePipelineService.source_hash(db_session, case) != before


def test_profile_output_is_deterministic_for_same_source_hash(db_session: Session):
    case = _create_case(db_session)
    first_event = db_session.query(OutboxEvent).one()
    CasePipelineService.process_event(db_session, first_event.id)
    first = db_session.query(CaseAnalysisProfile).one()

    payload = CasePipelineService.build_profile_payload(db_session, case)

    assert payload == first.payload


def _client(db: Session, role: str = "analyst") -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def principal(request: Request, call_next):
        request.state.principal = SimpleNamespace(user_id=1, role=role)
        return await call_next(request)

    app.include_router(case_pipeline.router, prefix="/api")

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_profile_and_pipeline_status_are_read_only_for_normal_user(db_session: Session):
    case = _create_case(db_session)
    event = db_session.query(OutboxEvent).one()
    CasePipelineService.process_event(db_session, event.id)
    client = _client(db_session)

    profile = client.get(f"/api/cases/{case.id}/analysis-profile/latest")
    status = client.get(f"/api/cases/{case.id}/pipeline-status")

    assert profile.status_code == 200
    assert profile.json()["payload"]["case_id"] == case.id
    assert status.status_code == 200
    assert status.json()["status"] == "completed"


def test_only_admin_can_start_historical_profile_backfill(db_session: Session):
    _create_case(db_session)

    denied = _client(db_session, role="analyst").post("/api/admin/case-profiles/backfill")
    allowed = _client(db_session, role="admin").post(
        "/api/admin/case-profiles/backfill",
        params={"limit": 100},
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["scanned"] == 1


def test_profile_backfill_cursor_advances_past_the_first_batch(db_session: Session):
    first = _create_case(db_session)
    second = CaseService.create_case(
        db=db_session,
        case_number="PIPE-002",
        occurred_time=datetime(2026, 9, 8, 2, 30),
    )
    db_session.query(OutboxEvent).delete()
    db_session.query(CasePipelineState).delete()
    db_session.commit()

    batch_one = CasePipelineService.backfill(db_session, limit=1)
    batch_two = CasePipelineService.backfill(
        db_session,
        limit=1,
        after_id=batch_one["next_after_id"],
    )

    assert batch_one["next_after_id"] == first.id
    assert batch_two["next_after_id"] == second.id
    assert {item.aggregate_id for item in db_session.query(OutboxEvent).all()} == {
        str(first.id),
        str(second.id),
    }


def test_outbox_completion_is_fenced_by_worker_token(db_session: Session):
    _create_case(db_session)
    event = db_session.query(OutboxEvent).one()
    claimed, acquired = OutboxClaimService.claim(
        db_session,
        event.id,
        expected_type="case.analysis.requested",
    )
    assert acquired is True
    original_worker = claimed.worker_id
    db_session.query(OutboxEvent).filter(OutboxEvent.id == event.id).update(
        {OutboxEvent.worker_id: "replacement-worker"},
        synchronize_session=False,
    )
    db_session.commit()

    with pytest.raises(OutboxClaimLostError, match="outbox_claim_lost"):
        OutboxClaimService.finish(
            db_session,
            event_id=event.id,
            worker_id=str(original_worker),
            status="completed",
        )

    db_session.refresh(event)
    assert event.status == "processing"
    assert event.worker_id == "replacement-worker"
