from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.deployment_advisor import TechDefenseImportRequest
from app.database import Base
from app.models.case import Case
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.deployment_advisor import DeploymentRecommendation, RecommendationFeedback, TechDefenseEventAggregate
from app.models.map_foundation import MapSnapshot, OperationalArea, PublicMapBundle
from app.services.deployment_advisor_service import DeploymentAdvisorService


@pytest.fixture
def db_session() -> Session:
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


def _analysis_fixture(db: Session) -> OperationalArea:
    area = OperationalArea(code="factory-a", name="一厂", is_default=True, status="active")
    db.add(area)
    db.flush()
    case = Case(
        case_number="ADVISOR-001",
        operational_area_id=area.id,
        occurred_time=datetime.now(timezone.utc) - timedelta(days=1),
        location="南区井场",
        latitude=46.6,
        longitude=125.1,
        case_type="涉油盗窃",
        modus_operandi="车辆转运",
    )
    db.add(case)
    for index in (2, 3):
        db.add(Case(case_number=f'ADVISOR-00{index}', operational_area_id=area.id,
                    occurred_time=case.occurred_time, case_type='涉油盗窃'))
    db.flush()
    profile = CaseAnalysisProfile(
        id="profile-advisor",
        case_id=case.id,
        profile_version=1,
        source_hash="b" * 64,
        schema_version="3.3.0",
        dictionary_version="oil-case-2026.09",
        payload={"spatial_grid": "46.60:125.10"},
        quality_score=80,
        analysis_readiness="ready",
        is_current=True,
    )
    bundle = PublicMapBundle(
        bundle_id="advisor-map",
        provider="fixture",
        source_version="1",
        license_record="test",
        bounds=[124, 46, 126, 47],
        manifest={},
        package_hash="c" * 64,
        status="accepted",
    )
    db.add_all([profile, bundle])
    db.flush()
    snapshot = MapSnapshot(
        id="snapshot-advisor",
        version="advisor-v1",
        operational_area_id=area.id,
        public_bundle_id=bundle.id,
        status="current",
        manifest={},
        feature_watermark="1",
    )
    db.add(snapshot)
    db.flush()
    run = CaseAnalysisRun(
        id="run-advisor",
        case_id=case.id,
        case_profile_id=profile.id,
        map_snapshot_id=snapshot.id,
        algorithm_version="dual-domain-3.4.0",
        status="completed",
        information_gaps=[],
        # Daily briefs now use the last closed business day, not a partial today.
        completed_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.add(run)
    db.flush()
    db.add(
        CaseHypothesis(
            id="hypothesis-advisor",
            analysis_run_id=run.id,
            case_id=case.id,
            hypothesis_type="possible_source",
            rank=1,
            title="可能盗取来源候选：南区井",
            claim="距案发点近，待核查",
            score=82,
            confidence=0.82,
            region={"type": "circle", "center": [125.1, 46.6], "radius_m": 500},
            evidence_refs=["case_profile:profile-advisor", "map_asset:1@snapshot:snapshot-advisor"],
            supporting_evidence=["距离较近"],
            counter_evidence=["空间接近不代表已确认"],
            information_gaps=["缺少现场核查"],
            score_components={"distance": 82},
            status="candidate",
            boundary="仅为候选",
        )
    )
    db.commit()
    return area


def test_tech_defense_input_forbids_raw_plate_and_images():
    with pytest.raises(ValidationError):
        TechDefenseImportRequest.model_validate(
            {
                "source_key": "camera-summary",
                "source_name": "监控摘要",
                "period_start": "2026-09-08T00:00:00Z",
                "period_end": "2026-09-08T01:00:00Z",
                "area_code": "factory-a",
                "device_type": "camera",
                "online_count": 10,
                "offline_count": 1,
                "alert_count": 3,
                "plate_number": "黑A12345",
            }
        )

    with pytest.raises(ValidationError):
        TechDefenseImportRequest.model_validate(
            {
                "source_key": "camera-summary",
                "source_name": "监控摘要",
                "period_start": "2026-09-08T00:00:00Z",
                "period_end": "2026-09-08T01:00:00Z",
                "area_code": "factory-a",
                "device_type": "camera",
                "disposition_summary": "已核查车辆黑A12345",
            }
        )


def test_advisor_generates_no_more_than_three_evidence_backed_recommendations(db_session: Session):
    area = _analysis_fixture(db_session)
    DeploymentAdvisorService.import_tech_summary(
        db_session,
        source_key="camera-summary",
        source_name="监控摘要",
        operational_area_id=area.id,
        period_start=datetime.now(timezone.utc) - timedelta(hours=6),
        period_end=datetime.now(timezone.utc),
        device_type="camera",
        online_count=8,
        offline_count=4,
        alert_count=5,
        redacted_vehicle_event_count=2,
        disposition_summary="2 条已人工核查",
    )

    brief, replay = DeploymentAdvisorService.generate_brief(
        db_session,
        operational_area_id=area.id,
        period_type="daily",
        as_of=datetime.now(timezone.utc),
    )

    assert replay is False
    recommendations = db_session.query(DeploymentRecommendation).all()
    assert 1 <= len(recommendations) <= 3
    for item in recommendations:
        assert item.evidence_refs
        assert item.valid_until
        assert item.status == "candidate"
        assert item.auto_execution_allowed is False
    assert brief.status == "completed"


def test_same_inputs_do_not_generate_repeated_generic_brief(db_session: Session):
    area = _analysis_fixture(db_session)
    as_of = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)

    first, first_replay = DeploymentAdvisorService.generate_brief(
        db_session,
        operational_area_id=area.id,
        period_type="daily",
        as_of=as_of,
    )
    second, second_replay = DeploymentAdvisorService.generate_brief(
        db_session,
        operational_area_id=area.id,
        period_type="daily",
        as_of=as_of + timedelta(hours=1),
    )

    assert first_replay is False
    assert second_replay is True
    assert first.id == second.id


def test_recommendation_feedback_does_not_create_execution_task(db_session: Session):
    area = _analysis_fixture(db_session)
    DeploymentAdvisorService.generate_brief(
        db_session,
        operational_area_id=area.id,
        period_type="daily",
        as_of=datetime.now(timezone.utc),
    )
    recommendation = db_session.query(DeploymentRecommendation).first()

    feedback = DeploymentAdvisorService.record_feedback(
        db_session,
        recommendation_id=recommendation.id,
        decision="adopt_reference",
        usefulness_score=5,
        note="作为本周核查参考",
        created_by=None,
    )

    assert isinstance(feedback, RecommendationFeedback)
    assert recommendation.status == "candidate"
    assert recommendation.auto_execution_allowed is False
    assert db_session.query(TechDefenseEventAggregate).count() == 0


def test_recommendation_feedback_respects_operational_area_scope(db_session: Session):
    area = _analysis_fixture(db_session)
    DeploymentAdvisorService.generate_brief(
        db_session,
        operational_area_id=area.id,
        period_type="daily",
        as_of=datetime.now(timezone.utc),
    )
    recommendation = db_session.query(DeploymentRecommendation).first()

    db_session.info["authorized_area_ids"] = (area.id + 999,)

    with pytest.raises(ValueError, match="recommendation_not_found"):
        DeploymentAdvisorService.record_feedback(
            db_session,
            recommendation_id=recommendation.id,
            decision="adopt_reference",
            usefulness_score=5,
            note=None,
            created_by=None,
        )
