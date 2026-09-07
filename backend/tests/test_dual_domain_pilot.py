from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import agent_runs, dual_domain_pilot
from app.database import Base, get_db
from app.models.agent_run import AgentArtifact, AgentRun
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.models.user import User
from app.services.dual_domain_pilot_service import DualDomainPilotService


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


def _add_case(db: Session, number: str = "CASE-DUAL-001") -> Case:
    case = Case(
        case_number=number,
        occurred_time=datetime(2026, 9, 1, 1, 20),
        location="脱敏测试地点",
        latitude=45.6,
        longitude=124.7,
        case_type="涉油盗窃",
        description="夜间活动，具体事实待人工核验。",
        status="closed",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _add_asset(db: Session, *, status: str = "active") -> JurisdictionAsset:
    asset = JurisdictionAsset(
        name="脱敏重点井",
        external_id=f"DUAL-WELL-{status}",
        asset_type="well",
        geometry_type="point",
        latitude=45.601,
        longitude=124.701,
        geometry={"type": "Point", "coordinates": [124.701, 45.601]},
        source="ledger",
        status=status,
        verified=True,
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
    api.include_router(dual_domain_pilot.router, prefix="/api/agent-dual-domain")

    def override_get_db():
        yield db

    api.dependency_overrides[get_db] = override_get_db
    return TestClient(api)


def _enable_agent_assist(monkeypatch) -> None:
    for module in (agent_runs, dual_domain_pilot):
        monkeypatch.setattr(module.settings, "ENABLE_AGENT_LAB", True)
        monkeypatch.setattr(module.settings, "AGENT_MODE", "assist")
    monkeypatch.setattr(agent_runs.settings, "AGENT_DUAL_DOMAIN_PILOT_MAX_CASES", 10)
    monkeypatch.setattr(agent_runs.settings, "AGENT_DUAL_DOMAIN_PILOT_MAX_ASSETS", 100)


def test_dual_domain_defaults_fail_closed_and_remain_read_only(pilot_db: Session):
    analyst = _add_user(pilot_db, "analyst", "analyst")

    status = DualDomainPilotService.build_status(
        pilot_db,
        principal_user_id=analyst.id,
        principal_role=analyst.role,
    )

    assert status["state"] == "disabled"
    assert status["enabled"] is False
    assert status["read_only"] is True
    assert status["can_start"] is False
    assert status["can_apply_changes"] is False
    assert "pilot_user_ids" not in status


def test_dual_domain_control_accepts_only_active_analysts_or_admins(pilot_db: Session):
    admin = _add_user(pilot_db, "admin", "admin")
    analyst = _add_user(pilot_db, "analyst", "analyst")
    viewer = _add_user(pilot_db, "viewer", "viewer")

    with pytest.raises(ValueError, match="pilot_user_not_eligible"):
        DualDomainPilotService.set_control(
            pilot_db,
            enabled=True,
            pilot_user_ids=[viewer.id],
            updated_by=admin.id,
            reason="不合格试用名单",
        )

    control = DualDomainPilotService.set_control(
        pilot_db,
        enabled=True,
        pilot_user_ids=[analyst.id, admin.id, analyst.id],
        updated_by=admin.id,
        reason="启动双域只读研判试用",
    )

    assert control.enabled is True
    assert control.pilot_user_ids == (analyst.id, admin.id)


@pytest.mark.parametrize("task_type", ["dual_domain_analysis", "evidence_report"])
def test_assist_mode_requires_named_user_and_explicit_bounded_dual_scope(
    pilot_db: Session,
    monkeypatch,
    task_type: str,
):
    _enable_agent_assist(monkeypatch)
    pilot = _add_user(pilot_db, "pilot", "analyst")
    outsider = _add_user(pilot_db, "outsider", "analyst")
    case = _add_case(pilot_db)
    asset = _add_asset(pilot_db)
    second_asset = _add_asset(pilot_db)
    inactive_asset = _add_asset(pilot_db, status="inactive")
    second_case = _add_case(pilot_db, "CASE-DUAL-002")
    DualDomainPilotService.set_control(
        pilot_db,
        enabled=True,
        pilot_user_ids=[pilot.id],
        updated_by=pilot.id,
        reason="试用范围确认",
    )
    dispatched: list[str] = []
    monkeypatch.setattr(agent_runs, "dispatch_agent_run", lambda run_id: dispatched.append(run_id))

    endpoint = "/api/agent-runs"
    base = {"task_type": task_type, "query": "开展所选范围的双域研判"}
    client = _client(pilot_db, user_id=pilot.id, role="analyst")
    outsider_response = _client(pilot_db, user_id=outsider.id, role="analyst").post(
        endpoint,
        json={**base, "case_ids": [case.id], "asset_ids": [asset.id]},
    )
    missing_cases = client.post(endpoint, json={**base, "asset_ids": [asset.id]})
    missing_assets = client.post(endpoint, json={**base, "case_ids": [case.id]})
    stale_asset = client.post(
        endpoint,
        json={**base, "case_ids": [case.id], "asset_ids": [inactive_asset.id]},
    )
    missing_record = client.post(
        endpoint,
        json={**base, "case_ids": [case.id, 999999], "asset_ids": [asset.id]},
    )
    monkeypatch.setattr(agent_runs.settings, "AGENT_DUAL_DOMAIN_PILOT_MAX_CASES", 1)
    too_many_cases = client.post(
        endpoint,
        json={**base, "case_ids": [case.id, second_case.id], "asset_ids": [asset.id]},
    )
    monkeypatch.setattr(agent_runs.settings, "AGENT_DUAL_DOMAIN_PILOT_MAX_ASSETS", 1)
    too_many_assets = client.post(
        endpoint,
        json={**base, "case_ids": [case.id], "asset_ids": [asset.id, second_asset.id]},
    )
    allowed = client.post(
        endpoint,
        json={**base, "case_ids": [case.id], "asset_ids": [asset.id]},
    )

    assert outsider_response.status_code == 403
    assert missing_cases.status_code == 422
    assert missing_assets.status_code == 422
    assert stale_asset.status_code == 422
    assert missing_record.status_code == 422
    assert too_many_cases.status_code == 422
    assert too_many_assets.status_code == 422
    assert allowed.status_code == 202
    assert allowed.json()["case_ids"] == [case.id]
    assert allowed.json()["asset_ids"] == [asset.id]
    assert dispatched == [allowed.json()["id"]]


def test_dual_domain_api_is_admin_controlled_and_suspend_cancels_both_task_types(
    pilot_db: Session,
    monkeypatch,
):
    _enable_agent_assist(monkeypatch)
    admin = _add_user(pilot_db, "admin", "admin")
    analyst = _add_user(pilot_db, "analyst", "analyst")
    client = _client(pilot_db, user_id=admin.id, role="admin")

    enabled = client.put(
        "/api/agent-dual-domain/control",
        json={
            "enabled": True,
            "pilot_user_ids": [admin.id, analyst.id],
            "reason": "开启双域只读试用",
        },
    )
    assert enabled.status_code == 200
    assert enabled.json()["state"] == "ready"
    assert enabled.json()["can_apply_changes"] is False

    runs = [
        AgentRun(
            id=f"dual-active-{index}",
            task_type=task_type,
            query="双域研判",
            case_ids=[],
            asset_ids=[],
            mode="assist",
            status="running",
            data_version=str(index) * 64,
            input_payload={},
            result_summary={},
            runtime_state={},
        )
        for index, task_type in enumerate(
            ["dual_domain_analysis", "evidence_report", "case_data_quality"],
            start=1,
        )
    ]
    pilot_db.add_all(runs)
    pilot_db.commit()

    suspended = client.post(
        "/api/agent-dual-domain/suspend",
        json={"reason": "双域演练结束"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["state"] == "disabled"
    for run in runs:
        pilot_db.refresh(run)
    assert runs[0].status == "cancelled"
    assert runs[1].status == "cancelled"
    assert runs[2].status == "running"

    analyst_control = _client(pilot_db, user_id=analyst.id, role="analyst").put(
        "/api/agent-dual-domain/control",
        json={
            "enabled": True,
            "pilot_user_ids": [analyst.id],
            "reason": "越权开启",
        },
    )
    assert analyst_control.status_code == 403


def test_dual_domain_metrics_count_explicit_scope_and_evidence(pilot_db: Session):
    run = AgentRun(
        id="dual-completed",
        task_type="dual_domain_analysis",
        query="双域研判",
        case_ids=[1, 2],
        asset_ids=[11, 12, 13],
        mode="assist",
        status="completed",
        data_version="a" * 64,
        input_payload={},
        result_summary={},
        runtime_state={},
    )
    artifact = AgentArtifact(
        id="dual-artifact",
        run_id=run.id,
        artifact_type="analysis_report",
        version=1,
        content={},
        evidence_refs=["case:1", "asset:11"],
        source_signature="b" * 64,
    )
    pilot_db.add_all([run, artifact])
    pilot_db.commit()

    metrics = DualDomainPilotService.metrics(pilot_db)

    assert metrics["runs_total"] == 1
    assert metrics["analyzed_case_count"] == 2
    assert metrics["analyzed_asset_count"] == 3
    assert metrics["evidence_coverage_percent"] == 100
