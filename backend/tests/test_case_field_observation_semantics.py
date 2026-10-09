"""Synthetic field records: response actions never establish a theft process."""
from copy import deepcopy

import pytest

from app.services.case_history_retrieval import business_conditions
from app.services.case_semantic_service import build_semantic_profile


def profile(text):
    return build_semantic_profile({"description": text})


def actions(result):
    return [item for fragment in result["event_fragments"]["items"] for item in fragment["actions"]]


@pytest.mark.parametrize("text", ["抽油机停机。", "油井抽油泵设备检修。", "携带抽油机配件。"])
def test_equipment_name_is_not_an_extraction_action(text):
    result = profile(text)
    assert not any(item["value"] == "抽取" for item in actions(result))
    assert ("action", "抽取", "stated") not in business_conditions(result)


def test_literal_extraction_is_preserved_beside_equipment_name():
    result = profile("抽油泵已停机，人员抽油。")
    assert [(item["value"], item["reference"]["quote"]) for item in actions(result)] == [("抽取", "抽油")]


def test_field_response_actions_are_separate_from_behavior_and_have_exact_sources():
    text = "巡逻发现车辆。查获原油120升。回收原油100升。已移交原油80升。"
    result = profile(text)
    records = result["field_observations"]["items"]
    assert [item["category"] for item in records] == ["discovery", "seizure", "recovery", "handover"]
    assert actions(result) == []
    assert not any(item[0] == "action" for item in business_conditions(result))
    assert [(item["measurements"][0]["value"], item["measurements"][0]["stage"])
            for item in records if item["measurements"]] == [(120, "seized"), (100, "recovered"), (80, "transferred")]
    for item in records:
        assert item["is_official_fact"] is False
        for row in [item, *item["measurements"]]:
            ref = row["reference"]
            assert text[ref["start"]:ref["end"]] == ref["quote"]
            assert ref["source_sha256"] == result["source_snapshot"]["fields"][0]["sha256"]


@pytest.mark.parametrize("text,kind", [
    ("未移交原油20升。", "negated"),
    ("拟移交原油20升。", "uncertain"),
    ("是否回收原油20升？", "uncertain"),
    ("据称查获原油20升。", "uncertain"),
    ("建议回收原油20升。", "uncertain"),
    ("拒绝移交原油20升。", "uncertain"),
    ("没有证据证明回收原油20升。", "uncertain"),
])
def test_response_polarity_is_not_promoted(text, kind):
    item, = profile(text)["field_observations"]["items"]
    assert item["kind"] == kind
    assert all(row["kind"] == kind and row["is_official_fact"] is False for row in item["measurements"])


@pytest.mark.parametrize("text", [
    "查获车辆载重10吨，原油数量未知。",
    "回收原油若干。",
    "回收原油120。",
    "回收-20升原油。",
    "回收10-20升原油。",
    "回收原油20升以上。",
    "移交人员2名携带原油20升。",
    "回收原油，数量100升。",
    "查获原油20升后移交原油10升。",
    "回收原油" + "9" * 400 + "吨。",
])
def test_capacity_missing_unit_cross_clause_or_ambiguous_stage_is_not_bound(text):
    records = profile(text)["field_observations"]["items"]
    assert records
    assert all(item["measurements"] == [] for item in records)


def test_recovery_does_not_establish_loss_or_police_disposal_and_input_unchanged():
    values = {"description": "回收原油0吨。已移交车辆，公安后续处理未获反馈。"}
    original = deepcopy(values)
    result = build_semantic_profile(values)
    assert values == original
    observations = result["field_observations"]
    assert observations["items"][0]["measurements"][0]["value"] == 0
    assert observations["items"][1]["measurements"] == []
    assert "损失" in observations["boundary"] and "办结" in observations["boundary"]
    assert result["process"]["relations"] == []


def test_field_observation_budget_is_reported_not_silent():
    result = profile("回收原油1升。" * 105)["field_observations"]
    assert len(result["items"]) == 100
    assert result["coverage"]["state"] == "partial"
    assert result["coverage"]["omitted_items"] == 5


def test_quantity_first_keeps_units_and_approximation_without_net_oil_conversion():
    result = profile("回收约20升原油。检斤原油10公斤。未回收原油约5吨。")
    first, second, third = result["field_observations"]["items"]
    assert first["measurements"][0]["value"] == 20
    assert first["measurements"][0]["unit"] == "liter"
    assert first["measurements"][0]["kind"] == "uncertain"
    assert second["measurements"][0]["unit"] == "kg"
    assert second["measurements"][0]["stage"] == "unknown"
    assert third["measurements"][0]["kind"] == "negated"


def test_equipment_names_and_procedure_wording_do_not_claim_completed_recovery():
    result = profile("回收站设备检修。移交清单尚未签字。要求回收原油20升。")
    first, second = result["field_observations"]["items"]
    assert first["category"] == "handover" and first["kind"] == "uncertain"
    assert second["category"] == "recovery" and second["kind"] == "uncertain"


@pytest.mark.parametrize("text", ["回收队到场。", "回收二队出动。", "回收大队配合检查。", "回收人员已到场。"])
def test_unit_and_staff_names_do_not_establish_recovery(text):
    assert profile(text)["field_observations"]["items"] == []


def test_recovery_unit_name_does_not_duplicate_actual_action_or_quantity():
    text = "回收二队回收含水原油：12.64吨。"
    item, = profile(text)["field_observations"]["items"]
    measurement, = item["measurements"]
    assert item["category"] == "recovery"
    assert measurement["value"] == 12.64 and measurement["unit"] == "tonne"
    assert measurement["stage"] == "recovered"
    assert "净油" not in measurement and "loss_amount" not in measurement
    ref = measurement["reference"]
    assert ref["quote"] == text[ref["start"]:ref["end"]] == "原油：12.64吨"
