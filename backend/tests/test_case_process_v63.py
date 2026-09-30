"""R07 provenance and unknown-relation acceptance, with synthetic inputs only."""
from copy import deepcopy

import pytest

from app.config import settings
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.case_source import CaseRevision
from app.services.case_pipeline_service import CASE_PROFILE_SCHEMA_VERSION, CasePipelineService
from app.services.case_process_contract import digest, validate_process
from app.services.case_semantic_service import build_semantic_profile
from app.services.case_service import CaseService
from tests.test_case_sources_v61 import db  # noqa: F401


def semantic(text="先抽取原油，随后转运。", *, revision=7, locations=None, measurements=None):
    payload = {"case": {"description": text}, "locations": locations or [], "measurements": measurements or []}
    return build_semantic_profile(payload["case"], source_revision_id=revision,
                                  source_hash=digest(payload), source_payload=payload)


def location():
    return {"role": "discovery", "description": "合成发现地点", "precision": "unknown",
            "geometry": None, "source_note": "仅记录发现位置"}


def measurement(**changes):
    return {"value": 120.0, "unit": "liter", "stage": "seized", "method": None,
            "measured_at": None, "water_cut": None, "water_cut_basis": None,
            "source_note": "合成计量记录", **changes}


def test_explicit_sequence_does_not_inherit_objects_between_clauses():
    result = semantic()
    process = result["process"]
    first, second = process["events"]
    relation, = process["relations"]
    assert first["objects"][0]["value"] == "原油"
    assert second["objects"] == [] and "object" in second["missing_dimensions"]
    assert relation["from_event_id"] == first["id"] and relation["to_event_id"] == second["id"]
    assert relation["reference"]["quote"] == "先抽取原油，随后转运。"
    assert relation["judgment_status"] == "rule_candidate" and relation["is_official_fact"] is False
    assert first["reference"]["source_revision_id"] == 7
    assert first["reference"]["snapshot_path"] == ["case", "description"]
    assert result["event_fragments"]["items"][0]["relation_status"] == "sentence_cooccurrence_only"
    validate_process(process, result["source_snapshot"])


@pytest.mark.parametrize("text", ["抽取原油。转运原油。", "次日在村屯存放原油。", "先抽取原油。另一条记录。随后转运。"])
def test_text_order_or_missing_anchor_does_not_invent_sequence(text):
    process = semantic(text)["process"]
    assert process["relations"] == []
    if text.startswith("次日"):
        assert process["events"][0]["time_intervals"] == []
        assert any(item["code"] == "relative_time_requires_anchor" for item in process["gaps"])


def test_unknown_context_is_kept_separate_without_unit_or_stage_conversion():
    inputs = [measurement(), measurement(value=0.05, unit="tonne", stage="recovered")]
    result = semantic("抽取原油。", locations=[location()], measurements=inputs)
    process = result["process"]
    event, = process["events"]
    assert event["locations"] == [] and event["measurements"] == []
    context = process["structured_context"]
    assert context["locations"][0]["role"] == "discovery"
    assert [(item["value"], item["unit"], item["stage"]) for item in context["measurements"]] == [
        (120.0, "liter", "seized"), (0.05, "tonne", "recovered")]
    ref = context["measurements"][0]["reference"]
    assert ref["snapshot_path"] == ["measurements", 0] and ref["source_revision_id"] == 7
    inputs[0]["value"] = 999
    assert ref["value"]["value"] == 120.0
    validate_process(process, result["source_snapshot"])


def test_explicit_place_roles_and_oil_measurement_have_local_evidence_only():
    process = semantic("从东井场转运至西村屯。发现原油120升。货车载重10吨。")["process"]
    transfer, oil, vehicle = process["events"]
    roles = [item for item in transfer["locations"] if item["role"] != "unknown"]
    assert [(item["value"], item["role"]) for item in roles] == [("东井场", "source"), ("西村屯", "destination")]
    assert all(item["role_reference"]["quote"] == "从东井场转运至西村屯" for item in roles)
    assert oil["measurements"][0]["value"] == 120 and oil["measurements"][0]["unit"] == "liter"
    assert oil["measurements"][0]["stage"] == "unknown"
    assert vehicle["measurements"] == []


def test_opposing_statements_keep_both_sources_and_do_not_resolve_fact():
    process = semantic("抽取原油。未抽取原油。")["process"]
    conflict = next(item for item in process["conflicts"] if item["category"] == "action")
    assert conflict["status"] == "needs_context_review" and len(conflict["event_ids"]) == 2
    assert [item["quote"] for item in conflict["references"]] == ["抽取原油。", "未抽取原油。"]
    assert conflict["references"][0]["start"] != conflict["references"][1]["start"]
    assert [item["statement_kind"] for item in process["events"]] == ["stated", "negated"]


def test_conflict_reference_cannot_be_moved_to_a_different_event():
    result = semantic("抽取原油。未抽取原油。销售柴油。")
    result["process"]["conflicts"][0]["references"][0] = deepcopy(result["process"]["events"][2]["reference"])
    with pytest.raises(ValueError, match="conflict_reference"):
        validate_process(result["process"], result["source_snapshot"])


def test_unknown_source_snapshot_schema_is_not_accepted():
    result = semantic()
    result["source_snapshot"]["schema_version"] = "future-unknown"
    with pytest.raises(ValueError, match="unsupported_process_source"):
        validate_process(result["process"], result["source_snapshot"])


@pytest.mark.parametrize("mutation", [
    lambda p: p["events"][0]["reference"].update(start=True),
    lambda p: p["events"][0]["reference"].update(quote="伪造原文"),
    lambda p: p["events"][0]["reference"].update(source_sha256="a" * 64),
    lambda p: p["events"][0]["reference"].update(source_revision_id=9),
    lambda p: p["events"][0]["reference"].update(snapshot_path=["case", "location"]),
    lambda p: p["events"][0].update(is_official_fact=True),
    lambda p: p["events"][0].update(is_official_fact=0),
    lambda p: p.update(source_hash=None),
    lambda p: p["relations"][0].update(to_event_id="missing"),
    lambda p: p["relations"][0].update(type="same_actor"),
    lambda p: p["events"][0].update(judgment_status="verified"),
    lambda p: p["structured_context"]["locations"][0].update(role="incident"),
    lambda p: p["structured_context"]["measurements"][0]["reference"].update(snapshot_path=["measurements", True]),
    lambda p: p["structured_context"]["measurements"][0]["reference"].update(source_sha256="a" * 64),
    lambda p: p["structured_context"]["measurements"][0]["reference"]["value"].update(value=999.0),
    lambda p: p["structured_context"]["snapshots"][1]["value"][0].update(value=999.0),
])
def test_tampered_process_cannot_pass_source_validation(mutation):
    result = semantic(locations=[location()], measurements=[measurement()])
    mutation(result["process"])
    with pytest.raises(ValueError):
        validate_process(result["process"], result["source_snapshot"])


def test_revision_hash_and_text_must_match_and_missing_revision_is_explicit():
    payload = {"case": {"description": "抽取原油。"}}
    with pytest.raises(ValueError, match="revision_payload_hash"):
        build_semantic_profile(payload["case"], source_revision_id=7, source_hash="a" * 64, source_payload=payload)
    with pytest.raises(ValueError, match="revision_text"):
        build_semantic_profile({"description": "转运原油。"}, source_revision_id=7,
                               source_hash=digest(payload), source_payload=payload)
    process = build_semantic_profile(payload["case"])["process"]
    assert process["source_revision_id"] is None
    assert any(item["code"] == "source_revision_unavailable" for item in process["gaps"])


def test_process_budget_reports_uncovered_clauses():
    result = semantic("转运原油，" * 105)
    assert len(result["process"]["events"]) == 100
    assert result["process"]["coverage"]["state"] == "partial"
    assert result["process"]["coverage"]["omitted_fragments"] == 5


def test_nonfinite_text_quantity_does_not_break_profile_or_become_measurement():
    process = semantic("原油" + "9" * 400 + "吨。")["process"]
    assert process["events"][0]["measurements"] == []


def test_frozen_numeric_measurement_preserves_json_number_without_coercing_source():
    process = semantic(measurements=[measurement(value=120)])["process"]
    assert process["structured_context"]["measurements"][0]["reference"]["value"]["value"] == 120


def test_supplement_creates_revision_bound_process_and_keeps_previous_frozen(db, monkeypatch):
    monkeypatch.setattr(settings, "CASE_SEMANTIC_MODEL_ID", None)
    case = CaseService.create_case(db, case_number="R07-SYNTHETIC", description="抽取原油。",
                                  initial_locations=[location()], initial_measurements=[measurement()])
    first_event = db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").one()
    CasePipelineService.process_event(db, first_event.id)
    first = db.query(CaseAnalysisProfile).one()
    original = deepcopy(first.payload)
    assert first.schema_version == CASE_PROFILE_SCHEMA_VERSION == "6.3.0"
    old_process = first.payload["semantics"]["process"]
    assert old_process["source_revision_id"] == db.query(CaseRevision).one().id
    assert old_process["structured_context"]["measurements"][0]["reference"]["value"]["unit"] == "liter"
    CaseService.update_case(db, case.id, description="先抽取原油，随后转运。",
                            initial_measurements=[measurement(value=130.0)])
    newest = db.query(OutboxEvent).filter_by(event_type="case.analysis.requested", status="pending").one()
    CasePipelineService.process_event(db, newest.id)
    profiles = db.query(CaseAnalysisProfile).order_by(CaseAnalysisProfile.profile_version).all()
    assert len(profiles) == 2 and profiles[0].payload == original
    new_process = profiles[1].payload["semantics"]["process"]
    assert new_process["source_revision_id"] != old_process["source_revision_id"]
    assert new_process["structured_context"]["measurements"][0]["value"] == 130.0
    assert new_process["relations"] and not old_process["relations"]
    assert profiles[0].is_current is False and profiles[1].is_current is True
