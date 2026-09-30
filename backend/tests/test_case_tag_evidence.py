"""Compatibility tags must not turn negation or derived text into facts."""
from copy import deepcopy
from datetime import datetime

import pytest

from app.models.case import Case
from app.services.case_intelligence_service import CaseIntelligenceService as Service
from test_case_intelligence import _session


@pytest.fixture
def db():
    session = _session()
    yield session
    session.close()


def make_case(db, description, **fields):
    case = Case(case_number="SYNTHETIC-POLARITY", description=description,
                occurred_time=datetime(2026, 9, 27, 12), location="合成地点", **fields)
    db.add(case)
    db.commit()
    return case


@pytest.mark.parametrize("description", ["未发现罐车", "无罐车", "罐车不在现场", "疑似罐车"])
def test_non_affirmative_vehicle_is_not_positive_tag(db, description):
    result = Service.build_case_tags(db, make_case(db, description))
    assert "vehicle_tanker" not in {tag["key"] for tag in result["tags"]}
    observation = next(item for item in result["observations"] if item["key"] == "vehicle_tanker")
    assert observation["kind"] in {"negated", "uncertain"}
    assert observation["references"][0]["quote"] == description


def test_negation_uncertainty_conflict_and_turning_clause(db):
    result = Service.build_case_tags(db, make_case(
        db, "未发现罐车，但发现油桶。疑似软管。发现皮卡。未发现皮卡。",
    ))
    keys = {tag["key"] for tag in result["tags"]}
    assert "tool_oil_bucket" in keys
    assert not {"vehicle_tanker", "tool_hose", "vehicle_pickup"} & keys
    assert any(item["kind"] == "conflicting" for item in result["observations"])


def test_derived_text_and_false_dictionary_keys_cannot_create_tags(db):
    case = make_case(db, "正在整理现场记录。", features={
        "analysis": "罐车使用油泵", "intelligence": {
            "tag_overrides": {"removed_keys": ["软管"], "added": []},
            "old_report": "皮卡和油桶",
        },
    }, vehicle_info={"套牌": False}, involved_items={"软管": False})
    before = deepcopy(case.features)
    result = Service.build_case_tags(db, case)
    assert not [tag for tag in result["tags"] if tag["category"] in {"vehicle", "tool"}]
    assert case.features == before


def test_structured_text_has_path_evidence_and_manual_tag_stays_separate(db):
    case = make_case(db, "未发现罐车", involved_items={"说明": "发现油桶"}, features={
        "intelligence": {"tag_overrides": {"added": [{
            "key": "vehicle_tanker", "label": "人工记录的罐车", "category": "vehicle",
            "basis": ["人工核验记录"],
        }]}},
    })
    result = Service.build_case_tags(db, case)
    tags = {tag["key"]: tag for tag in result["tags"]}
    assert tags["vehicle_tanker"]["manual"] is True
    assert tags["tool_oil_bucket"]["references"][0]["path"] == ["说明"]
    assert any(item["kind"] == "negated" for item in result["observations"])


def test_map_absence_does_not_prove_remoteness_or_defense_gap(db, monkeypatch):
    case = make_case(db, "井场记录", facility_type="井口")
    monkeypatch.setattr(Service, "_safe_case_context", lambda *_: {
        "state": "ready", "nearest": {"road": {"distance_km": 0.2}, "tech": {"distance_km": 2}},
    })
    result = Service.build_case_tags(db, case)
    labels = {tag["label"] for tag in result["tags"]}
    assert "道路通达" not in labels
    assert not {"偏远井场", "近距离技防不足"} & labels
    assert "邻近已登记道路" in labels
    assert result["information_gaps"]


def test_non_affirmative_evidence_remains_in_card_and_model_gaps(db):
    case = make_case(db, "未发现罐车。疑似软管。")
    before = deepcopy(case.features)
    workbench = Service.build_workbench(db, case_id=case.id)
    card = workbench["experience_card"]
    assert not any("罐车" in value or "软管" in value for value in card["why_it_matters"])
    assert card["evidence_basis"]["observations"]
    assert any("否定" in value for value in workbench["context_pack"]["information_gaps"])
    assert not any("技防覆盖待核实" in value for value in card["protection_shortcomings"])
    assert case.features == before


def test_new_preview_does_not_inherit_or_overwrite_historical_confirmation(db):
    historical = {"manual_review_status": "confirmed", "summary": "人工确认的旧版内容"}
    case = make_case(db, "未发现罐车", features={"intelligence": {"experience_card": historical}})
    preview = Service.build_experience_card(db, case.id, persist=False)
    assert preview["manual_review_status"] == "pending"
    assert Service.build_experience_card(db, case.id, persist=True) == historical
    db.refresh(case)
    assert case.features["intelligence"]["experience_card"] == historical


@pytest.mark.parametrize("vehicle_info", [
    {"未发现": ["罐车"]},
    {"vehicle_type": "罐车", "status": "疑似"},
    {"vehicle_type": "罐车", "confirmed": False},
    {"vehicle_type": "罐车", "description": "未发现"},
])
def test_structured_context_cannot_be_lost(db, vehicle_info):
    case = make_case(db, "现场资料待整理", vehicle_info=vehicle_info)
    result = Service.build_case_tags(db, case)
    assert "vehicle_tanker" not in {tag["key"] for tag in result["tags"]}
    assert any(item["key"] == "vehicle_tanker" and item["kind"] == "uncertain"
               for item in result["observations"])
