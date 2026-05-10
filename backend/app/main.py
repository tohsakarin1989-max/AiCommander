from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import cases, meetings, models, reports, suggestions, system_config, deployment, map_mcp, assistant, websocket, conclusions, agents, graphs, events, patrols, gangs, meeting_templates, personnel, key_locations, health, jurisdiction, case_intelligence, automation_alerts, chain_links
from app.database import engine, Base, SessionLocal
from app.config import settings
import app.models  # noqa: F401
from app.observability import install_observability
from app.schema_maintenance import ensure_auto_created_schema
from app.services.system_config_service import SystemConfigService

app = FastAPI(
    title="AI案件分析系统",
    description="基于人工智能的案件分析系统，支持多AI模型协作决策",
    version="1.0.0"
)

install_observability(app)

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
        db.close()
    except Exception as e:
        print(f"初始化默认配置时出错（可忽略）: {e}")

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health.router, tags=["health"])
app.include_router(cases.router, prefix="/api/cases", tags=["cases"])
app.include_router(meetings.router, prefix="/api/meetings", tags=["meetings"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(suggestions.router, prefix="/api/suggestions", tags=["suggestions"])
app.include_router(system_config.router, prefix="/api/system-config", tags=["system-config"])
app.include_router(deployment.router, prefix="/api/deployment", tags=["deployment"])
app.include_router(map_mcp.router, prefix="/api/map-mcp", tags=["map-mcp"])
app.include_router(assistant.router, prefix="/api/assistant", tags=["assistant"])
app.include_router(websocket.router, prefix="/api", tags=["websocket"])
app.include_router(conclusions.router, prefix="/api/conclusions", tags=["conclusions"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(graphs.router, prefix="/api/graphs", tags=["graphs"])
app.include_router(events.router, prefix="/api/events", tags=["events"])
app.include_router(patrols.router, prefix="/api/patrols", tags=["patrols"])
app.include_router(gangs.router, prefix="/api/gangs", tags=["gangs"])
app.include_router(meeting_templates.router, prefix="/api/meeting-templates", tags=["meeting-templates"])
app.include_router(personnel.router, prefix="/api/personnel", tags=["personnel"])
app.include_router(key_locations.router, prefix="/api/key-locations", tags=["key-locations"])
app.include_router(jurisdiction.router, prefix="/api/jurisdiction", tags=["jurisdiction"])
app.include_router(case_intelligence.router, prefix="/api/case-intelligence", tags=["case-intelligence"])
app.include_router(automation_alerts.router, prefix="/api/automation-alerts", tags=["automation-alerts"])
app.include_router(chain_links.router, prefix="/api/chain-links", tags=["chain-links"])

@app.get("/")
async def root():
    return {"message": "AI案件分析系统API", "version": "1.0.0"}
