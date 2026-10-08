"""Date filtering preserves exact, interval and unknown facts across entry points."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.case_history_retrieval import CaseHistoryRetrieval
from app.services.case_knowledge_service import CaseKnowledgeService
from tests.test_case_search_page import add_case, client_for, search_db  # noqa: F401


@pytest.fixture
def time_db(search_db):
    exact = datetime(2026, 9, 1)
    add_case(search_db, "exact-start", occurred_time=exact)
    add_case(search_db, "exact-end", occurred_time=exact + timedelta(days=1))
    for name, start, end in [
        ("spans-month", exact - timedelta(days=2), exact + timedelta(days=3)),
        ("ends-at-start", exact - timedelta(days=1), exact),
        ("point-interval", exact, exact),
        ("starts-at-end", exact + timedelta(days=1), exact + timedelta(days=2)),
        ("before", exact - timedelta(days=2), exact - timedelta(seconds=1)),
    ]:
        add_case(search_db, name, occurred_time=None, occurred_from=start,
                 occurred_to=end, time_precision="interval", description="合成打孔盗油")
    add_case(search_db, "unknown", occurred_time=None, time_precision="unknown")
    add_case(search_db, "private", operational_area_id=2, occurred_time=None,
             occurred_from=exact, occurred_to=exact, time_precision="interval")
    search_db.commit()
    search_db.info["authorized_area_ids"] = (1,)
    return search_db


@pytest.mark.parametrize("path", ["/api/cases/page", "/api/cases/"])
def test_half_open_query_overlaps_closed_uncertainty_interval(time_db, path):
    result = client_for(time_db).get(path, params={
        "start_date": "2026-09-01T08:00:00+08:00",
        "end_date": "2026-09-02T08:00:00+08:00", "end_exclusive": True,
    })
    assert result.status_code == 200
    rows = result.json()["items"] if path.endswith("page") else result.json()
    assert {row["case_number"] for row in rows} == {
        "exact-start", "spans-month", "ends-at-start", "point-interval"}
    point = next(row for row in rows if row["case_number"] == "point-interval")
    assert point["occurred_time"] is None and point["time_precision"] == "interval"


def test_time_window_preserves_unknown_without_date_filter_and_scope(time_db):
    result = client_for(time_db).get("/api/cases/page").json()
    assert result["total"] == 8
    assert "unknown" in {row["case_number"] for row in result["items"]}
    filtered = client_for(time_db).get("/api/cases/page", params={
        "start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-02T00:00:00Z"}).json()
    assert filtered["total"] == 4 and filtered["facets"]["case_types"] == {"盗油": 4}


@pytest.mark.parametrize("path", ["/api/cases/page", "/api/cases/"])
def test_empty_half_open_window_cannot_match_spanning_interval(time_db, path):
    result = client_for(time_db).get(path, params={
        "start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-01T00:00:00Z",
        "end_exclusive": True,
    })
    assert result.status_code == 422


def test_one_sided_date_filters_and_legacy_inclusive_end(time_db):
    client = client_for(time_db)
    end_only = client.get("/api/cases/page", params={"end_date": "2026-09-01T00:00:00Z"}).json()
    assert {row["case_number"] for row in end_only["items"]} == {"spans-month", "ends-at-start", "before"}
    start_only = client.get("/api/cases/page", params={"start_date": "2026-09-02T00:00:00Z"}).json()
    assert {row["case_number"] for row in start_only["items"]} == {"spans-month", "starts-at-end", "exact-end"}
    legacy = client.get("/api/cases/", params={"start_date": "2026-09-01T00:00:00Z",
                                             "end_date": "2026-09-02T00:00:00Z"}).json()
    assert "exact-end" in {row["case_number"] for row in legacy}


def test_history_population_uses_same_time_window(time_db):
    result = CaseHistoryRetrieval.search(time_db, query="打孔盗油", filters={
        "start_date": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "end_date": datetime(2026, 9, 2, tzinfo=timezone.utc),
    })
    assert result["coverage"]["authorized_cases"] == 4
    assert result["coverage"]["missing_index_cases"] == 4


def test_diagram_describes_interval_without_fabricating_exact_time(search_db):
    profile = {"case": {"case_number": "INTERVAL", "occurred_time": None,
                         "occurred_from": "2026-08-31T00:00:00+00:00",
                         "occurred_to": "2026-09-02T00:00:00+00:00",
                         "time_precision": "interval", "time_timezone": "Asia/Shanghai"}, "related": {}}
    diagram = CaseKnowledgeService.build_case_diagram(search_db, 1, profile=profile)
    node = next(row for row in diagram["nodes"] if row["type"] == "time")
    assert "2026-08-31" in node["label"] and "2026-09-02" in node["label"]
    assert "区间" in node["label"] and "未填" not in node["label"]


def test_statistics_separates_interval_and_unknown_from_exact_daily_counts(search_db):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    add_case(search_db, "exact", occurred_time=now)
    add_case(search_db, "interval", occurred_time=None, occurred_from=now - timedelta(days=1),
             occurred_to=now + timedelta(days=1), time_precision="interval")
    add_case(search_db, "unknown", occurred_time=None, time_precision="unknown")
    search_db.commit()
    result = client_for(search_db).get("/api/cases/statistics").json()
    assert result["interval_time_cases"] == result["unknown_time_cases"] == result["today_cases"] == 1
    assert sum(day["count"] for day in result["daily_trend"]) == 1


def test_read_tools_preserve_precision_and_warn_about_cross_window_counts(time_db):
    from app.services.intelligent_query_answers import compose_answer
    from app.services.intelligent_query_tools import execute_tool

    filters = {"start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-02T00:00:00Z"}
    found = execute_tool(time_db, "find_cases", filters)
    point = next(row for row in found["data"]["items"] if row["case_number"] == "point-interval")
    assert point["time_precision"] == "interval" and point["occurred_from"] == point["occurred_to"]
    count = execute_tool(time_db, "count_cases", filters)
    assert count["data"]["count"] == 4
    assert count["data"]["time_precision_counts"] == {"exact": 1, "interval": 3, "unknown": 0}
    comparison = execute_tool(time_db, "compare_periods", {
        "start": filters["start_date"], "end": filters["end_date"]})
    assert comparison["data"]["current_time_precision_counts"]["interval"] == 3
    assert comparison["data"]["previous_time_precision_counts"]["interval"] == 3
    assert any("相加" in text for text in comparison["information_gaps"])
    answer = compose_answer([count, comparison])
    assert "可能" in str(answer) and "精确" in str(answer)


def test_history_time_metadata_is_revalidated_before_reuse(time_db):
    from copy import deepcopy
    from app.services.case_history_fragment_search import validate_fragment_item
    from tests.history_index_helpers import build_history_index

    build_history_index(time_db)
    result = CaseHistoryRetrieval.search(time_db, query="合成打孔盗油", filters={
        "start_date": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "end_date": datetime(2026, 9, 2, tzinfo=timezone.utc),
    })
    item = result["items"][0]
    assert item["time_precision"] == "interval" and item["occurred_time"] is None
    forged = deepcopy(item)
    forged["occurred_from"] = "2025-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="history_time_changed"):
        validate_fragment_item(time_db, forged)


def test_daily_statistics_use_business_timezone_and_half_open_window(search_db, monkeypatch):
    from app.api import cases
    from zoneinfo import ZoneInfo

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 9, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(cases, "datetime", FrozenDatetime)
    add_case(search_db, "local-start", occurred_time=datetime(2026, 8, 31, 16))
    add_case(search_db, "before-local-start", occurred_time=datetime(2026, 8, 31, 15, 59))
    add_case(search_db, "next-local-day", occurred_time=datetime(2026, 9, 1, 16))
    search_db.commit()
    result = client_for(search_db).get("/api/cases/statistics").json()
    assert result["today_cases"] == result["daily_trend"][-1]["count"] == 1
    assert sum(day["count"] for day in result["daily_trend"]) == 2
    assert result["timezone"] == "Asia/Shanghai"
