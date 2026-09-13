from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.ai_model import AIModel
from app.services.system_config_service import SystemConfigService


router = APIRouter()


class RuntimeFeatures(BaseModel):
    legacy_operations: bool
    bonus_accounting: bool
    agent_lab: bool
    showcase: bool


class RuntimeStatusResponse(BaseModel):
    status: str
    database: str
    redis: str
    active_model_count: int
    map_provider: str
    map_configured: bool
    version: str
    features: RuntimeFeatures


def _redis_status() -> str:
    try:
        import redis

        client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=0.3,
            socket_timeout=0.3,
        )
        client.ping()
        return "ok"
    except Exception:
        return "unavailable"


@router.get("/status", response_model=RuntimeStatusResponse)
def runtime_status(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    active_models = db.query(AIModel).filter(AIModel.is_active.is_(True)).count()
    map_provider = SystemConfigService.get_config_value(
        db,
        "map_api_provider",
        "openstreetmap",
    ) or "openstreetmap"
    map_secret = SystemConfigService.get_config(db, "map_api_key")
    map_configured = map_provider == "openstreetmap" or bool(
        map_secret and SystemConfigService.is_configured(db, map_secret)
    )
    database_backend = "sqlite" if settings.DATABASE_URL.startswith("sqlite") else "postgresql"
    redis_status = _redis_status()
    return RuntimeStatusResponse(
        status="ready" if redis_status == "ok" else "degraded",
        database=database_backend,
        redis=redis_status,
        active_model_count=active_models,
        map_provider=map_provider,
        map_configured=map_configured,
        version=settings.APP_VERSION,
        features=RuntimeFeatures(
            legacy_operations=settings.ENABLE_LEGACY_OPERATIONS_MODULES,
            bonus_accounting=settings.ENABLE_BONUS_ACCOUNTING,
            agent_lab=settings.ENABLE_AGENT_LAB,
            showcase=settings.ENABLE_SHOWCASE,
        ),
    )
