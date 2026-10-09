from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.ai_model import AIModel
from app.services.system_config_service import SystemConfigService
from app.services.runtime_capabilities import query_creation_enabled


router = APIRouter()


@router.get('/capabilities')
def runtime_capabilities(request: Request, db: Session = Depends(get_db)):
    """Read-only local observations, not model calls or deployment acceptance."""
    from datetime import datetime, timezone
    from pathlib import Path
    from app.ai.model_factory import ModelFactory
    from app.services.offline_map_service import OfflineMapService
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        raise HTTPException(401, '请先登录')
    if principal.role != 'admin':
        raise HTTPException(403, '运行配置仅供管理员查看')
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        map_state = OfflineMapService.health(db)['status']
    except Exception:
        map_state = 'unavailable'
    model_id = settings.AGENT_MODEL_ID
    model = db.query(AIModel).filter(AIModel.id == model_id, AIModel.is_active.is_(True)).first() if model_id else None
    provider = (model.provider or '').strip().lower() if model else ''
    trusted_model = bool(model and ModelFactory._is_trusted_local_endpoint(model, provider))
    bundle = settings.LOCAL_EMBEDDING_BUNDLE
    return {'schema_version': 'runtime-capabilities-9.0-1', 'checked_at': checked_at,
            'capabilities': [
        {'key': 'recording', 'label': '案件登记与通用台账', 'state': 'enabled',
         'basis': '当前服务可读取数据库；不代表目标终端保存性能已验收'},
        {'key': 'offline_maps', 'label': '离线地图资源', 'state': map_state,
         'basis': '核对已发布版本与本地资源校验；首次断网打开仍需现场核验'},
        {'key': 'background', 'label': '后台资料与分析任务', 'state': _redis_status(),
         'basis': '仅观察队列连接；Worker/Beat 是否持续消费须看任务回执，不以 Redis 在线替代'},
        {'key': 'rule_answers', 'label': '规则问题入口',
         'state': 'enabled' if query_creation_enabled(settings) else 'disabled',
         'basis': '无需外部模型；关闭时历史材料保持可读'},
        {'key': 'model_queries', 'label': '内网模型增强',
         'state': 'configured_unverified' if trusted_model else 'disabled',
         'basis': '登记、信任边界、连通和业务验证分别核对；本次读取不调用模型'},
        {'key': 'semantic_search', 'label': '本地语义检索资源',
         'state': 'configured_unverified' if bundle and Path(bundle).is_dir() else 'not_configured',
         'basis': '目录存在不等于权重与清单完整或推理已验证；未启用时仍可结构和词项检索'},
    ], 'model_registered_count': db.query(AIModel).filter(AIModel.is_active.is_(True)).count(),
       'live_business_verified': False, 'model_probes_performed': False,
       'queue_connection_probed': True}


class RuntimeFeatures(BaseModel):
    legacy_operations: bool
    bonus_accounting: bool
    agent_lab: bool
    showcase: bool
    intelligent_query: bool
    query_history: bool = True
    query_cancel: bool = True


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
            legacy_operations=False,  # Compatibility flag: modules retired in v6.5.
            bonus_accounting=settings.ENABLE_BONUS_ACCOUNTING,
            agent_lab=settings.ENABLE_AGENT_LAB,
            showcase=settings.ENABLE_SHOWCASE,
            intelligent_query=query_creation_enabled(settings),
        ),
    )
