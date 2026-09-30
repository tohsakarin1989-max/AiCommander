#!/usr/bin/env python3
"""Full API for retained v1-v3 browser checks, using disposable synthetic storage."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    if os.environ.get("AIC_DISPOSABLE_LEGACY") != "1":
        raise RuntimeError("explicit_disposable_test_required")
    use_redis = os.environ.get("AIC_LEGACY_REDIS_TEST") == "1"
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "backend"))
    with tempfile.TemporaryDirectory(prefix="aic-legacy-http-") as directory:
        os.chdir(directory)
        retained = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        os.environ.update(
            DATABASE_URL=f"sqlite:///{directory}/synthetic.sqlite",
            MAP_PACKAGE_ROOT=f"{directory}/maps", SECRET_KEY="isolated-legacy-verification-only",
            ENVIRONMENT="test", AUTH_REQUIRED="true", AUTO_CREATE_TABLES="false",
            ENABLE_VECTOR_DB="false", ENABLE_LEGACY_OPERATIONS_MODULES="true",
            ENABLE_BONUS_ACCOUNTING="true", ENABLE_AGENT_LAB="true", AGENT_MODE="shadow",
            AGENT_USE_EXTERNAL_MODEL="false", AGENT_PROVIDER="deterministic",
            REDIS_URL="redis://127.0.0.1:16389/0" if use_redis else f"unix://{directory}/disabled.sock",
            CELERY_BROKER_URL="redis://127.0.0.1:16389/0" if use_redis else "memory://",
            CELERY_RESULT_BACKEND="redis://127.0.0.1:16389/1" if use_redis else "cache+memory://",
            SESSION_COOKIE_SECURE="false",
            SESSION_COOKIE_NAME="aic_legacy_verification", FRONTEND_URL="http://127.0.0.1:13046",
            CORS_ORIGINS="http://127.0.0.1:13046", ALLOWED_HOSTS="127.0.0.1,localhost",
        )
        import app.models  # noqa: F401
        from app.database import Base, engine, SessionLocal
        from app.services.auth_service import AuthService
        from app.models.case import Case
        from app.models.jurisdiction import JurisdictionAsset
        from app.models.ai_model import AIModel
        from app.models.meeting import Meeting
        from app.models.report import Report
        from datetime import datetime, timedelta, timezone
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            for role in ("admin", "analyst", "viewer"):
                AuthService.create_user(db, username=f"legacy-{role}", display_name=f"合成验证{role}",
                                        password="Disposable-Legacy-0912!", role=role)
            for index in range(6):
                db.add(Case(case_number=f"LEGACY-{index+1:03}", operational_area_id=1,
                            description="合成测试，夜间在井场利用胶管转运原油，现场查获货车。",
                            location="合成测试井场", case_type="涉油盗窃", status="pending",
                            occurred_time=datetime.now(timezone.utc)-timedelta(days=index+1),
                            latitude=46.5+index/1000, longitude=125.1+index/1000))
            db.add(JurisdictionAsset(name="合成验证井", asset_type="well", operational_area_id=1,
                                     latitude=46.5, longitude=125.1))
            db.commit()
            # Persisted historical fixture: browser tests reading/export, not model quality.
            db.add_all([AIModel(id=index, name=f"停用历史合成模型{index}", provider="openai",
                                model_name="archived-synthetic", api_key="no-network-archived",
                                role="moderator" if index == 101 else "analyst", is_active=False)
                        for index in (101, 102)])
            db.flush()
            for index in range(102):
                db.add(Meeting(meeting_id=f"HISTORICAL-{index:03}", operational_area_id=1,
                               case_ids=[1], status="completed", moderator_model_id=101,
                               analyst_model_ids=[102], created_at=datetime(2025, 1, 1)+timedelta(days=index),
                               completed_at=datetime(2025, 1, 1)+timedelta(days=index, hours=1)))
            db.flush()
            report = Report(meeting_id="HISTORICAL-000", report_type="comprehensive",
                            content={"summary": "合成历史报告：现场条件需核验，不确认串案。",
                                     "consensus_points": ["保持合成案件事实"],
                                     "recommendations": ["补充现场资料"]},
                            consensus_points=["保持合成案件事实"], disagreement_points=[], model_contributions={})
            db.add(report)
            db.flush()
            db.query(Meeting).filter_by(meeting_id="HISTORICAL-000").one().final_report_id = report.id
            db.commit()
        from app.main import app
        import uvicorn
        try:
            uvicorn.run(app, host="127.0.0.1", port=18056, access_log=False)
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
