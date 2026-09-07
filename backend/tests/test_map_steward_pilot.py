from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.agent_runtime.service import AgentRunService
from app.agent_runtime.tools import asset_source_signature
from app.api import agent_runs, map_steward
from app.database import Base, get_db
from app.models.agent_run import AgentApproval, AgentArtifact
from app.models.jurisdiction import JurisdictionAsset
from app.models.user import User
from app.services.map_steward_service import MapStewardPilotService


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


def _add_asset(db: Session) -> JurisdictionAsset:
    asset = JurisdictionAsset(
        name=" 重点井-01 ",
        external_id="PILOT-WELL-01",
        asset_type="well",
        geometry_type="point",
        latitude=45.6,
        longitude=124.7,
        geometry={"type": "Point", "coordinates": [120.0, 40.0]},
        source="ledger",
        status="active",
        verified=False,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


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
    api.include_router(map_steward.router, prefix="/api/agent-map-steward")

    def override_get_db():
        yield db

    api.dependency_overrides[get_db] = override_get_db
    return TestClient(api)


def _enable_agent_assist(monkeypatch) -> None:
    monkeypatch.setattr(agent_runs.settings, "ENABLE_AGENT_LAB", True)
    monkeypatch.setattr(agent_runs.settings, "AGENT_MODE", "assist")
    monkeypatch.setattr(agent_runs.settings, "AGENT_MUTATIONS_ENABLED", True)
    monkeypatch.setattr(agent_runs.settings, "AGENT_MAP_PILOT_MAX_ASSETS", 100)
    monkeypatch.setattr(map_steward.settings, "ENABLE_AGENT_LAB", True)
    monkeypatch.setattr(map_steward.settings, "AGENT_MODE", "assist")
    monkeypatch.setattr(map_steward.settings, "AGENT_MUTATIONS_ENABLED", True)


def test_map_steward_control_defaults_fail_closed(pilot_db: Session):
    analyst = _add_user(pilot_db, "analyst", "analyst")

    status = MapStewardPilotService.build_status(
        pilot_db,
        principal_user_id=analyst.id,
        principal_role=analyst.role,
    )

    assert status["state"] == "disabled"
    assert status["enabled"] is False
    assert status["mutations_suspended"] is True
    assert "pilot_user_ids" not in status
    assert status["can_start"] is False
    assert status["can_apply_changes"] is False


def test_control_accepts_only_active_analysts_or_admins(pilot_db: Session):
    admin = _add_user(pilot_db, "admin", "admin")
    analyst = _add_user(pilot_db, "analyst", "analyst")
    viewer = _add_user(pilot_db, "viewer", "viewer")
    inactive = _add_user(pilot_db, "inactive", "analyst", active=False)

    with pytest.raises(ValueError, match="pilot_user_not_eligible"):
        MapStewardPilotService.set_control(
            pilot_db,
            enabled=True,
            mutations_suspended=False,
            pilot_user_ids=[viewer.id, inactive.id],
            updated_by=admin.id,
            reason="不合格试用名单",
        )

    control = MapStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        mutations_suspended=False,
        pilot_user_ids=[analyst.id, admin.id, analyst.id],
        updated_by=admin.id,
        reason="启动首轮地图数据管家试用",
    )

    assert control.enabled is True
    assert control.mutations_suspended is False
    assert control.pilot_user_ids == (analyst.id, admin.id)
    assert control.reason == "启动首轮地图数据管家试用"


def test_assist_mode_only_allows_bounded_map_runs_from_pilot_users(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    pilot = _add_user(pilot_db, "pilot", "analyst")
    outsider = _add_user(pilot_db, "outsider", "analyst")
    asset = _add_asset(pilot_db)
    MapStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        mutations_suspended=False,
        pilot_user_ids=[pilot.id],
        updated_by=pilot.id,
        reason="试用名单确认",
    )
    dispatched: list[str] = []
    monkeypatch.setattr(agent_runs, "dispatch_agent_run", lambda run_id: dispatched.append(run_id))

    outsider_response = _client(pilot_db, user_id=outsider.id, role="analyst").post(
        "/api/agent-runs",
        json={"task_type": "map_data_quality", "query": "地图质检", "asset_ids": [asset.id]},
    )
    wrong_task = _client(pilot_db, user_id=pilot.id, role="analyst").post(
        "/api/agent-runs",
        json={"task_type": "case_data_quality", "query": "案件质检", "case_ids": [1]},
    )
    unbounded = _client(pilot_db, user_id=pilot.id, role="analyst").post(
        "/api/agent-runs",
        json={"task_type": "map_data_quality", "query": "全库地图质检"},
    )
    mixed_scope = _client(pilot_db, user_id=pilot.id, role="analyst").post(
        "/api/agent-runs",
        json={
            "task_type": "map_data_quality",
            "query": "错误混入案件范围",
            "case_ids": [1],
            "asset_ids": [asset.id],
        },
    )
    allowed = _client(pilot_db, user_id=pilot.id, role="analyst").post(
        "/api/agent-runs",
        json={"task_type": "map_data_quality", "query": "检查所选重点井", "asset_ids": [asset.id]},
    )

    assert outsider_response.status_code == 403
    # v2.3 已开放独立的案件只读试用；此处没有合法案件范围，因此按范围校验拒绝。
    assert wrong_task.status_code == 422
    assert unbounded.status_code == 422
    assert mixed_scope.status_code == 422
    assert allowed.status_code == 202
    assert allowed.json()["created_by"] == pilot.id
    assert dispatched == [allowed.json()["id"]]


def test_assist_run_rejects_missing_map_assets(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    pilot = _add_user(pilot_db, "pilot", "analyst")
    asset = _add_asset(pilot_db)
    MapStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        mutations_suspended=False,
        pilot_user_ids=[pilot.id],
        updated_by=pilot.id,
        reason="试用名单确认",
    )
    dispatched: list[str] = []
    monkeypatch.setattr(agent_runs, "dispatch_agent_run", lambda run_id: dispatched.append(run_id))

    response = _client(pilot_db, user_id=pilot.id, role="analyst").post(
        "/api/agent-runs",
        json={
            "task_type": "map_data_quality",
            "query": "检查明确选择的地图资源",
            "asset_ids": [asset.id, 999999],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "所选地图资源不存在或已失效"
    assert dispatched == []


def test_suspended_control_blocks_approval_without_consuming_it(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    pilot = _add_user(pilot_db, "pilot", "analyst")
    asset = _add_asset(pilot_db)
    MapStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        mutations_suspended=True,
        pilot_user_ids=[pilot.id],
        updated_by=admin.id,
        reason="暂停正式写入",
    )
    run = AgentRunService.create_run(
        pilot_db,
        task_type="map_data_quality",
        query="地图质检",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=pilot.id,
    )
    run.status = "waiting_approval"
    artifact = AgentArtifact(
        run_id=run.id,
        artifact_type="candidate_patch",
        version=1,
        content={},
        evidence_refs=[f"asset:{asset.id}"],
        source_signature="artifact-source",
    )
    pilot_db.add(artifact)
    pilot_db.flush()
    approval = AgentApproval(
        run_id=run.id,
        artifact_id=artifact.id,
        action_type="asset_patch",
        target_type="jurisdiction_asset",
        target_id=asset.id,
        candidate_patch={"name": "重点井-01"},
        source_signature=asset_source_signature(asset),
        status="pending",
        requested_by=pilot.id,
        idempotency_key="pilot-suspended",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    pilot_db.add(approval)
    pilot_db.commit()

    response = _client(pilot_db, user_id=admin.id, role="admin").post(
        f"/api/agent-runs/{run.id}/approvals/{approval.id}",
        json={"decision": "approve"},
    )

    pilot_db.refresh(approval)
    pilot_db.refresh(asset)
    assert response.status_code == 409
    assert approval.status == "pending"
    assert asset.name == " 重点井-01 "


def test_one_click_suspend_cancels_map_runs_and_expires_pending_changes(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    pilot = _add_user(pilot_db, "pilot", "analyst")
    asset = _add_asset(pilot_db)
    MapStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        mutations_suspended=False,
        pilot_user_ids=[pilot.id],
        updated_by=admin.id,
        reason="开始试用",
    )
    active = AgentRunService.create_run(
        pilot_db,
        task_type="map_data_quality",
        query="活动任务",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=pilot.id,
    )
    active.status = "running"
    waiting = AgentRunService.create_run(
        pilot_db,
        task_type="map_data_quality",
        query="待审批任务",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=pilot.id,
    )
    waiting.status = "waiting_approval"
    artifact = AgentArtifact(
        run_id=waiting.id,
        artifact_type="candidate_patch",
        version=1,
        content={},
        evidence_refs=[f"asset:{asset.id}"],
        source_signature="artifact-source",
    )
    pilot_db.add(artifact)
    pilot_db.flush()
    approval = AgentApproval(
        run_id=waiting.id,
        artifact_id=artifact.id,
        action_type="asset_patch",
        target_type="jurisdiction_asset",
        target_id=asset.id,
        candidate_patch={"name": "重点井-01"},
        source_signature=asset_source_signature(asset),
        status="pending",
        requested_by=pilot.id,
        idempotency_key="pilot-stop",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    pilot_db.add(approval)
    pilot_db.commit()

    response = _client(pilot_db, user_id=admin.id, role="admin").post(
        "/api/agent-map-steward/suspend",
        json={"reason": "发现异常，立即回到稳定链路"},
    )

    pilot_db.refresh(approval)
    pilot_db.refresh(asset)
    active_after = AgentRunService.get_run(pilot_db, active.id)
    waiting_after = AgentRunService.get_run(pilot_db, waiting.id)
    assert response.status_code == 200
    assert response.json()["state"] == "disabled"
    assert active_after.status == "cancelled"
    assert waiting_after.status == "cancelled"
    assert approval.status == "expired"
    assert approval.execution_result["reason"] == "map_pilot_suspended"
    assert active_after.events[-1].event_type == "pilot_suspended"
    assert asset.name == " 重点井-01 "


def test_one_click_suspend_still_works_after_a_pilot_user_is_deactivated(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    pilot = _add_user(pilot_db, "pilot", "analyst")
    MapStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        mutations_suspended=False,
        pilot_user_ids=[pilot.id],
        updated_by=admin.id,
        reason="开始试用",
    )
    pilot.is_active = False
    pilot_db.commit()

    response = _client(pilot_db, user_id=admin.id, role="admin").post(
        "/api/agent-map-steward/suspend",
        json={"reason": "人员权限变化，立即停用"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "disabled"


def test_status_exposes_pilot_metrics_without_exposing_other_users_to_analysts(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    pilot = _add_user(pilot_db, "pilot", "analyst")
    _add_user(pilot_db, "other", "analyst")
    asset = _add_asset(pilot_db)
    MapStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        mutations_suspended=False,
        pilot_user_ids=[pilot.id],
        updated_by=admin.id,
        reason="指标试用",
    )
    run = AgentRunService.create_run(
        pilot_db,
        task_type="map_data_quality",
        query="完成任务",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=pilot.id,
    )
    run.status = "completed"
    run.completed_at = datetime.utcnow()
    pilot_db.add(AgentArtifact(
        run_id=run.id,
        artifact_type="analysis_report",
        version=1,
        content={},
        evidence_refs=[f"asset:{asset.id}"],
        source_signature="metrics-source",
    ))
    pilot_db.commit()

    response = _client(pilot_db, user_id=pilot.id, role="analyst").get(
        "/api/agent-map-steward/status"
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["state"] == "ready"
    assert payload["can_start"] is True
    assert payload["metrics"]["runs_total"] == 1
    assert payload["metrics"]["evidence_coverage_percent"] == 100
    assert "eligible_users" not in payload
    assert "pilot_user_ids" not in payload


def test_admin_status_includes_control_users_and_shadow_is_read_only(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    pilot = _add_user(pilot_db, "pilot", "analyst")
    MapStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        mutations_suspended=False,
        pilot_user_ids=[pilot.id],
        updated_by=admin.id,
        reason="管理员查看试用范围",
    )
    monkeypatch.setattr(map_steward.settings, "AGENT_MODE", "shadow")

    payload = _client(pilot_db, user_id=admin.id, role="admin").get(
        "/api/agent-map-steward/status"
    ).json()

    assert payload["state"] == "read_only"
    assert payload["environment_ready"] is False
    assert payload["pilot_user_ids"] == [pilot.id]
    assert [item["id"] for item in payload["eligible_users"]] == [admin.id, pilot.id]


def test_only_admin_can_update_pilot_control(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    analyst = _add_user(pilot_db, "analyst", "analyst")
    payload = {
        "enabled": True,
        "mutations_suspended": False,
        "pilot_user_ids": [analyst.id],
        "reason": "批准首轮指定人员试用",
    }

    denied = _client(pilot_db, user_id=analyst.id, role="analyst").put(
        "/api/agent-map-steward/control",
        json=payload,
    )
    accepted = _client(pilot_db, user_id=admin.id, role="admin").put(
        "/api/agent-map-steward/control",
        json=payload,
    )

    assert denied.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["state"] == "ready"
    assert accepted.json()["pilot_user_ids"] == [analyst.id]


def test_completed_approval_remains_idempotent_after_pilot_is_disabled(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    pilot = _add_user(pilot_db, "pilot", "analyst")
    asset = _add_asset(pilot_db)
    MapStewardPilotService.set_control(
        pilot_db,
        enabled=True,
        mutations_suspended=False,
        pilot_user_ids=[pilot.id],
        updated_by=admin.id,
        reason="批准地图候选测试",
    )
    run = AgentRunService.create_run(
        pilot_db,
        task_type="map_data_quality",
        query="地图质检",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=pilot.id,
    )
    run.status = "waiting_approval"
    artifact = AgentArtifact(
        run_id=run.id,
        artifact_type="candidate_patch",
        version=1,
        content={},
        evidence_refs=[f"asset:{asset.id}"],
        source_signature="artifact-source",
    )
    pilot_db.add(artifact)
    pilot_db.flush()
    approval = AgentApproval(
        run_id=run.id,
        artifact_id=artifact.id,
        action_type="asset_patch",
        target_type="jurisdiction_asset",
        target_id=asset.id,
        candidate_patch={"name": "重点井-01"},
        source_signature=asset_source_signature(asset),
        status="pending",
        requested_by=pilot.id,
        idempotency_key="pilot-repeat-after-disable",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    pilot_db.add(approval)
    pilot_db.commit()
    client = _client(pilot_db, user_id=admin.id, role="admin")

    first = client.post(
        f"/api/agent-runs/{run.id}/approvals/{approval.id}",
        json={"decision": "approve"},
    )
    MapStewardPilotService.set_control(
        pilot_db,
        enabled=False,
        mutations_suspended=True,
        pilot_user_ids=[pilot.id],
        updated_by=admin.id,
        reason="试用结束",
    )
    repeated = client.post(
        f"/api/agent-runs/{run.id}/approvals/{approval.id}",
        json={"decision": "approve"},
    )

    pilot_db.refresh(asset)
    assert first.status_code == 200
    assert first.json()["status"] == "executed"
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "executed"
    assert asset.name == "重点井-01"


def test_assist_replay_cannot_bypass_a_disabled_pilot(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    asset = _add_asset(pilot_db)
    run = AgentRunService.create_run(
        pilot_db,
        task_type="map_data_quality",
        query="地图质检",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=admin.id,
    )
    run.status = "completed"
    pilot_db.commit()
    MapStewardPilotService.set_control(
        pilot_db,
        enabled=False,
        mutations_suspended=True,
        pilot_user_ids=[admin.id],
        updated_by=admin.id,
        reason="试用尚未开放",
    )
    dispatched: list[str] = []
    monkeypatch.setattr(agent_runs, "dispatch_agent_run", lambda run_id: dispatched.append(run_id))

    response = _client(pilot_db, user_id=admin.id, role="admin").post(
        f"/api/agent-runs/{run.id}/replay"
    )

    assert response.status_code == 409
    assert dispatched == []
