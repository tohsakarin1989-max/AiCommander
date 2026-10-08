"""Source navigation uses synthetic in-memory SQLite only."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.case_sources import router
from app.database import get_db
from app.models.case import Case
from app.models.case_source import CaseRevision, SourceReference
from tests.test_chain_analysis import _session


@pytest.fixture
def source_client():
    db = _session()
    db.info["authorized_area_ids"] = None
    case = Case(case_number="V70-PAGES", description="合成来源分页", status="pending")
    other = Case(case_number="V70-OTHER", description="其他案件", status="pending")
    db.add_all([case, other]); db.flush()
    db.add_all([CaseRevision(case_id=case.id, revision=number, source_hash=str(number), payload={}) for number in range(1, 4)])
    db.add_all([SourceReference(case_id=case.id, kind="evidence" if number % 2 else "text", locator={"title": f"合成{number}"}) for number in range(422)])
    db.add(SourceReference(case_id=other.id, kind="evidence", locator={"title": "不可串入"}))
    db.commit()
    app = FastAPI(); app.include_router(router, prefix="/cases")
    def session():
        yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        yield client, db, case.id
    db.close()


def test_all_evidence_pages_filter_before_limit_and_never_cross_cases(source_client):
    client, db, case_id = source_client
    params = {"references_limit": 20, "reference_kind": "evidence", "limit": 1}
    seen = []
    for _ in range(12):
        response = client.get(f"/cases/{case_id}/sources", params=params)
        assert response.status_code == 200
        page = response.json()
        assert all(row["kind"] == "evidence" and row["case_id"] == case_id for row in page["references"])
        assert len(page["references"]) <= 20
        seen.extend(row["id"] for row in page["references"])
        if page["next_before_reference"] is None:
            break
        params["before_reference"] = page["next_before_reference"]
    expected = [row.id for row in db.query(SourceReference).filter_by(case_id=case_id, kind="evidence").order_by(SourceReference.id.desc())]
    assert seen == expected and len(seen) == 211 and len(set(seen)) == 211


def test_revision_and_reference_cursors_are_independent_and_current_version_stays_named(source_client):
    client, _, case_id = source_client
    first = client.get(f"/cases/{case_id}/sources", params={"limit": 2}).json()
    assert len(first["references"]) == 200 and first["next_before_reference"] is not None
    second = client.get(f"/cases/{case_id}/sources", params={"limit": 2, "before_revision": first["next_before_revision"]}).json()
    assert [row["revision"] for row in first["revisions"] + second["revisions"]] == [3, 2, 1]
    assert second["current_revision"] == 3 and second["current_revision_id"] == first["current_revision_id"]
    assert first["references"] == second["references"]


def test_pagination_preserves_scope_and_rejects_unbounded_page_sizes(source_client):
    client, db, case_id = source_client
    assert client.get(f"/cases/{case_id}/sources", params={"references_limit": 201}).status_code == 422
    assert client.get(f"/cases/{case_id}/sources", params={"reference_kind": "arbitrary"}).status_code == 422
    db.info["authorized_area_ids"] = []
    assert client.get(f"/cases/{case_id}/sources", params={"before_reference": 400}).status_code == 404
