"""Synthetic contract tests, not live-model or deployment acceptance."""
import json
from copy import deepcopy
from datetime import datetime

import pytest

from app.config import settings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import get_db
from app.api import case_pipeline
from app.models.ai_model import AIModel
from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile, CasePipelineState, OutboxEvent
from app.models.case_preprocess_supplement import CasePreprocessSupplement
from app.models.case_source import CaseRevision
from app.models.map_foundation import OperationalArea
from app.models.preprocess_job import PreprocessJob
from app.models.user import User
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_preprocess_adapter import current_profile, queue_status
from app.services.case_service import CaseService
from app.services.preprocess_service import CasePreprocessService
from app.services import case_preprocess_supplement as supplements
from test_batch_review import _client, _session


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(settings, "CASE_SEMANTIC_MODEL_ID", None)
    db = _session()
    yield db
    db.close()


def create_case(db, **extra):
    return CaseService.create_case(db, case_number=None, occurred_time=datetime(2026, 10, 1),
        description="夜间井场发现车辆，未发现囤油设施。", case_type="涉油盗窃", location="测试井场", **extra)


def configure_model(db, monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_LOCAL_MODEL_HOSTS", "model.synthetic.invalid")
    model = AIModel(name="synthetic-only", provider="openai-compatible", model_name="synthetic",
        api_key="", role="moderator", is_active=True, is_default=True,
        config={"api_base": "http://model.synthetic.invalid/v1"})
    db.add(model)
    db.commit()
    return model


def response():
    return json.dumps({"summary": {"text": "车辆线索仍需核对。", "evidence_refs": [
        {"field": "description", "start": 0, "end": 8, "quote": "夜间井场发现车辆"}]},
        "scene_conditions": [], "inferences": [], "recommendations": [], "information_gaps": ["车辆去向未知"]}, ensure_ascii=False)


def test_same_revision_reuses_profile_and_preserves_manual_and_historical_json(session):
    case = create_case(session)
    case.features = {"tags_override": ["人工核实"], "intelligence": {"experience_card": {"manual_review_status": "confirmed"}},
                     "basic": {"summary": "历史摘要"}}
    session.commit()
    original = deepcopy(case.features)
    first = CasePreprocessService.preprocess_case(session, case.id, use_llm=False)
    second = CasePreprocessService.preprocess_case(session, case.id, use_llm=False)
    assert first["profile_binding"] == second["profile_binding"]
    assert session.query(CaseAnalysisProfile).count() == session.query(CaseRevision).count() == 1
    assert session.query(PreprocessJob).count() == 0
    assert case.features == original
    outcome = CasePreprocessService.preprocess_cases(session, only_missing=True, use_llm=False)
    assert outcome["processed"] == 0
    case.description += "新补充明确现场入口。"
    CasePipelineService.enqueue_case_change(session, case)
    session.commit()
    outcome = CasePreprocessService.preprocess_cases(session, only_missing=True, use_llm=False)
    assert outcome["success"] == 1 and session.query(CaseAnalysisProfile).count() == 2
    assert case.features == original


def test_old_json_does_not_count_as_processed_and_gets_do_not_write(session):
    case = create_case(session)
    case.features = {"basic": {"summary": "旧的无来源摘要"}}
    session.add(PreprocessJob(case_id=case.id, status="success"))
    session.commit()
    client = _client(session)
    before = (session.query(CaseRevision).count(), session.query(OutboxEvent).count())
    result = client.get(f"/api/cases/{case.id}/preprocess-result").json()
    assert result["status"] == "unavailable" and result["data"] is None
    assert result["legacy_features"] == case.features
    assert client.get("/api/cases/preprocess/profiles", params={"case_ids": case.id}).json()["items"][0]["status"] == "unavailable"
    status = queue_status(session)
    assert status["pending"] == 1 and status["success"] == 0 and status["legacy_history"]["count"] == 1
    assert before == (session.query(CaseRevision).count(), session.query(OutboxEvent).count())
    assert session.query(CaseAnalysisProfile).count() == 0
    assert CasePreprocessService.preprocess_cases(session, only_missing=True, use_llm=False)["success"] == 1


def test_queue_reads_actual_claimed_event_instead_of_stale_state_label(session):
    case = create_case(session)
    state = session.query(CasePipelineState).filter_by(case_id=case.id).one()
    event = session.get(OutboxEvent, state.event_id)
    event.status = "processing"
    session.commit()
    assert state.status == "pending"
    assert queue_status(session)["processing"] == 1 and queue_status(session)["pending"] == 0


def test_bound_supplement_is_idempotent_and_reading_never_calls_model(session, monkeypatch):
    case = create_case(session)
    configure_model(session, monkeypatch)
    calls = []
    def request(plan, prompt, **kwargs):
        calls.append(json.loads(prompt))
        return response()
    monkeypatch.setattr(supplements, "_request", request)
    first = CasePreprocessService.preprocess_case(session, case.id)
    frozen = deepcopy(session.query(CaseAnalysisProfile).one().payload)
    second = CasePreprocessService.preprocess_case(session, case.id)
    assert first["model_supplement"]["status"] == second["model_supplement"]["status"] == "ready"
    assert len(calls) == 1 and session.query(CasePreprocessSupplement).count() == 1
    row = session.query(CasePreprocessSupplement).one()
    assert row.source_revision_id == frozen["source_revision_id"]
    assert row.payload["content"]["summary"]["judgment_status"] == "model_candidate"
    assert session.query(CaseAnalysisProfile).one().payload == frozen and case.features is None
    assert _client(session).get(f"/api/cases/{case.id}/preprocess-result").json()["model_supplement"]["status"] == "ready"
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["invalid_json", "wrong_quote", "timeout"])
def test_model_failure_never_undoes_rule_profile(session, monkeypatch, kind):
    case = create_case(session)
    configure_model(session, monkeypatch)
    def request(*args, **kwargs):
        if kind == "timeout":
            raise TimeoutError("synthetic")
        return "not JSON" if kind == "invalid_json" else response().replace("夜间井场发现车辆", "没有依据的内容")
    monkeypatch.setattr(supplements, "_request", request)
    result = CasePreprocessService.preprocess_case(session, case.id)
    assert result["model_supplement"]["status"] == "unavailable"
    assert current_profile(session, case) and session.query(CasePreprocessSupplement).count() == 0
    assert queue_status(session)["success"] == 1


@pytest.mark.parametrize("change", ["source", "model", "revoke", "revoke_timeout"])
def test_late_model_response_cannot_publish_after_input_config_or_authority_change(session, monkeypatch, change):
    case = create_case(session)
    model = configure_model(session, monkeypatch)
    if change.startswith("revoke"):
        actor = User(username="synthetic-admin", display_name="管理员", password_hash="not-a-password", role="admin", is_active=True)
        session.add(actor)
        session.commit()
        session.info["principal_user_id"] = actor.id
    def request(*args, **kwargs):
        if change == "source":
            current = session.query(Case).filter_by(id=case.id).one()
            current.description = "后续修正：无车辆线索。"
            CasePipelineService.enqueue_case_change(session, current)
        elif change == "model":
            model.config = {**model.config, "revision": "changed"}
        else:
            actor.is_active = False
        session.commit()
        if change == "revoke_timeout":
            raise TimeoutError("synthetic")
        return response()
    monkeypatch.setattr(supplements, "_request", request)
    if change == "source":
        with pytest.raises(ValueError, match="pending_or_superseded"):
            CasePreprocessService.preprocess_case(session, case.id)
    elif change.startswith("revoke"):
        with pytest.raises(PermissionError, match="access_changed"):
            CasePreprocessService.preprocess_case(session, case.id)
        session.info["authorized_area_ids"] = None
    else:
        result = CasePreprocessService.preprocess_case(session, case.id)
        assert result["model_supplement"]["status"] == "superseded"
    assert session.query(CasePreprocessSupplement).count() == 0
    assert session.query(CaseAnalysisProfile).count() == 1


def test_hidden_area_has_no_profile_supplement_or_legacy_counter_leak(session, monkeypatch):
    area = OperationalArea(name="隐藏厂区", code="HIDDEN", status="active")
    session.add(area)
    session.commit()
    case = create_case(session, operational_area_id=area.id)
    configure_model(session, monkeypatch)
    monkeypatch.setattr(supplements, "_request", lambda *args, **kwargs: response())
    CasePreprocessService.preprocess_case(session, case.id)
    session.add(PreprocessJob(case_id=case.id, status="success"))
    session.commit()
    session.info["authorized_area_ids"] = ()
    client = _client(session)
    assert client.get(f"/api/cases/{case.id}/preprocess-result").status_code == 404
    assert client.get("/api/cases/preprocess/profiles", params={"case_ids": case.id}).json()["items"] == []
    assert queue_status(session)["success"] == queue_status(session)["legacy_history"]["count"] == 0
    assert session.query(CasePreprocessSupplement).count() == 0


def test_legacy_latest_profile_labels_pending_update_without_rewriting_or_recomputing(session):
    case = create_case(session)
    CasePreprocessService.preprocess_case(session, case.id, use_llm=False)
    app = FastAPI()
    app.include_router(case_pipeline.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    first = client.get(f"/api/cases/{case.id}/analysis-profile/latest").json()
    assert first["freshness"] == "current" and first["is_current"] is True
    case.description += "后补入口资料。"
    CasePipelineService.enqueue_case_change(session, case)
    session.commit()
    count = session.query(OutboxEvent).count()
    stale = client.get(f"/api/cases/{case.id}/analysis-profile/latest").json()
    assert stale["id"] == first["id"] and stale["source_revision_id"] == first["source_revision_id"]
    assert stale["freshness"] == "updating" and stale["is_current"] is False
    assert session.query(OutboxEvent).count() == count
    assert session.query(CaseAnalysisProfile).one().is_current is True  # Storage unchanged by GET.
