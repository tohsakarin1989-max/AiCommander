"""v1/v2 会议完整链路：仅替换模型传输层，不跳过真实会商和持久化。"""
import json
import re
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import conclusions, meeting_templates, meetings, reports
from app.ai.model_factory import ModelFactory
from app.config import settings
from app.database import Base, get_db
from app.models.ai_model import AIModel
from app.models.case import Case
from app.models.map_foundation import OperationalArea
from app.models.meeting import AnalysisResult, Meeting, MeetingConversation, Ranking
from app.models.report import Report
from app.services.conclusion_factory_service import ConclusionFactoryService
from app.services import meeting_service
from app.tasks import meeting_tasks


@pytest.fixture
def legacy_meeting(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add(OperationalArea(id=1, code="LEGACY-MEET", name="合成会议辖区"))
        db.add_all([
            AIModel(id=index, name=f"合成模型{index}", provider="openai", model_name="synthetic",
                    api_key="synthetic-no-network", role="moderator" if index == 1 else "analyst",
                    is_active=True, config={})
            for index in (1, 2, 3)
        ])
        db.flush()
        db.add(Case(id=1, operational_area_id=1, case_number="LEGACY-MEET-001",
                    occurred_time=datetime(2026, 9, 1, 2), location="合成井场",
                    description="已处置合成案件，井场发现油桶和软管，需复核现场照明条件。"))
        db.commit()

    state = {"failure": None, "calls": [], "progress": []}

    class OfflineModel:
        def __init__(self, model_id):
            self.model_id = model_id
            self.call_count = 0

        async def ainvoke(self, prompt):
            self.call_count += 1
            stage = "format" if self.model_id == 1 and self.call_count == 1 else (
                "final" if self.model_id == 1 else "analysis" if self.call_count == 1 else "ranking"
            )
            state["calls"].append((self.model_id, stage))
            if state["failure"] == stage:
                raise RuntimeError("synthetic_provider_unavailable")
            if state["failure"] == f"{stage}_json":
                return SimpleNamespace(content="synthetic invalid JSON")
            if state["failure"] == f"{stage}_empty_json":
                return SimpleNamespace(content="{}")
            if stage == "format":
                return SimpleNamespace(content="合成会议议程：现场事实、相似条件、证据缺口及人工复核。")
            if stage == "analysis":
                result = {"patterns": [{"type": "现场条件", "description": "井场照明需复核",
                                          "evidence": ["LEGACY-MEET-001"], "confidence": "medium"}],
                          "experience_summary": "合成案件条件复盘，不确认串案。"}
            elif stage == "ranking":
                anonymous_ids = re.findall(r'"_anonymous_id":\s*"(Response_\d+)"', prompt)
                assert len(anonymous_ids) == 1
                own_id = f"Response_{self.model_id - 1}"
                assert own_id not in anonymous_ids
                result = {"rankings": [{"anonymous_id": anonymous_ids[0], "rank": 1, "score": 8}],
                          "overall_comment": "有案件依据，仍需人工复核。"}
            else:
                result = {"summary": "合成会议综合报告：现场照明条件需人工复核。",
                          "consensus_points": ["仅依据已发生案件"], "recommendations": ["补齐现场照片"],
                          "next_steps": ["人工核验依据"]}
            return SimpleNamespace(content=json.dumps(result, ensure_ascii=False))

    async def capture_progress(*args, **kwargs):
        state["progress"].append((args, kwargs))

    def unavailable_queue(**kwargs):
        raise RuntimeError("synthetic_queue_unavailable")

    monkeypatch.setattr(ModelFactory, "create_llm", lambda self, model: OfflineModel(model.id))
    monkeypatch.setattr(meeting_service, "_default_progress_callback", capture_progress)
    monkeypatch.setattr(meeting_tasks.run_meeting_task, "delay", unavailable_queue)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    monkeypatch.setattr(settings, "ENABLE_LEGACY_EXTERNAL_GEO", False)
    app = FastAPI()
    for module, prefix in ((meetings, "meetings"), (meeting_templates, "meeting-templates"),
                           (conclusions, "conclusions"), (reports, "reports")):
        app.include_router(module.router, prefix=f"/api/{prefix}")

    def database():
        with factory() as db:
            db.info.update(authorized_area_ids=(1,), area_access_levels={1: "write"},
                           default_operational_area_id=1)
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, factory, state
    engine.dispose()


def create_meeting(client):
    response = client.post("/api/meetings/", json={
        "case_ids": [1], "moderator_model_id": 1, "analyst_model_ids": [2, 3],
    })
    assert response.status_code == 200, response.text
    return response.json()["meeting_id"]


def test_template_to_three_stage_meeting_report_and_manual_conclusion(legacy_meeting, monkeypatch):
    client, factory, state = legacy_meeting
    template = client.post("/api/meeting-templates/", json={
        "name": "合成历史会商模板", "moderator_model_id": 1, "analyst_model_ids": [2, 3],
        "config": {"focus": "现场条件复盘"},
    })
    assert template.status_code == 200
    template_id = template.json()["id"]
    used = client.post(f"/api/meeting-templates/{template_id}/use")
    assert used.status_code == 200
    assert client.get(f"/api/meeting-templates/{template_id}").json()["use_count"] == 1
    created = client.post("/api/meetings/", json={"case_ids": [1], **{
        field: used.json()[field] for field in ("moderator_model_id", "analyst_model_ids")
    }})
    assert created.status_code == 200, created.text
    meeting_id = created.json()["meeting_id"]
    with factory() as db:
        meeting = db.query(Meeting).filter_by(meeting_id=meeting_id).one()
        assert meeting.status == "completed"
        assert meeting.final_report_id is not None
        assert db.query(AnalysisResult).count() == 2
        assert db.query(Ranking).count() == 3
        assert db.query(MeetingConversation).count() == 6
    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["completed_at"]
    conversations = client.get(f"/api/meetings/{meeting_id}/conversations")
    assert conversations.status_code == 200, conversations.text
    assert [item["round_number"] for item in conversations.json()] == [0, 1, 1, 2, 2, 3]
    assert len(client.get(f"/api/meetings/{meeting_id}/analyses").json()) == 2
    assert len(client.get(f"/api/meetings/{meeting_id}/rankings").json()) == 3
    report = client.get(f"/api/meetings/{meeting_id}/report")
    assert report.status_code == 200
    assert "现场照明" in report.json()["content"]["summary"]
    assert client.get(f"/api/reports/{report.json()['id']}").status_code == 200
    monkeypatch.setattr(ConclusionFactoryService, "_get_llm", lambda db: None)
    conclusion = client.post(f"/api/conclusions/from-meeting/{meeting_id}")
    assert conclusion.status_code == 200, conclusion.text
    assert conclusion.json()["status"] == "needs_review"
    assert "现场照明" in conclusion.json()["summary"]
    approved = client.post(f"/api/conclusions/{conclusion.json()['id']}/review", json={"action": "approve"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "published"
    assert {stage for _, stage in state["calls"]} == {"format", "analysis", "ranking", "final"}
    assert len(state["progress"]) == 6
    assert client.delete(f"/api/meeting-templates/{template_id}").status_code == 200


def test_meeting_conversation_datetime_contract(legacy_meeting):
    client, _, _ = legacy_meeting
    meeting_id = create_meeting(client)
    response = client.get(f"/api/meetings/{meeting_id}/conversations")
    assert response.status_code == 200, response.text
    assert len(response.json()) == 6


@pytest.mark.parametrize("llm_mode", ["missing", "failed"])
def test_meeting_conclusion_fallback_accepts_structured_report(legacy_meeting, monkeypatch, llm_mode):
    client, _, _ = legacy_meeting
    meeting_id = create_meeting(client)

    class FailedModel:
        async def ainvoke(self, prompt):
            raise RuntimeError("synthetic_provider_unavailable")

    monkeypatch.setattr(ConclusionFactoryService, "_get_llm", lambda db: None if llm_mode == "missing" else FailedModel())
    response = client.post(f"/api/conclusions/from-meeting/{meeting_id}")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "needs_review"
    assert response.json()["summary"].startswith("合成会议综合报告")


@pytest.mark.parametrize("stage", ["format", "analysis", "ranking", "final", "analysis_json", "ranking_json", "final_json", "final_empty_json"])
def test_failed_meeting_stage_never_publishes_completed_report(legacy_meeting, stage):
    client, factory, state = legacy_meeting
    state["failure"] = stage
    meeting_id = create_meeting(client)
    with factory() as db:
        meeting = db.query(Meeting).filter_by(meeting_id=meeting_id).one()
        assert meeting.status == "failed"
        assert meeting.final_report_id is None
        assert db.query(Report).count() == 0
    assert client.get(f"/api/meetings/{meeting_id}/report").status_code == 404
    assert not any(args[4] == 100 for args, _ in state["progress"])


def test_final_transcript_commit_failure_rolls_back_report_and_completion(legacy_meeting, monkeypatch):
    client, factory, state = legacy_meeting
    commit = factory.class_.commit

    def fail_final_transcript(db):
        if any(isinstance(row, MeetingConversation) and row.round_number == 3 for row in db.new):
            raise RuntimeError("synthetic_final_transcript_commit_failure")
        return commit(db)

    monkeypatch.setattr(factory.class_, "commit", fail_final_transcript)
    meeting_id = create_meeting(client)
    with factory() as db:
        meeting = db.query(Meeting).filter_by(meeting_id=meeting_id).one()
        assert meeting.status == "failed"
        assert meeting.final_report_id is None and meeting.completed_at is None
        assert db.query(Report).count() == 0
        assert db.query(Ranking).filter_by(stage="final").count() == 0
    assert client.get(f"/api/meetings/{meeting_id}/report").status_code == 404
    assert not any(args[4] == 100 for args, _ in state["progress"])


@pytest.mark.parametrize("change", ["missing_moderator", "wrong_moderator", "inactive_moderator",
                                     "missing_analyst", "wrong_analyst", "inactive_analyst", "duplicate_analyst"])
def test_invalid_model_selection_is_rejected_before_meeting_creation(legacy_meeting, change):
    client, factory, state = legacy_meeting
    payload = {"case_ids": [1], "moderator_model_id": 1, "analyst_model_ids": [2, 3]}
    if change.startswith("inactive"):
        with factory() as db:
            db.get(AIModel, 1 if change.endswith("moderator") else 2).is_active = False
            db.commit()
    else:
        field, value = {
            "missing_moderator": ("moderator_model_id", 999),
            "wrong_moderator": ("moderator_model_id", 2),
            "missing_analyst": ("analyst_model_ids", [999]),
            "wrong_analyst": ("analyst_model_ids", [1]),
            "duplicate_analyst": ("analyst_model_ids", [2, 2]),
        }[change]
        payload[field] = value
    response = client.post("/api/meetings/", json=payload)
    assert response.status_code == 400, response.text
    with factory() as db:
        assert db.query(Meeting).count() == 0
    assert not state["calls"]


def test_analyst_can_read_safe_model_options_without_model_management_access(legacy_meeting):
    from app.api import auth, models
    from app.models.user import User
    from app.security import AuthMiddleware
    from app.services.auth_service import AuthService

    _, factory, _ = legacy_meeting
    with factory() as db:
        db.add(User(username="legacy_analyst", display_name="合成分析员", role="analyst",
                    password_hash=AuthService.hash_password("SyntheticPassword!2026")))
        db.get(AIModel, 3).is_active = False
        db.get(AIModel, 1).config = {"api_base": "https://secret.invalid", "secret": "synthetic-secret"}
        db.commit()
    secured = FastAPI()
    secured.include_router(auth.router, prefix="/api/auth")
    secured.include_router(meetings.router, prefix="/api/meetings")
    secured.include_router(models.router, prefix="/api/models")

    def database():
        with factory() as db:
            yield db

    secured.dependency_overrides[get_db] = database
    secured.add_middleware(AuthMiddleware, session_factory=factory, auth_required=True,
                           bootstrap_token="synthetic-bootstrap", secure_cookie=False,
                           allowed_origins=("http://testserver",))
    with TestClient(secured) as client:
        assert client.get("/api/meetings/model-options").status_code == 401
        assert client.post("/api/auth/login", json={
            "username": "legacy_analyst", "password": "SyntheticPassword!2026",
        }).status_code == 200
        assert client.get("/api/models/").status_code == 403
        response = client.get("/api/meetings/model-options")
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()] == [1, 2]
        assert all(set(item) == {"id", "name", "role", "is_active"} for item in response.json())
        assert "synthetic-secret" not in response.text
        assert "secret.invalid" not in response.text


def test_model_edit_with_blank_key_keeps_encrypted_credential(legacy_meeting):
    from app.services.ai_model_service import AIModelService

    _, factory, _ = legacy_meeting
    with factory() as db:
        model = AIModelService.create_model(db, name="合成加密模型", provider="openai",
                                            model_name="synthetic", api_key="synthetic-original",
                                            role="analyst")
        encrypted_key = model.api_key
        updated = AIModelService.update_model(db, model.id, name="合成已编辑模型", api_key="")
        assert updated.name == "合成已编辑模型"
        assert updated.api_key == encrypted_key
        assert AIModelService.get_decrypted_api_key(updated) == "synthetic-original"
        replaced = AIModelService.update_model(db, model.id, api_key="synthetic-replacement")
        assert replaced.api_key != "synthetic-replacement"
        assert AIModelService.get_decrypted_api_key(replaced) == "synthetic-replacement"
