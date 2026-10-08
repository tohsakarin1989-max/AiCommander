"""Sparse scene records stay useful without inventing an incident endpoint."""
from datetime import datetime, timezone

import pytest

from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.case_result import CaseResultSnapshot
from app.services.case_analysis_applicability import assess, allows
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_result_document import build_case_result_document
from app.services.case_result_service import CaseResultService
from app.services.case_semantic_service import build_semantic_profile, TEXT_FIELDS
from app.services.case_service import CaseService
from app.services.case_source_service import CaseSourceService
from app.services.case_insight_service import CaseInsightService
from app.services.case_road_triggers import enqueue_completed_result
from test_case_insights import db_session, _current_map, _freeze_assets  # noqa: F401


def location(role="discovery", precision="exact"):
    return {"role": role, "precision": precision, "description": "合成测试地点",
            "geometry": {"type": "Point", "coordinates": [125.1, 46.6]}, "source_note": "仅测试"}


def semantics(values):
    return build_semantic_profile({key: value for key, value in values.items() if key in TEXT_FIELDS})


@pytest.mark.parametrize("role,precision,text,expected", [
    ("discovery", "exact", "现场查获车辆，来源不详。", False),
    ("mentioned", "exact", "打孔盗油", False),
    ("incident", "area", "打孔盗油", False),
    ("incident", "exact", "未发现打孔盗油", False),
    ("incident", "exact", "疑似打孔盗油", False),
    ("incident", "exact", "打孔盗油", True),
])
def test_explicit_role_precision_and_positive_clue_are_required(role, precision, text, expected):
    values = {"description": text, "discovered_at": "2026-10-08T12:00:00+08:00"}
    result = assess({"case": values, "locations": [location(role, precision)]}, semantics(values), source_revision_id=42)
    assert allows({"analysis_applicability": result}, "source_inference") is expected
    assert all(item["evidence_refs"] == ["case_revision:42"] for item in result["entries"])


def test_legacy_coordinates_do_not_imply_incident_and_conflicts_do_not_trigger():
    values = {"latitude": 46.6, "longitude": 125.1, "description": "打孔盗油"}
    assert not allows({"analysis_applicability": assess({"case": values}, semantics(values))}, "source_inference")
    values["description"] = "初报打孔盗油。复核未发现打孔盗油。"
    assert not allows({"analysis_applicability": assess({"case": values, "locations": [location("incident")]}, semantics(values))}, "source_inference")
    assert not allows({}, "road_analysis")


def create_scene(db, *, role="discovery", text="22时发现车辆载有疑似原油，已移交公安，来源去向不详。"):
    area, snapshot = _current_map(db)
    db.info["default_operational_area_id"] = area.id
    case = CaseService.create_case(db, case_number="V80-SCENE", description=text,
        discovered_at=datetime(2026, 10, 8, 14, tzinfo=timezone.utc), location="合成测试地点",
        initial_locations=[location(role)], person_handling="已移交公安，后续未知")
    before = CaseSourceService.source_hash(db, case)
    event = db.query(OutboxEvent).filter_by(event_type="case.analysis.requested", aggregate_id=str(case.id)).one()
    CasePipelineService.process_event(db, event.id)
    profile = db.query(CaseAnalysisProfile).filter_by(case_id=case.id, is_current=True).one()
    return case, profile, snapshot, before


def test_discovery_record_produces_exportable_result_without_deep_jobs(db_session):
    case, profile, snapshot, before = create_scene(db_session)
    assert profile.payload["analysis_facts"]["latitude"] is None
    assert profile.payload["spatial_grid"] is None
    assert profile.payload["recorded_locations"][0]["role"] == "discovery"
    assert db_session.query(OutboxEvent).filter_by(event_type="case.insights.requested").count() == 0
    assert CaseInsightService.enqueue_analysis(db_session, profile, snapshot) is None
    assert enqueue_completed_result(db_session, profile, "not-needed") is None
    db_session.info["authorized_area_ids"] = (case.operational_area_id,)
    result = CaseResultService.latest(db_session, case.id)
    assert result["content"]["analysis_status"] == "not_applicable"
    assert result["composition_status"] == "not_applicable"
    assert result["content"]["candidates"] == []
    document = build_case_result_document(result)
    body = "\n".join(block.text for block in document.blocks)
    assert "不据此寻找盗取来源" in body and "未知/未获反馈" in body
    assert CasePipelineService.enqueue_case_change(db_session, case) is None
    assert db_session.query(CaseResultSnapshot).count() == 1
    assert CaseSourceService.source_hash(db_session, case) == before


def test_suitable_incident_enqueues_and_uses_recorded_endpoint(db_session):
    case, profile, snapshot, before = create_scene(db_session, role="incident", text="现场明确记录打孔盗油痕迹。")
    assert profile.payload["analysis_facts"]["latitude"] == 46.6
    assert profile.payload["spatial_grid"] == "46.60:125.10"
    event = CaseInsightService.enqueue_analysis(db_session, profile, snapshot)
    assert event is not None
    assert db_session.query(OutboxEvent).filter_by(event_type="case.insights.requested").count() == 1
    output = CaseInsightService.process_event(db_session, event.id)
    assert output["status"] == "degraded"  # No production facilities in this map.
    assert CaseSourceService.source_hash(db_session, case) == before


def test_preupgrade_queued_event_does_not_bypass_current_suitability(db_session):
    case, profile, snapshot, _ = create_scene(db_session)
    event = OutboxEvent(id="old-pending-insight", event_type="case.insights.requested", aggregate_type="case",
        aggregate_id=str(case.id), payload={"case_profile_id": profile.id, "map_snapshot_id": snapshot.id},
        idempotency_key="old-pending-insight", status="pending")
    db_session.add(event)
    db_session.commit()
    assert CaseInsightService.process_event(db_session, event.id)["outcome"] == "analysis_not_applicable"
    assert db_session.query(CaseResultSnapshot).count() == 1
