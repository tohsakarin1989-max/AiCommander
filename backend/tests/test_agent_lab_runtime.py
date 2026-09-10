from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import agent_runs
from app.database import Base, get_db
from app.models.agent_run import AgentApproval, AgentArtifact, AgentEvent, AgentRun
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.models.user import User
from app.agent_runtime.redaction import AgentPayloadRedactor
from app.agent_runtime.runtime import AgentRunExecutor
from app.agent_runtime.service import AgentRunService
from app.agent_runtime.tools import AgentToolContext, AgentToolNotAllowed, AgentToolRegistry, asset_source_signature


@pytest.fixture
def agent_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = local()
    session.add_all(
        [
            User(
                id=user_id,
                username=f"agent-user-{user_id}",
                display_name=f"Agent User {user_id}",
                password_hash="test-only",
                role="admin" if user_id == 1 else "analyst",
            )
            for user_id in (1, 7, 9)
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_case(db: Session) -> Case:
    case = Case(
        case_number="AIC-2026-0001",
        occurred_time=datetime(2026, 8, 20, 2, 10),
        location="北区英平6002井东侧便道",
        latitude=45.612345,
        longitude=124.712345,
        case_type="盗油",
        description="张三驾驶黑E12345在井场附近活动，电话13800138000。",
        police_phone="13900139000",
        status="closed",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _add_asset(db: Session) -> JurisdictionAsset:
    asset = JurisdictionAsset(
        name=" 英平6002井 ",
        external_id="WELL-6002",
        asset_type="well",
        geometry_type="point",
        latitude=45.613,
        longitude=124.713,
        geometry={"type": "Point", "coordinates": [120.0, 40.0]},
        address="北区采油作业区3号路",
        source="ledger",
        status="active",
        verified=False,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def test_external_payload_redactor_removes_identifiers_and_exact_locations():
    payload = {
        "case_id": 12,
        "case_number": "AIC-2026-0001",
        "description": "张三驾驶黑E12345，电话13800138000，身份证220102199001011234。",
        "location": "北区英平6002井东侧便道",
        "latitude": 45.612345,
        "longitude": 124.712345,
        "occurred_time": "2026-08-20T02:10:00",
        "modus_operandi": "张三通过内部便道实施作案",
        "source_type": "王五电话举报",
        "source": "/srv/internal/重点井台账.xlsx",
        "attributes": {"owner_note": "联系人李四13900139000"},
        "tags": ["英平6002井", "内部专用"],
        "asset_id": 8,
        "name": "英平6002井",
        "distance_km": 0.83,
        "risk_score": 62,
        "evidence_refs": ["case:12", "asset:8"],
        "inferences": [
            "已记录作案方式：张三通过内部便道实施作案",
            "发现来源为王五电话举报",
            "资料来自/srv/internal/重点井台账.xlsx",
        ],
    }

    result = AgentPayloadRedactor().redact(payload)
    serialized = str(result.payload)

    for secret in (
        "AIC-2026-0001",
        "张三",
        "黑E12345",
        "13800138000",
        "220102199001011234",
        "北区英平6002井东侧便道",
        "英平6002井",
        "45.612345",
        "124.712345",
        "2026-08-20T02:10:00",
        "张三通过内部便道实施作案",
        "王五电话举报",
        "/srv/internal/重点井台账.xlsx",
        "联系人李四13900139000",
    ):
        assert secret not in serialized
    assert result.payload["case_id"] == "CASE-001"
    assert result.payload["asset_id"] == "ASSET-001"
    assert result.payload["distance_km"] == 0.83
    assert result.payload["risk_score"] == 62
    assert result.payload["evidence_refs"] == ["case:CASE-001", "asset:ASSET-001"]


def test_external_payload_redactor_aliases_all_tool_output_identifier_shapes():
    payload = {
        "tool_outputs": [
            {
                "case_ids": [12, 13],
                "asset_ids": [8, 9],
                "candidate_actions": [
                    {
                        "target_type": "jurisdiction_asset",
                        "target_id": 8,
                        "evidence_refs": ["map_asset:8@snapshot:3"],
                    }
                ],
                "facts": [
                    {
                        "case_id": 12,
                        "nearest": {
                            "production_target": {
                                "asset": {"id": 9, "asset_type": "well"}
                            }
                        },
                    }
                ],
                "inferences": [
                    "案件 12 与 case:13 仅为条件相近，设施 9 和 asset:8 待核验。"
                ],
            }
        ]
    }

    result = AgentPayloadRedactor().redact(payload)
    serialized = str(result.payload)

    assert "'case_ids': [12, 13]" not in serialized
    assert "'asset_ids': [8, 9]" not in serialized
    assert "'target_id': 8" not in serialized
    assert "'id': 9" not in serialized
    assert "案件 12" not in serialized
    assert "case:13" not in serialized
    assert "asset:8" not in serialized
    assert result.payload["tool_outputs"][0]["case_ids"] == ["CASE-001", "CASE-002"]
    assert result.payload["tool_outputs"][0]["asset_ids"] == ["ASSET-001", "ASSET-002"]


def test_case_quality_tool_is_read_only_and_has_evidence(agent_db: Session):
    case = _add_case(agent_db)
    original_quality = case.quality_score

    output = AgentToolRegistry().execute(
        "case_data_quality",
        agent_db,
        AgentToolContext(case_ids=[case.id], asset_ids=[], query="检查案件质量"),
    )

    agent_db.refresh(case)
    assert case.quality_score == original_quality
    assert output["tool"] == "case_data_quality"
    assert output["evidence_refs"] == [f"case:{case.id}"]
    assert output["facts"][0]["case_id"] == case.id
    assert output["boundary"]


def test_case_quality_tool_flags_probable_duplicates_as_review_only(agent_db: Session):
    first = _add_case(agent_db)
    second = Case(
        case_number="AIC-2026-0002",
        occurred_time=first.occurred_time + timedelta(minutes=20),
        location=first.location,
        latitude=first.latitude,
        longitude=first.longitude,
        case_type=first.case_type,
        description="同一地点的另一条脱敏测试记录",
        status="closed",
    )
    agent_db.add(second)
    agent_db.commit()

    output = AgentToolRegistry().execute(
        "case_data_quality",
        agent_db,
        AgentToolContext(case_ids=[first.id, second.id], asset_ids=[], query="检查重复记录"),
    )

    duplicate = [item for item in output["findings"] if item["severity"] == "duplicate_candidate"]
    assert duplicate
    assert duplicate[0]["case_ids"] == [first.id, second.id]
    assert "待人工核验" in duplicate[0]["message"]


def test_map_quality_tool_stages_deterministic_patch_without_mutating(agent_db: Session):
    asset = _add_asset(agent_db)
    outside_scope = JurisdictionAsset(
        name="范围外资源",
        external_id="OUTSIDE-SCOPE-ASSET",
        asset_type="well",
        geometry_type="point",
        latitude=None,
        longitude=None,
        source="ledger",
        status="active",
        verified=False,
    )
    agent_db.add(outside_scope)
    agent_db.commit()
    original_name = asset.name
    original_geometry = dict(asset.geometry)

    output = AgentToolRegistry().execute(
        "map_data_quality",
        agent_db,
        AgentToolContext(case_ids=[], asset_ids=[asset.id], query="检查井点数据"),
    )

    agent_db.refresh(asset)
    assert asset.name == original_name
    assert asset.geometry == original_geometry
    assert f"asset:{asset.id}" in output["evidence_refs"]
    assert output["aggregate"]["total_assets"] == 1
    assert output["aggregate"]["missing_coordinates"] == 0
    actions = output["candidate_actions"]
    assert any(item["patch"] == {"name": "英平6002井"} for item in actions)
    assert any(
        item["patch"].get("geometry", {}).get("coordinates") == [124.713, 45.613]
        for item in actions
    )


def test_map_quality_tool_reports_duplicate_points_without_merging(agent_db: Session):
    first = _add_asset(agent_db)
    second = JurisdictionAsset(
        name="英平6002井",
        external_id="WELL-6002-COPY",
        asset_type="well",
        geometry_type="point",
        latitude=first.latitude,
        longitude=first.longitude,
        geometry={"type": "Point", "coordinates": [first.longitude, first.latitude]},
        source="eval_copy",
        status="active",
        verified=False,
    )
    agent_db.add(second)
    agent_db.commit()

    output = AgentToolRegistry().execute(
        "map_data_quality",
        agent_db,
        AgentToolContext(case_ids=[], asset_ids=[first.id, second.id], query="检查重复井点"),
    )

    duplicates = [item for item in output["findings"] if item["severity"] == "duplicate_candidate"]
    assert duplicates
    assert duplicates[0]["asset_ids"] == [first.id, second.id]
    agent_db.refresh(first)
    agent_db.refresh(second)
    assert first.status == "active"
    assert second.status == "active"


def test_dual_domain_tool_uses_case_and_asset_evidence(agent_db: Session):
    case = _add_case(agent_db)
    asset = _add_asset(agent_db)
    outside_asset = JurisdictionAsset(
        name="范围外更近井",
        external_id="OUTSIDE-WELL",
        asset_type="well",
        geometry_type="point",
        latitude=case.latitude,
        longitude=case.longitude,
        geometry={"type": "Point", "coordinates": [case.longitude, case.latitude]},
        source="ledger",
        status="active",
        verified=True,
    )
    outside_case = Case(
        case_number="OUTSIDE-CASE",
        occurred_time=case.occurred_time + timedelta(days=1),
        location="范围外案件",
        latitude=case.latitude,
        longitude=case.longitude,
        case_type=case.case_type,
        description="范围外历史记录",
        status="closed",
    )
    agent_db.add_all([outside_asset, outside_case])
    agent_db.commit()

    output = AgentToolRegistry().execute(
        "dual_domain_analysis",
        agent_db,
        AgentToolContext(case_ids=[case.id], asset_ids=[asset.id], query="开展双域研判"),
    )

    assert f"case:{case.id}" in output["evidence_refs"]
    assert any(ref.startswith("asset:") for ref in output["evidence_refs"])
    assert output["facts"]
    assert "historical_frequency" in output["facts"][0]
    assert output["facts"][0]["historical_frequency"]["case_count"] == 0
    assert "modus_tags" in output["facts"][0]
    assert output["case_asset_links"]
    assert output["case_asset_links"][0]["case_id"] == case.id
    assert output["case_asset_links"][0]["asset_id"] == asset.id
    assert output["hotspots"]
    assert output["hotspots"][0]["asset_id"] == asset.id
    assert f"asset:{outside_asset.id}" not in output["evidence_refs"]
    assert f"case:{outside_case.id}" not in output["evidence_refs"]
    assert output["recommendations"]
    assert "不是犯罪预测" in " ".join(output["boundary"])


@pytest.mark.asyncio
async def test_assist_evidence_report_never_stages_formal_data_changes(agent_db: Session):
    case = _add_case(agent_db)
    asset = _add_asset(agent_db)
    run = AgentRunService.create_run(
        agent_db,
        task_type="evidence_report",
        query="形成双域综合证据报告",
        case_ids=[case.id],
        asset_ids=[asset.id],
        mode="assist",
        created_by=7,
    )

    completed = await AgentRunExecutor(narrator=None).execute(agent_db, run.id)

    assert completed.status == "completed"
    assert completed.approvals == []
    assert completed.result_summary["pending_approval_count"] == 0


def test_tool_registry_rejects_everything_outside_the_business_allowlist(agent_db: Session):
    with pytest.raises(AgentToolNotAllowed):
        AgentToolRegistry().execute(
            "shell",
            agent_db,
            AgentToolContext(case_ids=[], asset_ids=[], query="运行任意命令"),
        )


class _RecordingNarrator:
    provider_name = "openai_agents"
    model_name = "test-model"

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.payload = None

    async def summarize(self, query: str, payload: dict) -> dict:
        self.payload = payload
        if self.fail:
            raise RuntimeError("model unavailable")
        return {
            "result": "模型仅对脱敏特征进行了归纳。",
            "inferences": ["需要人工核验"],
            "recommendations": ["补齐缺失信息"],
            "information_gaps": [],
            "boundary": ["不得视为已确认事实"],
        }


def test_executor_allows_an_explicit_deterministic_narrator(monkeypatch):
    automatic = _RecordingNarrator()
    monkeypatch.setattr("app.agent_runtime.runtime.build_narrator", lambda: automatic)

    assert AgentRunExecutor().narrator is automatic
    assert AgentRunExecutor(narrator=None).narrator is None


@pytest.mark.asyncio
async def test_rule_only_execution_is_primary_mode_not_a_degraded_fallback(agent_db: Session):
    case = _add_case(agent_db)
    run = AgentRunService.create_run(
        agent_db,
        task_type="case_data_quality",
        query="仅使用内网规则检查案件质量",
        case_ids=[case.id],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )

    completed = await AgentRunExecutor(narrator=None).execute(agent_db, run.id)

    assert completed.status == "completed"
    assert completed.result_summary["mode"] == "deterministic"
    assert completed.model_provider is None
    assert completed.model_name is None


@pytest.mark.asyncio
async def test_cancelled_map_run_does_not_stage_late_candidate_changes(agent_db: Session):
    asset = _add_asset(agent_db)
    run = AgentRunService.create_run(
        agent_db,
        task_type="map_data_quality",
        query="地图质检",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=7,
    )

    class _CancellingRegistry:
        def execute(self, tool_name, db, context):
            AgentRunService.cancel_run(db, run.id, actor_user_id=1)
            return {
                "tool": tool_name,
                "facts": [],
                "findings": [],
                "inferences": [],
                "recommendations": [],
                "information_gaps": [],
                "evidence_refs": [f"asset:{asset.id}"],
                "boundary": [],
                "candidate_actions": [{
                    "action_type": "asset_patch",
                    "target_type": "jurisdiction_asset",
                    "target_id": asset.id,
                    "patch": {"name": "不应进入审批"},
                    "source_signature": asset_source_signature(asset),
                }],
            }

    cancelled = await AgentRunExecutor(
        narrator=None,
        tool_registry=_CancellingRegistry(),
    ).execute(agent_db, run.id)

    assert cancelled.status == "cancelled"
    assert cancelled.artifacts == []
    assert cancelled.approvals == []


@pytest.mark.asyncio
async def test_pilot_suspend_during_model_summary_wins_over_late_result(agent_db: Session):
    case = _add_case(agent_db)
    asset = _add_asset(agent_db)
    run = AgentRunService.create_run(
        agent_db,
        task_type="dual_domain_analysis",
        query="双域研判",
        case_ids=[case.id],
        asset_ids=[asset.id],
        mode="assist",
        created_by=7,
    )

    class _SuspendingNarrator(_RecordingNarrator):
        async def summarize(self, query: str, payload: dict) -> dict:
            AgentRunService.cancel_run(agent_db, run.id, actor_user_id=1)
            return await super().summarize(query, payload)

    cancelled = await AgentRunExecutor(narrator=_SuspendingNarrator()).execute(
        agent_db,
        run.id,
    )

    assert cancelled.status == "cancelled"
    assert not cancelled.result_summary
    assert not any(event.event_type == "run_completed" for event in cancelled.events)


@pytest.mark.asyncio
async def test_executor_persists_trace_artifacts_approvals_and_redacts_model_input(agent_db: Session):
    case = _add_case(agent_db)
    case.modus_operandi = "张三联系李四13900139000后从内部便道进入"
    case.source_type = "王五电话举报"
    agent_db.commit()
    asset = _add_asset(agent_db)
    run = AgentRunService.create_run(
        agent_db,
        task_type="evidence_report",
        query="检查英平6002井及案件AIC-2026-0001，联系人张三13800138000",
        case_ids=[case.id],
        asset_ids=[asset.id],
        mode="shadow",
        created_by=7,
    )
    narrator = _RecordingNarrator()

    completed = await AgentRunExecutor(narrator=narrator).execute(agent_db, run.id)

    assert completed.status == "completed"
    assert [event.sequence for event in completed.events] == list(range(1, len(completed.events) + 1))
    assert {event.event_type for event in completed.events} >= {
        "run_created",
        "planning_started",
        "tool_completed",
        "verification_started",
        "run_completed",
    }
    assert completed.artifacts
    assert completed.artifacts[0].evidence_refs == [f"case:{case.id}", f"asset:{asset.id}"]
    assert completed.approvals
    assert all(item.status == "pending" for item in completed.approvals)
    external_payload = str(narrator.payload)
    for secret in (
        "英平6002井",
        "AIC-2026-0001",
        "张三",
        "李四",
        "王五",
        "13800138000",
        "13900139000",
        "2026-08-20T02:10:00",
        "45.613",
        "124.713",
    ):
        assert secret not in external_payload


@pytest.mark.asyncio
async def test_executor_degrades_without_losing_rule_based_artifact(agent_db: Session):
    case = _add_case(agent_db)
    run = AgentRunService.create_run(
        agent_db,
        task_type="case_data_quality",
        query="案件质检",
        case_ids=[case.id],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )

    completed = await AgentRunExecutor(narrator=_RecordingNarrator(fail=True)).execute(agent_db, run.id)

    assert completed.status == "degraded"
    assert completed.artifacts
    assert completed.result_summary["mode"] == "deterministic_fallback"
    assert any(event.event_type == "model_degraded" for event in completed.events)


@pytest.mark.asyncio
async def test_redelivered_completed_run_is_idempotent(agent_db: Session):
    case = _add_case(agent_db)
    run = AgentRunService.create_run(
        agent_db,
        task_type="case_data_quality",
        query="案件质检",
        case_ids=[case.id],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )
    executor = AgentRunExecutor(narrator=None)
    completed = await executor.execute(agent_db, run.id)
    counts_before = (
        len(completed.events),
        len(completed.artifacts),
        len(completed.approvals),
        completed.attempt_count,
    )

    redelivered = await executor.execute(agent_db, run.id)

    assert redelivered.status == "completed"
    assert (
        len(redelivered.events),
        len(redelivered.artifacts),
        len(redelivered.approvals),
        redelivered.attempt_count,
    ) == counts_before


def test_global_run_data_version_changes_when_source_dataset_changes(agent_db: Session):
    _add_case(agent_db)
    before = AgentRunService.create_run(
        agent_db,
        task_type="case_data_quality",
        query="全库案件质检",
        case_ids=[],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )
    second = Case(
        case_number="AIC-2026-0002",
        occurred_time=datetime(2026, 8, 21, 3, 15),
        location="脱敏测试区域",
        status="pending",
    )
    agent_db.add(second)
    agent_db.commit()

    after = AgentRunService.create_run(
        agent_db,
        task_type="case_data_quality",
        query="全库案件质检",
        case_ids=[],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )

    assert before.data_version != after.data_version


def test_replay_rejects_changed_source_data_version(agent_db: Session):
    _add_case(agent_db)
    original = AgentRunService.create_run(
        agent_db,
        task_type="case_data_quality",
        query="全库案件质检",
        case_ids=[],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )
    agent_db.add(Case(
        case_number="AIC-2026-REPLAY-CHANGED",
        occurred_time=datetime(2026, 9, 2, 4, 0),
        location="脱敏测试区域",
        status="pending",
    ))
    agent_db.commit()

    with pytest.raises(ValueError, match="agent_replay_data_version_changed"):
        AgentRunService.replay_run(agent_db, original.id, created_by=1)


def test_execution_failure_is_recorded_for_retry_and_recovery(agent_db: Session):
    run = AgentRunService.create_run(
        agent_db,
        task_type="case_data_quality",
        query="案件质检",
        case_ids=[],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )

    failed = AgentRunService.mark_execution_failed(
        agent_db,
        run.id,
        reason="agent_timeout",
    )

    assert failed.status == "failed"
    assert failed.error_message == "agent_timeout"
    assert failed.events[-1].event_type == "run_failed"


def test_expired_approvals_are_closed_without_mutating_core_data(agent_db: Session):
    asset = _add_asset(agent_db)
    run = AgentRunService.create_run(
        agent_db,
        task_type="map_data_quality",
        query="地图质检",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=7,
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
    agent_db.add(artifact)
    agent_db.flush()
    approval = AgentApproval(
        run_id=run.id,
        artifact_id=artifact.id,
        action_type="asset_patch",
        target_type="jurisdiction_asset",
        target_id=asset.id,
        candidate_patch={"name": "不应执行"},
        source_signature=asset_source_signature(asset),
        status="pending",
        requested_by=7,
        idempotency_key="expired-approval",
        expires_at=datetime.utcnow() - timedelta(seconds=1),
    )
    agent_db.add(approval)
    agent_db.commit()

    expired_count = AgentRunService.expire_stale_approvals(agent_db)

    agent_db.refresh(asset)
    refreshed = AgentRunService.get_run(agent_db, run.id)
    assert expired_count == 1
    assert refreshed.status == "expired"
    assert refreshed.approvals[0].status == "expired"
    assert refreshed.approvals[0].execution_result["applied"] is False
    assert asset.name == " 英平6002井 "


def test_approval_is_idempotent_and_mutations_are_fail_closed(agent_db: Session):
    asset = _add_asset(agent_db)
    run = AgentRunService.create_run(
        agent_db,
        task_type="map_data_quality",
        query="地图质检",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=7,
    )
    artifact = AgentArtifact(
        run_id=run.id,
        artifact_type="candidate_patch",
        version=1,
        content={},
        evidence_refs=[f"asset:{asset.id}"],
        source_signature="source-v1",
    )
    agent_db.add(artifact)
    agent_db.flush()
    approval = AgentApproval(
        run_id=run.id,
        artifact_id=artifact.id,
        action_type="asset_patch",
        target_type="jurisdiction_asset",
        target_id=asset.id,
        candidate_patch={"name": "英平6002井"},
        source_signature="source-v1",
        status="pending",
        requested_by=7,
        idempotency_key="approval-once",
    )
    agent_db.add(approval)
    agent_db.commit()

    first = AgentRunService.review_approval(
        agent_db,
        approval_id=approval.id,
        decision="approve",
        decided_by=1,
        comment="同意修正空格",
        allow_mutations=False,
    )
    second = AgentRunService.review_approval(
        agent_db,
        approval_id=approval.id,
        decision="approve",
        decided_by=1,
        comment="重复提交",
        allow_mutations=False,
    )

    agent_db.refresh(asset)
    assert first.id == second.id
    assert first.status == "approved"
    assert first.execution_result["applied"] is False
    assert asset.name == " 英平6002井 "


def test_approved_map_patch_executes_once_when_all_guards_pass(agent_db: Session):
    asset = _add_asset(agent_db)
    run = AgentRunService.create_run(
        agent_db,
        task_type="map_data_quality",
        query="地图质检",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=7,
    )
    artifact = AgentArtifact(
        run_id=run.id,
        artifact_type="candidate_patch",
        version=1,
        content={},
        evidence_refs=[f"asset:{asset.id}"],
        source_signature="artifact-source",
    )
    agent_db.add(artifact)
    agent_db.flush()
    approval = AgentApproval(
        run_id=run.id,
        artifact_id=artifact.id,
        action_type="asset_patch",
        target_type="jurisdiction_asset",
        target_id=asset.id,
        candidate_patch={"name": "英平6002井"},
        source_signature=asset_source_signature(asset),
        status="pending",
        requested_by=7,
        idempotency_key="execute-once",
    )
    agent_db.add(approval)
    agent_db.commit()

    executed = AgentRunService.review_approval(
        agent_db,
        approval_id=approval.id,
        decision="approve",
        decided_by=1,
        comment="已核对原始台账",
        allow_mutations=True,
    )
    repeated = AgentRunService.review_approval(
        agent_db,
        approval_id=approval.id,
        decision="approve",
        decided_by=1,
        comment="重复请求",
        allow_mutations=True,
    )

    agent_db.refresh(asset)
    assert executed.status == "executed"
    assert repeated.status == "executed"
    assert asset.name == "英平6002井"
    assert executed.execution_result["fields"] == ["name"]


@pytest.mark.parametrize(
    ("candidate_patch", "expected_reason"),
    [
        ({"name": "任意改名"}, "candidate_name_outside_policy"),
        (
            {"geometry": {"type": "Point", "coordinates": [1.0, 2.0]}},
            "candidate_geometry_outside_policy",
        ),
    ],
)
def test_approval_rejects_candidate_values_outside_map_steward_policy(
    agent_db: Session,
    candidate_patch,
    expected_reason,
):
    asset = _add_asset(agent_db)
    original_name = asset.name
    original_geometry = dict(asset.geometry)
    run = AgentRunService.create_run(
        agent_db,
        task_type="map_data_quality",
        query="地图质检",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=7,
    )
    artifact = AgentArtifact(
        run_id=run.id,
        artifact_type="candidate_patch",
        version=1,
        content={},
        evidence_refs=[f"asset:{asset.id}"],
        source_signature="artifact-source",
    )
    agent_db.add(artifact)
    agent_db.flush()
    approval = AgentApproval(
        run_id=run.id,
        artifact_id=artifact.id,
        action_type="asset_patch",
        target_type="jurisdiction_asset",
        target_id=asset.id,
        candidate_patch=candidate_patch,
        source_signature=asset_source_signature(asset),
        status="pending",
        requested_by=7,
        idempotency_key=f"policy-{expected_reason}",
    )
    agent_db.add(approval)
    agent_db.commit()

    reviewed = AgentRunService.review_approval(
        agent_db,
        approval_id=approval.id,
        decision="approve",
        decided_by=1,
        comment="安全边界测试",
        allow_mutations=True,
    )

    agent_db.refresh(asset)
    assert reviewed.status == "approved"
    assert reviewed.execution_result["reason"] == expected_reason
    assert asset.name == original_name
    assert asset.geometry == original_geometry


def test_verified_assets_are_never_mutated_by_agent_approval(agent_db: Session):
    asset = _add_asset(agent_db)
    asset.verified = True
    agent_db.commit()
    run = AgentRunService.create_run(
        agent_db,
        task_type="map_data_quality",
        query="地图质检",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=7,
    )
    artifact = AgentArtifact(
        run_id=run.id,
        artifact_type="candidate_patch",
        version=1,
        content={},
        evidence_refs=[f"asset:{asset.id}"],
        source_signature="artifact-source",
    )
    agent_db.add(artifact)
    agent_db.flush()
    approval = AgentApproval(
        run_id=run.id,
        artifact_id=artifact.id,
        action_type="asset_patch",
        target_type="jurisdiction_asset",
        target_id=asset.id,
        candidate_patch={"name": "禁止改名"},
        source_signature=asset_source_signature(asset),
        status="pending",
        requested_by=7,
        idempotency_key="verified-protected",
    )
    agent_db.add(approval)
    agent_db.commit()

    reviewed = AgentRunService.review_approval(
        agent_db,
        approval_id=approval.id,
        decision="approve",
        decided_by=1,
        comment=None,
        allow_mutations=True,
    )

    agent_db.refresh(asset)
    assert reviewed.status == "approved"
    assert reviewed.execution_result["reason"] == "verified_asset_is_protected"
    assert asset.name == " 英平6002井 "


def _client(db: Session, *, role: str = "analyst") -> TestClient:
    api = FastAPI()

    @api.middleware("http")
    async def principal(request: Request, call_next):
        request.state.principal = SimpleNamespace(id=9, role=role, username="tester")
        return await call_next(request)

    api.include_router(agent_runs.router, prefix="/api/agent-runs")

    def override_get_db():
        yield db

    api.dependency_overrides[get_db] = override_get_db
    return TestClient(api)


def test_agent_dispatch_fails_fast_when_broker_is_unavailable(monkeypatch):
    from app.tasks import agent_tasks

    calls = []
    pings = []

    class _Redis:
        def ping(self):
            pings.append(True)

        def close(self):
            return None

    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *args, **kwargs: _Redis(),
    )
    monkeypatch.setattr(
        agent_tasks.execute_agent_run_task,
        "apply_async",
        lambda **kwargs: calls.append(kwargs),
    )

    agent_runs.dispatch_agent_run("run-fast-fail")

    assert pings == [True]
    assert calls == [{
        "args": ["run-fast-fail"],
        "queue": agent_runs.settings.AGENT_REDIS_QUEUE,
        "retry": False,
    }]


def test_agent_run_api_is_hidden_when_feature_is_disabled(agent_db: Session, monkeypatch):
    monkeypatch.setattr(agent_runs.settings, "ENABLE_AGENT_LAB", False)

    response = _client(agent_db).post(
        "/api/agent-runs",
        json={"task_type": "case_data_quality", "query": "质检"},
    )

    assert response.status_code == 404


def test_agent_run_api_creates_lists_and_exposes_polling_events(agent_db: Session, monkeypatch):
    monkeypatch.setattr(agent_runs.settings, "ENABLE_AGENT_LAB", True)
    monkeypatch.setattr(agent_runs.settings, "AGENT_MODE", "shadow")
    dispatched = []
    monkeypatch.setattr(agent_runs, "dispatch_agent_run", lambda run_id: dispatched.append(run_id))

    client = _client(agent_db)
    created = client.post(
        "/api/agent-runs",
        json={"task_type": "case_data_quality", "query": "质检", "case_ids": []},
    )

    assert created.status_code == 202
    run_id = created.json()["id"]
    assert dispatched == [run_id]
    assert client.get("/api/agent-runs").json()[0]["id"] == run_id
    assert client.get(f"/api/agent-runs/{run_id}").json()["events"][0]["event_type"] == "run_created"
    assert client.get(f"/api/agent-runs/{run_id}/events").json()[0]["sequence"] == 1
    run = AgentRunService.get_run(agent_db, run_id)
    run.status = "completed"
    agent_db.commit()
    streamed = client.get(f"/api/agent-runs/{run_id}/events?stream=true")
    assert "event: run_created" in streamed.text
    assert "event: stream_end" in streamed.text


def test_viewer_cannot_create_and_only_admin_can_replay(agent_db: Session, monkeypatch):
    monkeypatch.setattr(agent_runs.settings, "ENABLE_AGENT_LAB", True)
    monkeypatch.setattr(agent_runs.settings, "AGENT_MODE", "shadow")
    monkeypatch.setattr(agent_runs, "dispatch_agent_run", lambda run_id: None)

    denied = _client(agent_db, role="viewer").post(
        "/api/agent-runs",
        json={"task_type": "case_data_quality", "query": "质检"},
    )
    created = _client(agent_db, role="analyst").post(
        "/api/agent-runs",
        json={"task_type": "case_data_quality", "query": "质检"},
    )
    replay_denied = _client(agent_db, role="analyst").post(
        f"/api/agent-runs/{created.json()['id']}/replay"
    )

    assert denied.status_code == 403
    assert replay_denied.status_code == 403


def test_approval_id_must_belong_to_the_run_in_the_url(agent_db: Session, monkeypatch):
    monkeypatch.setattr(agent_runs.settings, "ENABLE_AGENT_LAB", True)
    monkeypatch.setattr(agent_runs.settings, "AGENT_MODE", "assist")
    monkeypatch.setattr(agent_runs.settings, "AGENT_MUTATIONS_ENABLED", True)
    monkeypatch.setattr(agent_runs, "dispatch_agent_run", lambda run_id: None)
    asset = _add_asset(agent_db)
    first = AgentRunService.create_run(
        agent_db,
        task_type="map_data_quality",
        query="first",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=9,
    )
    second = AgentRunService.create_run(
        agent_db,
        task_type="map_data_quality",
        query="second",
        case_ids=[],
        asset_ids=[asset.id],
        mode="assist",
        created_by=9,
    )
    artifact = AgentArtifact(
        run_id=second.id,
        artifact_type="candidate_patch",
        version=1,
        content={},
        evidence_refs=[f"asset:{asset.id}"],
        source_signature="artifact-source",
    )
    agent_db.add(artifact)
    agent_db.flush()
    approval = AgentApproval(
        run_id=second.id,
        artifact_id=artifact.id,
        action_type="asset_patch",
        target_type="jurisdiction_asset",
        target_id=asset.id,
        candidate_patch={"name": "不应被执行"},
        source_signature=asset_source_signature(asset),
        status="pending",
        requested_by=9,
        idempotency_key="wrong-run",
    )
    agent_db.add(approval)
    agent_db.commit()

    response = _client(agent_db, role="admin").post(
        f"/api/agent-runs/{first.id}/approvals/{approval.id}",
        json={"decision": "approve"},
    )

    agent_db.refresh(approval)
    agent_db.refresh(asset)
    assert response.status_code == 404
    assert approval.status == "pending"
    assert asset.name == " 英平6002井 "
