"""Strictly subtractive private graphs, with optional real Valhalla execution."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
from threading import Event, Timer

import pytest

osmium = pytest.importorskip("osmium", reason="PBF integration dependency")

from app.models.internal_roads import InternalRoadReview
from app.models.map_foundation import PublicMapBundle
from app.models.road_network import RoadAccessGroup, RoadAccessMembership, RoadNetworkVersion
from app.services import road_build_job, road_network_service, road_scenario_networks as service
from app.services.internal_road_service import ingest_roads
from app.services.road_access_policy import VehicleAssumption
from app.services.road_graph_artifact import graph_inventory_sha256
from app.services.road_graph_builder import _compile_command
from app.services.road_network_contracts import RoadNetworkUnavailable
from app.services.road_public_alias_service import record_alias_decision
from app.services.road_publication_service import publish_road_candidate
from app.services.road_retained_source import install_retained_source, verify_retained_source
from app.services.vehicle_router import ENGINE_VERSION, RoadCalculationError, RoadLocation
from test_road_build_inputs import prepared  # noqa: F401
from test_map_foundation import db_session  # noqa: F401
from test_internal_road_import import source, collection  # noqa: F401
from test_road_public_alias import decision
from test_road_access_policy import AT

NATIVE = os.environ.get("AIC_SCENARIO_NATIVE") == "1"


def fake_compile(source, output, *, expected_source_sha256, cancel_event=None, timeout_seconds=1200):
    """Only metadata/security tests; explicitly not a native graph."""
    assert hashlib.sha256(source.read_bytes()).hexdigest() == expected_source_sha256
    tiles = output / "tiles"
    tiles.mkdir(parents=True)
    (tiles / "001.gph").write_bytes(b"not-native:" + expected_source_sha256.encode())
    return {"graph_sha256": graph_inventory_sha256(tiles), "source_sha256": expected_source_sha256,
            "status": "built_not_published"}


@pytest.fixture
def baseline(prepared, tmp_path, monkeypatch):
    db, road, _ = prepared
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("exclusion_fixture", root / "scripts/verify-road-hard-exclusions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "base.osm.pbf"
    module.write_fixture(path, True)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    road["geometry"] = {"type": "LineString", "coordinates": [[125, 46], [125.002, 46]]}
    batch, _ = ingest_roads(db, 1, collection(road), 1)
    db.add(InternalRoadReview(import_id=batch["id"], operational_area_id=1, feature_id="road-1",
        sequence=1, request_key="scenario-road", decision="verified", note="合成道路",
        evidence_reference="synthetic-only", created_by=1))
    db.add(PublicMapBundle(id=991, bundle_id="scenario-synthetic", provider="synthetic", source_version="1",
        license_record="synthetic only", bounds=[124, 45, 126, 47], package_hash="e" * 64,
        manifest={"assets": [{"role": "road_source", "sha256": digest}]}, status="accepted"))
    db.add(RoadAccessMembership(group_id=1, user_id=1, valid_from=AT - timedelta(days=1)))
    db.commit()
    record_alias_decision(db, decision(batch["id"], public_source_sha256=digest, osm_way_id=10,
        request_key="scenario-alias"))
    db.commit()
    monkeypatch.setattr(road_network_service, "_now", lambda: AT)
    if not NATIVE:
        monkeypatch.setattr(road_build_job, "compile_local_graph", fake_compile)
        monkeypatch.setattr(service, "compile_local_graph", fake_compile)
    vehicle = VehicleAssumption(kind="auto", source="explicit_reference_assumption")
    root = tmp_path / "artifacts"
    candidate = road_build_job.run_road_build_job(db, source_pbf=path, work_root=tmp_path / "jobs",
        source_ids=[1], group_id=1, at=AT, vehicle=vehicle, public_bundle_id=991)
    publish_road_candidate(db, candidate["id"], work_root=tmp_path / "jobs", artifact_root=root)
    graph = db.get(RoadNetworkVersion, candidate["id"])
    option = service.eligible_exclusion_options(db, graph.id, analysis_at=AT, vehicle=vehicle)[0]
    arguments = {"base_network_id": graph.id, "base_graph_sha256": graph.graph_sha256,
        "analysis_at": AT, "vehicle": vehicle, "registered_road_id": option["registered_road_id"],
        "scenario_id": "synthetic-scenario-only", "artifact_root": root}
    return db, arguments, option


def test_retained_pbf_checksum_and_links_are_checked(tmp_path):
    source = tmp_path / "eligible.osm.pbf"
    source.write_bytes(b"unit source retention fixture")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    root = tmp_path / "artifacts"
    descriptor = install_retained_source(source, root, expected_source_sha256=digest)
    retained = verify_retained_source(root, descriptor)
    assert install_retained_source(source, root, expected_source_sha256=digest) == descriptor
    retained.chmod(0o644)
    retained.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        verify_retained_source(root, descriptor)
    linked = tmp_path / "linked.pbf"
    linked.symlink_to(source)
    with pytest.raises(ValueError, match="link_forbidden"):
        install_retained_source(linked, root, expected_source_sha256=digest)


def test_private_graph_never_becomes_default_or_published_and_reuses_exact_source(baseline):
    db, args, option = baseline
    original = deepcopy(db.get(RoadNetworkVersion, args["base_network_id"]).source_manifest)
    result = service.prepare_private_network(db, **args)
    assert result["state"] == "ready" and result["network_id"] != args["base_network_id"]
    row = db.get(RoadNetworkVersion, result["network_id"])
    assert row.status == "building" and row.source_manifest["build_status"] == "ready_private"
    assert row.source_manifest["scenario_filter_result"]["requested_excluded_way_ids"] == [10]
    assert row.source_manifest["private_scenario"]["option"]["source_sha256"] == option["source_sha256"]
    assert db.get(RoadNetworkVersion, args["base_network_id"]).source_manifest == original
    assert road_network_service.select_network(db, analysis_at=AT, vehicle=args["vehicle"],
        engine_version=ENGINE_VERSION).network_id == args["base_network_id"]
    with pytest.raises(RoadNetworkUnavailable, match="private_network"):
        road_network_service.resolve_network(db, row.id, analysis_at=AT, vehicle=args["vehicle"])
    with service.use_private_network(db, row.id, args["scenario_id"]):
        binding = road_network_service.resolve_network(db, row.id, analysis_at=AT, vehicle=args["vehicle"])
        road_network_service.recheck_network(db, binding, analysis_at=AT, vehicle=args["vehicle"])
    assert service.CONTEXT_KEY not in db.info
    with pytest.raises(ValueError, match="candidate_invalid"):
        publish_road_candidate(db, row.id, work_root=args["artifact_root"], artifact_root=args["artifact_root"])
    repeated = service.prepare_private_network(db, **args)
    assert repeated["network_id"] == row.id and not repeated["created"]


@pytest.mark.parametrize("change", ["membership", "scope", "policy", "parent_graph", "owner", "scenario"])
def test_private_graph_rechecks_parent_authority_and_owner(baseline, change):
    db, args, _ = baseline
    result = service.prepare_private_network(db, **args)
    if change == "membership":
        db.query(RoadAccessMembership).delete()
    elif change == "scope":
        db.info["authorized_area_ids"] = ()
    elif change == "policy":
        db.get(RoadAccessGroup, 1).policy_revision += 1
    elif change == "parent_graph":
        db.get(RoadNetworkVersion, args["base_network_id"]).graph_sha256 = "0" * 64
    elif change == "owner":
        db.info["principal_user_id"] = 2
    db.commit()
    with service.use_private_network(db, result["network_id"], "wrong" if change == "scenario" else args["scenario_id"]):
        with pytest.raises(RoadNetworkUnavailable):
            road_network_service.resolve_network(db, result["network_id"], analysis_at=AT, vehicle=args["vehicle"])


def test_missing_source_is_actionable_not_ready_and_unknown_road_is_rejected(baseline):
    db, args, _ = baseline
    graph = db.get(RoadNetworkVersion, args["base_network_id"])
    graph.source_manifest = {key: value for key, value in graph.source_manifest.items() if key != "retained_source"}
    db.commit()
    assert service.prepare_private_network(db, **args) == {"state": "not_ready", "reason": "road_scenario_source_not_retained"}
    with pytest.raises(RoadNetworkUnavailable, match="registered_road"):
        service.prepare_private_network(db, **{**args, "registered_road_id": "10"})
    assert db.query(RoadNetworkVersion).count() == 1


@pytest.mark.parametrize("failure", ["cancel", "compiler", "permission"])
def test_failed_private_build_never_changes_baseline(baseline, monkeypatch, failure):
    db, args, _ = baseline
    original = deepcopy(db.get(RoadNetworkVersion, args["base_network_id"]).source_manifest)
    cancel = Event()
    def interrupted(source, output, **kwargs):
        assert not db.in_transaction()
        if failure == "cancel":
            cancel.set()
        elif failure == "compiler":
            raise RoadCalculationError("road_graph_build_failed")
        else:
            db.get(RoadAccessGroup, 1).policy_revision += 1
            db.commit()
        return fake_compile(source, output, **kwargs)
    monkeypatch.setattr(service, "compile_local_graph", interrupted)
    with pytest.raises((RoadCalculationError, RoadNetworkUnavailable)):
        service.prepare_private_network(db, **args, cancel_event=cancel)
    parent = db.get(RoadNetworkVersion, args["base_network_id"])
    assert parent.status == "ready" and parent.source_manifest == original
    child = db.query(RoadNetworkVersion).filter_by(builder_version=service.BUILDER_VERSION).one()
    assert child.status == "failed" and child.artifact_key is None


def test_native_compiler_cancel_reaps_owned_child_process(tmp_path, monkeypatch):
    from app.services import road_graph_builder
    original = road_graph_builder.subprocess.Popen
    children = []
    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(road_graph_builder.subprocess, "Popen", spawn)
    cancel = Event()
    timer = Timer(.15, cancel.set)
    timer.start()
    try:
        with (tmp_path / "log").open("wb") as log:
            with pytest.raises(RoadCalculationError, match="cancelled"):
                _compile_command([sys.executable, "-c", "import time; time.sleep(30)"], log,
                    cancel_event=cancel, timeout_seconds=5)
    finally:
        timer.cancel()
    assert children and all(child.poll() is not None for child in children)


def test_failed_private_build_can_retry_same_identity(baseline, monkeypatch):
    db, args, _ = baseline
    def fail(*args, **kwargs):
        raise RoadCalculationError("road_graph_build_failed")
    monkeypatch.setattr(service, "compile_local_graph", fail)
    with pytest.raises(RoadCalculationError):
        service.prepare_private_network(db, **args)
    identifier = db.query(RoadNetworkVersion).filter_by(builder_version=service.BUILDER_VERSION).one().id
    monkeypatch.setattr(service, "compile_local_graph", fake_compile)
    result = service.prepare_private_network(db, **args)
    assert result["network_id"] == identifier and result["state"] == "ready"
    assert db.query(RoadNetworkVersion).count() == 2


def test_source_filter_cancellation_stops_before_compilation(baseline, monkeypatch):
    db, args, _ = baseline
    class CancelDuringPbf:
        def __init__(self):
            self.checks = 0

        def is_set(self):
            self.checks += 1
            return self.checks > 8

    def forbidden_compile(*args, **kwargs):
        pytest.fail("cancelled source parsing must not start compiler")

    monkeypatch.setattr(service, "compile_local_graph", forbidden_compile)
    with pytest.raises(RoadCalculationError, match="cancelled"):
        service.prepare_private_network(db, **args, cancel_event=CancelDuringPbf())
    child = db.query(RoadNetworkVersion).filter_by(builder_version=service.BUILDER_VERSION).one()
    assert child.status == "failed"
    assert db.get(RoadNetworkVersion, args["base_network_id"]).status == "ready"


def test_work_directory_failure_is_retryable_not_stuck_building(baseline, tmp_path):
    db, args, _ = baseline
    work = args["artifact_root"] / ".scenario-work"
    target = tmp_path / "untrusted"
    target.mkdir()
    work.symlink_to(target)
    with pytest.raises(ValueError, match="work_link_forbidden"):
        service.prepare_private_network(db, **args)
    child = db.query(RoadNetworkVersion).filter_by(builder_version=service.BUILDER_VERSION).one()
    assert child.status == "failed" and not list(target.iterdir())
    work.unlink()
    assert service.prepare_private_network(db, **args)["network_id"] == child.id


def test_private_builder_cannot_be_promoted_by_dropping_marker(baseline):
    db, args, _ = baseline
    result = service.prepare_private_network(db, **args)
    child = db.get(RoadNetworkVersion, result["network_id"])
    child.status = "ready"
    child.source_manifest = {key: value for key, value in child.source_manifest.items() if key != "private_scenario"}
    db.commit()
    with pytest.raises(RoadNetworkUnavailable, match="private_network"):
        road_network_service.resolve_network(db, child.id, analysis_at=AT, vehicle=args["vehicle"])
    selected = road_network_service.select_network(db, analysis_at=AT, vehicle=args["vehicle"], engine_version=ENGINE_VERSION)
    assert selected.network_id == args["base_network_id"]


def test_crashed_private_build_resumes_same_catalog_identity(baseline):
    db, args, _ = baseline
    result = service.prepare_private_network(db, **args)
    child = db.get(RoadNetworkVersion, result["network_id"])
    child.artifact_key, child.graph_sha256 = None, None
    child.source_manifest = {**child.source_manifest, "build_status": "building_private"}
    db.commit()
    resumed = service.prepare_private_network(db, **args)
    assert resumed["state"] == "ready" and resumed["network_id"] == child.id
    assert db.query(RoadNetworkVersion).count() == 2


def test_live_private_build_lock_does_not_start_second_compiler(baseline, monkeypatch):
    db, args, _ = baseline
    original = service.compile_local_graph
    overlaps = []

    def compiling(*values, **kwargs):
        overlaps.append(service.prepare_private_network(db, **args))
        return original(*values, **kwargs)

    monkeypatch.setattr(service, "compile_local_graph", compiling)
    assert service.prepare_private_network(db, **args)["state"] == "ready"
    assert overlaps == [{"state": "not_ready", "reason": "road_scenario_build_in_progress"}]


@pytest.mark.skipif(not NATIVE, reason="requires existing native road runtime")
def test_real_private_graph_route_matrix_and_range_use_exclusion(baseline, record_property):
    from app.services.road_calculation_service import calculate_reference_route, calculate_distance_matrix, calculate_distance_reachability
    db, args, _ = baseline
    start = RoadLocation(longitude=124.9995, latitude=46)
    end = RoadLocation(longitude=125.0025, latitude=46)
    common = {"analysis_at": AT, "vehicle": args["vehicle"], "artifact_root": args["artifact_root"]}
    original = calculate_reference_route(db, network_id=args["base_network_id"], start=start, end=end, **common)
    changed = service.prepare_private_network(db, **args)
    with service.use_private_network(db, changed["network_id"], args["scenario_id"]):
        route = calculate_reference_route(db, network_id=changed["network_id"], start=start, end=end, **common)
        matrix = calculate_distance_matrix(db, network_id=changed["network_id"], sources=[start], targets=[end], **common)
        reached = calculate_distance_reachability(db, network_id=changed["network_id"], origin=start, distance_m=500, **common)
    assert 10 in original["way_ids"] and 10 not in route["way_ids"]
    assert 20 in route["way_ids"] and route["distance_m"] > original["distance_m"] + 300
    assert abs(route["distance_m"] - matrix["cells"][0]["distance_m"]) <= 5
    assert reached["network_id"] == changed["network_id"]
    assert road_network_service.select_network(db, analysis_at=AT, vehicle=args["vehicle"], engine_version=ENGINE_VERSION).network_id == args["base_network_id"]
    record_property("baseline_distance_m", original["distance_m"])
    record_property("private_distance_m", route["distance_m"])
    record_property("private_matrix_distance_m", matrix["cells"][0]["distance_m"])
    record_property("private_graph_sha256", changed["graph_sha256"])
