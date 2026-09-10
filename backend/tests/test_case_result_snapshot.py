import pytest

from app.models.case_insight import CaseAnalysisRun, CaseHypothesis
from app.models.case_pipeline import CaseAnalysisProfile
from app.services.case_result_snapshot import assemble_case_result, verify_snapshot


def inputs():
    profile = CaseAnalysisProfile(id="profile-1", case_id=1, profile_version=1, source_hash="source-1",
        schema_version="4.1.0", dictionary_version="rules-1", payload={
            "source_hash": "source-1", "standard": {"location": "合成地点"},
            "semantics": {"assertions": [{"kind": "negated", "value": "罐车"}]}})
    run = CaseAnalysisRun(id="run-1", case_id=1, case_profile_id="profile-1",
        map_snapshot_id="map-1", algorithm_version="algorithm-1", status="completed", information_gaps=[])
    candidate = CaseHypothesis(id="candidate-1", case_id=1, analysis_run_id="run-1", rank=1,
        hypothesis_type="source", title="测试候选", claim="仅用于测试", region=None, score=12,
        score_components={"test": 12}, evidence_refs=["case_profile:profile-1"],
        supporting_evidence=["合成证据"], counter_evidence=[], information_gaps=["尚未核实"],
        boundary="仅供核查", status="candidate")
    return profile, run, candidate


def test_result_is_deterministic_and_source_mutation_does_not_change_frozen_content():
    profile, run, candidate = inputs()
    result = assemble_case_result(profile, run, [candidate])
    assert result == assemble_case_result(profile, run, [candidate])
    assert verify_snapshot(result)
    candidate.supporting_evidence.append("后续新增证据")
    profile.payload["standard"]["location"] = "修改后的地点"
    assert result["content"]["facts_summary"]["recorded_fields"]["location"] == "合成地点"
    assert len(result["content"]["candidates"][0]["supporting_evidence"]) == 1
    assert result["content_sha256"] != assemble_case_result(profile, run, [candidate])["content_sha256"]
    assert result["content"]["semantics"]["assertions"][0]["kind"] == "negated"


@pytest.mark.parametrize("field,value", [("case_id", 2), ("case_profile_id", "old-profile"), ("map_snapshot_id", None)])
def test_result_cannot_mix_case_or_profile_versions(field, value):
    profile, run, candidate = inputs()
    setattr(run, field, value)
    with pytest.raises(ValueError):
        assemble_case_result(profile, run, [candidate])


@pytest.mark.parametrize("field,value", [
    ("case_id", 2), ("analysis_run_id", "other-run"), ("evidence_refs", []),
    ("supporting_evidence", []), ("information_gaps", []), ("rank", 0), ("score", float("nan")),
])
def test_incomplete_or_mismatched_candidate_is_rejected(field, value):
    profile, run, candidate = inputs()
    setattr(candidate, field, value)
    with pytest.raises(ValueError):
        assemble_case_result(profile, run, [candidate])


def test_partial_profile_does_not_invent_analysis_and_tampering_invalidates_digest():
    profile, _, _ = inputs()
    result = assemble_case_result(profile, None, [])
    assert result["content"]["candidates"] == []
    assert result["content"]["analysis_status"] == "not_generated"
    result["content"]["case_id"] = 2
    assert not verify_snapshot(result)


def test_map_or_algorithm_version_changes_snapshot_identity():
    profile, run, candidate = inputs()
    original = assemble_case_result(profile, run, [candidate])
    run.map_snapshot_id = "map-2"
    changed_map = assemble_case_result(profile, run, [candidate])
    assert original["content_sha256"] != changed_map["content_sha256"]
    run.algorithm_version = "algorithm-2"
    assert changed_map["content_sha256"] != assemble_case_result(profile, run, [candidate])["content_sha256"]


def test_profile_payload_cannot_identify_another_case():
    profile, run, candidate = inputs()
    profile.payload["case_id"] = 2
    with pytest.raises(ValueError, match="profile_case_mismatch"):
        assemble_case_result(profile, run, [candidate])
