"""Model-name conflicts must roll back cleanly without exposing SQL or credentials."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import models
from app.database import Base, get_db


@pytest.fixture
def model_client():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(models.router, prefix="/api/models")

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    engine.dispose()


def create(client, name):
    return client.post("/api/models/", json={"name": name, "provider": "openai",
                       "model_name": "synthetic", "api_key": "synthetic-never-disclose",
                       "role": "analyst"})


@pytest.mark.parametrize("deleted", [False, True])
def test_duplicate_name_is_safe_conflict_including_archived_models(model_client, deleted):
    client = model_client
    first = create(client, "duplicate-model")
    assert first.status_code == 200
    if deleted:
        assert client.delete(f"/api/models/{first.json()['id']}").status_code == 200
    response = create(client, "duplicate-model")
    assert response.status_code == 409, response.text
    assert "名称" in response.json()["detail"]
    assert "synthetic-never-disclose" not in response.text
    assert "INSERT" not in response.text
    assert create(client, "new-name").status_code == 200


def test_conflicting_rename_keeps_original_configuration(model_client):
    client = model_client
    first = create(client, "first-model").json()
    second = create(client, "second-model").json()
    response = client.put(f"/api/models/{second['id']}", json={"name": first["name"]})
    assert response.status_code == 409, response.text
    assert client.get(f"/api/models/{second['id']}").json()["name"] == "second-model"
    assert client.put(f"/api/models/{second['id']}", json={"name": "third-model"}).status_code == 200
