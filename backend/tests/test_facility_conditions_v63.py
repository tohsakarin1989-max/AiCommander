"""Source-bounded condition comparisons; no live database or road engine."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from app.services.facility_conditions_v63 import entrance_state, compare_rankings
from app.models.map_foundation import JurisdictionAssetVersion, MapSnapshotFeature, MapSource
from app.services.case_facility_comparison import compare_case_facilities
from app.services.facility_candidate_pool import require_current_pool_source, validate_pool_access
from app.services.case_road_artifact_service import freeze_road_artifact, read_road_artifact
from test_case_facility_comparison import prepared, ready, db_session, result_data, freeze, VEHICLE  # noqa: F401
from test_road_access_policy import AT


@pytest.mark.parametrize("reasons,expected", [
    (["vehicle_limit_exceeded"], "restricted"),
    (["explicitly_closed", "vehicle_limit_exceeded"], "restricted"),
    (["explicitly_closed", "vehicle_dimensions_missing"], "entrance_unknown"),
    (["conditions_expired"], "entrance_unknown"),
    ([], "entrance_unknown"),
])
def test_only_all_explicit_entry_limits_exclude(reasons, expected):
    entries = [{"eligible": False, "reason": reason} for reason in reasons]
    assert entrance_state(entries, source_verified=True) == expected
    assert entrance_state(entries + [{"eligible": True, "reason": "eligible"}],
                          source_verified=True) == "not_calculated"


def comparison(rank=1, state="unknown", refs=None):
    return {"schema_version": "facility-conditions-6.3-1", "rows": [{
        "asset_id": 1, "name": "合成设施", "rank": rank, "score": 1,
        "conditions": [{"key": "production", "state": state,
            "reason": "合成比较", "evidence_refs": refs or ["asset_version:1"], "dependencies": []}]}]}


def test_rank_change_requires_real_baseline_and_does_not_claim_single_cause():
    old = comparison()
    current = comparison(2, "supported", ["asset_version:2"])
    baseline = {"artifact_id": "old", "content_sha256": "old-hash"}
    result = compare_rankings(current, old, baseline=baseline, context_changes=["network", "algorithm"])
    assert result["state"] == "compared"
    row = result["changes"][0]
    assert (row["previous_rank"], row["current_rank"]) == (1, 2)
    assert row["changed_conditions"][0]["evidence_refs"] == ["asset_version:2"]
    assert any("不能归因" in reason for reason in row["reasons"])
    assert compare_rankings(current, None)["state"] == "no_baseline"
    assert old == comparison()  # Comparisons never rewrite a saved result.


def test_identical_conditions_do_not_claim_new_information():
    old = comparison()
    assert compare_rankings(deepcopy(old), old,
        baseline={"artifact_id": "old", "content_sha256": "hash"})["changes"] == []


def append_history(db, asset_id, *, attributes=None, known_at=None, **changes):
    previous = db.query(JurisdictionAssetVersion).filter_by(asset_id=asset_id).order_by(
        JurisdictionAssetVersion.version.desc()).first()
    snapshot = deepcopy(previous.snapshot)
    if attributes is not None:
        snapshot["attributes"] = {**snapshot["attributes"], **attributes}
    values = {"asset_id": asset_id, "version": previous.version + 1, "snapshot": snapshot,
              "change_type": "synthetic_correction", "temporal_status": "declared",
              "valid_from": previous.valid_from, "valid_to": previous.valid_to,
              "known_at": known_at or datetime.now(timezone.utc) - timedelta(seconds=1), **changes}
    row = JurisdictionAssetVersion(**values)
    db.add(row)
    db.commit()
    return row


def compare(prepared, tmp_path):
    db, source, _ = prepared
    return compare_case_facilities(db, result_id=source["id"], network_id="graph-1", analysis_at=AT,
                                  vehicle=VEHICLE, artifact_root=tmp_path)


def test_all_recalled_facilities_have_four_state_conditions_and_concrete_gaps(prepared, tmp_path):
    value = compare(prepared, tmp_path)
    result = value["result"]
    assert result["algorithm_version"] == "facility-roads-6.3.0-1"
    assert len(result["candidates"]) == 3
    assert len(result["all_candidates"]) == len(result["condition_comparison"]["rows"]) == 12
    rows = result["condition_comparison"]["rows"]
    assert {row["rank"] for row in rows} == set(range(1, 13))
    by_id = {row["asset_id"]: {condition["key"]: condition for condition in row["conditions"]} for row in rows}
    assert by_id[13]["oil"]["state"] == "supported"
    assert by_id[2]["oil"]["state"] == "different"
    assert by_id[2]["production"]["state"] == "unknown"
    assert any(ref.startswith("asset_version:") for ref in by_id[13]["oil"]["evidence_refs"])
    assert all(gap["dependencies"] and gap["asset_ids"] for gap in result["condition_comparison"]["priority_gaps"])
    assert len(result["condition_comparison"]["priority_gaps"]) <= 3
    assert result["ranking_changes"]["state"] == "no_baseline"


def test_missing_historical_declaration_never_uses_current_matching_map(prepared, tmp_path):
    db, _, _ = prepared
    db.query(JurisdictionAssetVersion).filter_by(asset_id=13).delete(synchronize_session=False)
    db.commit()
    value = compare(prepared, tmp_path)
    asset = next(row for row in value["pool"]["assets"] if row["asset_id"] == 13)
    assert asset["oil_match"] == asset["production_comparison"]["state"] == "unknown"
    row = next(row for row in value["result"]["condition_comparison"]["rows"] if row["asset_id"] == 13)
    assert row["source_context"]["version_id"] is None
    assert row["source_context"]["state"] == "unknown"
    assert next(item for item in row["conditions"] if item["key"] == "source")["dependencies"]


def test_late_production_correction_freezes_true_changes_without_rewriting_history(prepared, tmp_path):
    db, _, _ = prepared
    old = compare(prepared, tmp_path)
    saved = freeze_road_artifact(db, old)
    db.commit()
    frozen_old = read_road_artifact(db, saved["id"])
    version = append_history(db, 2, attributes={"oil_type": "原油"})
    value = compare(prepared, tmp_path)
    change = value["result"]["ranking_changes"]
    assert change["state"] == "compared"
    assert change["baseline"] == {"artifact_id": saved["id"], "content_sha256": saved["content_sha256"]}
    item = next(row for row in change["changes"] if row["asset_id"] == 2)
    assert item["current_rank"] < item["previous_rank"]
    oil = next(row for row in item["changed_conditions"] if row["key"] == "oil")
    assert oil["previous_state"] == "different" and oil["current_state"] == "supported"
    assert f"asset_version:{version.id}" in oil["evidence_refs"]
    assert read_road_artifact(db, saved["id"]) == frozen_old
    validate_pool_access(db, old["pool"])
    with pytest.raises(ValueError, match="production_changed"):
        require_current_pool_source(db, old["pool"])
    freeze_road_artifact(db, value)


def test_future_received_or_outside_business_period_not_used(prepared, tmp_path):
    db, source, _ = prepared
    original = freeze(db, source)
    append_history(db, 2, attributes={"oil_type": "原油"},
                   known_at=datetime.now(timezone.utc) + timedelta(days=1))
    current = freeze(db, source)
    find = lambda pool: next(row for row in pool["assets"] if row["asset_id"] == 2)
    assert find(original)["production_context"]["version_id"] == find(current)["production_context"]["version_id"]
    assert find(current)["oil_match"] == "different"
    append_history(db, 13, attributes={"oil_type": "柴油"}, valid_from=AT + timedelta(days=10),
                   valid_to=AT + timedelta(days=20))
    assert next(row for row in freeze(db, source)["assets"] if row["asset_id"] == 13)["oil_match"] == "matched"


def test_unavailable_baseline_only_source_is_never_exposed_in_new_changes(prepared, tmp_path):
    db, _, _ = prepared
    db.add(MapSource(id=11, operational_area_id=1, source_key="historic-production", name="合成生产来源",
                     source_type="internal_gis", status="active"))
    db.commit()
    append_history(db, 13, attributes={"source_id": 11})
    old = compare(prepared, tmp_path)
    saved = freeze_road_artifact(db, old)
    db.commit()
    db.query(MapSnapshotFeature).filter_by(asset_id=13).update({"status": "inactive"})
    db.query(MapSource).filter_by(id=11).update({"status": "inactive"})
    db.commit()
    with pytest.raises(PermissionError, match="production_unavailable"):
        read_road_artifact(db, saved["id"])
    value = compare(prepared, tmp_path)
    assert value["result"]["ranking_changes"]["baseline"] is None
    assert value["result"]["ranking_changes"]["changes"] == []
    assert 13 not in [row["asset_id"] for row in value["result"]["condition_comparison"]["rows"]]


def test_last_history_lookup_exceeding_budget_cannot_claim_complete(prepared, monkeypatch):
    from types import SimpleNamespace
    from app.services import facility_candidate_pool as service
    ticks = iter([0, *([0] * 12), 6])
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    db, source, _ = prepared
    pool = freeze(db, source)
    assert pool["coverage"]["scanned"] == 12
    assert pool["coverage"]["complete"] is False
    assert pool["coverage"]["scan_complete"] is False


def test_old_scoring_input_version_replays_original_algorithm():
    from app.services.frozen_facility_inputs import replay_facility_inputs
    from app.services.frozen_insight_inputs import checksum
    from app.services.scorers.facility_roads_v52 import FacilityEvidence, VERSION, rank_facilities
    from app.services.scorers.registry import resolve_facility_scorer
    row = FacilityEvidence(asset_id=1, evidence_ref="map_asset:1@snapshot:old", straight_distance_m=100,
                           road_state="calculated", road_distance_m=500, entrance_verified=True, passage_allowed=True)
    payload = {"facility_evaluation": {"input_schema": "facility-scoring-inputs-5.2-1",
        "algorithm_version": VERSION, "scorer_checksum": resolve_facility_scorer(VERSION)[1],
        "evidence": [asdict(row)], "recall_complete": True}}
    result = replay_facility_inputs({"payload": payload, "checksum": checksum(payload)})
    assert result["candidates"][0]["score"] == rank_facilities([row], recall_complete=True)["candidates"][0]["score"]
    assert result["status"] == "completed"


def test_equal_trust_conflict_and_public_source_are_not_historical_support(prepared, tmp_path):
    from app.models.map_foundation import FacilitySourceIdentity
    db, _, _ = prepared
    db.add(MapSource(id=11, operational_area_id=1, source_key="another-production", name="合成来源",
                     source_type="internal_gis", status="active"))
    db.flush()
    identity = FacilitySourceIdentity(source_id=11, operational_area_id=1, native_asset_id=2,
        identity_key="id:second", source_record_id="second", asset_type="well", identity_kind="exact_id")
    db.add(identity)
    db.commit()
    append_history(db, 2, attributes={"source_id": 11, "oil_type": "原油"}, source_identity_id=identity.id)
    value = compare(prepared, tmp_path)
    asset = next(row for row in value["pool"]["assets"] if row["asset_id"] == 2)
    assert asset["production_context"]["state"] == "conflict" and asset["oil_match"] == "unknown"
    db.query(MapSource).filter_by(id=11).update({"source_type": "public_map"})
    db.commit()
    append_history(db, 13, attributes={"source_id": 11})
    value = compare(prepared, tmp_path)
    asset = next(row for row in value["pool"]["assets"] if row["asset_id"] == 13)
    assert asset["production_context"]["state"] == "unavailable" and asset["oil_match"] == "unknown"


def test_road_exclusion_unknown_and_no_path_are_distinct_in_full_output(prepared, tmp_path, monkeypatch):
    from app.services import facility_candidate_pool as pool_service, facility_road_batches as batches
    original = pool_service.verified_entrances
    matrix = batches.calculate_distance_matrix
    def entries(*args, **kwargs):
        result = original(*args, **kwargs)
        result[2][0].update(eligible=False, reason="vehicle_limit_exceeded")
        closed = {**result[3][0], "eligible": False, "reason": "explicitly_closed"}
        result[3][0].update(eligible=False, reason="vehicle_dimensions_missing")
        result[3].append(closed)
        return result
    def no_path(*args, **kwargs):
        result = matrix(*args, **kwargs)
        for point, cell in zip(kwargs["targets"], result["cells"]):
            if round((point.longitude - 125) * 1000) == 4:
                cell.update(status="no_path_found", distance_m=None)
        return result
    monkeypatch.setattr(pool_service, "verified_entrances", entries)
    monkeypatch.setattr(batches, "calculate_distance_matrix", no_path)
    value = compare(prepared, tmp_path)
    rows = {row["asset_id"]: row for row in value["result"]["condition_comparison"]["rows"]}
    road = lambda identifier: next(c for c in rows[identifier]["conditions"] if c["key"] == "road")
    assert rows[2]["eligibility"] == "excluded" and road(2)["state"] == "hard_excluded"
    assert rows[3]["eligibility"] == "unresolved" and road(3)["state"] == "unknown"
    assert road(4)["state"] == "unknown" and "不证明现实" in road(4)["reason"]
    assert not value["result"]["coverage"]["complete"]
    assert all(rows[i]["rank"] is None for i in (2, 3, 4))


def bind_revision(prepared):
    from app.models.case import Case
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.services.case_pipeline_service import CasePipelineService
    from app.services.case_result_service import CaseResultService
    from app.services.case_source_service import CaseSourceService
    db, _, _ = prepared
    case = db.get(Case, 1)
    revision, _ = CaseSourceService.capture_change(db, case)
    profile = db.get(CaseAnalysisProfile, "profile-1")
    profile.source_revision_id = revision.id
    profile.payload = CasePipelineService.build_profile_payload(db, case)
    db.flush()
    # A snapshot frozen before the revision existed cannot be rebound by
    # mutating its profile. Freeze a matching source-backed result instead.
    source, _ = CaseResultService.create_current(db, case.id)
    db.commit()
    return case, profile, revision, source


def edit_and_restore(db, case):
    from app.services.case_source_service import CaseSourceService
    original = case.description
    case.description = "合成 B 修订"
    CaseSourceService.capture_change(db, case)
    case.description = original
    revision, _ = CaseSourceService.capture_change(db, case)
    db.commit()
    return revision


def test_revision_round_trip_cannot_start_or_publish_new_roads_but_history_reads(prepared, tmp_path):
    db, _, calls = prepared
    case, profile, first, source = bind_revision(prepared)
    prepared = db, source, calls
    content = compare(prepared, tmp_path)
    saved = freeze_road_artifact(db, content)
    db.commit()
    frozen = read_road_artifact(db, saved["id"])
    latest = edit_and_restore(db, case)
    assert latest.source_hash == profile.source_hash and latest.id != first.id
    assert profile.is_current
    with pytest.raises(ValueError, match="facility_recall_source_outdated"):
        freeze(db, source)
    with pytest.raises(ValueError, match="facility_recall_source_outdated"):
        require_current_pool_source(db, content["pool"])
    with pytest.raises(ValueError, match="facility_recall_source_outdated"):
        freeze_road_artifact(db, content)
    assert read_road_artifact(db, saved["id"]) == frozen


def test_revision_round_trip_during_routing_is_rejected_before_return(prepared, tmp_path, monkeypatch):
    from app.services import facility_road_batches as batches
    db, _, calls = prepared
    case, _, _, source = bind_revision(prepared)
    prepared = db, source, calls
    original = batches.calculate_distance_matrix
    changed = False
    def matrix(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            edit_and_restore(db, case)
            changed = True
        return result
    monkeypatch.setattr(batches, "calculate_distance_matrix", matrix)
    with pytest.raises(ValueError, match="facility_recall_source_outdated"):
        compare(prepared, tmp_path)


@pytest.mark.parametrize("precision", ["unknown", "interval", "day", None])
def test_typed_nonexact_time_never_uses_stored_timestamp_for_historical_conditions(prepared, precision):
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.services.case_result_service import CaseResultService
    db, _, _ = prepared
    profile = db.get(CaseAnalysisProfile, "profile-1")
    profile.payload = {**profile.payload, "standard": {**profile.payload["standard"], "time_precision": precision}}
    db.commit()
    source, _ = CaseResultService.create_current(db, 1)
    db.commit()
    pool = freeze(db, source)
    assert all(row["production_context"]["valid_at"] is None for row in pool["assets"])
    assert all(row["oil_match"] == "unknown" for row in pool["assets"])
    assert pool["history"]["state"] == "information_missing"
