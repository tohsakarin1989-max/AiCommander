"""结论 API 交付与人工操作均重新验证冻结来源，而不是只检查结论所属案件。"""

from copy import deepcopy
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import conclusions
from app.database import get_db
from app.models.case import Case
from app.models.conclusion import Conclusion
from app.models.conclusion_review import ConclusionReview
from app.models.meeting import Meeting
from app.models.map_foundation import OperationalArea
from app.services.case_result_service import CaseResultService
from test_case_result_access import result_data  # noqa: F401
from test_case_results import db_session  # noqa: F401
from test_conclusion_result_reuse import current_profile, forbid_analysis, frozen_result  # noqa: F401


def client_for(db):
    app = FastAPI()
    app.include_router(conclusions.router, prefix="/api/conclusions")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def meeting_for(db):
    meeting = Meeting(meeting_id="conclusion-meeting", operational_area_id=1,
                      case_ids=[1], status="completed", created_at=datetime(2026, 9, 1))
    db.add(meeting)
    db.commit()
    return meeting


def generate(client):
    response = client.post("/api/conclusions/generate", json={"case_id": 1})
    assert response.status_code == 200, response.text
    return response.json()


def test_current_result_create_list_detail_review_and_link_without_reanalysis(
    db_session, frozen_result, forbid_analysis,
):
    meeting = meeting_for(db_session)
    client = client_for(db_session)
    original = db_session.scalar(select(Case.description).where(Case.id == 1))
    draft = generate(client)
    assert draft["model_status"] == "reused_case_result"
    assert draft["confidence_available"] is False
    assert draft["ai_output"]["confidence_available"] is False
    assert draft["evidence"]["source_result"]["result_id"] == frozen_result["id"]
    assert draft["ai_output"]["recommendations"] == []
    # The legacy Float placeholder is never a low-probability signal or filter match.
    assert draft["confidence"] == 0.0
    listed = client.get("/api/conclusions/").json()
    assert len(listed) == 1 and listed[0]["review_reason"] is None
    assert listed[0]["confidence_available"] is False
    assert client.get("/api/conclusions/?max_confidence=0.7").json() == []
    assert client.get(f"/api/conclusions/{draft['id']}").json()["evidence"] == draft["evidence"]
    assert client.post(f"/api/conclusions/{draft['id']}/review", json={"action": "approve"}).status_code == 200
    linked = client.post(f"/api/conclusions/{draft['id']}/link-meeting", params={"meeting_id": meeting.meeting_id})
    assert linked.status_code == 200
    again = generate(client)
    assert again["id"] == draft["id"] and again["status"] == "published"
    assert db_session.scalar(select(Case.description).where(Case.id == 1)) == original
    assert len(list(db_session.scalars(select(Conclusion.id)))) == 1
    assert len(list(db_session.scalars(select(ConclusionReview.id)))) == 1


def test_absent_result_returns_409_and_does_not_generate_any_assets(
    db_session, current_profile, forbid_analysis,
):
    response = client_for(db_session).post("/api/conclusions/generate", json={"case_id": 1})
    assert response.status_code == 409
    assert "等待后台" in response.json()["detail"]
    assert list(db_session.scalars(select(Conclusion.id))) == []


def test_changed_case_returns_409_instead_of_generating_or_delivering_stale_content(
    db_session, frozen_result, forbid_analysis,
):
    db_session.execute(Case.__table__.update().where(Case.id == 1).values(description="修改后的资料"))
    db_session.commit()
    response = client_for(db_session).post("/api/conclusions/generate", params={"case_id": 1})
    assert response.status_code == 409
    assert list(db_session.scalars(select(Conclusion.id))) == []


def test_scope_revocation_removes_summary_and_blocks_generate_detail_review_and_link(
    db_session, current_profile, result_data, forbid_analysis,
):
    result_data[2].evidence_refs = ["case:2"]
    db_session.commit()
    CaseResultService.create_current(db_session, 1)
    db_session.commit()
    meeting = meeting_for(db_session)
    client = client_for(db_session)
    draft = generate(client)
    # The owning case remains authorized; only its frozen evidence was revoked.
    db_session.info["authorized_area_ids"] = (1,)
    assert client.get("/api/conclusions/").json() == []
    responses = [
        client.get(f"/api/conclusions/{draft['id']}"),
        client.post("/api/conclusions/generate", json={"case_id": 1}),
        client.post(f"/api/conclusions/{draft['id']}/review", json={"action": "approve"}),
        client.post(f"/api/conclusions/{draft['id']}/link-meeting", params={"meeting_id": meeting.meeting_id}),
    ]
    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"detail": "结论不存在或来源成果不可访问"}
        assert "case:2" not in response.text and draft["summary"] not in response.text
        assert response.headers["cache-control"] == "no-store"
    stored = db_session.get(Conclusion, draft["id"])
    assert stored.status == "needs_review" and stored.meeting_id is None
    assert list(db_session.scalars(select(ConclusionReview.id))) == []


@pytest.mark.parametrize("kind", ["hash", "missing", "malformed"])
def test_corrupt_source_reference_is_not_disclosed_or_reviewable(
    db_session, frozen_result, forbid_analysis, kind,
):
    client = client_for(db_session)
    draft = generate(client)
    stored = db_session.get(Conclusion, draft["id"])
    evidence = deepcopy(stored.evidence)
    if kind == "hash":
        evidence["source_result"]["content_sha256"] = "different"
    elif kind == "missing":
        evidence["source_result"]["result_id"] = "missing-private-id"
    else:
        evidence["source_result"] = None
    stored.evidence = evidence
    db_session.commit()
    assert client.get("/api/conclusions/").json() == []
    for response in (
        client.get(f"/api/conclusions/{draft['id']}"),
        client.post(f"/api/conclusions/{draft['id']}/review", json={"action": "reject"}),
    ):
        assert response.status_code == 404
        assert "missing-private-id" not in response.text
    assert stored.status == "needs_review"


def test_read_only_area_can_read_but_not_generate_review_or_link(
    db_session, frozen_result, forbid_analysis,
):
    meeting = meeting_for(db_session)
    client = client_for(db_session)
    draft = generate(client)
    db_session.info["area_access_levels"] = {1: "read"}
    assert client.get(f"/api/conclusions/{draft['id']}").status_code == 200
    assert len(client.get("/api/conclusions/").json()) == 1
    for response in (
        client.post("/api/conclusions/generate", json={"case_id": 1}),
        client.post(f"/api/conclusions/{draft['id']}/review", json={"action": "approve"}),
        client.post(f"/api/conclusions/{draft['id']}/link-meeting", params={"meeting_id": meeting.meeting_id}),
    ):
        assert response.status_code == 403
        assert response.json() == {"detail": "没有目标辖区写权限"}
    assert db_session.get(Conclusion, draft["id"]).status == "needs_review"


def test_legacy_meeting_conclusion_is_not_required_to_have_case_result(db_session):
    db_session.add(OperationalArea(id=1, code="LEGACY-CONCLUSION", name="合成历史辖区"))
    db_session.commit()
    meeting = meeting_for(db_session)
    legacy = Conclusion(case_id=7, meeting_id=meeting.meeting_id, confidence=0.6,
                        summary="保留的历史会议结论", evidence={"key_evidence": ["历史会议记录"]})
    db_session.add(legacy)
    db_session.commit()
    client = client_for(db_session)
    detail = client.get(f"/api/conclusions/{legacy.id}")
    assert detail.status_code == 200 and detail.json()["confidence_available"] is True
    assert len(client.get("/api/conclusions/").json()) == 1
    assert client.post(f"/api/conclusions/{legacy.id}/review", json={"action": "flag"}).status_code == 200
    assert client.post(f"/api/conclusions/{legacy.id}/link-meeting", params={"meeting_id": meeting.meeting_id}).status_code == 200
