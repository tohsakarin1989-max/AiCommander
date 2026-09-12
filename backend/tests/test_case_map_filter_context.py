"""Map/list filters share the same selection; legacy inclusive endpoints stay compatible."""
from datetime import datetime

from test_case_search_page import add_case, client_for, search_db  # noqa: F401


def test_map_multi_filters_match_paged_search_and_scope(search_db):
    add_case(search_db, "A", status="pending")
    add_case(search_db, "B", status="resolved")
    add_case(search_db, "C", oil_type="柴油")
    add_case(search_db, "SECRET", operational_area_id=2)
    search_db.commit()
    search_db.info["authorized_area_ids"] = (1,)
    params = [("statuses", "pending"), ("statuses", "resolved"), ("case_types", "盗油"), ("oil_types", "原油")]
    with client_for(search_db) as client:
        legacy = client.get("/api/cases/", params=params)
        page = client.get("/api/cases/page", params=params)
    assert legacy.status_code == page.status_code == 200
    assert {case["case_number"] for case in legacy.json()} == {"A", "B"}
    assert {case["id"] for case in legacy.json()} == {case["id"] for case in page.json()["items"]}


def test_map_half_open_time_boundary_is_explicit_and_old_contract_survives(search_db):
    add_case(search_db, "BEFORE", occurred_time=datetime(2026, 9, 9, 11, 59))
    add_case(search_db, "BOUNDARY", occurred_time=datetime(2026, 9, 9, 12))
    search_db.commit()
    with client_for(search_db) as client:
        assert len(client.get("/api/cases/", params={"end_date": "2026-09-09T12:00:00Z"}).json()) == 2
        result = client.get("/api/cases/", params={"end_date": "2026-09-09T12:00:00Z", "end_exclusive": True})
        assert [case["case_number"] for case in result.json()] == ["BEFORE"]
        assert client.get("/api/cases/", params={"has_geo": "invalid"}).status_code == 422
