from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.case import Case, CaseEvidence
from app.models.conclusion import Conclusion
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis, HypothesisFeedback
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.governance import EvaluationDataset, EvaluationRun
from app.models.jurisdiction import JurisdictionAsset, JurisdictionFeedback
from app.models.map_foundation import (
    MapSnapshot,
    MapSnapshotFeature,
    OperationalArea,
    PublicMapBundle,
)
from app.models.meeting import Meeting
from app.services.case_service import CaseService
from app.services.governance_service import GovernanceService
from app.services.jurisdiction_service import JurisdictionService
from app.database import AreaWriteAccessError


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


def test_area_scope_filters_cases_and_assets_and_assigns_new_case(db_session: Session):
    area_a = OperationalArea(code="a", name="甲厂", status="active", is_default=True)
    area_b = OperationalArea(code="b", name="乙厂", status="active")
    db_session.add_all([area_a, area_b])
    db_session.flush()
    db_session.add_all(
        [
            Case(case_number="SCOPE-A", operational_area_id=area_a.id, occurred_time=datetime.now(timezone.utc)),
            Case(case_number="SCOPE-B", operational_area_id=area_b.id, occurred_time=datetime.now(timezone.utc)),
            JurisdictionAsset(name="甲井", asset_type="well", operational_area_id=area_a.id),
            JurisdictionAsset(name="乙井", asset_type="well", operational_area_id=area_b.id),
        ]
    )
    db_session.commit()
    case_a = db_session.query(Case).filter(Case.case_number == "SCOPE-A").first()
    case_b = db_session.query(Case).filter(Case.case_number == "SCOPE-B").first()
    db_session.add_all([
        CaseEvidence(case_id=case_a.id, title="甲厂证据"),
        CaseEvidence(case_id=case_b.id, title="乙厂证据"),
    ])
    db_session.commit()

    db_session.info["authorized_area_ids"] = (area_a.id,)
    db_session.info["default_operational_area_id"] = area_a.id

    assert [item.case_number for item in db_session.query(Case).all()] == ["SCOPE-A"]
    assert [item.name for item in db_session.query(JurisdictionAsset).all()] == ["甲井"]
    assert [item.title for item in db_session.query(CaseEvidence).all()] == ["甲厂证据"]

    db_session.info["authorized_area_ids"] = (area_b.id,)
    db_session.info["default_operational_area_id"] = area_b.id
    assert [item.case_number for item in db_session.query(Case).all()] == ["SCOPE-B"]
    assert [item.name for item in db_session.query(JurisdictionAsset).all()] == ["乙井"]
    assert [item.title for item in db_session.query(CaseEvidence).all()] == ["乙厂证据"]

    db_session.info["authorized_area_ids"] = (area_a.id,)
    db_session.info["default_operational_area_id"] = area_a.id

    created = CaseService.create_case(
        db_session,
        case_number="SCOPE-NEW",
        occurred_time=datetime.now(timezone.utc),
    )
    assert created.operational_area_id == area_a.id


def test_case_creation_accepts_an_explicit_writable_area_and_rejects_read_only_area(
    db_session: Session,
):
    area_a = OperationalArea(code="case-write-a", name="可写厂区", status="active")
    area_b = OperationalArea(code="case-read-b", name="只读厂区", status="active")
    db_session.add_all([area_a, area_b])
    db_session.commit()
    db_session.info["authorized_area_ids"] = (area_a.id, area_b.id)
    db_session.info["default_operational_area_id"] = area_a.id
    db_session.info["area_access_levels"] = {area_a.id: "write", area_b.id: "read"}

    created = CaseService.create_case(
        db_session,
        case_number="EXPLICIT-WRITABLE-AREA",
        occurred_time=datetime.now(timezone.utc),
        operational_area_id=area_a.id,
    )

    assert created.operational_area_id == area_a.id
    with pytest.raises(AreaWriteAccessError):
        CaseService.create_case(
            db_session,
            case_number="READ-ONLY-AREA",
            occurred_time=datetime.now(timezone.utc),
            operational_area_id=area_b.id,
        )


def test_legacy_map_import_paths_assign_the_session_default_area(db_session: Session):
    area = OperationalArea(code="legacy-map", name="旧导入兼容厂区", status="active", is_default=True)
    db_session.add(area)
    db_session.commit()
    db_session.info["authorized_area_ids"] = (area.id,)
    db_session.info["default_operational_area_id"] = area.id

    JurisdictionService.bulk_create_assets(
        db_session,
        [{"name": "批量井", "asset_type": "well", "latitude": 46.6, "longitude": 125.1}],
    )
    JurisdictionService.import_tabular_assets(
        db_session,
        [{"名称": "台账站库", "类型": "station", "纬度": 46.61, "经度": 125.11}],
    )
    JurisdictionService.import_geojson(
        db_session,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"id": "road-area-test", "name": "厂区道路", "asset_type": "road"},
                    "geometry": {"type": "Point", "coordinates": [125.12, 46.62]},
                }
            ],
        },
    )

    assets = db_session.query(JurisdictionAsset).all()
    assert len(assets) == 3
    assert {item.operational_area_id for item in assets} == {area.id}


def test_read_only_area_scope_cannot_create_or_update_case(db_session: Session):
    area = OperationalArea(code="read-only", name="只读厂区", status="active", is_default=True)
    db_session.add(area)
    db_session.flush()
    case = Case(
        case_number="READ-ONLY-001",
        operational_area_id=area.id,
        occurred_time=datetime.now(timezone.utc),
    )
    db_session.add(case)
    db_session.commit()
    db_session.info["authorized_area_ids"] = (area.id,)
    db_session.info["default_operational_area_id"] = area.id
    db_session.info["area_access_levels"] = {area.id: "read"}

    with pytest.raises(AreaWriteAccessError):
        CaseService.create_case(
            db_session,
            case_number="READ-ONLY-NEW",
            occurred_time=datetime.now(timezone.utc),
        )
    with pytest.raises(AreaWriteAccessError):
        CaseService.update_case(db_session, case.id, location="不得修改")


def test_jurisdiction_feedback_is_scoped_by_referenced_case_area(db_session: Session):
    area_a = OperationalArea(code="feedback-a", name="反馈甲厂", status="active", is_default=True)
    area_b = OperationalArea(code="feedback-b", name="反馈乙厂", status="active")
    db_session.add_all([area_a, area_b])
    db_session.flush()
    case_a = Case(
        case_number="FEEDBACK-A",
        operational_area_id=area_a.id,
        occurred_time=datetime.now(timezone.utc),
    )
    case_b = Case(
        case_number="FEEDBACK-B",
        operational_area_id=area_b.id,
        occurred_time=datetime.now(timezone.utc),
    )
    db_session.add_all([case_a, case_b])
    db_session.flush()
    db_session.add_all(
        [
            JurisdictionFeedback(
                operational_area_id=area_a.id,
                case_id=case_a.id,
                feedback_type="check",
            ),
            JurisdictionFeedback(
                operational_area_id=area_b.id,
                case_id=case_b.id,
                feedback_type="check",
            ),
        ]
    )
    db_session.commit()

    db_session.info["authorized_area_ids"] = (area_a.id,)
    db_session.info["default_operational_area_id"] = area_a.id
    db_session.info["area_access_levels"] = {area_a.id: "write"}

    assert JurisdictionService.summarize_effectiveness(db_session)["total_feedback"] == 1
    with pytest.raises(ValueError, match="case_not_found_or_out_of_scope"):
        JurisdictionService.record_feedback(
            db_session,
            {"case_id": case_b.id, "feedback_type": "check"},
        )


def test_legacy_conclusions_and_meetings_follow_case_area_scope(db_session: Session):
    area_a = OperationalArea(code="legacy-a", name="旧模块甲厂", status="active", is_default=True)
    area_b = OperationalArea(code="legacy-b", name="旧模块乙厂", status="active")
    db_session.add_all([area_a, area_b])
    db_session.flush()
    case_a = Case(
        case_number="LEGACY-A",
        operational_area_id=area_a.id,
        occurred_time=datetime.now(timezone.utc),
    )
    case_b = Case(
        case_number="LEGACY-B",
        operational_area_id=area_b.id,
        occurred_time=datetime.now(timezone.utc),
    )
    db_session.add_all([case_a, case_b])
    db_session.flush()
    db_session.add_all(
        [
            Conclusion(case_id=case_a.id, summary="甲厂结论"),
            Conclusion(case_id=case_b.id, summary="乙厂结论"),
            Meeting(
                meeting_id="MEET-SCOPE-A",
                operational_area_id=area_a.id,
                case_ids=[case_a.id],
                status="completed",
            ),
            Meeting(
                meeting_id="MEET-SCOPE-B",
                operational_area_id=area_b.id,
                case_ids=[case_b.id],
                status="completed",
            ),
        ]
    )
    db_session.commit()
    db_session.info["authorized_area_ids"] = (area_a.id,)
    db_session.info["default_operational_area_id"] = area_a.id

    assert [item.summary for item in db_session.query(Conclusion).all()] == ["甲厂结论"]
    assert [item.meeting_id for item in db_session.query(Meeting).all()] == ["MEET-SCOPE-A"]


def test_read_only_area_scope_cannot_write_unlinked_feedback(db_session: Session):
    area = OperationalArea(code="feedback-read", name="只读厂区", status="active", is_default=True)
    db_session.add(area)
    db_session.commit()
    db_session.info["authorized_area_ids"] = (area.id,)
    db_session.info["area_access_levels"] = {area.id: "read"}
    db_session.info["default_operational_area_id"] = area.id

    with pytest.raises(AreaWriteAccessError, match="area_write_access_required"):
        JurisdictionService.record_feedback(
            db_session,
            {
                "feedback_type": "prevention_reference",
                "adopted": False,
                "result": "只读账号不应写入",
            },
        )


def _evaluation_fixture(db: Session) -> tuple[Case, MapSnapshot, CaseHypothesis]:
    area = OperationalArea(code="eval", name="评测厂区", status="active", is_default=True)
    db.add(area)
    db.flush()
    case = Case(
        case_number="EVAL-001",
        operational_area_id=area.id,
        occurred_time=datetime.now(timezone.utc),
        latitude=46.6,
        longitude=125.1,
    )
    db.add(case)
    db.flush()
    profile = CaseAnalysisProfile(
        id="eval-profile",
        case_id=case.id,
        profile_version=1,
        source_hash="a" * 64,
        schema_version="3.3.0",
        dictionary_version="oil-case-2026.09",
        payload={"spatial_grid": "46.60:125.10"},
        quality_score=90,
        analysis_readiness="ready",
        is_current=True,
    )
    bundle = PublicMapBundle(
        bundle_id="eval-map",
        provider="fixture",
        source_version="1",
        license_record="test",
        bounds=[124, 46, 126, 47],
        manifest={},
        package_hash="b" * 64,
        status="accepted",
    )
    db.add_all([profile, bundle])
    db.flush()
    snapshot = MapSnapshot(
        id="eval-snapshot",
        version="eval-v1",
        operational_area_id=area.id,
        public_bundle_id=bundle.id,
        status="current",
        manifest={},
        feature_watermark="1",
    )
    db.add(snapshot)
    db.flush()
    run = CaseAnalysisRun(
        id="eval-run",
        case_id=case.id,
        case_profile_id=profile.id,
        map_snapshot_id=snapshot.id,
        algorithm_version="dual-domain-3.4.0",
        status="completed",
        information_gaps=[],
        completed_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()
    hypothesis = CaseHypothesis(
        id="eval-hypothesis",
        analysis_run_id=run.id,
        case_id=case.id,
        hypothesis_type="possible_source",
        rank=1,
        title="候选",
        claim="待核查",
        score=85,
        confidence=0.85,
        evidence_refs=["case_profile:eval-profile", "map_snapshot:eval-snapshot"],
        supporting_evidence=["距离条件"],
        counter_evidence=["距离不能证明来源"],
        information_gaps=[],
        score_components={"distance": 85},
        status="candidate",
        boundary="仅供人工判断",
    )
    db.add(hypothesis)
    db.flush()
    db.add(HypothesisFeedback(hypothesis_id=hypothesis.id, decision="useful"))
    db.commit()
    return case, snapshot, hypothesis


def test_evaluation_run_records_versioned_metrics_and_lineage(db_session: Session):
    case, snapshot, _ = _evaluation_fixture(db_session)
    dataset = GovernanceService.create_dataset(
        db_session,
        name="30案脱敏评测集",
        version="2026.09",
        case_ids=[case.id],
        classification="redacted",
    )
    run = GovernanceService.run_evaluation(db_session, dataset_id=dataset.id)
    lineage = GovernanceService.case_lineage(db_session, case.id)

    assert isinstance(dataset, EvaluationDataset)
    assert isinstance(run, EvaluationRun)
    assert run.status == "completed"
    assert run.metrics["evidence_coverage"] == 1.0
    assert run.metrics["counter_or_gap_coverage"] == 1.0
    assert run.metrics["top3_useful_case_rate"] == 1.0
    assert run.metrics["top3_ground_truth_hit_rate"] is None
    assert run.metrics["ground_truth_label_recall"] is None
    assert run.metrics["high_confidence_error_rate"] is None
    assert run.metrics["high_confidence_feedback_error_rate"] == 0.0
    assert run.metrics["source_top3_ground_truth_hit_rate"] is None
    assert run.metrics["nearest_facility_baseline_hit_rate"] is None
    assert run.metrics["source_top3_lift_percentage_points"] is None
    assert lineage["case_profile"]["id"] == "eval-profile"
    assert lineage["map_snapshot"]["id"] == snapshot.id
    assert lineage["algorithm_version"] == "dual-domain-3.4.0"


def test_evaluation_uses_explicit_ground_truth_for_top3_hit_rate(db_session: Session):
    case, _, hypothesis = _evaluation_fixture(db_session)
    hypothesis.evidence_refs = [
        *hypothesis.evidence_refs,
        "map_asset:42@snapshot:eval-snapshot",
    ]
    db_session.commit()
    dataset = GovernanceService.create_dataset(
        db_session,
        name="有标注脱敏评测集",
        version="2026.09",
        case_ids=[case.id],
        classification="redacted",
        ground_truth={
            str(case.id): [
                {
                    "hypothesis_type": "possible_source",
                    "expected_asset_ids": [42],
                }
            ]
        },
    )

    run = GovernanceService.run_evaluation(db_session, dataset_id=dataset.id)

    assert dataset.manifest["ground_truth_case_count"] == 1
    assert dataset.manifest["ground_truth_label_count"] == 1
    assert run.metrics["top3_ground_truth_hit_rate"] == 1.0
    assert run.metrics["ground_truth_label_recall"] == 1.0
    assert run.metrics["ground_truth_coverage"] == 1.0
    assert run.metrics["high_confidence_error_rate"] == 0.0


def test_evaluation_reports_lift_over_nearest_facility_baseline(db_session: Session):
    case, snapshot, hypothesis = _evaluation_fixture(db_session)
    db_session.add_all(
        [
            MapSnapshotFeature(
                snapshot_id=snapshot.id,
                operational_area_id=snapshot.operational_area_id,
                asset_id=99,
                name="最近设施",
                asset_type="well",
                geometry_type="point",
                latitude=46.6001,
                longitude=125.1001,
                source="ledger",
                status="active",
                verified=True,
                attributes={},
            ),
            MapSnapshotFeature(
                snapshot_id=snapshot.id,
                operational_area_id=snapshot.operational_area_id,
                asset_id=42,
                name="真实来源",
                asset_type="well",
                geometry_type="point",
                latitude=46.605,
                longitude=125.105,
                source="ledger",
                status="active",
                verified=True,
                attributes={"oil_type": "原油", "production_output": 95},
            ),
        ]
    )
    hypothesis.evidence_refs = [
        *hypothesis.evidence_refs,
        "map_asset:42@snapshot:eval-snapshot",
    ]
    db_session.commit()
    dataset = GovernanceService.create_dataset(
        db_session,
        name="最近设施基线对比集",
        version="2026.09",
        case_ids=[case.id],
        classification="redacted",
        ground_truth={
            str(case.id): [
                {
                    "hypothesis_type": "possible_source",
                    "expected_asset_ids": [42],
                }
            ]
        },
    )

    run = GovernanceService.run_evaluation(db_session, dataset_id=dataset.id)

    assert run.metrics["source_top3_ground_truth_hit_rate"] == 1.0
    assert run.metrics["nearest_facility_baseline_hit_rate"] == 0.0
    assert run.metrics["source_top3_lift_percentage_points"] == 100.0
    assert run.metrics["source_baseline_assessable_case_count"] == 1


def test_source_baseline_includes_current_runs_with_zero_candidates(db_session: Session):
    case, snapshot, hypothesis = _evaluation_fixture(db_session)
    db_session.query(HypothesisFeedback).delete()
    db_session.delete(hypothesis)
    db_session.add(
        MapSnapshotFeature(
            snapshot_id=snapshot.id,
            operational_area_id=snapshot.operational_area_id,
            asset_id=42,
            name="真实且最近来源",
            asset_type="well",
            geometry_type="point",
            latitude=46.6001,
            longitude=125.1001,
            source="ledger",
            status="active",
            verified=True,
            attributes={},
        )
    )
    db_session.commit()
    dataset = GovernanceService.create_dataset(
        db_session,
        name="零候选来源评测集",
        version="2026.09",
        case_ids=[case.id],
        classification="redacted",
        ground_truth={
            str(case.id): [
                {
                    "hypothesis_type": "possible_source",
                    "expected_asset_ids": [42],
                }
            ]
        },
    )

    run = GovernanceService.run_evaluation(db_session, dataset_id=dataset.id)

    assert run.metrics["candidate_count"] == 0
    assert run.metrics["source_baseline_assessable_case_count"] == 1
    assert run.metrics["source_top3_ground_truth_hit_rate"] == 0.0
    assert run.metrics["nearest_facility_baseline_hit_rate"] == 1.0
    assert run.metrics["source_top3_lift_percentage_points"] == -100.0


def test_high_confidence_error_rate_uses_ground_truth_not_feedback(db_session: Session):
    case, _, hypothesis = _evaluation_fixture(db_session)
    hypothesis.evidence_refs = [
        *hypothesis.evidence_refs,
        "map_asset:99@snapshot:eval-snapshot",
    ]
    db_session.query(HypothesisFeedback).delete()
    db_session.commit()
    dataset = GovernanceService.create_dataset(
        db_session,
        name="高置信错误评测集",
        version="2026.09",
        case_ids=[case.id],
        classification="redacted",
        ground_truth={
            str(case.id): [
                {
                    "hypothesis_type": "possible_source",
                    "expected_asset_ids": [42],
                }
            ]
        },
    )

    run = GovernanceService.run_evaluation(db_session, dataset_id=dataset.id)

    assert run.metrics["high_confidence_error_rate"] == 1.0
    assert run.metrics["high_confidence_feedback_error_rate"] is None


def test_evaluation_rejects_ambiguous_ground_truth_label(db_session: Session):
    case, _, _ = _evaluation_fixture(db_session)

    with pytest.raises(ValueError, match="invalid_ground_truth"):
        GovernanceService.create_dataset(
            db_session,
            name="无定位标注",
            version="2026.09",
            case_ids=[case.id],
            classification="redacted",
            ground_truth={
                str(case.id): [{"hypothesis_type": "possible_source"}],
            },
        )


def test_non_redacted_dataset_is_rejected(db_session: Session):
    case, _, _ = _evaluation_fixture(db_session)
    with pytest.raises(ValueError, match="redacted_dataset_required"):
        GovernanceService.create_dataset(
            db_session,
            name="原始数据",
            version="1",
            case_ids=[case.id],
            classification="internal_raw",
        )


def test_evaluation_uses_only_current_versions_and_reviewed_high_confidence_denominator(db_session: Session):
    case, snapshot, current_hypothesis = _evaluation_fixture(db_session)
    current_hypothesis.confidence = 0.9
    historical_profile = CaseAnalysisProfile(
        id="historical-profile",
        case_id=case.id,
        profile_version=0,
        source_hash="c" * 64,
        schema_version="3.3.0",
        dictionary_version="oil-case-2026.09",
        payload={},
        quality_score=20,
        analysis_readiness="insufficient",
        is_current=False,
    )
    historical_snapshot = MapSnapshot(
        id="historical-snapshot",
        version="historical-v0",
        operational_area_id=snapshot.operational_area_id,
        public_bundle_id=snapshot.public_bundle_id,
        status="superseded",
        manifest={},
        feature_watermark="old",
    )
    db_session.add_all([historical_profile, historical_snapshot])
    db_session.flush()
    historical_run = CaseAnalysisRun(
        id="historical-run",
        case_id=case.id,
        case_profile_id=historical_profile.id,
        map_snapshot_id=historical_snapshot.id,
        algorithm_version="dual-domain-3.4.0",
        status="completed",
        information_gaps=[],
        completed_at=datetime.now(timezone.utc),
    )
    db_session.add(historical_run)
    db_session.flush()
    db_session.add(
        CaseHypothesis(
            id="historical-hypothesis",
            analysis_run_id=historical_run.id,
            case_id=case.id,
            hypothesis_type="possible_source",
            rank=1,
            title="旧候选",
            claim="旧结果",
            score=99,
            confidence=0.99,
            evidence_refs=["old"],
            supporting_evidence=["old"],
            counter_evidence=["old"],
            information_gaps=[],
            score_components={},
            status="candidate",
            boundary="旧版本",
        )
    )
    db_session.commit()
    dataset = GovernanceService.create_dataset(
        db_session,
        name="当前版本评测",
        version="1",
        case_ids=[case.id],
        classification="redacted",
    )

    evaluation = GovernanceService.run_evaluation(db_session, dataset_id=dataset.id)

    assert evaluation.metrics["candidate_count"] == 1
    assert evaluation.metrics["high_confidence_error_rate"] is None
    assert evaluation.metrics["high_confidence_feedback_error_rate"] == 0.0
    assert evaluation.metrics["high_confidence_feedback_coverage"] == 1.0
    assert evaluation.trace_manifest["analysis_run_ids"] == ["eval-run"]
