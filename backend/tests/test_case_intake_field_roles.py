"""Synthetic intake role regressions; contains no operational case records."""
import json
from types import SimpleNamespace

import pytest

from app.services.case_automation_service import CaseAutomationService


def preview(text, fields=None):
    model = None if fields is None else SimpleNamespace(invoke=lambda _: SimpleNamespace(
        content=json.dumps({"case_fields": fields, "candidates": [
            {"field": key, "value": value} for key, value in fields.items()]})))
    return CaseAutomationService.structure_case_text(text, llm=model)


@pytest.mark.parametrize("verb,field", [("发现", "discovered_at"), ("查获", "discovered_at"),
                                        ("接报", "report_time"), ("案发", "occurred_time")])
def test_exact_time_is_bound_to_its_event_role(verb, field):
    result = preview(f"2026年10月8日22时30分{verb}，其余时间不详。")
    fields = result["case_fields"]
    assert fields.get(field) == "2026-10-08T22:30:00"
    assert set(fields) & {"occurred_time", "discovered_at", "report_time"} == {field}
    anchor = next(item for item in result["evidence_anchors"] if item["field"] == field)
    assert anchor["reference_status"] == "verified"
    assert verb in anchor["text"]


def test_distinct_dates_and_discovery_do_not_supply_occurrence_time():
    fields = preview("案发时间：2026年10月7日20时00分；2026年10月8日22时30分发现油迹；"
                     "2026年10月9日08时15分接报。")['case_fields']
    assert fields["occurred_time"] == "2026-10-07T20:00:00"
    assert fields["discovered_at"] == "2026-10-08T22:30:00"
    assert fields["report_time"] == "2026-10-09T08:15:00"
    assert "occurred_time" not in preview("2026年10月8日22时30分，车辆登记记录。")['case_fields']


@pytest.mark.parametrize("text,value,unit", [
    ("现场发现原油，车辆载重10吨。", None, None),
    ("现场发现原油，油罐容积10立方米。", None, None),
    ("车辆载重10吨，车内原油2吨，含水率8%。", 2, "tonne"),
    ("现场发现2吨原油，含水率8%。", 2, "tonne"),
    ("查获原油2吨，移交原油1.8吨。", None, None),
    ("发现原油，数量不详，车辆10吨。", None, None),
    ("车辆运输废铁2吨，现场发现油迹。", None, None),
    ("车辆拉油，大概1.5吨，含水8%。", None, None),
    ("检验记录：原油0吨，车辆载重10吨。", 0, "tonne"),
    ("检斤记录：原油-2吨。", None, None),
    ("合成井场附近发现原油2吨。", 2, "tonne"),
    ("合成井场附近发现原油，共2吨。", 2, "tonne"),
])
def test_oil_quantity_requires_local_material_binding(text, value, unit):
    fields = preview(text)["case_fields"]
    assert fields.get("oil_volume") == value
    assert fields.get("oil_volume_unit") == unit


@pytest.mark.parametrize("text,person,vehicle,oil", [
    ("油品已移交公安，人员尚未移交。", None, None, "移交公安"),
    ("人员已移交公安，车辆尚未移交，油品暂存。", "移交公安", None, "暂存"),
    ("油品移交公安但人员未移交公安。", None, None, "移交公安"),
    ("拟将人员移交公安，车辆是否移交待核。", None, None, None),
    ("车辆已移交公安，油品未入库。", None, "移交公安", None),
    ("抓获2人并移交公安，原油检斤入库。", "移交公安", None, "检斤入库"),
    ("油罐车已移交公安，油品去向不详。", None, "移交公安", None),
    ("收缴原油2吨，后续处置不详。", None, None, None),
])
def test_disposition_is_object_specific_and_negation_scoped(text, person, vehicle, oil):
    fields = preview(text)["case_fields"]
    assert fields.get("person_handling") == person
    assert fields.get("vehicle_handling") == vehicle
    assert fields.get("oil_handling") == oil


def test_model_cannot_restore_unsupported_roles_through_fields_candidates_or_summary():
    raw = "2026年10月8日22时30分发现车辆，车辆载重10吨，油品已移交公安，人员尚未移交。"
    result = preview(raw, {"occurred_time": "2026-10-08T22:30:00", "oil_volume": 10,
                          "oil_volume_unit": "tonne", "person_handling": "移交公安",
                          "description": "2026年10月8日22时30分案发，收缴原油10吨，人员已移交公安。"})
    fields = result["case_fields"]
    assert fields.get("occurred_time") is None
    assert fields.get("oil_volume") is None
    assert fields.get("person_handling") is None
    assert fields["discovered_at"] == "2026-10-08T22:30:00"
    assert fields["description"] == raw
    assert not {"occurred_time", "oil_volume", "person_handling"} & {
        item["field"] for item in result["candidates"]}
    for ref in result["evidence_anchors"]:
        if ref["reference_status"] == "verified":
            assert raw[ref["start"]:ref["end"]] == ref["text"]


def test_model_keeps_correct_supported_role_fields_and_exact_unicode_source_ranges():
    raw = "  合成材料🙂，案发于2024年1月2日20时01分；2026年10月8日22时30分查获，"
    raw += "油品已移交公安，人员尚未移交。\n"
    expected = {"occurred_time": "2024-01-02T20:01:00", "discovered_at": "2026-10-08T22:30:00",
                "oil_handling": "移交公安"}
    result = preview(raw, expected)
    for key, value in expected.items():
        assert result["case_fields"][key] == value
        ref = next(item for item in result["evidence_anchors"] if item["field"] == key)
        assert ref["reference_status"] == "verified"
        assert raw[ref["start"]:ref["end"]] == ref["text"]


@pytest.mark.parametrize("text", [
    "回收原油2吨。", "移交原油2吨。", "原油移交量2吨。", "原油已回收，共2吨。",
    "原油入库2吨。", "查获原油3吨，移交原油2吨。",
])
def test_stage_specific_measurement_does_not_fill_general_oil_quantity(text):
    result = preview(text, {"oil_volume": 2, "oil_volume_unit": "tonne"})
    assert result["case_fields"].get("oil_volume") is None
    assert result["case_fields"].get("oil_volume_unit") is None
    assert not {"oil_volume", "oil_volume_unit"} & {item["field"] for item in result["candidates"]}


@pytest.mark.parametrize("handling", ["行政拘留", "治安拘留", "刑事拘留", "刑拘"])
def test_explicit_person_handling_keeps_original_wording(handling):
    result = preview(f"人员已被{handling}。")
    assert result["case_fields"]["person_handling"] == handling


def test_sparse_record_prompts_do_not_demand_police_feedback_or_assert_incident_location():
    result = preview("在合成井场附近发现油迹，来源不详，尚未获得公安后续反馈。")
    location = next(item for item in result["candidates"] if item["field"] == "location")
    assert location["label"] == "原文地点（角色待核）"
    assert not any("请补充公安" in question for question in result["follow_up_questions"])
    assert "未知" in " ".join(result["follow_up_questions"])


def test_model_location_label_cannot_promote_a_discovery_place_to_incident_place():
    model = SimpleNamespace(invoke=lambda _: SimpleNamespace(content=json.dumps({
        "case_fields": {"location": "合成井场附近"},
        "candidates": [{"field": "location", "value": "合成井场附近", "label": "案发地点"}],
    })))
    result = CaseAutomationService.structure_case_text("在合成井场附近发现油迹，案发地点未知。", llm=model)
    assert next(item for item in result["candidates"] if item["field"] == "location")["label"] == "原文地点（角色待核）"


@pytest.mark.parametrize("use_model", [False, True])
@pytest.mark.parametrize("text,field", [
    ("建议将人员移交公安。", "person_handling"),
    ("拒绝将人员移交公安。", "person_handling"),
    ("人员移交公安情况不详。", "person_handling"),
    ("车辆移交公安情况待核。", "vehicle_handling"),
    ("明日将人员移交公安。", "person_handling"),
    ("预计将车辆移交公安。", "vehicle_handling"),
    ("人员移交公安机关的情况尚未确认。", "person_handling"),
    ("人员移交公安？", "person_handling"),
    ("人员移交公安申请被拒绝。", "person_handling"),
])
def test_proposed_refused_unknown_or_future_handling_is_not_completed(text, field, use_model):
    result = preview(text, {field: "移交公安"} if use_model else None)
    assert result["case_fields"].get(field) is None
    assert not any(item["field"] == field for item in result["candidates"])


def test_handling_uncertainty_stays_with_its_object_and_does_not_reject_completed_ba_construction():
    result = preview("已将油品移交公安，建议将人员移交公安。")
    assert result["case_fields"]["oil_handling"] == "移交公安"
    assert result["case_fields"].get("person_handling") is None
    assert preview("已将人员移交公安。")['case_fields']["person_handling"] == "移交公安"


@pytest.mark.parametrize("text,field", [
    ("2026年10月8日22时30分案发时间未知。", "occurred_time"),
    ("2026年10月8日22时30分发现时间待核。", "discovered_at"),
    ("案发时间：2026年10月8日22时30分，时间尚未确认。", "occurred_time"),
])
@pytest.mark.parametrize("use_model", [False, True])
def test_time_role_with_trailing_unknown_status_stays_unknown(text, field, use_model):
    result = preview(text, {field: "2026-10-08T22:30:00"} if use_model else None)
    assert result["case_fields"].get(field) is None
    assert not any(item["field"] == field for item in result["candidates"])


def test_unknown_occurrence_does_not_cancel_explicit_discovery_in_another_clause():
    fields = preview("2026年10月8日22时30分发现车辆，案发时间未知。")['case_fields']
    assert fields["discovered_at"] == "2026-10-08T22:30:00"
    assert fields.get("occurred_time") is None


@pytest.mark.parametrize("use_model", [False, True])
@pytest.mark.parametrize("text", [
    "现场原油2至3吨。", "现场原油2～3吨。", "现场原油2吨至3吨。",
    "现场原油不足2吨。", "现场原油不超过2吨。", "现场原油至少2吨。",
    "现场原油大约2吨。", "现场原油2吨左右。", "现场原油2吨多。",
    "现场发现约2吨原油。", "现场发现不足2吨原油。", "车辆拉油，大概2吨。",
    "现场约有原油2吨。", "现场估计有原油2吨。", "可能发现2吨原油。",
    "未发现2吨原油。", "现场原油2吨？", "现场原油1,200吨。",
])
def test_inexact_quantities_never_fill_exact_case_fields(text, use_model):
    result = preview(text, {"oil_volume": 2, "oil_volume_unit": "tonne"} if use_model else None)
    assert result["case_fields"].get("oil_volume") is None
    assert result["case_fields"].get("oil_volume_unit") is None
    assert not {"oil_volume", "oil_volume_unit"} & {item["field"] for item in result["candidates"]}


@pytest.mark.parametrize("use_model", [False, True])
@pytest.mark.parametrize("text", [
    "人员移交公安未获同意。", "人员移交公安未获得许可。",
    "人员移交公安遭拒绝。", "人员已移交公安的说法未核实。",
])
def test_transfer_permission_or_completion_must_not_be_assumed(text, use_model):
    result = preview(text, {"person_handling": "移交公安"} if use_model else None)
    assert result["case_fields"].get("person_handling") is None
    assert not any(item["field"] == "person_handling" for item in result["candidates"])


@pytest.mark.parametrize("use_model", [False, True])
@pytest.mark.parametrize("text", [
    "2026年10月8日22时30分记录车辆，次日发现油迹。",
    "2026年10月8日22时30分记录车辆，翌日查获油品。",
    "2026年10月8日22时30分记录车辆，第二天接报。",
    "2026年10月8日22时30分登记车辆次日发现油迹。",
    "2026年10月8日22时30分登记车辆后两小时发现油迹。",
    "2026年10月8日22时30分登记车辆10月9日接报。",
])
def test_exact_time_does_not_cross_an_event_clause_to_another_relative_date(text, use_model):
    expected = {"discovered_at": "2026-10-08T22:30:00", "report_time": "2026-10-08T22:30:00"}
    result = preview(text, expected if use_model else None)
    assert not {"occurred_time", "discovered_at", "report_time"} & set(result["case_fields"])


@pytest.mark.parametrize("use_model", [False, True])
def test_explicit_quantity_and_adjacent_time_still_work_with_zero_and_transfer(use_model):
    raw = "2026年10月8日22时30分，巡逻人员在合成区域发现原油净重0吨；人员已将车辆移交公安。"
    expected = {"discovered_at": "2026-10-08T22:30:00", "oil_volume": 0,
                "oil_volume_unit": "tonne", "vehicle_handling": "移交公安"}
    fields = preview(raw, expected if use_model else None)["case_fields"]
    for field, value in expected.items():
        assert fields[field] == value
