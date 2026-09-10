"""仅供 v4 浏览器回归；必须显式启用，数据库位于自动清理的临时目录。"""
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

if os.environ.get("AIC_BROWSER_FIXTURE") != "1":
    raise RuntimeError("仅可在 AIC_BROWSER_FIXTURE=1 的隔离测试中启动")

from fastapi import FastAPI, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api import auth, case_imports, cases
from app.config import settings
from app.database import Base, bind_principal_scope, get_db
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import OperationalArea
from app.security import AuthMiddleware


temporary_directory = tempfile.TemporaryDirectory(prefix="aic-v4-browser-")
engine = create_engine(f"sqlite:///{Path(temporary_directory.name) / 'fixture.sqlite'}",
                       connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
sessions = sessionmaker(bind=engine)
settings.ENABLE_VECTOR_DB = False
settings.ENABLE_AGENT_LAB = False
settings.AGENT_MODE = "off"
with sessions() as db:
    db.add_all([OperationalArea(id=1, code="fixture-1", name="合成测试一区", is_default=True),
                OperationalArea(id=2, code="fixture-2", name="合成测试二区")])
    db.flush()
    now = datetime.now(timezone.utc)
    for index in range(125):
        db.add(Case(case_number=f"DEMO-{index:03d}", operational_area_id=1,
                    description=f"合成回归样本 {index}，不含真实业务资料。", location="测试地点",
                    case_type="管线涉油" if index % 2 else "运输涉油", status="pending",
                    occurred_time=now - timedelta(hours=index + 1),
                    latitude=46.5 + index / 1000 if index < 10 else None,
                    longitude=125.1 + index / 1000 if index < 10 else None))
    db.add(Case(case_number="AREA-TWO-ONLY", operational_area_id=2,
                description="仅二区可见", occurred_time=now - timedelta(hours=1), status="pending"))
    db.add(JurisdictionAsset(name="合成井场", asset_type="well", operational_area_id=1,
                             latitude=46.51, longitude=125.12))
    db.commit()


@asynccontextmanager
async def lifespan(_app):
    yield
    engine.dispose()
    temporary_directory.cleanup()


app = FastAPI(lifespan=lifespan)
app.state.environment = "development"


def fixture_db(request: Request):
    with sessions() as db:
        bind_principal_scope(db, getattr(request.state, "principal", None), method=request.method)
        yield db


app.dependency_overrides[get_db] = fixture_db
app.include_router(auth.router, prefix="/api/auth")
app.include_router(cases.router, prefix="/api/cases")
app.include_router(case_imports.router, prefix="/api/case-imports")


@app.get("/api/runtime/status")
def runtime_status():
    return {"status": "ok", "database": "fixture", "redis": "off", "active_model_count": 0,
            "map_provider": "fixture-unavailable", "map_configured": False, "version": "v4-test-fixture"}


app.add_middleware(AuthMiddleware, session_factory=sessions, auth_required=True,
                   bootstrap_token="fixture-only-token", secure_cookie=False,
                   allowed_origins=("http://127.0.0.1:13040",))
