from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.config import settings
from app.database import Base
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis, HypothesisFeedback
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature, PublicMapBundle
from app.services.case_insight_service import CaseInsightService
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_service import CaseService
from app.services.map_foundation_service import MapFoundationService


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


def _case(db: Session, number: str, lat: float | None = 46.6, lon: float | None = 125.1):
    case = CaseService.create_case(
        db=db,
        case_number=number,
        occurred_time=datetime(2026, 9, 8, 1, 30),
        location="南区井场",
        latitude=lat,
        longitude=lon,
        case_type="涉油盗窃",
        description="夜间车辆进入井场后发现原油损失。",
        oil_type="原油",
        facility_type="井口",
        modus_operandi="车辆转运",
    )
    event = db.query(OutboxEvent).filter(OutboxEvent.aggregate_id == str(case.id)).one()
    CasePipelineService.process_event(db, event.id)
    return case


def _current_map(db: Session):
    area = MapFoundationService.ensure_default_area(db)
    db.flush()
    bundle = PublicMapBundle(
        bundle_id="fixture-map",
        provider="fixture",
        source_version="1",
        license_record="test",
        bounds=[124, 46, 126, 47],
        manifest={"fixture": True},
        package_hash="a" * 64,
        status="accepted",
    )
    db.add(bundle)
    db.flush()
    snapshot = MapSnapshot(
        id="snapshot-fixture",
        version="fixture-v1",
        operational_area_id=area.id,
        public_bundle_id=bundle.id,
        status="current",
        manifest={"fixture": True},
        feature_watermark="fixture",
    )
    db.add(snapshot)
    db.commit()
    return area, snapshot


def _freeze_assets(db: Session, snapshot: MapSnapshot, assets: list[JurisdictionAsset]) -> None:
    for asset in assets:
        db.add(
            MapSnapshotFeature(
                snapshot_id=snapshot.id,
                operational_area_id=snapshot.operational_area_id,
                asset_id=asset.id,
                name=asset.name,
                asset_type=asset.asset_type,
                geometry_type=asset.geometry_type or "point",
                latitude=asset.latitude,
                longitude=asset.longitude,
                geometry=asset.geometry,
                source=asset.source,
                status=asset.status,
                verified=asset.verified,
                verification_state=asset.verification_state,
                attributes=dict(asset.attributes or {}),
            )
        )
    db.commit()


def test_deterministic_case_map_fusion_returns_at_most_three_explainable_candidates(db_session: Session):
    area, snapshot = _current_map(db_session)
    case = _case(db_session, "INSIGHT-001")
    case.operational_area_id = area.id
    assets = [
        JurisdictionAsset(
            operational_area_id=area.id,
            canonical_key="well:1",
            external_id="W-1",
            name="南区 12 号井",
            asset_type="well",
            latitude=46.602,
            longitude=125.102,
            source="ledger",
            verified=True,
            verification_state="source_verified",
            status="active",
            attributes={"oil_type": "原油", "production_output": 95},
        ),
        JurisdictionAsset(
            operational_area_id=area.id,
            canonical_key="storage:1",
            name="南区临时存储区",
            asset_type="storage",
            latitude=46.61,
            longitude=125.11,
            source="ledger",
            verified=True,
            verification_state="source_verified",
            status="active",
        ),
        JurisdictionAsset(
            operational_area_id=area.id,
            canonical_key="road:1",
            name="南北便道",
            asset_type="road",
            latitude=46.604,
            longitude=125.104,
            source="public_map",
            verified=False,
            verification_state="reference_only",
            status="active",
        ),
    ]
    db_session.add_all(assets)
    db_session.commit()
    _freeze_assets(db_session, snapshot, assets)
    profile = db_session.query(CaseAnalysisProfile).filter(CaseAnalysisProfile.case_id == case.id).one()

    event = CaseInsightService.enqueue_analysis(db_session, profile, snapshot)
    db_session.commit()
    result = CaseInsightService.process_event(db_session, event.id)

    assert result["status"] == "completed"
    run = db_session.query(CaseAnalysisRun).one()
    hypotheses = db_session.query(CaseHypothesis).order_by(CaseHypothesis.rank).all()
    assert run.algorithm_version == "dual-domain-3.4.0"
    assert run.map_snapshot_id == snapshot.id
    assert 1 <= len(hypotheses) <= 3
    for hypothesis in hypotheses:
        assert hypothesis.evidence_refs
        assert hypothesis.supporting_evidence
        assert hypothesis.counter_evidence or hypothesis.information_gaps
        assert hypothesis.status == "candidate"
        assert "候选" in hypothesis.boundary


def test_source_candidate_uses_business_score_instead_of_nearest_only(db_session: Session):
    area, snapshot = _current_map(db_session)
    case = _case(db_session, "INSIGHT-SOURCE-SCORE")
    case.operational_area_id = area.id
    assets = [
        JurisdictionAsset(
            operational_area_id=area.id,
            canonical_key="well:nearest",
            name="最近但属性不匹配井",
            asset_type="well",
            latitude=46.6005,
            longitude=125.1005,
            source="ledger",
            verified=True,
            status="active",
            attributes={"oil_type": "天然气", "production_output": 10},
        ),
        JurisdictionAsset(
            operational_area_id=area.id,
            canonical_key="well:matched",
            name="稍远但油品与产量匹配井",
            asset_type="well",
            latitude=46.608,
            longitude=125.108,
            source="ledger",
            verified=True,
            status="active",
            attributes={"oil_type": "原油", "production_output": 95},
        ),
    ]
    db_session.add_all(assets)
    db_session.commit()
    _freeze_assets(db_session, snapshot, assets)

    candidates = CaseInsightService._source_candidates(
        db_session,
        case,
        db_session.query(CaseAnalysisProfile).filter(
            CaseAnalysisProfile.case_id == case.id,
            CaseAnalysisProfile.is_current.is_(True),
        ).one(),
        snapshot,
    )

    assert len(candidates) == 1
    assert candidates[0]["title"] == "可能盗取来源候选：稍远但油品与产量匹配井"
    assert candidates[0]["score_components"]["oil_match"] == 10.0
    assert candidates[0]["score_components"]["production"] == 10.0


def test_profile_completion_automatically_enqueues_dual_domain_analysis(db_session: Session):
    _current_map(db_session)

    case = _case(db_session, "INSIGHT-AUTO")

    event = db_session.query(OutboxEvent).filter(
        OutboxEvent.aggregate_id == str(case.id),
        OutboxEvent.event_type == "case.insights.requested",
    ).one()
    assert event.status == "pending"


def test_reconciler_restores_missing_current_profile_map_pair(db_session: Session):
    area, snapshot = _current_map(db_session)
    case = _case(db_session, "INSIGHT-RECONCILE")
    case.operational_area_id = area.id
    db_session.commit()
    profile = db_session.query(CaseAnalysisProfile).filter(
        CaseAnalysisProfile.case_id == case.id,
        CaseAnalysisProfile.is_current.is_(True),
    ).one()
    db_session.query(OutboxEvent).filter(
        OutboxEvent.event_type == "case.insights.requested"
    ).delete(synchronize_session=False)
    db_session.commit()

    result = CaseInsightService.reconcile_current_pairs(db_session)

    event = db_session.query(OutboxEvent).filter(
        OutboxEvent.event_type == "case.insights.requested",
        OutboxEvent.payload["case_profile_id"].as_string() == profile.id,
    ).one()
    assert result["missing_pairs"] == 1
    assert event.payload["map_snapshot_id"] == snapshot.id
    assert event.status == "pending"


def test_missing_geo_returns_explicit_gap_and_no_fabricated_candidate(db_session: Session):
    _, snapshot = _current_map(db_session)
    case = _case(db_session, "INSIGHT-NO-GEO", lat=None, lon=None)
    profile = db_session.query(CaseAnalysisProfile).filter(CaseAnalysisProfile.case_id == case.id).one()
    event = CaseInsightService.enqueue_analysis(db_session, profile, snapshot)
    db_session.commit()

    result = CaseInsightService.process_event(db_session, event.id)

    assert result["status"] == "degraded"
    run = db_session.query(CaseAnalysisRun).one()
    assert run.information_gaps == ["案件缺少经纬度，无法执行案件—地图空间融合"]
    assert db_session.query(CaseHypothesis).count() == 0


def test_feedback_never_turns_candidate_into_case_fact(db_session: Session):
    area, snapshot = _current_map(db_session)
    case = _case(db_session, "INSIGHT-FEEDBACK")
    case.operational_area_id = area.id
    asset = JurisdictionAsset(
        operational_area_id=area.id,
        canonical_key="well:feedback",
        name="核查井",
        asset_type="well",
        latitude=46.601,
        longitude=125.101,
        source="ledger",
        verified=True,
        status="active",
    )
    db_session.add(asset)
    db_session.commit()
    _freeze_assets(db_session, snapshot, [asset])
    original_upstream = case.upstream_source
    profile = db_session.query(CaseAnalysisProfile).filter(CaseAnalysisProfile.case_id == case.id).one()
    event = CaseInsightService.enqueue_analysis(db_session, profile, snapshot)
    db_session.commit()
    CaseInsightService.process_event(db_session, event.id)
    hypothesis = db_session.query(CaseHypothesis).first()

    feedback = CaseInsightService.record_feedback(
        db_session,
        hypothesis_id=hypothesis.id,
        decision="useful",
        note="纳入人工核查范围",
        created_by=None,
    )

    assert isinstance(feedback, HypothesisFeedback)
    db_session.refresh(case)
    assert case.upstream_source == original_upstream
    assert hypothesis.status == "candidate"


def test_stale_profile_event_is_superseded_before_it_can_create_insights(db_session: Session):
    _, snapshot = _current_map(db_session)
    case = _case(db_session, "INSIGHT-STALE")
    old_profile = db_session.query(CaseAnalysisProfile).filter(
        CaseAnalysisProfile.case_id == case.id,
        CaseAnalysisProfile.is_current.is_(True),
    ).one()
    old_event = CaseInsightService.enqueue_analysis(db_session, old_profile, snapshot)
    db_session.commit()

    CaseService.update_case(db_session, case.id, location="南区新位置")
    profile_event = db_session.query(OutboxEvent).filter(
        OutboxEvent.event_type == "case.analysis.requested",
        OutboxEvent.status == "pending",
    ).one()
    CasePipelineService.process_event(db_session, profile_event.id)

    result = CaseInsightService.process_event(db_session, old_event.id)

    assert result["status"] == "superseded"
    assert db_session.query(CaseAnalysisRun).filter(
        CaseAnalysisRun.case_profile_id == old_profile.id,
    ).count() == 0
