from datetime import datetime
from time import perf_counter
from typing import Dict, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal


router = APIRouter()


class DependencyHealth(BaseModel):
    status: str
    latency_ms: Optional[float] = None
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
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
            detail=str(exc),
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
            status="optional_down",
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
            detail=str(exc),
        )


@router.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(
        status="alive",
        timestamp=datetime.now(),
        dependencies={},
    )


@router.get("/health/ready", response_model=HealthResponse)
def health_ready():
    dependencies = {
        "database": _check_database(),
        "redis": _check_redis(),
    }
    if dependencies["database"].status != "ok":
        status = "not_ready"
    elif dependencies["redis"].status == "ok":
        status = "ready"
    else:
        status = "degraded"

    response = HealthResponse(
        status=status,
        timestamp=datetime.now(),
        dependencies=dependencies,
    )
    if status == "not_ready":
        return JSONResponse(status_code=503, content=response.model_dump(mode="json"))
    return response


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    dependencies = {"database": _check_database()}
    return HealthResponse(
        status="healthy" if dependencies["database"].status == "ok" else "not_ready",
        timestamp=datetime.now(),
        dependencies=dependencies,
    )
