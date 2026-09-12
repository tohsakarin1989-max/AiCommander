"""Workspace uses real SQLite services and makes no derived-data writes."""
from sqlalchemy import select

from app.models.case import Case
from app.models.case_result import CaseResultSnapshot
from app.services.case_result_service import CaseResultService
from test_case_results import client_for, db_session, prepare  # noqa: F401
from test_case_result_access import result_data  # noqa: F401


def test_workspace_reuses_result_without_writes(db_session, result_data, monkeypatch):
    prepare(db_session)
    saved, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    def forbidden(*_args, **_kwargs):
        raise AssertionError("GET must not generate or commit")
    monkeypatch.setattr(CaseResultService, "create_current", forbidden)
    monkeypatch.setattr(db_session, "commit", forbidden)
    with client_for(db_session, "viewer") as client:
        response = client.get("/api/cases/1/workspace")
    assert response.status_code == 200, response.text
    data = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert data["result"]["data"]["id"] == saved["id"]
    assert data["links"]["evidence"] == "/graphs/evidence?caseId=1"
    assert list(db_session.scalars(select(CaseResultSnapshot.id))) == [saved["id"]]


def test_workspace_empty_derived_data_stays_empty(db_session, result_data):
    prepare(db_session)
    with client_for(db_session) as client:
        response = client.get("/api/cases/1/workspace")
    assert response.status_code == 200
    assert response.json()["result"] == {"status": "unavailable", "data": None}
    assert not list(db_session.scalars(select(CaseResultSnapshot.id)))


def test_workspace_auth_and_revoked_evidence(db_session, result_data):
    prepare(db_session)
    result_data[2].evidence_refs = ["case:2"]
    db_session.commit()
    db_session.info["authorized_area_ids"] = (1, 2)
    CaseResultService.create_current(db_session, 1)
    db_session.commit()
    db_session.info["authorized_area_ids"] = (1,)
    with client_for(db_session, "viewer") as client:
        response = client.get("/api/cases/1/workspace")
        assert response.status_code == 200
        assert response.json()["result"]["data"] is None
        assert "测试候选" not in response.text and "case:2" not in response.text
        assert client.get("/api/cases/2/workspace").status_code == 404
    with client_for(db_session, None) as client:
        assert client.get("/api/cases/1/workspace").status_code == 401
    db_session.info.pop("authorized_area_ids")
    with client_for(db_session) as client:
        assert client.get("/api/cases/1/workspace").status_code == 404


def test_workspace_marks_changed_original_as_updating(db_session, result_data):
    prepare(db_session)
    CaseResultService.create_current(db_session, 1)
    db_session.commit()
    case = db_session.scalar(select(Case).where(Case.id == 1))
    case.description = "更新后的原始案情，后台尚未处理"
    db_session.commit()
    with client_for(db_session) as client:
        data = client.get("/api/cases/1/workspace").json()
    assert data["profile"]["status"] == "updating"
    assert data["result"]["status"] == "updating"
    assert case.description == "更新后的原始案情，后台尚未处理"
