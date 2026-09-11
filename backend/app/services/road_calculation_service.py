"""Authorized reference-path orchestration for the isolated road worker.

HTTP reference calculations select an authorized published graph automatically.
"""
from datetime import datetime
from pathlib import Path

from app.services.road_access_policy import VehicleAssumption
from app.services.road_graph_artifact import verify_graph_artifact
from app.services.road_network_service import resolve_network, select_network, recheck_network, RoadNetworkUnavailable
from app.services.vehicle_router import ENGINE_VERSION, RoadLocation, RoadCalculationError
from app.services.road_worker_process import (run_route_process, run_matrix_process,
    run_distance_reachability_process, run_time_reachability_process)


def _check_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise RoadCalculationError('road_calculation_cancelled')


def _binding(db, network_id, analysis_at, vehicle):
    if network_id is None:
        return select_network(db, analysis_at=analysis_at, vehicle=vehicle, engine_version=ENGINE_VERSION)
    return resolve_network(db, network_id, analysis_at=analysis_at, vehicle=vehicle)


def calculate_reference_route(db, *, network_id: str | None = None, analysis_at: datetime,
                              start: RoadLocation, end: RoadLocation,
                              vehicle: VehicleAssumption, artifact_root: Path, cancel_event=None):
    _check_cancelled(cancel_event)
    binding = _binding(db, network_id, analysis_at, vehicle)
    if binding.engine_version != ENGINE_VERSION:
        raise RoadNetworkUnavailable('road_engine_version_mismatch')
    tiles = verify_graph_artifact(artifact_root, binding)
    result = run_route_process(tiles, start, end, vehicle, cancel_event=cancel_event)
    recheck_network(db, binding, analysis_at=analysis_at, vehicle=vehicle)
    _check_cancelled(cancel_event)
    return {**result, 'network_id': binding.network_id,
            'policy_revision': binding.policy_revision, 'graph_sha256': binding.graph_sha256,
            'analysis_at': analysis_at.isoformat(),
            'origin': start.model_dump(), 'destination': end.model_dump()}


def calculate_distance_matrix(db, *, network_id: str | None = None, analysis_at: datetime,
                              sources: list[RoadLocation], targets: list[RoadLocation],
                              vehicle: VehicleAssumption, artifact_root: Path, cancel_event=None):
    _check_cancelled(cancel_event)
    binding = _binding(db, network_id, analysis_at, vehicle)
    if binding.engine_version != ENGINE_VERSION:
        raise RoadNetworkUnavailable('road_engine_version_mismatch')
    tiles = verify_graph_artifact(artifact_root, binding)
    result = run_matrix_process(tiles, sources, targets, vehicle, cancel_event=cancel_event)
    recheck_network(db, binding, analysis_at=analysis_at, vehicle=vehicle)
    _check_cancelled(cancel_event)
    return {**result, 'network_id': binding.network_id,
            'policy_revision': binding.policy_revision, 'graph_sha256': binding.graph_sha256,
            'analysis_at': analysis_at.isoformat(),
            'sources': [point.model_dump() for point in sources],
            'targets': [point.model_dump() for point in targets]}


def calculate_distance_reachability(db, *, network_id: str | None = None, analysis_at: datetime,
                                   origin: RoadLocation, distance_m: float,
                                   vehicle: VehicleAssumption, artifact_root: Path, cancel_event=None):
    _check_cancelled(cancel_event)
    binding = _binding(db, network_id, analysis_at, vehicle)
    if binding.engine_version != ENGINE_VERSION:
        raise RoadNetworkUnavailable('road_engine_version_mismatch')
    tiles = verify_graph_artifact(artifact_root, binding)
    result = run_distance_reachability_process(tiles, origin, vehicle, distance_m, cancel_event=cancel_event)
    recheck_network(db, binding, analysis_at=analysis_at, vehicle=vehicle)
    _check_cancelled(cancel_event)
    return {**result, 'network_id': binding.network_id,
            'policy_revision': binding.policy_revision, 'graph_sha256': binding.graph_sha256,
            'analysis_at': analysis_at.isoformat(), 'origin': origin.model_dump()}


def calculate_time_reachability(db, *, network_id: str | None = None, analysis_at: datetime,
                               origin: RoadLocation, seconds: float,
                               vehicle: VehicleAssumption, artifact_root: Path, cancel_event=None):
    _check_cancelled(cancel_event)
    binding = _binding(db, network_id, analysis_at, vehicle)
    if binding.engine_version != ENGINE_VERSION:
        raise RoadNetworkUnavailable('road_engine_version_mismatch')
    tiles = verify_graph_artifact(artifact_root, binding)
    result = run_time_reachability_process(tiles, origin, vehicle, seconds, cancel_event=cancel_event)
    recheck_network(db, binding, analysis_at=analysis_at, vehicle=vehicle)
    _check_cancelled(cancel_event)
    return {**result, 'network_id': binding.network_id,
            'policy_revision': binding.policy_revision, 'graph_sha256': binding.graph_sha256,
            'analysis_at': analysis_at.isoformat(), 'origin': origin.model_dump()}
