"""Exercise real v5.2 saved candidates and entrance records, not shaped mocks."""
from app.models.road_network import RoadAccessMembership
from app.services.facility_dossier_content import build_dossier_content
from test_case_facility_comparison import prepared, ready, db_session, result_data  # noqa: F401
from test_case_result_composition import composed  # noqa: F401


def test_saved_road_candidate_entrance_and_revocation(composed):
    from app.services.case_result_service import CaseResultService
    db, source, artifact, _, calls = composed
    current = CaseResultService.latest(db, 1)
    before_calls = len(calls)
    result = build_dossier_content(db, 13)
    candidates = result["sections"]["candidate_links"]["items"]
    assert any(row.get("artifact_id") and row["case_id"] == 1 for row in candidates)
    assert all(row["result_id"] == current["id"] and row["content_sha256"] == current["content_sha256"] for row in candidates)
    assert any("道路" in str(row["counter"]) for row in candidates)
    entrance = result["sections"]["roads"]["items"][0]
    assert entrance["feature_id"] == "gate-13" and entrance["facility_link_verified"]
    assert entrance["routing_available"] is False and len(calls) == before_calls
    db.query(RoadAccessMembership).delete()
    db.commit()
    restricted = build_dossier_content(db, 13)["sections"]["candidate_links"]
    assert restricted["state"] == "unavailable" and restricted["items"] == []
    assert artifact["id"] not in str(restricted)


def test_facility_does_not_borrow_another_scope_or_owner_composition(composed):
    db, _, artifact, _, _ = composed
    db.info['principal_user_id'] = 2
    value = build_dossier_content(db, 13)
    assert value['sections']['candidate_links']['items'] == []
    assert artifact['id'] not in str(value)
