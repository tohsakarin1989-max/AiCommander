import pytest

from app.services.case_semantic_evidence import freeze_sources
from app.services.case_semantic_time import extract_time_intervals


@pytest.mark.parametrize("text", [
    "2026年9月10日22时至2026年9月11日2时",
    "2026-09-10 22:00到2026-09-11 02:00",
])
def test_complete_cross_midnight_interval_keeps_original_reference(text):
    source, = freeze_sources({"description": "🚗案情：" + text + "，其余不详。"})
    items, gaps = extract_time_intervals(source)
    item, = items
    assert item["start"] == "2026-09-10T22:00"
    assert item["end"] == "2026-09-11T02:00"
    assert item["reference"]["quote"] == text
    assert item["timezone"] is None
    assert item["is_official_fact"] is False
    assert gaps == []


@pytest.mark.parametrize("text", [
    "2026年2月30日22时至2026年3月1日2时",
    "2026-09-10 25:00至2026-09-11 02:00",
    "2026-09-11 22:00至2026-09-10 02:00",
])
def test_invalid_interval_is_gap_not_silently_repaired(text):
    source, = freeze_sources({"description": text})
    items, gaps = extract_time_intervals(source)
    assert items == []
    assert gaps[0]["code"] == "invalid_time_interval"


def test_relative_time_never_uses_current_date():
    source, = freeze_sources({"description": "昨晚22时至次日2时"})
    items, gaps = extract_time_intervals(source)
    assert not items
    assert "relative_time_requires_anchor" in {item["code"] for item in gaps}


def test_clock_without_date_is_explicit_gap():
    source, = freeze_sources({"description": "凌晨两点见到车辆"})
    items, gaps = extract_time_intervals(source)
    assert not items
    assert gaps[0]["code"] == "time_expression_requires_context"
    assert gaps[0]["reference"]["quote"] == "凌晨两点"


def test_hour_precision_is_not_presented_as_explicit_minute():
    source, = freeze_sources({"description": "2026年9月10日22时15分至2026年9月11日2时"})
    item, = extract_time_intervals(source)[0]
    assert item["start_precision"] == "minute"
    assert item["end_precision"] == "hour"
