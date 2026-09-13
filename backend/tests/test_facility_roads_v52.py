from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from threading import Event

import pytest

from app.services import facility_road_batches as service
from app.services.road_access_policy import VehicleAssumption
from app.services.scorers.facility_roads_v52 import FacilityEvidence, rank_facilities
from app.services.vehicle_router import RoadLocation, RoadCalculationError


def facility(identifier, **values):
    return FacilityEvidence(**{"asset_id": identifier,
        "evidence_ref": f"map_asset:{identifier}@snapshot:map-1",
        "straight_distance_m": identifier * 1000, "road_state": "calculated",
        "road_distance_m": identifier * 1000, "entrance_verified": True,
        "passage_allowed": True, **values})


def test_more_than_three_facilities_are_compared_before_final_selection():
    rows = [facility(i, road_distance_m=50_000 - i * 1000) for i in range(1, 9)]
    rows[-1] = replace(rows[-1], road_distance_m=8500, oil_match="matched", attribute_refs=("profile:one",))
    result = rank_facilities(rows, recall_complete=True)
    assert result["coverage"]["compared"] == 8
    assert len(result["candidates"]) == 3 and result["candidates"][0]["asset_id"] == 8
    assert result["candidates"][0]["rank_change_from_distance"] == 7
    assert all(item["counter_evidence"] and item["evidence_refs"] and not item["is_official_fact"] for item in result["candidates"])
    assert rank_facilities(list(reversed(rows)), recall_complete=True) == result


def test_hard_permission_and_missing_entry_cannot_be_overcome_by_good_attributes():
    rows = [facility(1, passage_allowed=False, oil_match="matched", attribute_refs=("profile:one",)),
            facility(2, entrance_verified=False), facility(3, passage_allowed=None), facility(4)]
    result = rank_facilities(rows, recall_complete=True)
    assert [item["asset_id"] for item in result["candidates"]] == [4]
    assert [item["state"] for item in result["unresolved"]] == ["restricted", "entrance_unknown", "permission_unknown"]
    assert all(item["score"] is None and item["road_distance_m"] is None for item in result["unresolved"])
    assert not result["coverage"]["complete"]


def test_unknown_failure_no_path_and_missing_network_remain_distinct():
    states = ["no_path_found", "network_missing", "calculation_failed", "not_calculated"]
    rows = [facility(i + 1, road_state=state, road_distance_m=None) for i, state in enumerate(states)]
    result = rank_facilities(rows, recall_complete=False)
    assert not result["candidates"] and [item["state"] for item in result["unresolved"]] == states
    assert result["coverage"]["recall_complete"] is False


def test_detour_changes_ranking_and_unknown_attributes_are_not_matches():
    result = rank_facilities([facility(1, road_distance_m=20_000), facility(2, road_distance_m=2500)], recall_complete=True)
    assert [item["asset_id"] for item in result["candidates"]] == [2, 1]
    assert "明显绕行" in repr(result["candidates"][1]["counter_evidence"])
    assert result["candidates"][0]["components"]["oil_match"] == 0
    assert len(result["candidates"][0]["information_gaps"]) == 4
    assert rank_facilities([facility(1, straight_distance_m=0)], recall_complete=True)["candidates"][0]["detour_ratio"] is None


@pytest.mark.parametrize("values", [{"asset_id": True}, {"straight_distance_m": float("nan")},
    {"road_distance_m": None}, {"road_distance_m": -1}, {"road_state": "no_path_found"},
    {"oil_match": "matched"}, {"entrance_verified": 1}, {"passage_allowed": "yes"}])
def test_invalid_or_unreferenced_inputs_fail_closed(values):
    with pytest.raises(ValueError):
        facility(1, **values)


@pytest.fixture
def batch(monkeypatch):
    db = SimpleNamespace(info={"authorized_area_ids": (1,), "principal_user_id": 1})
    binding = SimpleNamespace(network_id="graph", graph_sha256="hash", policy_revision=1, engine_version="test-engine")
    monkeypatch.setattr(service, "resolve_network", lambda *args, **kwargs: binding)
    calls = []
    def calculate(_db, **kwargs):
        calls.append(kwargs)
        return {"network_id": "graph", "graph_sha256": "hash", "policy_revision": 1,
            "cells": [{"source_index": 0, "target_index": i, "status": "calculated",
                       "distance_m": point.longitude * 1000} for i, point in enumerate(kwargs["targets"])]}
    monkeypatch.setattr(service, "calculate_distance_matrix", calculate)
    def run(count=24, **changes):
        parameters = dict(origin=RoadLocation(longitude=125, latitude=46),
            evidence=[facility(i, road_state="not_calculated", road_distance_m=None) for i in range(1, count + 1)],
            entrances={i: RoadLocation(longitude=125 + i / 1000, latitude=46) for i in range(1, count + 1)},
            network_id="graph", analysis_at=datetime.now(timezone.utc),
            vehicle=VehicleAssumption(kind="auto", source="explicit_reference_assumption"), artifact_root=None,
            source_versions={"case_profile_id": "one", "case_source_hash": "hash", "map_snapshot_id": "map-1", "recall_version": "test"},
            recall_complete=True)
        parameters.update(changes)
        return service.compare_facility_pool(db, **parameters)
    return db, binding, calls, run


def test_matrix_batches_keep_global_order_versions_and_all_targets(batch):
    _, _, calls, run = batch
    result = run()
    assert [len(call["targets"]) for call in calls] == [10, 10, 4]
    assert result["coverage"]["compared"] == 24 and result["coverage"]["complete"]
    assert result["versions"]["scope"] == (1,) and result["versions"]["network_id"] == "graph"
    assert all(0 < call["timeout_seconds"] <= 90 for call in calls)
    assert len(result["candidates"]) == 3


def test_wrong_snapshot_and_duplicate_targets_are_rejected_before_routing(batch):
    _, _, calls, run = batch
    item = facility(1, road_state="not_calculated", road_distance_m=None)
    with pytest.raises(ValueError, match="duplicate"):
        run(evidence=[item, item])
    with pytest.raises(ValueError, match="reference_mismatch"):
        run(evidence=[replace(item, evidence_ref="map_asset:1@snapshot:old-map")])
    assert not calls


def test_unknown_entrance_is_not_snapped_and_failure_does_not_repeat_batches(batch, monkeypatch):
    _, _, calls, run = batch
    result = run(2, entrances={})
    assert not calls and not result["candidates"]
    def fail(*args, **kwargs):
        calls.append(kwargs)
        raise RoadCalculationError("road_engine_timeout")
    monkeypatch.setattr(service, "calculate_distance_matrix", fail)
    result = run(24)
    assert len(calls) == 1 and not result["candidates"]
    assert len([row for row in result["unresolved"] if row["state"] == "calculation_failed"]) == 10
    assert len([row for row in result["unresolved"] if row["state"] == "not_calculated"]) == 14


def test_cancel_and_authority_change_never_return_partial_authorized_results(batch, monkeypatch):
    db, _, _, run = batch
    cancellation = Event()
    cancellation.set()
    with pytest.raises(RoadCalculationError, match="cancelled"):
        run(cancel_event=cancellation)
    def revoke(*args, **kwargs):
        db.info["authorized_area_ids"] = ()
        return {"network_id": "graph", "graph_sha256": "hash", "policy_revision": 1,
                "cells": [{"source_index": 0, "target_index": 0, "status": "calculated", "distance_m": 2000}]}
    monkeypatch.setattr(service, "calculate_distance_matrix", revoke)
    with pytest.raises(PermissionError, match="authority_changed"):
        run(1)


def test_budget_exhaustion_keeps_uncomputed_targets_explicit(batch, monkeypatch):
    _, _, calls, run = batch
    times = iter([0, 0, 91, 92])
    monkeypatch.setattr(service.time, "monotonic", lambda: next(times))
    result = run(24)
    assert len(calls) == 1 and result["budget_exhausted"]
    assert result["coverage"]["compared"] == 10 and not result["coverage"]["complete"]
    assert len(result["unresolved"]) == 14


def test_all_verified_entrances_compared_before_selecting_facility(batch, monkeypatch):
    _, _, calls, run = batch
    gates = [RoadLocation(longitude=125 + i / 1000, latitude=46) for i in range(12)]
    def matrix(_db, **kwargs):
        calls.append(kwargs)
        return {"network_id": "graph", "graph_sha256": "hash", "policy_revision": 1,
            "cells": [{"source_index": 0, "target_index": i, "status": "calculated",
                       "distance_m": 20_000 - round((point.longitude - 125) * 1000) * 1000}
                      for i, point in enumerate(kwargs["targets"])]}
    monkeypatch.setattr(service, "calculate_distance_matrix", matrix)
    result = run(1, entrances={1: gates})
    assert [len(call["targets"]) for call in calls] == [10, 2]
    best = result["candidates"][0]
    assert best["selected_entry_index"] == 11 and best["road_distance_m"] == 9000
    assert best["entrances_compared"] == 12
    assert result["coverage"]["compared"] == 1  # Twelve gates are not twelve facilities.


def test_unfinished_alternative_entrance_cannot_be_presented_as_best(batch, monkeypatch):
    _, _, calls, run = batch
    gates = [RoadLocation(longitude=125 + i / 1000, latitude=46) for i in range(12)]
    times = iter([0, 0, 91, 92])
    monkeypatch.setattr(service.time, "monotonic", lambda: next(times))
    result = run(1, entrances={1: gates})
    assert len(calls) == 1 and not result["candidates"]
    assert result["unresolved"][0]["state"] == "not_calculated"
    assert result["entrance_results"][0]["entries"][0]["state"] == "calculated"
