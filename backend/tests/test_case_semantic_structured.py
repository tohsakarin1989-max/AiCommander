from copy import deepcopy

import pytest

from app.services.case_semantic_structured import extract_structured_sources, resolve_reference


def test_array_paths_keep_types_and_snapshot_is_not_mutated_with_input():
    raw = {"vehicle_info": [{"type": "罐车", "套牌": False, "载重": 0}]}
    result = extract_structured_sources(raw)
    snapshot, = result["snapshots"]
    entries = result["entries"]
    assert len(entries) == 3
    for entry in entries:
        assert resolve_reference(snapshot, entry["reference"]) == entry["reference"]["value"]
        assert "start" not in entry["reference"]
        assert entry["is_official_fact"] is False
    raw["vehicle_info"][0]["type"] = "货车"
    assert snapshot["value"][0]["type"] == "罐车"


@pytest.mark.parametrize("change", [
    {"path": [True, "type"]}, {"path": [-1, "type"]}, {"path": [1, "type"]},
    {"field": "description"}, {"value": "伪造车辆"}, {"source_sha256": "0" * 64},
])
def test_modified_reference_cannot_pass_validation(change):
    result = extract_structured_sources({"vehicle_info": [{"type": "罐车"}]})
    reference = {**result["entries"][0]["reference"], **change}
    with pytest.raises(ValueError):
        resolve_reference(result["snapshots"][0], reference)


def test_modified_snapshot_and_boolean_number_substitution_are_rejected():
    result = extract_structured_sources({"vehicle_info": {"套牌": False}})
    reference = result["entries"][0]["reference"]
    with pytest.raises(ValueError):
        resolve_reference(result["snapshots"][0], {**reference, "value": 0})
    modified = deepcopy(result["snapshots"][0])
    modified["value"]["套牌"] = True
    with pytest.raises(ValueError):
        resolve_reference(modified, reference)


def test_bad_or_large_data_returns_gap_without_inventing_values():
    result = extract_structured_sources({"vehicle_info": float("nan"), "involved_items": "大" * 400000})
    assert result["entries"] == []
    assert {item["code"] for item in result["information_gaps"]} == {"invalid_structured_source", "structured_source_too_large"}


def test_structured_extraction_is_bounded_and_marks_partial_result():
    result = extract_structured_sources({"involved_items": list(range(250))})
    assert len(result["entries"]) == 200
    assert result["information_gaps"][0]["code"] == "structured_extraction_limit"
