"""Source-field keywords share the authorized page/facet/assistant query."""
import pytest

from app.services.intelligent_query_tools import execute_tool
from tests.test_case_search_page import add_case, client_for, search_db


@pytest.mark.parametrize("field", ["modus_operandi", "upstream_source", "downstream_destination",
    "source_detail", "facility_type", "facility_owner", "oil_type", "oil_nature",
    "source_type", "report_unit"])
def test_page_and_assistant_find_source_business_fields_beyond_first_page(search_db, field):
    expected = add_case(search_db, "first", **{field: "独特关键词"})
    add_case(search_db, "hidden", operational_area_id=2, **{field: "独特关键词"})
    for n in range(105):
        add_case(search_db, f"ordinary-{n}")
    search_db.commit()
    search_db.info["authorized_area_ids"] = (1,)
    result = client_for(search_db).get("/api/cases/page", params={"keyword": "独特关键词", "page_size": 1})
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["id"] == expected.id
    assert sum(result.json()["facets"]["statuses"].values()) == 1
    assistant = execute_tool(search_db, "find_cases", {"keyword": "独特关键词", "page_size": 1})
    assert assistant["data"]["total"] == 1
    assert assistant["data"]["items"][0]["id"] == expected.id


def test_stale_derived_features_are_not_source_keyword_facts(search_db):
    add_case(search_db, "derived-only", features={"modus_operandi": "未经确认的旧特征"})
    search_db.commit()
    assert client_for(search_db).get("/api/cases/page", params={"keyword": "未经确认"}).json()["total"] == 0
