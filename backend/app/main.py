from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import agent_runs, auth, case_imports, case_insights, case_pipeline, case_steward, cases, deployment_advisor, dual_domain_pilot, governance, meetings, models, reports, suggestions, system_config, deployment, map_foundation, map_mcp, offline_maps, assistant, websocket, conclusions, agents, graphs, events, patrols, gangs, meeting_templates, personnel, key_locations, health, jurisdiction, case_intelligence, automation_alerts, chain_links, knowledge, map_steward, runtime, situation, workbench
from app.api import map_package_imports
from app.api import intelligent_queries
from app.api import showcase
from app.api import case_results
from app.api import road_analysis
from app.cors import build_cors_origins
from app.database import engine, Base, SessionLocal
from app.config import settings
import app.models  # noqa: F401
from app.observability import install_observability
from app.schema_maintenance import ensure_auto_created_schema
from app.services.system_config_service import SystemConfigService
from app.security import AuthMiddleware, SecurityHeadersMiddleware

app = FastAPI(
    title="AI案件分析系统",
    description="基于人工智能的案件分析系统，支持多AI模型协作决策",
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.ENABLE_API_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
)

install_observability(app)
app.state.auth_session_factory = SessionLocal
app.state.auth_bootstrap_token = settings.BOOTSTRAP_TOKEN
app.state.auth_secure_cookie = settings.SESSION_COOKIE_SECURE
app.state.environment = settings.ENVIRONMENT

def _prepare_schema() -> None:
    if settings.AUTO_CREATE_TABLES:
        Base.metadata.create_all(bind=engine)
        ensure_auto_created_schema(engine)


_prepare_schema()


@app.on_event("startup")
def startup() -> None:
    # 创建数据表
    _prepare_schema()

    # 初始化默认配置
    try:
        db = SessionLocal()
        SystemConfigService.init_default_configs(db)
        SystemConfigService.encrypt_legacy_secrets(db)
        db.close()
    except Exception as e:
        print(f"初始化默认配置时出错（可忽略）: {e}")

# 安全中间件。CORS 最后注册，使预检和错误响应也带正确的 CORS 头。
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[item.strip() for item in settings.ALLOWED_HOSTS.split(",") if item.strip()],
)
app.add_middleware(
    AuthMiddleware,
    session_factory=SessionLocal,
    allowed_origins=build_cors_origins(settings.FRONTEND_URL, settings.CORS_ORIGINS),
)
app.add_middleware(SecurityHeadersMiddleware)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=build_cors_origins(settings.FRONTEND_URL, settings.CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(runtime.router, prefix="/api/runtime", tags=["runtime"])
app.include_router(cases.router, prefix="/api/cases", tags=["cases"])
app.include_router(case_imports.router, prefix="/api/case-imports", tags=["case-imports"])
app.include_router(case_pipeline.router, prefix="/api", tags=["case-pipeline"])
app.include_router(case_insights.router, prefix="/api", tags=["case-insights"])
app.include_router(case_results.router, prefix="/api", tags=["case-results"])
app.include_router(road_analysis.router, prefix="/api/road-analysis", tags=["road-analysis"])
app.include_router(deployment_advisor.router, prefix="/api", tags=["deployment-advisor"])
app.include_router(governance.router, prefix="/api", tags=["intelligence-governance"])
app.include_router(meetings.router, prefix="/api/meetings", tags=["meetings"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(suggestions.router, prefix="/api/suggestions", tags=["suggestions"])
app.include_router(system_config.router, prefix="/api/system-config", tags=["system-config"])
app.include_router(deployment.router, prefix="/api/deployment", tags=["deployment"])
app.include_router(map_mcp.router, prefix="/api/map-mcp", tags=["map-mcp"])
app.include_router(assistant.router, prefix="/api/assistant", tags=["assistant"])
app.include_router(intelligent_queries.router, prefix="/api/intelligent-queries", tags=["intelligent-queries"])
app.include_router(showcase.router, prefix="/api/showcase", tags=["showcase"])
app.include_router(websocket.router, prefix="/api", tags=["websocket"])
app.include_router(conclusions.router, prefix="/api/conclusions", tags=["conclusions"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(agent_runs.router, prefix="/api/agent-runs", tags=["agent-runs"])
app.include_router(map_steward.router, prefix="/api/agent-map-steward", tags=["agent-map-steward"])
app.include_router(case_steward.router, prefix="/api/agent-case-steward", tags=["agent-case-steward"])
app.include_router(dual_domain_pilot.router, prefix="/api/agent-dual-domain", tags=["agent-dual-domain"])
app.include_router(graphs.router, prefix="/api/graphs", tags=["graphs"])
app.include_router(events.router, prefix="/api/events", tags=["events"])
app.include_router(gangs.router, prefix="/api/gangs", tags=["gangs"])
app.include_router(meeting_templates.router, prefix="/api/meeting-templates", tags=["meeting-templates"])
if settings.ENABLE_LEGACY_OPERATIONS_MODULES:
    app.include_router(patrols.router, prefix="/api/patrols", tags=["patrols"])
    app.include_router(personnel.router, prefix="/api/personnel", tags=["personnel"])
    app.include_router(key_locations.router, prefix="/api/key-locations", tags=["key-locations"])
app.include_router(jurisdiction.router, prefix="/api/jurisdiction", tags=["jurisdiction"])
app.include_router(map_foundation.router, prefix="/api", tags=["map-foundation"])
app.include_router(offline_maps.router, prefix="/api", tags=["offline-maps"])
app.include_router(map_package_imports.router, prefix="/api", tags=["offline-map-imports"])
app.include_router(case_intelligence.router, prefix="/api/case-intelligence", tags=["case-intelligence"])
app.include_router(automation_alerts.router, prefix="/api/automation-alerts", tags=["automation-alerts"])
app.include_router(chain_links.router, prefix="/api/chain-links", tags=["chain-links"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])
app.include_router(workbench.router, prefix="/api/workbench", tags=["workbench"])
app.include_router(situation.router, prefix="/api/situation", tags=["situation"])

@app.get("/")
async def root():
    return {"message": "AI案件分析系统API", "version": settings.APP_VERSION}
