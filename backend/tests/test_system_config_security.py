from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import system_config
from app.database import Base, get_db
from app.models.system_config import SystemConfig
from app.services.system_config_service import SystemConfigService


def test_api_key_configs_are_encrypted_at_rest(db_session: Session):
    config = SystemConfigService.set_config(
        db_session,
        config_key="meeting_api_key",
        config_value="secret-value-123",
        config_type="api_key",
        category="meeting",
    )

    assert config.config_value != "secret-value-123"
    assert config.is_encrypted == "true"
    assert SystemConfigService.get_config_value(
        db_session,
        "meeting_api_key",
    ) == "secret-value-123"


def test_config_api_masks_secret_values():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with session_factory() as db:
        SystemConfigService.set_config(
            db,
            config_key="meeting_api_key",
            config_value="secret-value-123",
            config_type="api_key",
            category="meeting",
        )

    app = FastAPI()
    app.include_router(system_config.router, prefix="/api/system-config")

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    detail = client.get("/api/system-config/meeting_api_key")
    runtime = client.get("/api/system-config/meeting/config")

    assert detail.status_code == 200
    assert detail.json()["config_value"] == ""
    assert detail.json()["is_configured"] is True
    assert detail.json()["value_masked"] == "********"
    assert runtime.status_code == 200
    assert "api_key" not in runtime.json()
    assert runtime.json()["api_key_configured"] is True

    with session_factory() as db:
        stored = db.query(SystemConfig).filter_by(config_key="meeting_api_key").one()
        assert "secret-value-123" not in stored.config_value


def test_blank_secret_update_preserves_existing_value(db_session: Session):
    SystemConfigService.set_config(
        db_session,
        config_key="map_api_key",
        config_value="existing-secret",
        config_type="api_key",
        category="map",
    )

    SystemConfigService.set_config(
        db_session,
        config_key="map_api_key",
        config_value="",
        config_type="api_key",
        category="map",
        preserve_blank_secret=True,
    )

    assert SystemConfigService.get_config_value(
        db_session,
        "map_api_key",
    ) == "existing-secret"
