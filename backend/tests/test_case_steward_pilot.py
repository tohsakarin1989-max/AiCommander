from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import agent_runs, case_steward
from app.database import Base, get_db
from app.models.agent_run import AgentArtifact, AgentRun
from app.models.case import Case
from app.models.user import User
from app.services.case_steward_service import CaseStewardPilotService


@pytest.fixture
def pilot_db() -> Session:
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
        engine.dispose()


def _add_user(db: Session, username: str, role: str, *, active: bool = True) -> User:
    user = User(
        username=username,
        display_name=username,
        password_hash="test-hash",
        role=role,
        is_active=active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _add_case(db: Session, number: str = "CASE-PILOT-001") -> Case:
    case = Case(
        case_number=number,
        occurred_time=datetime(2026, 9, 1, 1, 20),
        location="重点井周边便道",
        case_type="涉油盗窃",
        description="夜间发现涉案车辆和油桶，具体坐标及处置材料待人工核验。",
        status="pending",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _client(db: Session, *, user_id: int, role: str) -> TestClient:
    api = FastAPI()

    @api.middleware("http")
    async def principal(request: Request, call_next):
        request.state.principal = SimpleNamespace(
            user_id=user_id,
            role=role,
            username=f"user-{user_id}",
        )
        return await call_next(request)

    api.include_router(agent_runs.router, prefix="/api/agent-runs")
    api.include_router(case_steward.router, prefix="/api/agent-case-steward")

    def override_get_db():
        yield db

    api.dependency_overrides[get_db] = override_get_db
    return TestClient(api)


def _enable_agent_assist(monkeypatch) -> None:
    for module in (agent_runs, case_steward):
        monkeypatch.setattr(module.settings, "ENABLE_AGENT_LAB", True)
        monkeypatch.setattr(module.settings, "AGENT_MODE", "assist")
    monkeypatch.setattr(agent_runs.settings, "AGENT_MUTATIONS_ENABLED", True)
    monkeypatch.setattr(agent_runs.settings, "AGENT_CASE_PILOT_MAX_CASES", 30)


def test_case_steward_defaults_fail_closed_and_remain_read_only(pilot_db: Session):
    analyst = _add_user(pilot_db, "analyst", "analyst")

    status = CaseStewardPilotService.build_status(
        pilot_db,
        principal_user_id=analyst.id,
        principal_role=analyst.role,
    )

    assert status["state"] == "disabled"
    assert status["enabled"] is False
    assert status["can_start"] is False
    assert status["can_apply_changes"] is False
    assert status["read_only"] is True
    assert "pilot_user_ids" not in status


def test_case_steward_control_accepts_only_active_analysts_or_admins(pilot_db: Session):
    admin = _add_user(pilot_db, "admin", "admin")
    analyst = _add_user(pilot_db, "analyst", "analyst")
    viewer = _add_user(pilot_db, "viewer", "viewer")

    with pytest.raises(ValueError, match="pilot_user_not_eligible"):
        CaseStewardPilotService.set_control(
            pilot_db,
            enabled=True,
            pilot_user_ids=[viewer.id],
            updated_by=admin.id,
            reason="不合格试用名单",
        )

    control = CaseStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        pilot_user_ids=[analyst.id, admin.id, analyst.id],
        updated_by=admin.id,
        reason="启动案件数据管家试用",
    )

    assert control.enabled is True
    assert control.pilot_user_ids == (analyst.id, admin.id)
    assert control.reason == "启动案件数据管家试用"


def test_assist_mode_allows_only_bounded_explicit_case_scope_for_pilot_user(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    pilot = _add_user(pilot_db, "pilot", "analyst")
    outsider = _add_user(pilot_db, "outsider", "analyst")
    case = _add_case(pilot_db)
    CaseStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        pilot_user_ids=[pilot.id],
        updated_by=pilot.id,
        reason="试用名单确认",
    )
    dispatched: list[str] = []
    monkeypatch.setattr(agent_runs, "dispatch_agent_run", lambda run_id: dispatched.append(run_id))

    outsider_response = _client(pilot_db, user_id=outsider.id, role="analyst").post(
        "/api/agent-runs",
        json={"task_type": "case_data_quality", "query": "案件质检", "case_ids": [case.id]},
    )
    unbounded = _client(pilot_db, user_id=pilot.id, role="analyst").post(
        "/api/agent-runs",
        json={"task_type": "case_data_quality", "query": "全库案件质检"},
    )
    mixed_scope = _client(pilot_db, user_id=pilot.id, role="analyst").post(
        "/api/agent-runs",
        json={
            "task_type": "case_data_quality",
            "query": "错误混入地图范围",
            "case_ids": [case.id],
            "asset_ids": [1],
        },
    )
    missing_case = _client(pilot_db, user_id=pilot.id, role="analyst").post(
        "/api/agent-runs",
        json={"task_type": "case_data_quality", "query": "不存在案件", "case_ids": [999999]},
    )
    allowed = _client(pilot_db, user_id=pilot.id, role="analyst").post(
        "/api/agent-runs",
        json={"task_type": "case_data_quality", "query": "检查所选案件", "case_ids": [case.id]},
    )

    assert outsider_response.status_code == 403
    assert unbounded.status_code == 422
    assert mixed_scope.status_code == 422
    assert missing_case.status_code == 422
    assert allowed.status_code == 202
    assert allowed.json()["case_ids"] == [case.id]
    assert allowed.json()["asset_ids"] == []
    assert dispatched == [allowed.json()["id"]]


def test_case_steward_api_is_admin_controlled_and_suspend_cancels_active_runs(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    analyst = _add_user(pilot_db, "analyst", "analyst")
    client = _client(pilot_db, user_id=admin.id, role="admin")

    enabled = client.put(
        "/api/agent-case-steward/control",
        json={
            "enabled": True,
            "pilot_user_ids": [admin.id, analyst.id],
            "reason": "开启案件只读试用",
        },
    )
    assert enabled.status_code == 200
    assert enabled.json()["state"] == "ready"
    assert enabled.json()["can_apply_changes"] is False

    run = AgentRun(
        id="case-run-active",
        task_type="case_data_quality",
        query="案件质检",
        case_ids=[],
        asset_ids=[],
        mode="assist",
        status="running",
        data_version="a" * 64,
        input_payload={},
        result_summary={},
        runtime_state={},
    )
    pilot_db.add(run)
    pilot_db.commit()

    suspended = client.post(
        "/api/agent-case-steward/suspend",
        json={"reason": "试用窗口结束"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["state"] == "disabled"
    pilot_db.refresh(run)
    assert run.status == "cancelled"

    analyst_control = _client(pilot_db, user_id=analyst.id, role="analyst").put(
        "/api/agent-case-steward/control",
        json={
            "enabled": True,
            "pilot_user_ids": [analyst.id],
            "reason": "越权开启",
        },
    )
    assert analyst_control.status_code == 403


def test_case_run_can_never_apply_candidate_changes(pilot_db: Session, monkeypatch):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    case = _add_case(pilot_db)
    CaseStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        pilot_user_ids=[admin.id],
        updated_by=admin.id,
        reason="只读案件试用",
    )
    run = AgentRun(
        id="case-run-approval",
        task_type="case_data_quality",
        query="案件质检",
        case_ids=[case.id],
        asset_ids=[],
        mode="assist",
        status="waiting_approval",
        data_version="b" * 64,
        input_payload={},
        result_summary={},
        runtime_state={},
        created_by=admin.id,
    )
    pilot_db.add(run)
    pilot_db.commit()

    from app.models.agent_run import AgentApproval

    artifact = AgentArtifact(
        id="case-artifact",
        run_id=run.id,
        artifact_type="case_quality_report",
        content={},
        evidence_refs=[f"case:{case.id}"],
        source_signature="test",
    )
    pilot_db.add(artifact)
    pilot_db.commit()

    approval = AgentApproval(
        id="case-approval",
        run_id=run.id,
        artifact_id=artifact.id,
        action_type="case_patch",
        target_type="case",
        target_id=case.id,
        candidate_patch={"location": "禁止自动修改"},
        source_signature="test",
        status="pending",
        idempotency_key="case-approval-idempotency",
    )
    pilot_db.add(approval)
    pilot_db.commit()

    response = _client(pilot_db, user_id=admin.id, role="admin").post(
        f"/api/agent-runs/{run.id}/approvals/{approval.id}",
        json={"decision": "approve"},
    )

    assert response.status_code == 403
    pilot_db.refresh(approval)
    pilot_db.refresh(case)
    assert approval.status == "pending"
    assert case.location == "重点井周边便道"


def test_case_assist_replay_rechecks_pilot_and_source_scope(pilot_db: Session, monkeypatch):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    case = _add_case(pilot_db)
    CaseStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        pilot_user_ids=[admin.id],
        updated_by=admin.id,
        reason="允许案件任务重放",
    )
    dispatched: list[str] = []
    monkeypatch.setattr(agent_runs, "dispatch_agent_run", lambda run_id: dispatched.append(run_id))
    client = _client(pilot_db, user_id=admin.id, role="admin")

    created = client.post(
        "/api/agent-runs",
        json={"task_type": "case_data_quality", "query": "案件质检", "case_ids": [case.id]},
    )
    replayed = client.post(f"/api/agent-runs/{created.json()['id']}/replay")

    assert created.status_code == 202
    assert replayed.status_code == 202
    assert replayed.json()["replay_of_id"] == created.json()["id"]

    CaseStewardPilotService.set_control(
        pilot_db,
        enabled=False,
        pilot_user_ids=[admin.id],
        updated_by=admin.id,
        reason="结束案件试用",
    )
    blocked = client.post(f"/api/agent-runs/{created.json()['id']}/replay")

    assert blocked.status_code == 409
    assert dispatched == [created.json()["id"], replayed.json()["id"]]
