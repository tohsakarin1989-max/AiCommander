from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Dict, Optional

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal


router = APIRouter()
BACKEND_DIR = Path(__file__).resolve().parents[2]


class DependencyHealth(BaseModel):
    status: str
    latency_ms: Optional[float] = None
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime
    dependencies: Dict[str, DependencyHealth]


def _check_database() -> DependencyHealth:
    started_at = perf_counter()
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return DependencyHealth(
            status="ok",
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
        )
    except Exception as exc:
        return DependencyHealth(
            status="down",
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
            detail="数据库连接失败" if settings.ENVIRONMENT == "production" else str(exc),
        )


def _check_redis() -> DependencyHealth:
    started_at = perf_counter()
    try:
        import redis

        client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=0.3,
            socket_timeout=0.3,
        )
        client.ping()
        return DependencyHealth(
            status="ok",
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
        )
    except Exception as exc:
        return DependencyHealth(
            status="down" if settings.ENVIRONMENT == "production" else "optional_down",
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
            detail="Redis 连接失败" if settings.ENVIRONMENT == "production" else str(exc),
        )


def _expected_schema_revisions() -> set[str]:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


def _current_schema_revisions() -> set[str]:
    db = SessionLocal()
    try:
        return set(db.execute(text("SELECT version_num FROM alembic_version")).scalars())
    finally:
        db.close()


def _check_schema() -> DependencyHealth:
    started_at = perf_counter()
    try:
        expected = _expected_schema_revisions()
        current = _current_schema_revisions()
        if current == expected:
            return DependencyHealth(
                status="ok",
                latency_ms=round((perf_counter() - started_at) * 1000, 2),
            )

        detail = "数据库迁移未到当前版本"
        if settings.ENVIRONMENT != "production":
            detail = (
                f"当前版本 {sorted(current) or ['未记录']}，"
                f"期望版本 {sorted(expected)}"
            )
        return DependencyHealth(
            status="outdated" if settings.ENVIRONMENT == "production" else "optional_outdated",
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
            detail=detail,
        )
    except Exception as exc:
        return DependencyHealth(
            status="outdated" if settings.ENVIRONMENT == "production" else "optional_untracked",
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
            detail=(
                "无法确认数据库迁移版本"
                if settings.ENVIRONMENT == "production"
                else str(exc)
            ),
        )


@router.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(
        status="alive",
        version=settings.APP_VERSION,
        timestamp=datetime.now(),
        dependencies={},
    )


@router.get("/health/ready", response_model=HealthResponse)
def health_ready():
    dependencies = {
        "database": _check_database(),
        "schema": _check_schema(),
        "redis": _check_redis(),
    }
    if dependencies["database"].status != "ok" or (
        settings.ENVIRONMENT == "production"
        and (
            dependencies["redis"].status != "ok"
            or dependencies["schema"].status != "ok"
        )
    ):
        status = "not_ready"
    elif dependencies["redis"].status == "ok":
        status = "ready"
    else:
        status = "degraded"

    response = HealthResponse(
        status=status,
        version=settings.APP_VERSION,
        timestamp=datetime.now(),
        dependencies=dependencies,
    )
    if status == "not_ready":
        return JSONResponse(status_code=503, content=response.model_dump(mode="json"))
    return response


@router.get("/health/agents")
def health_agents():
    """Agent 独立健康状态，不参与核心 readiness 判定。"""
    if not settings.ENABLE_AGENT_LAB or settings.AGENT_MODE == "off":
        return {
            "status": "off",
            "version": settings.APP_VERSION,
            "mode": "off",
            "queue": settings.AGENT_REDIS_QUEUE,
            "worker": "not_required",
            "external_model": "disabled",
            "affects_core_readiness": False,
        }

    redis_health = _check_redis()
    worker_status = "unavailable"
    if redis_health.status == "ok":
        try:
            from app.tasks.celery_app import celery_app

            replies = celery_app.control.inspect(timeout=0.5).ping() or {}
            worker_status = (
                "online"
                if any(str(worker).startswith("agent@") for worker in replies)
                else "unavailable"
            )
        except Exception:
            worker_status = "unavailable"
    external_model = (
        "configured"
        if settings.AGENT_USE_EXTERNAL_MODEL and settings.OPENAI_API_KEY
        else "disabled"
        if not settings.AGENT_USE_EXTERNAL_MODEL
        else "missing_credentials"
    )
    ready = redis_health.status == "ok" and worker_status == "online"
    return {
        "status": "ready" if ready else "degraded",
        "version": settings.APP_VERSION,
        "mode": settings.AGENT_MODE,
        "queue": settings.AGENT_REDIS_QUEUE,
        "redis": redis_health.model_dump(mode="json"),
        "worker": worker_status,
        "external_model": external_model,
        "external_data_policy": settings.AGENT_EXTERNAL_DATA_POLICY,
        "mutations_enabled": settings.AGENT_MUTATIONS_ENABLED,
        "affects_core_readiness": False,
    }


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    dependencies = {"database": _check_database()}
    return HealthResponse(
        status="healthy" if dependencies["database"].status == "ok" else "not_ready",
        version=settings.APP_VERSION,
        timestamp=datetime.now(),
        dependencies=dependencies,
    )
