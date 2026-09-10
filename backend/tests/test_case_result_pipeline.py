"""真实服务链：录入→Outbox→画像/融合→冻结成果，不调用生成接口。"""
import pytest
from sqlalchemy import select

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.case_result import CaseResultSnapshot
from app.models.jurisdiction import JurisdictionAsset
from app.services.case_insight_service import CaseInsightService
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_result_service import CaseResultService
from app.services.case_service import CaseService
from app.services.map_foundation_service import MapFoundationService
from test_case_insights import db_session, _case, _current_map, _freeze_assets  # noqa: F401
from test_case_pipeline import _create_case


@pytest.fixture(autouse=True)
def default_area(db_session):
    area = MapFoundationService.ensure_default_area(db_session)
    db_session.commit()
    db_session.info["default_operational_area_id"] = area.id


def allow_case(db, case):
    db.info["authorized_area_ids"] = (case.operational_area_id,)


def test_case_save_returns_before_automatic_profile_result_and_get_is_read_only(db_session):
    case = _create_case(db_session)
    assert db_session.query(CaseResultSnapshot).count() == 0
    result = CasePipelineService.process_pending(db_session)
    assert result["completed"] == 1
    assert db_session.query(CaseResultSnapshot).count() == 1
    allow_case(db_session, case)
    latest = CaseResultService.latest(db_session, case.id)
    assert latest["content"]["analysis_status"] == "not_generated"
    assert latest["content"]["candidates"] == []
    assert latest["freshness"] == "current"
    assert CaseResultService.latest(db_session, case.id)["id"] == latest["id"]
    assert db_session.query(CaseResultSnapshot).count() == 1


def test_fusion_automatically_freezes_evidence_and_replay_does_not_duplicate(db_session):
    area, map_snapshot = _current_map(db_session)
    case = _case(db_session, "SYNTHETIC-AUTO-RESULT")
    asset = JurisdictionAsset(operational_area_id=area.id, name="合成井", asset_type="well",
                              latitude=46.601, longitude=125.101, source="ledger", verified=True,
                              verification_state="source_verified", status="active",
                              attributes={"oil_type": "原油", "production_output": 95})
    db_session.add(asset)
    db_session.commit()
    _freeze_assets(db_session, map_snapshot, [asset])
    event = db_session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "case.insights.requested"))
    executed = CaseInsightService.process_event(db_session, event.id)
    assert executed["status"] == "completed"
    assert db_session.query(CaseResultSnapshot).count() == 2
    allow_case(db_session, case)
    latest = CaseResultService.latest(db_session, case.id)
    assert latest["content"]["versions"]["analysis_run_id"] == executed["run_id"]
    assert latest["content"]["candidates"][0]["evidence_refs"]
    CaseInsightService.process_event(db_session, event.id)
    assert db_session.query(CaseResultSnapshot).count() == 2
    # A non-current map never masquerades as current analysis; old ID remains historical.
    map_snapshot.status = "superseded"
    db_session.commit()
    assert CaseResultService.latest(db_session, case.id)["content"]["analysis_status"] == "not_generated"
    assert CaseResultService.read(db_session, latest["id"])["content"] == latest["content"]


def test_pending_case_changes_are_explicit_and_new_profile_replaces_latest(db_session):
    case = _create_case(db_session)
    CasePipelineService.process_pending(db_session)
    allow_case(db_session, case)
    before = CaseResultService.latest(db_session, case.id)
    case.description = "后续补充的合成案情"
    event = CasePipelineService.enqueue_case_change(db_session, case)
    db_session.commit()
    pending = CaseResultService.latest(db_session, case.id)
    assert pending["id"] == before["id"]
    assert pending["freshness"] == "pending_update"
    CasePipelineService.process_event(db_session, event.id)
    after = CaseResultService.latest(db_session, case.id)
    assert after["freshness"] == "current" and after["id"] != before["id"]
    assert CaseResultService.read(db_session, before["id"])["content"] == before["content"]


def test_failure_after_freeze_rolls_back_derived_rows_and_retry_recovers(db_session, monkeypatch):
    case = _create_case(db_session)
    original = case.description
    event = db_session.scalar(select(OutboxEvent))
    freeze = CaseResultService.freeze_completed_inputs

    def fail_after_insert(*args, **kwargs):
        freeze(*args, **kwargs)
        raise RuntimeError("synthetic-result-failure")

    with monkeypatch.context() as patch:
        patch.setattr(CaseResultService, "freeze_completed_inputs", fail_after_insert)
        with pytest.raises(RuntimeError, match="synthetic-result-failure"):
            CasePipelineService.process_event(db_session, event.id)
    assert db_session.query(CaseAnalysisProfile).count() == 0
    assert db_session.query(CaseResultSnapshot).count() == 0
    assert db_session.scalar(select(Case.description).where(Case.id == case.id)) == original
    db_session.refresh(event)
    assert event.status == "retry"
    assert CasePipelineService.process_event(db_session, event.id)["status"] == "completed"
    assert db_session.query(CaseResultSnapshot).count() == 1


def test_existing_case_delete_still_works_after_automatic_result(db_session):
    case = _create_case(db_session)
    CasePipelineService.process_pending(db_session)
    assert CaseService.delete_case(db_session, case.id)
    assert db_session.query(CaseResultSnapshot).count() == 0
