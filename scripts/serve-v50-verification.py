#!/usr/bin/env python3
"""Temporary SQLite/full-API fixture, explicitly separate from real data."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    if os.environ.get("AIC_DISPOSABLE_V50") != "1":
        raise RuntimeError("explicit_disposable_test_required")
    history_variant = os.environ.get("AIC_DISPOSABLE_V51_HISTORY") == "1"
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "backend"))
    with tempfile.TemporaryDirectory(prefix="aic-v50-http-") as directory:
        os.chdir(directory)
        retained = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        os.environ.update(
            DATABASE_URL=f"sqlite:///{directory}/synthetic.sqlite",
            MAP_PACKAGE_ROOT=f"{directory}/maps", SECRET_KEY="disposable-v50-verification-only",
            ENVIRONMENT="test", AUTH_REQUIRED="true", AUTO_CREATE_TABLES="false",
            ENABLE_VECTOR_DB="false", ENABLE_AGENT_LAB="false", AGENT_MODE="off",
            AGENT_USE_EXTERNAL_MODEL="false", AGENT_PROVIDER="deterministic",
            REDIS_URL=f"unix://{directory}/disabled.sock", CELERY_BROKER_URL="memory://",
            CELERY_RESULT_BACKEND="cache+memory://", SESSION_COOKIE_SECURE="false",
            SESSION_COOKIE_NAME="aic_v50_verification", FRONTEND_URL="http://127.0.0.1:13150",
            CORS_ORIGINS="http://127.0.0.1:13150", ALLOWED_HOSTS="127.0.0.1,localhost",
        )
        if history_variant:
            os.environ.update(ENABLE_AGENT_LAB="true", AGENT_MODE="shadow")
        import app.models  # noqa: F401
        from app.database import Base, engine, SessionLocal
        from app.services.auth_service import AuthService
        from app.services.case_pipeline_service import CasePipelineService
        from app.models.case import Case
        from datetime import datetime, timezone
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            user = AuthService.create_user(db, username="v50-analyst", display_name="合成验收用户",
                                    password="Disposable-V50-0912!", role="analyst")
            case = Case(case_number="V50-SYNTHETIC-001", operational_area_id=1,
                        description="合成验证资料：夜间在井场利用胶管转运原油，具体来源尚未确认。",
                        location="合成验证井场", case_type="涉油盗窃", oil_type="原油", status="pending",
                        occurred_time=datetime.now(timezone.utc))
            db.add(case)
            db.flush()
            CasePipelineService.enqueue_case_change(db, case)
            db.commit()
            # Real deterministic pipeline, without model or routing fixtures.
            CasePipelineService.process_pending(db)
            if history_variant:
                import asyncio
                import json
                from types import SimpleNamespace
                from app.services.case_history_index_service import CaseHistoryIndexService
                from app.services import intelligent_query_tasks as queries
                from app.database import bind_principal_scope

                db.add(Case(case_number="V51-HISTORY-OLD", operational_area_id=1,
                    description="合成历史资料：夜间在井场利用胶管转运原油，具体来源尚未确认。",
                    location="合成历史井场", occurred_time=datetime(2000, 1, 1, tzinfo=timezone.utc)))
                db.commit()
                CaseHistoryIndexService.reconcile_batch(db)
                db.commit()
                bind_principal_scope(db, SimpleNamespace(user_id=user.id, role=user.role), method="GET")
                task = queries.create_query(db, "找本案的历史相似案件", initial_context={"source_case_id": case.id, "filters": {}})
                decisions = iter([
                    {"action": "call", "tool": "find_history", "arguments": {"source_case_id": case.id, "case_id": None},
                     "change_basis": "历史相似案件"},
                    {"action": "finish", "reason": "completed"},
                ])
                class FixturePlanner:
                    async def ainvoke(self, prompt):
                        return SimpleNamespace(content=json.dumps(next(decisions)))
                asyncio.run(queries.execute_query(db, task["id"], model=FixturePlanner()))
                assert queries.read_query(db, task["id"])["status"] == "completed"
                evidence = repository / "output/v51-history-browser"
                evidence.mkdir(parents=True, exist_ok=True)
                (evidence / "fixture.json").write_text(json.dumps({"query_id": task["id"], "source_case_id": case.id,
                    "synthetic_only": True, "planner": "simulation_not_real_model"}))
        from app.main import app
        import uvicorn
        try:
            uvicorn.run(app, host="127.0.0.1", port=18150, access_log=False)
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
