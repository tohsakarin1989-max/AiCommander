from copy import deepcopy

import pytest

from app.services.facility_production_conditions import production_comparison


def compare(**changes):
    attributes = {"water_cut_min": 20, "water_cut_max": 40, "water_cut_unit": "percent",
        "production_valid_from": "2026-09-01T00:00:00Z", "production_valid_to": "2026-10-01T00:00:00Z"}
    params = {"attributes": attributes, "verified": True,
              "case_fields": {"occurred_time": "2026-09-12T00:00:00Z"}, "case_facts": {"water_cut": 30}}
    params.update(changes)
    return production_comparison(**params)


def test_comparison_uses_declared_interval_without_risk_or_production_bonus():
    value = compare()
    assert value["state"] == "matched" and value["support"] and value["counter"]
    assert value["comparison"]["unit"] == "percent"
    assert compare(case_facts={"water_cut": 45})["state"] == "different"
    assert compare(attributes={"production_output": 10000, "is_high_production": True})["state"] == "unknown"


@pytest.mark.parametrize("value", [None, True, "30", float("nan"), -1, 101])
def test_invalid_or_missing_case_measurement_is_unknown(value):
    assert compare(case_facts={"water_cut": value})["state"] == "unknown"


@pytest.mark.parametrize("change", [
    {"water_cut_unit": "fraction"}, {"water_cut_min": 60}, {"water_cut_max": float("inf")},
    {"production_valid_to": "2026-09-01T00:00:00Z"}, {"production_valid_from": "2026-09-15T00:00:00Z"},
    {"production_valid_from": "2026-09-01"},
])
def test_unknown_units_expiry_and_bad_ranges_never_become_mismatch(change):
    attributes = {"water_cut_min": 20, "water_cut_max": 40, "water_cut_unit": "percent",
        "production_valid_from": "2026-09-01T00:00:00Z", "production_valid_to": "2026-10-01T00:00:00Z", **change}
    original = deepcopy(attributes)
    result = compare(attributes=attributes)
    assert result["state"] == "unknown" and result["gaps"] and not result["support"]
    assert attributes == original


def test_unverified_map_claim_and_missing_case_time_stay_unknown():
    assert compare(verified=False)["state"] == "unknown"
    assert compare(case_fields={})["state"] == "unknown"
