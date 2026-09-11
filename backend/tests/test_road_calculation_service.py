import pytest
import threading
from sqlalchemy import update

from app.models.road_network import RoadNetworkVersion, RoadAccessGroup
from app.services import road_calculation_service as service
from app.services.road_access_policy import VehicleAssumption
from app.services.road_graph_artifact import graph_inventory_sha256
from app.services.vehicle_router import RoadLocation, RoadCalculationError
from app.services.road_network_service import RoadNetworkUnavailable
from test_case_results import db_session, result_data  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_road_access_policy import AT


@pytest.mark.parametrize('change', ['none', 'revocation', 'engine_failure', 'bad_graph', 'cancelled'])
@pytest.mark.parametrize('operation', ['route', 'matrix', 'reachability', 'time_reachability'])
@pytest.mark.parametrize('automatic', [False, True])
def test_route_orchestration_checks_before_and_after_native_call(ready, tmp_path, monkeypatch, change, operation, automatic):
    tiles = tmp_path / ('c' * 64) / 'tiles'
    tiles.mkdir(parents=True)
    (tiles / '001.gph').write_bytes(b'synthetic tile, not a real engine graph')
    digest = graph_inventory_sha256(tiles)
    ready.execute(update(RoadNetworkVersion).values(engine_version='3.8.3', graph_sha256=digest))
    ready.commit()
    called = []
    cancellation = threading.Event()

    def fake_process(directory, start, end, vehicle, *, cancel_event=None):
        assert directory == tiles
        assert cancel_event is cancellation
        called.append(True)
        if change == 'cancelled':
            cancel_event.set()
        if change == 'revocation':
            ready.execute(update(RoadAccessGroup).values(policy_revision=2))
            ready.commit()
        if change == 'engine_failure':
            raise RoadCalculationError('road_engine_calculation_failed')
        return {'distance_m': 123, 'way_ids': [1]}

    monkeypatch.setattr(service, 'run_route_process', fake_process)
    monkeypatch.setattr(service, 'run_matrix_process', fake_process)
    monkeypatch.setattr(service, 'run_distance_reachability_process', fake_process)
    monkeypatch.setattr(service, 'run_time_reachability_process', fake_process)
    if change == 'bad_graph':
        (tiles / '001.gph').write_bytes(b'damaged')
    arguments = dict(network_id='graph-1', analysis_at=AT,
                     start=RoadLocation(longitude=125., latitude=46.),
                     end=RoadLocation(longitude=125.1, latitude=46.1),
                     vehicle=VehicleAssumption(kind='auto', source='explicit_reference_assumption'),
                     artifact_root=tmp_path, cancel_event=cancellation)
    if automatic:
        arguments.pop('network_id')
    calculate = service.calculate_reference_route
    if operation == 'matrix':
        arguments['sources'] = [arguments.pop('start')]
        arguments['targets'] = [arguments.pop('end')]
        calculate = service.calculate_distance_matrix
    elif operation in ('reachability', 'time_reachability'):
        arguments['origin'] = arguments.pop('start')
        arguments.pop('end')
        if operation == 'reachability':
            arguments['distance_m'] = 500.
            calculate = service.calculate_distance_reachability
        else:
            arguments['seconds'] = 60.
            calculate = service.calculate_time_reachability
    if change == 'none':
        result = calculate(ready, **arguments)
        assert result['distance_m'] == 123 and result['graph_sha256'] == digest
        assert result['network_id'] == 'graph-1'
    else:
        with pytest.raises((RoadCalculationError, RoadNetworkUnavailable)):
            calculate(ready, **arguments)
    assert bool(called) == (change != 'bad_graph')


@pytest.mark.parametrize('operation', ['route', 'matrix', 'reachability'])
@pytest.mark.parametrize('change', ['truck', 'weight', 'missing_binding'])
def test_vehicle_binding_rejected_before_graph_access_or_engine(ready, tmp_path, monkeypatch, operation, change):
    def forbidden(*args, **kwargs):
        pytest.fail('Mismatched vehicle must not read graph files or invoke engine')
    monkeypatch.setattr(service, 'verify_graph_artifact', forbidden)
    vehicle = VehicleAssumption(kind='auto', source='case_record')
    if change == 'truck':
        vehicle = VehicleAssumption(kind='truck', height_m=3., weight_t=10., source='case_record')
    elif change == 'weight':
        vehicle = VehicleAssumption(kind='auto', weight_t=2., source='case_record')
    else:
        ready.execute(update(RoadNetworkVersion).values(source_manifest={'internal_area_ids': [1]}))
        ready.commit()
    point = RoadLocation(longitude=125., latitude=46.)
    kwargs = dict(network_id='graph-1', analysis_at=AT, vehicle=vehicle, artifact_root=tmp_path)
    with pytest.raises(RoadNetworkUnavailable, match='road_graph_vehicle_'):
        if operation == 'route':
            service.calculate_reference_route(ready, start=point, end=point, **kwargs)
        elif operation == 'matrix':
            service.calculate_distance_matrix(ready, sources=[point], targets=[point], **kwargs)
        else:
            service.calculate_distance_reachability(ready, origin=point, distance_m=500., **kwargs)
