from copy import deepcopy
from threading import Event

import pytest

from app.models.road_network import RoadAccessMembership, RoadNetworkVersion
from app.services import frozen_road_inputs as replay
from app.services.case_road_artifact_service import freeze_road_artifact
from app.services import frozen_road_dataset
from app.services.vehicle_router import RoadCalculationError
from tests.test_case_road_artifacts import artifact_input  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401


def freeze(db, content, monkeypatch, tmp_path):
    content['matrix']['sources'] = [{'latitude': 47.0, 'longitude': 125.0}]
    content['matrix']['targets'] = [{'latitude': 47.01, 'longitude': 125.01}]
    stored = freeze_road_artifact(db, content)
    db.commit()
    monkeypatch.setattr(replay, 'verify_graph_artifact', lambda *args: tmp_path)
    return replay.capture_road_inputs(db, stored['id'], artifact_root=tmp_path)


def test_replay_pins_request_and_rejects_changes(artifact_input, monkeypatch, tmp_path):
    db, content = artifact_input
    envelope = freeze(db, content, monkeypatch, tmp_path)
    calls = []
    def calculate(db, **kwargs):
        calls.append(kwargs)
        return {'state': 'calculated', 'distance_m': 123.0}
    monkeypatch.setattr(replay, 'calculate_distance_matrix', calculate)
    result = replay.replay_road_inputs(db, envelope, artifact_root=tmp_path)
    assert result['result']['distance_m'] == 123.0
    assert calls[0]['network_id'] == 'graph-1'
    assert calls[0]['sources'][0].latitude == 47.0
    damaged = deepcopy(envelope)
    damaged['payload']['request']['sources'][0]['latitude'] = 0
    with pytest.raises(ValueError, match='integrity'):
        replay.replay_road_inputs(db, damaged, artifact_root=tmp_path)
    network = db.get(RoadNetworkVersion, 'graph-1')
    network.conditions_sha256 = 'f' * 64
    db.commit()
    with pytest.raises(ValueError, match='network_changed'):
        replay.replay_road_inputs(db, envelope, artifact_root=tmp_path)
    assert len(calls) == 1


def test_current_permission_revocation_blocks_native_execution(artifact_input, monkeypatch, tmp_path):
    db, content = artifact_input
    envelope = freeze(db, content, monkeypatch, tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('must not execute after revocation')
    monkeypatch.setattr(replay, 'calculate_distance_matrix', forbidden)
    db.query(RoadAccessMembership).delete()
    db.commit()
    with pytest.raises(PermissionError):
        replay.replay_road_inputs(db, envelope, artifact_root=tmp_path)


@pytest.mark.parametrize('change', ['permission', 'cancel', 'engine_failure'])
def test_running_replay_does_not_return_stale_or_fallback_results(artifact_input, monkeypatch, tmp_path, change):
    db, content = artifact_input
    envelope = freeze(db, content, monkeypatch, tmp_path)
    cancelled = Event()
    def calculate(db, **kwargs):
        assert kwargs['cancel_event'] is cancelled
        if change == 'permission':
            db.query(RoadAccessMembership).delete()
            db.commit()
        elif change == 'cancel':
            cancelled.set()
        else:
            raise RoadCalculationError('native_unavailable')
        return {'state': 'calculated', 'distance_m': 123}
    monkeypatch.setattr(replay, 'calculate_distance_matrix', calculate)
    with pytest.raises(PermissionError if change == 'permission' else RoadCalculationError):
        replay.replay_road_inputs(db, envelope, artifact_root=tmp_path, cancel_event=cancelled)


def test_route_replays_original_endpoints(artifact_input, monkeypatch, tmp_path):
    db, content = artifact_input
    content['schema_version'] = 'case-road-route-4.2.0-1'
    content['route'] = content.pop('matrix')
    content['route'].update(origin={'latitude': 47, 'longitude': 125},
                            destination={'latitude': 47.01, 'longitude': 125.01})
    stored = freeze_road_artifact(db, content)
    db.commit()
    monkeypatch.setattr(replay, 'verify_graph_artifact', lambda *args: tmp_path)
    envelope = replay.capture_road_inputs(db, stored['id'], artifact_root=tmp_path)
    def calculate(db, **kwargs):
        assert kwargs['network_id'] == 'graph-1'
        assert kwargs['start'].longitude == 125
        assert kwargs['end'].latitude == 47.01
        return {'state': 'calculated', 'distance_m': 800}
    monkeypatch.setattr(replay, 'calculate_reference_route', calculate)
    assert replay.replay_road_inputs(db, envelope, artifact_root=tmp_path)['result']['distance_m'] == 800
    cancelled = Event()
    cancelled.set()
    with pytest.raises(RoadCalculationError, match='cancelled'):
        replay.replay_road_inputs(db, envelope, artifact_root=tmp_path, cancel_event=cancelled)


def test_road_dataset_persistence_idempotency_and_authorization(artifact_input, monkeypatch, tmp_path):
    db, content = artifact_input
    envelope = freeze(db, content, monkeypatch, tmp_path)
    kwargs = dict(name='道路合成输入', version='1', artifact_ids=[envelope['payload']['artifact_id']],
                  artifact_root=tmp_path)
    dataset = frozen_road_dataset.create_dataset(db, **kwargs)
    db.commit()
    assert dataset.case_ids == [1]
    assert dataset.ground_truth == {}  # No invented correctness labels.
    assert frozen_road_dataset.create_dataset(db, **kwargs).id == dataset.id
    db.info['authorized_area_ids'] = ()
    with pytest.raises(PermissionError):
        frozen_road_dataset.read_dataset(db, dataset.id)
    with pytest.raises(PermissionError):
        frozen_road_dataset.create_dataset(db, **kwargs)
