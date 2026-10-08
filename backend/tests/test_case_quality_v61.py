from datetime import datetime, timedelta, timezone

import pytest

from app.models.case import Case, CasePerson, CaseVehicle
from app.services.case_quality_service import CaseQualityService, QUALITY_RULE_VERSION


def case_record(**changes):
    values = dict(
        case_number="QUALITY-61", occurred_time=None, time_precision="unknown",
        location="测试生产区域", description="现场发现软管，发现方式待补充。",
        case_type="涉油盗窃", current_stage="reported", report_unit="测试单位",
        source_type="群众举报", report_time=datetime(2026, 9, 27, 1),
        created_at=datetime(2026, 9, 27, 1, 30),
    )
    values.update(changes)
    return Case(**values)


def evaluate(case, **related):
    return CaseQualityService.evaluate_case(None, case, related_data={
        "vehicles": [], "persons": [], "evidence": [], "oil_recovery": [], **related,
    })


@pytest.mark.parametrize("description", [
    "未发现车辆，未抓获人员。", "未发现车辆转运原油，未查获嫌疑人。",
    "车辆未出现在现场，人员不在场。", "不排除车辆，但人员情况待查。",
])
def test_negated_or_uncertain_mentions_do_not_require_details_or_disposal(description):
    result = evaluate(case_record(description=description))
    assert result["facts"]["has_vehicle_signal"] is False
    assert result["facts"]["has_person_signal"] is False
    missing = {gap["field"] for gap in result["missing_required"]}
    assert not missing & {"vehicles", "persons", "vehicle_handling", "person_handling", "case_evidence"}
    assert "拓印" not in str(result["recommendations"])


def test_quality_layers_allow_unknown_and_limit_priorities_without_completion_score():
    result = evaluate(case_record(oil_volume=200, oil_volume_unit="unknown"))
    assert result["validation"]["can_save"] is True
    assert result["validation"]["errors"] == []
    assert result["completeness"]["status"] == "partial"
    assert len(result["priority_gaps"]) <= 3
    assert result["score_purpose"] == "legacy_reference_not_case_completion"
    assert result["rule_version"] == QUALITY_RULE_VERSION
    assert set(result["capabilities"]) == {
        "history_retrieval", "regional_analysis", "road_comparison", "material_export",
    }
    for capability in result["capabilities"].values():
        assert capability["runtime_state"] == "not_checked"
        assert capability["assessment_scope"] == "input_data_only"


@pytest.mark.parametrize("precision", ["unknown", "interval"])
def test_non_exact_time_never_evaluates_organizational_deadline(precision):
    changes = {"time_precision": precision}
    if precision == "interval":
        changes.update(occurred_from=datetime(2026, 9, 1), occurred_to=datetime(2026, 9, 20))
    result = evaluate(case_record(**changes))
    assert result["completeness"]["timeliness"]["status"] == "not_evaluable"
    assert result["facts"]["reported_within_1h"] is None
    assert result["facts"]["entered_within_48h"] is None
    assert not any("小时" in warning["message"] for warning in result["warnings"])


def test_deadlines_compare_instants_in_utc_not_clock_faces():
    result = evaluate(case_record(
        occurred_time=datetime(2026, 9, 27, 9, tzinfo=timezone(timedelta(hours=8))),
        time_precision="exact", report_time=datetime(2026, 9, 27, 1, 30, tzinfo=timezone.utc),
        created_at=datetime(2026, 9, 27, 2),
    ))
    assert result["facts"]["reported_within_1h"] is True
    assert result["facts"]["entered_within_48h"] is True
    assert not any("早于" in item["message"] for item in result["warnings"])


def test_canonical_child_rows_not_legacy_json_determine_counts():
    result = evaluate(case_record(
        vehicle_info=[{"plate_number": "测试牌"}], involved_persons=[{"name": "某甲"}],
    ), vehicles=[CaseVehicle(id=1, plate_number="测试牌")], persons=[CasePerson(id=1, name="某甲")])
    assert result["facts"]["vehicle_count"] == 1
    assert result["facts"]["person_count"] == 1
    legacy_only = evaluate(case_record(vehicle_info=[{"plate": "旧记录"}]))
    assert legacy_only["facts"]["vehicle_count"] == 0


def test_intake_stage_does_not_require_disposal_or_twelve_vehicle_photos():
    result = evaluate(case_record(description="发现油罐车和人员。"), vehicles=[CaseVehicle(id=1)])
    fields = {item["field"] for item in result["missing_required"]}
    assert not fields & {"vehicle_handling", "person_handling", "case_evidence"}
    assert "身份证" not in str(result)
    assert "同伙" not in str(result)


def test_applicable_transferred_vehicle_materials_remain_separate_gaps():
    result = evaluate(case_record(current_stage="transferred"), vehicles=[
        CaseVehicle(id=1, transferred_to_police=True, handling_status="已移交公安"),
    ])
    materials = [item for item in result["completeness"]["gaps"] if item["field"] == "case_evidence"]
    assert materials and materials[0]["category"] == "applicable_material"
    assert result["validation"]["can_save"] is True


@pytest.mark.parametrize("changes", [
    {"latitude": 100, "longitude": 120}, {"oil_volume": -1}, {"oil_volume_unit": "barrel"},
])
def test_malformed_data_is_invalid_but_missing_data_is_not(changes):
    result = evaluate(case_record(**changes))
    assert result["validation"]["can_save"] is False
    assert result["validation"]["errors"]


def test_custom_deadline_policy_is_versioned_and_not_mislabelled_as_one_hour():
    from app.services.case_quality_rules import TimelinessPolicy

    case = case_record(occurred_time=datetime(2026, 9, 27, 0), time_precision="exact")
    result = CaseQualityService.evaluate_case(None, case, related_data={},
        timeliness_policy=TimelinessPolicy(version="unit-rule-2", report_limit_minutes=120))
    timing = result["completeness"]["timeliness"]
    assert timing["rule_version"] == "unit-rule-2"
    assert timing["reported_in_time"] is True
    # Old key retains its literal semantics; it cannot claim a custom limit is one hour.
    assert result["facts"]["reported_within_1h"] is None


@pytest.mark.parametrize("text,value,unit", [
    ("涉案原油 100 升", 100, "liter"), ("原油检斤 350 公斤", 350, "kg"),
    ("车内原油 1.2 吨", 1.2, "tonne"), ("原油 2 立方米", 2, "m3"),
    ("查扣5吨以下机动车，车内原油100升", 100, "liter"),
])
def test_intake_candidates_preserve_original_quantity_and_unit(text, value, unit):
    from app.services.case_automation_service import CaseAutomationService
    result = CaseAutomationService.structure_case_text(text)["case_fields"]
    assert (result["oil_volume"], result["oil_volume_unit"]) == (value, unit)


@pytest.mark.parametrize("unit", ["liter", "kg", "m3", "unknown", None])
def test_legacy_tonnage_calculation_never_assumes_unknown_or_other_units(unit):
    from app.services.case_automation_service import CaseAutomationService
    assert CaseAutomationService._oil_tons(case_record(oil_volume=100, oil_volume_unit=unit), []) is None


def test_unknown_occurrence_cannot_be_assigned_to_current_bonus_quarter():
    from app.services.case_automation_service import CaseAutomationService
    with pytest.raises(ValueError, match="bonus_period_unknown"):
        CaseAutomationService._bonus_period_bounds(case_record())


def test_measurement_is_not_a_missing_quantity_and_unknown_unit_remains_a_gap():
    from app.models.case_source import OilMeasurement
    result = evaluate(case_record(), oil_measurements=[OilMeasurement(value=10, unit="unknown", stage="seized")])
    fields = {item["field"] for item in result["missing_required"]}
    assert "oil_volume" not in fields
    assert "oil_measurements.unit" in fields


def test_area_location_cannot_inherit_legacy_point_as_a_trusted_road_endpoint():
    from app.models.case_source import CaseLocation
    result = evaluate(case_record(latitude=46, longitude=124), locations=[CaseLocation(
        role="incident", precision="area", description="某区域", geometry={
            "type": "Polygon", "coordinates": [[[124, 46], [125, 46], [125, 47], [124, 46]]],
        })])
    assert result["capabilities"]["road_comparison"]["data_state"] == "missing"


def test_unknown_time_bonus_preserves_material_review_without_assigning_a_period(monkeypatch):
    from app.services.case_automation_service import CaseAutomationService
    monkeypatch.setattr(CaseQualityService, "get_related_data", lambda *args: {
        "vehicles": [], "persons": [], "evidence": [], "oil_recovery": [],
    })
    result = CaseAutomationService.build_bonus_assessment(None, case_record())
    assert result["management_context"]["status"] == "unknown_period"
    assert result["calculation_gate"]["status"] == "blocked_by_data"
    assert result["total_suggested_amount"] == 0
    assert "material_checks" in result


def test_patrol_staff_are_not_treated_as_case_subjects():
    result = evaluate(case_record(description="巡逻人员在生产区域发现软管。"))
    assert result["facts"]["has_person_signal"] is False
    assert "persons" not in {item["field"] for item in result["missing_required"]}


def test_preprocess_does_not_map_quality_score_to_probability_or_unknown_units_to_tons(monkeypatch):
    from app.services.preprocess_service import CasePreprocessService
    case = case_record(oil_volume=100, oil_volume_unit="unknown")
    monkeypatch.setattr(CaseQualityService, "get_related_data", lambda *args: {
        "vehicles": [], "persons": [], "evidence": [], "oil_recovery": [], "locations": [], "oil_measurements": [],
    })
    result = CasePreprocessService._build_deterministic_features(None, case)
    assert result["confidence"] is None
    assert result["risk"]["level"] == "not_assessed"
    assert result["facts"]["oil"]["volume_unit"] == "unknown"
    assert "涉案油量较大" not in result["risk"]["factors"]
    assert result["modus"]["time_pattern"] == []


@pytest.mark.parametrize("text", ["5月6日凌晨发现异常", "2026年5月6日发现异常", "昨晚发现异常"])
def test_intake_never_invents_year_or_midnight_for_imprecise_time(text):
    from app.services.case_automation_service import CaseAutomationService
    assert CaseAutomationService._extract_datetime(text) is None


def test_model_cannot_reintroduce_precision_or_unit_via_rewritten_summary():
    import json
    from types import SimpleNamespace
    from app.services.case_automation_service import CaseAutomationService

    model = SimpleNamespace(invoke=lambda prompt: SimpleNamespace(content=json.dumps({
        "case_fields": {"occurred_time": "2026-05-06T00:00:00", "description": "2026年5月6日0时0分发现原油100吨"},
        "candidates": [{"field": "occurred_time", "value": "2026-05-06T00:00:00"}],
    })))
    raw = "昨晚发现原油100升，尚未检斤"
    result = CaseAutomationService.structure_case_text(raw, llm=model)
    assert result["case_fields"].get("occurred_time") is None
    assert result["case_fields"]["description"] == raw
    assert not any(item["field"] == "occurred_time" for item in result["candidates"])
