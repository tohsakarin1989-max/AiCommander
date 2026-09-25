"""Exercise real v5.2 saved candidates and entrance records, not shaped mocks."""
from app.models.road_network import RoadAccessMembership
from app.services.case_facility_comparison import compare_case_facilities
from app.services.case_road_artifact_service import freeze_road_artifact
from app.services.facility_dossier_content import build_dossier_content
from test_case_facility_comparison import prepared, ready, db_session, result_data, VEHICLE  # noqa: F401
from test_road_access_policy import AT


def test_saved_road_candidate_entrance_and_revocation(prepared, tmp_path):
    db, source, calls = prepared
    compared = compare_case_facilities(db, result_id=source["id"], network_id="graph-1",
        analysis_at=AT, vehicle=VEHICLE, artifact_root=tmp_path)
    freeze_road_artifact(db, compared)
    db.commit()
    before_calls = len(calls)
    result = build_dossier_content(db, 13)
    candidates = result["sections"]["candidate_links"]["items"]
    assert any(row.get("artifact_id") and row["case_id"] == 1 for row in candidates)
    assert any("道路" in str(row["counter"]) for row in candidates)
    entrance = result["sections"]["roads"]["items"][0]
    assert entrance["feature_id"] == "gate-13" and entrance["facility_link_verified"]
    assert entrance["routing_available"] is False and len(calls) == before_calls
    db.query(RoadAccessMembership).delete()
    db.commit()
    restricted = build_dossier_content(db, 13)["sections"]["candidate_links"]
    assert restricted["state"] == "restricted" and "items" not in restricted and "total" not in restricted
