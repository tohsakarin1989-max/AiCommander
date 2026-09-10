from datetime import datetime, timezone

import pytest

from app.services.case_import_values import normalize_case_row


def test_explicit_china_time_applies_only_to_naive_source_values():
    values = normalize_case_row({"occurred_time": "2026-09-10 08:00", "description": "原文", "report_time": "2026-09-10T09:00:00+09:00"}, time_zone="Asia/Shanghai")
    assert values["occurred_time"].astimezone(timezone.utc) == datetime(2026, 9, 10, tzinfo=timezone.utc)
    assert values["report_time"].astimezone(timezone.utc) == datetime(2026, 9, 10, tzinfo=timezone.utc)


def test_legacy_default_remains_utc_and_original_text_is_not_rewritten():
    values = normalize_case_row({"occurred_time": "2026/09/10 08:00", "description": "  原文\n内容  "})
    assert values["occurred_time"] == datetime(2026, 9, 10, 8, tzinfo=timezone.utc)
    assert values["description"] == "  原文\n内容  "


@pytest.mark.parametrize("value", ["Europe/Paris", "../UTC", "", None])
def test_unknown_time_configuration_is_not_guessed(value):
    with pytest.raises(ValueError, match="时区"):
        normalize_case_row({"occurred_time": "2026-09-10", "description": "原文"}, time_zone=value)


@pytest.mark.parametrize("field,value", [("longitude", "NaN"), ("latitude", 91), ("oil_volume", True), ("case_filed", "可能"), ("description", "  "), ("occurred_time", "错误日期")])
def test_every_import_path_uses_strict_validation(field, value):
    with pytest.raises(ValueError):
        normalize_case_row({"occurred_time": "2026-09-10", "description": "原文", field: value})


def test_scope_and_unknown_fields_never_become_create_arguments():
    values = normalize_case_row({"occurred_time": "2026-09-10", "description": "原文", "operational_area_id": 99, "commit": True})
    assert "operational_area_id" not in values
    assert "commit" not in values


def test_all_optional_values_and_unit_conflict():
    source = {"occurred_time": "2026-09-10", "description": "原文", "longitude": "0", "latitude": "0", "police_reported": "否", "case_filed": "是", "report_unit": "甲", "security_team": "甲", "oil_volume": "0"}
    values = normalize_case_row(source)
    assert values["longitude"] == values["latitude"] == values["oil_volume"] == 0
    assert values["police_reported"] is False
    assert values["case_filed"] is True
    assert values["report_unit"] == "甲"
    with pytest.raises(ValueError, match="冲突"):
        normalize_case_row({**source, "security_team": "乙"})
