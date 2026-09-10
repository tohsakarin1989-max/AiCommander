from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.agent_runtime.providers import (
    AgentNarrationOutcome,
    AgentNarrationUsage,
    ModelRegistryNarrator,
    build_narrator,
)
from app.agent_runtime.runtime import AgentRunExecutor
from app.agent_runtime.service import AgentRunService
from app.api import agent_runs
from app.database import Base, get_db
from app.models.agent_run import AgentUsageRecord
from app.models.ai_model import AIModel
from app.models.case import Case
from app.models.user import User
from app.services.agent_observability_service import AgentObservabilityService


@pytest.fixture
def observability_db() -> Session:
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
                id=7,
                username="observer-7",
                display_name="Observer 7",
                password_hash="test-only",
                role="analyst",
            ),
            User(
                id=9,
                username="observer-9",
                display_name="Observer 9",
                password_hash="test-only",
                role="analyst",
            ),
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
        case_number="OBS-2026-0001",
        occurred_time=datetime(2026, 9, 1, 2, 30),
        location="脱敏测试区域",
        latitude=46.6,
        longitude=125.1,
        case_type="盗油",
        status="closed",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


class _MeteredNarrator:
    provider_name = "openai-compatible"
    model_name = "deepseek-chat"
    input_cost_per_million_usd = 2.0
    output_cost_per_million_usd = 8.0

    async def summarize(self, query: str, payload: dict) -> AgentNarrationOutcome:
        return AgentNarrationOutcome(
            content={
                "result": "模型仅整理脱敏事实。",
                "inferences": [],
                "recommendations": [],
                "information_gaps": [],
                "boundary": ["不得视为已确认事实"],
            },
            usage=AgentNarrationUsage(
                request_count=1,
                input_tokens=1200,
                output_tokens=300,
            ),
        )


@pytest.mark.asyncio
async def test_executor_persists_model_usage_latency_and_estimated_cost(
    observability_db: Session,
):
    case = _add_case(observability_db)
    run = AgentRunService.create_run(
        observability_db,
        task_type="case_data_quality",
        query="检查案件质量",
        case_ids=[case.id],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )

    completed = await AgentRunExecutor(narrator=_MeteredNarrator()).execute(
        observability_db,
        run.id,
    )

    assert completed.status == "completed"
    assert completed.model_provider == "openai-compatible"
    assert completed.model_name == "deepseek-chat"
    assert len(completed.usage_records) == 1
    usage = completed.usage_records[0]
    assert usage.status == "completed"
    assert usage.request_count == 1
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 300
    assert usage.total_tokens == 1500
    assert usage.estimated_cost_microusd == 4800
    assert usage.duration_ms >= 0
    model_event = next(event for event in completed.events if event.event_type == "model_completed")
    assert model_event.output_summary["total_tokens"] == 1500
    assert model_event.output_summary["estimated_cost_usd"] == 0.0048


@pytest.mark.asyncio
async def test_model_failure_is_attributed_without_losing_deterministic_result(
    observability_db: Session,
):
    case = _add_case(observability_db)
    run = AgentRunService.create_run(
        observability_db,
        task_type="case_data_quality",
        query="检查案件质量",
        case_ids=[case.id],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )

    class _UnavailableNarrator(_MeteredNarrator):
        async def summarize(self, query: str, payload: dict):
            raise TimeoutError("provider timeout")

    completed = await AgentRunExecutor(narrator=_UnavailableNarrator()).execute(
        observability_db,
        run.id,
    )

    assert completed.status == "degraded"
    assert completed.result_summary["mode"] == "deterministic_fallback"
    assert completed.model_provider == "openai-compatible"
    assert completed.model_name == "deepseek-chat"
    assert len(completed.usage_records) == 1
    usage = completed.usage_records[0]
    assert usage.status == "failed"
    assert usage.error_code == "TimeoutError"
    assert usage.total_tokens == 0
    assert usage.estimated_cost_microusd == 0


def test_model_registry_selects_an_active_configured_provider_without_exposing_secret(
    observability_db: Session,
    monkeypatch,
):
    model = AIModel(
        name="竞赛脱敏叙述模型",
        provider="openai-compatible",
        model_name="deepseek-chat",
        api_key="encrypted-secret",
        role="analyst",
        is_active=True,
        is_default=False,
        config={
            "api_base": "https://model-gateway.example/v1",
            "input_cost_per_million_usd": 0.28,
            "output_cost_per_million_usd": 0.42,
        },
    )
    observability_db.add(model)
    observability_db.commit()
    monkeypatch.setattr("app.agent_runtime.providers.settings.AGENT_USE_EXTERNAL_MODEL", True)
    monkeypatch.setattr("app.agent_runtime.providers.settings.AGENT_EXTERNAL_DATA_POLICY", "redacted_only")
    monkeypatch.setattr(
        "app.agent_runtime.providers.settings.MODEL_DATA_EGRESS_POLICY",
        "external_redacted_only",
    )
    monkeypatch.setattr("app.agent_runtime.providers.settings.AGENT_PROVIDER", "model_registry")
    monkeypatch.setattr("app.agent_runtime.providers.settings.AGENT_MODEL_ID", model.id)

    narrator = build_narrator(observability_db)

    assert isinstance(narrator, ModelRegistryNarrator)
    assert narrator.provider_name == "openai-compatible"
    assert narrator.model_name == "deepseek-chat"
    assert narrator.input_cost_per_million_usd == 0.28
    assert narrator.output_cost_per_million_usd == 0.42
    assert "encrypted-secret" not in repr(narrator)


@pytest.mark.asyncio
async def test_model_registry_normalizes_json_and_provider_usage(
    observability_db: Session,
    monkeypatch,
):
    model = AIModel(
        name="兼容网关模型",
        provider="openai-compatible",
        model_name="local-model",
        api_key="encrypted-secret",
        role="analyst",
        is_active=True,
        is_default=False,
        config={},
    )
    observability_db.add(model)
    observability_db.commit()
    captured_messages = []

    class _FakeLlm:
        async def ainvoke(self, messages):
            captured_messages.extend(messages)
            return SimpleNamespace(
                content=(
                    '{"result":"已整理","inferences":[],"recommendations":[],'
                    '"information_gaps":[],"boundary":["人工复核"]}'
                ),
                usage_metadata={"input_tokens": 40, "output_tokens": 12},
            )

    monkeypatch.setattr(
        "app.agent_runtime.providers.ModelFactory.create_llm",
        lambda _factory, _model, **_kwargs: _FakeLlm(),
    )

    outcome = await ModelRegistryNarrator(model).summarize(
        "整理脱敏结果",
        {"case_alias": "CASE-001", "distance_band": "0-1km"},
    )

    assert outcome.content["result"] == "已整理"
    assert outcome.usage.request_count == 1
    assert outcome.usage.input_tokens == 40
    assert outcome.usage.output_tokens == 12
    serialized_messages = " ".join(str(item.content) for item in captured_messages)
    assert "CASE-001" in serialized_messages
    assert "encrypted-secret" not in serialized_messages


@pytest.mark.asyncio
async def test_executor_resolves_registry_model_and_marks_model_assisted_mode(
    observability_db: Session,
    monkeypatch,
):
    model = AIModel(
        name="部署指定模型",
        provider="openai-compatible",
        model_name="local-model",
        api_key="encrypted-secret",
        role="analyst",
        is_active=True,
        is_default=False,
        config={"input_cost_per_million_usd": 1, "output_cost_per_million_usd": 2},
    )
    observability_db.add(model)
    observability_db.commit()
    run = AgentRunService.create_run(
        observability_db,
        task_type="map_data_quality",
        query="检查脱敏地图范围",
        case_ids=[],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )
    monkeypatch.setattr("app.agent_runtime.runtime.settings.AGENT_USE_EXTERNAL_MODEL", True)
    monkeypatch.setattr(
        "app.agent_runtime.providers.settings.MODEL_DATA_EGRESS_POLICY",
        "external_redacted_only",
    )
    monkeypatch.setattr("app.agent_runtime.runtime.settings.AGENT_PROVIDER", "model_registry")
    monkeypatch.setattr("app.agent_runtime.runtime.settings.AGENT_MODEL_ID", model.id)

    async def _summarize(_self, _query, _payload):
        return AgentNarrationOutcome(
            content={
                "result": "模型仅整理脱敏事实。",
                "inferences": [],
                "recommendations": [],
                "information_gaps": [],
                "boundary": ["人工复核"],
            },
            usage=AgentNarrationUsage(request_count=1, input_tokens=10, output_tokens=5),
        )

    monkeypatch.setattr(ModelRegistryNarrator, "summarize", _summarize)

    completed = await AgentRunExecutor().execute(observability_db, run.id)

    assert completed.status == "completed"
    assert completed.result_summary["mode"] == "agent_lab"
    assert completed.model_provider == "openai-compatible"
    assert completed.model_name == "local-model"
    assert completed.usage_records[0].estimated_cost_microusd == 20


def test_overview_combines_run_health_performance_provider_and_cost(
    observability_db: Session,
    monkeypatch,
):
    now = datetime.utcnow()
    first = AgentRunService.create_run(
        observability_db,
        task_type="case_data_quality",
        query="规则运行",
        case_ids=[],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )
    first.status = "completed"
    first.started_at = now - timedelta(seconds=4)
    first.completed_at = now - timedelta(seconds=2)
    second = AgentRunService.create_run(
        observability_db,
        task_type="dual_domain_analysis",
        query="模型运行",
        case_ids=[],
        asset_ids=[],
        mode="shadow",
        created_by=7,
    )
    second.status = "degraded"
    second.model_provider = "openai-compatible"
    second.model_name = "deepseek-chat"
    second.started_at = now - timedelta(seconds=8)
    second.completed_at = now - timedelta(seconds=3)
    observability_db.add(AgentUsageRecord(
        run_id=second.id,
        provider="openai-compatible",
        model_name="deepseek-chat",
        status="failed",
        request_count=1,
        input_tokens=1200,
        output_tokens=300,
        total_tokens=1500,
        duration_ms=900,
        estimated_cost_microusd=4800,
    ))
    observability_db.commit()
    monkeypatch.setattr("app.services.agent_observability_service.settings.AGENT_PROVIDER", "deterministic")
    monkeypatch.setattr("app.services.agent_observability_service.settings.AGENT_USE_EXTERNAL_MODEL", False)

    overview = AgentObservabilityService.build_overview(observability_db, days=30)

    assert overview["summary"]["runs_total"] == 2
    assert overview["summary"]["completed_runs"] == 1
    assert overview["summary"]["degraded_runs"] == 1
    assert overview["summary"]["completion_rate_percent"] == 100.0
    assert overview["summary"]["average_duration_ms"] == 3500
    assert overview["summary"]["p95_duration_ms"] == 5000
    assert overview["summary"]["model_calls"] == 1
    assert overview["summary"]["total_tokens"] == 1500
    assert overview["summary"]["estimated_cost_usd"] == 0.0048
    providers = {item["provider"]: item for item in overview["providers"]}
    assert providers["deterministic"]["runs"] == 1
    assert providers["openai-compatible"]["runs"] == 1
    assert providers["openai-compatible"]["models"] == ["deepseek-chat"]
    assert overview["runtime"]["external_model_enabled"] is False
    assert overview["runtime"]["configured_provider"] == "deterministic"


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


def test_agent_overview_api_is_authorized_and_never_returns_model_secrets(
    observability_db: Session,
    monkeypatch,
):
    observability_db.add(AIModel(
        name="内网模型",
        provider="openai-compatible",
        model_name="local-qwen",
        api_key="must-never-leave-server",
        role="analyst",
        is_active=True,
        is_default=False,
        config={"api_base": "http://private-model.internal/v1"},
    ))
    observability_db.commit()
    monkeypatch.setattr(agent_runs.settings, "ENABLE_AGENT_LAB", True)
    monkeypatch.setattr(agent_runs.settings, "AGENT_MODE", "shadow")

    response = _client(observability_db).get("/api/agent-runs/overview?days=30")
    denied = _client(observability_db, role="viewer").get("/api/agent-runs/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["window_days"] == 30
    assert payload["model_catalog"][0] == {
        "id": 1,
        "name": "内网模型",
        "provider": "openai-compatible",
        "model_name": "local-qwen",
        "role": "analyst",
        "is_default": False,
    }
    serialized = response.text
    assert "must-never-leave-server" not in serialized
    assert "private-model.internal" not in serialized
    assert denied.status_code == 403
