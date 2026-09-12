from app.services.facility_history_conditions import facility_history_match
import pytest


def context(**changes):
    row = {"case_id": 3, "source_fields": {"facility_type": "井口", "oil_type": "原油"},
           "shared_conditions": [["method", "打孔盗油", "stated"], ["facility", "井口", "stated"]],
           "different_conditions": [], **changes}
    return {"state": "ready", "records": [row]}


def test_similar_type_conditions_do_not_create_actual_facility_links():
    result = facility_history_match(context(), asset_type="well", oil_type="原油", verified=True)
    assert result["state"] == "matched" and result["case_ids"] == [3]
    assert "实际涉案关系" in result["counter"][0]
    assert "不是全库数量统计" in result["support"][0]


def test_opposition_missing_oil_or_unverified_facility_do_not_match():
    values = context(different_conditions=[["method", "打孔盗油", "negated"]])
    assert facility_history_match(values, asset_type="well", oil_type="原油", verified=True)["state"] == "unknown"
    assert facility_history_match(context(), asset_type="well", oil_type=None, verified=True)["state"] == "unknown"
    assert facility_history_match(context(), asset_type="well", oil_type="原油", verified=False)["state"] == "unknown"


@pytest.mark.parametrize("kind", ["negated", "uncertain", "missing"])
def test_nonaffirmative_conditions_cannot_supply_history_support(kind):
    for conditions in (
        [["method", "打孔盗油", kind], ["facility", "井口", "stated"]],
        [["method", "打孔盗油", "stated"], ["facility", "井口", kind]],
    ):
        result = facility_history_match(context(shared_conditions=conditions),
            asset_type="well", oil_type="原油", verified=True)
        assert result["state"] == "unknown" and not result["case_ids"]
