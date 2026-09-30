#!/usr/bin/env python3
"""Full production routes with disposable storage and no external model calls."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    if os.environ.get("AIC_UI_FIXTURE") != "1":
        raise RuntimeError("explicit_disposable_test_required")
    map_bundle_value = os.environ.get("AIC_UI_MAP_BUNDLE")
    # 在切换临时目录和清空环境前固定调用方指定的路径。
    map_bundle_path = Path(map_bundle_value).expanduser().resolve(strict=True) if map_bundle_value else None
    if map_bundle_path is not None and not map_bundle_path.is_file():
        raise RuntimeError("ui_map_bundle_not_a_file")
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "backend"))
    with tempfile.TemporaryDirectory(prefix="aic-ui-verification-") as directory:
        os.chdir(directory)
        retained = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        os.environ.update(
            DATABASE_URL=f"sqlite:///{directory}/synthetic.sqlite",
            MAP_PACKAGE_ROOT=f"{directory}/maps", SECRET_KEY="isolated-ui-verification-only",
            ENVIRONMENT="test", AUTH_REQUIRED="true", AUTO_CREATE_TABLES="false",
            ENABLE_VECTOR_DB="false", ENABLE_LEGACY_OPERATIONS_MODULES="true",
            ENABLE_BONUS_ACCOUNTING="true", ENABLE_AGENT_LAB="false", ENABLE_SHOWCASE="true",
            AGENT_MODE="off", AGENT_USE_EXTERNAL_MODEL="false", AGENT_PROVIDER="deterministic",
            REDIS_URL=f"unix://{directory}/disabled.sock", CELERY_BROKER_URL="memory://",
            CELERY_RESULT_BACKEND="cache+memory://", SESSION_COOKIE_SECURE="false",
            SESSION_COOKIE_NAME="aic_ui_verification", FRONTEND_URL="http://127.0.0.1:13048",
            CORS_ORIGINS="http://127.0.0.1:13048", ALLOWED_HOSTS="127.0.0.1,localhost",
        )
        from datetime import datetime, timedelta, timezone
        import app.models  # noqa: F401
        from app.database import Base, engine, SessionLocal
        from app.models.case import Case
        from app.models.jurisdiction import JurisdictionAsset
        from app.models.map_foundation import OperationalArea
        from app.services.auth_service import AuthService
        from app.services.case_pipeline_service import CasePipelineService
        from app.models.case_pipeline import OutboxEvent
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            db.add_all([OperationalArea(id=1, code="ui-1", name="合成测试一区", is_default=True),
                        OperationalArea(id=2, code="ui-2", name="合成测试二区")])
            db.flush()
            admin_user_id = None
            for role in ("admin", "analyst", "viewer"):
                user = AuthService.create_user(db, username=f"ui-{role}", display_name=f"合成验证{role}",
                                               password="Disposable-UI-0912!", role=role)
                if role == "admin":
                    admin_user_id = user.id
            for index in range(24):
                case = Case(case_number=f"UI-DEMO-{index+1:03}", operational_area_id=1,
                    description="合成测试：夜间在井场利用胶管转运原油，现场查获货车。非真实案件。",
                    location="合成测试井场", case_type="涉油盗窃", status="pending",
                    occurred_time=datetime.now(timezone.utc)-timedelta(hours=index*8+1),
                    latitude=46.5+index/1000 if index < 12 else None,
                    longitude=125.1+index/1000 if index < 12 else None)
                db.add(case)
                db.flush()
                CasePipelineService.enqueue_case_change(db, case, changed_fields=["description"])
            db.add(JurisdictionAsset(name="合成验证井", asset_type="well", operational_area_id=1,
                                     latitude=46.5, longitude=125.1))
            db.commit()
            initial_events = [event.id for event in db.query(OutboxEvent).order_by(OutboxEvent.created_at).limit(5)]
            for event_id in initial_events:
                CasePipelineService.process_event(db, event_id)
            if map_bundle_path is not None:
                from app.services.offline_map_service import OfflineMapService
                try:
                    bundle, _ = OfflineMapService.import_bundle(
                        db, filename=map_bundle_path.name, content=map_bundle_path.read_bytes(),
                        imported_by=admin_user_id,
                    )
                    snapshot, _ = OfflineMapService.build_snapshot(
                        db, operational_area_id=1, public_bundle_id=bundle.id, built_by=admin_user_id,
                    )
                    OfflineMapService.publish_snapshot(db, snapshot.id)
                except Exception as error:
                    raise RuntimeError(f"ui_map_initialization_failed: {error}") from error
        from app.main import app
        from fastapi import HTTPException, Request

        @app.post("/api/ui-verification/process")
        def process_fixture(request: Request):
            if getattr(getattr(request.state, "principal", None), "role", None) != "admin":
                raise HTTPException(403)
            with SessionLocal() as db:
                return CasePipelineService.process_pending(db, limit=50)

        import uvicorn
        try:
            uvicorn.run(app, host="127.0.0.1", port=18068, access_log=False)
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
