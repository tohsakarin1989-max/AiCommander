from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import os

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models.case_pipeline import CasePipelineState, OutboxEvent
from app.models.road_network import RoadNetworkVersion, RoadAccessMembership
from app.models.case_road_artifact import CaseRoadArtifact
from app.services.case_result_service import CaseResultService
from app.services import case_road_triggers as triggers, case_road_jobs as jobs
from test_case_road_artifacts import artifact_input  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401


def source_event(db, profile, *, authority=True, changed=False):
    payload = {'source_hash': 'different' if changed else profile.source_hash}
    if authority:
        payload['road_authority'] = {'user_id': 1, 'scope': [1]}
    db.add(OutboxEvent(id='source-event', event_type='case.analysis.requested', aggregate_type='case',
        aggregate_id=str(profile.case_id), payload=payload, idempotency_key='source-event', status='completed'))
    db.flush()
    db.add(CasePipelineState(case_id=profile.case_id, source_hash=profile.source_hash,
        event_id='source-event', schema_version=profile.schema_version,
        dictionary_version=profile.dictionary_version, status='completed'))
    db.commit()


@pytest.mark.parametrize('complete', [True, False])
def test_frozen_truck_conditions_reach_job_and_manual_route_without_car_fallback(ready, result_data, complete):
    from app.api.road_analysis import _case_calculation
    from app.services.case_semantic_service import build_semantic_profile
    from fastapi import HTTPException
    db = ready
    profile, run, _ = result_data
    record = {'type': '货车', 'height_m': 3.2}
    if complete:
        record['gross_weight_t'] = 12.5
    profile.payload = {**profile.payload, 'semantics': build_semantic_profile(
        {'description': '现场查获货车'}, structured={'vehicle_info': record})}
    graph = db.get(RoadNetworkVersion, 'graph-1')
    graph.engine_version = '3.8.3'
    graph.valid_from = datetime(2020, 1, 1, tzinfo=timezone.utc)
    vehicle = {'kind': 'truck', 'height_m': 3.2, 'weight_t': 12.5, 'source': 'case_record'}
    graph.source_manifest = {**graph.source_manifest, 'vehicle': vehicle}
    db.commit()
    source_event(db, profile)
    result_id, _ = CaseResultService.freeze_completed_inputs(db, profile, run)
    db.commit()
    request_id = db.scalar(select(OutboxEvent.id).where(OutboxEvent.event_type == triggers.REQUEST_TYPE))
    outcome = triggers.process_request(db, request_id)
    assert outcome['status'] == 'completed'
    calculation = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == jobs.EVENT_TYPE))
    if complete:
        assert calculation.payload['vehicle'] == vehicle
        assert _case_calculation(db, result_id, datetime.now(timezone.utc)).vehicle.model_dump() == vehicle
    else:
        assert calculation is None and outcome['outcome'] == 'vehicle_information_missing'
        with pytest.raises(HTTPException) as error:
            _case_calculation(db, result_id, datetime.now(timezone.utc))
        assert error.value.status_code == 422


@pytest.mark.parametrize('authority,changed,expected', [(True, False, 1), (False, False, 0), (True, True, 0)])
def test_completed_result_handoff_is_exact_and_transactional(artifact_input, result_data, authority, changed, expected):
    db, _ = artifact_input
    source_event(db, result_data[0], authority=authority, changed=changed)
    first = CaseResultService.freeze_completed_inputs(db, *result_data[:2])
    second = CaseResultService.freeze_completed_inputs(db, *result_data[:2])
    assert first[0] == second[0]
    assert db.query(OutboxEvent).filter_by(event_type=triggers.REQUEST_TYPE).count() == expected
    db.rollback()
    assert db.query(OutboxEvent).filter_by(event_type=triggers.REQUEST_TYPE).count() == 0


@pytest.mark.parametrize('revoked', [False, True])
def test_result_to_registered_worker_does_not_implicitly_elevate(artifact_input, result_data, monkeypatch, revoked):
    from app.tasks import case_road_tasks
    db, content = artifact_input
    source_event(db, result_data[0])
    result_id, _ = CaseResultService.freeze_completed_inputs(db, *result_data[:2])
    graph = db.get(RoadNetworkVersion, 'graph-1')
    graph.engine_version = '3.8.3'
    # Graph fixture is applicable now; this does not assert native graph validity.
    graph.valid_from = datetime(2020, 1, 1, tzinfo=timezone.utc)
    if revoked:
        db.query(RoadAccessMembership).delete()
    db.commit()
    monkeypatch.setattr(case_road_tasks, 'SessionLocal', sessionmaker(bind=db.bind, autoflush=False))
    def calculate(session, **kwargs):
        assert not revoked
        assert session.info['authorized_area_ids'] == (1,)
        output = deepcopy(content)
        output['result_id'] = result_id
        output['content_sha256'] = CaseResultService.read(session, result_id)['content_sha256']
        output['map_snapshot_id'] = result_data[1].map_snapshot_id
        output['matrix']['analysis_at'] = kwargs['analysis_at'].isoformat()
        return output
    monkeypatch.setattr('app.services.case_facility_comparison.compare_case_facilities', calculate)
    first = case_road_tasks.process_next_comparison.run()
    assert first['status'] == ('waiting_dependency' if revoked else 'completed')
    if revoked:
        assert db.query(OutboxEvent).filter_by(event_type=jobs.EVENT_TYPE).count() == 0
        assert case_road_tasks.process_next_comparison.run() == {'selected': 0}
    else:
        second = case_road_tasks.process_next_comparison.run()
        assert second['outcome'] == 'calculated'
        assert db.query(CaseRoadArtifact).count() == 1


def test_capture_uses_copied_server_scope_without_role_assertions(db_session):
    db_session.info.update(principal_user_id=1, authorized_area_ids=[2, 1])
    value = triggers.capture_road_authority(db_session)
    db_session.info['authorized_area_ids'].append(3)
    assert value == {'user_id': 1, 'scope': [1, 2]}
    db_session.info.clear()
    assert triggers.capture_road_authority(db_session) is None


@pytest.mark.skipif(os.environ.get('AIC_BUILD_ROAD_CONDITIONS') != '1', reason='optional real compiler')
@pytest.mark.parametrize('closed', [False, True])
@pytest.mark.parametrize('truck', [False, True])
def test_legacy_explicit_job_through_actual_native_matrix_and_persistence(
        ready, result_data, monkeypatch, tmp_path, closed, truck):
    """Retained legacy job: real PBF/graph, matrix, queue task and storage.

    Calls the registered task directly; does not claim a Redis/broker deployment.
    v5.2 automatic facility governance is tested by verify-v52-native-workflow.py;
    this fixture deliberately has no verified facility entrances.
    """
    osmium = pytest.importorskip('osmium')
    from app.models.map_foundation import MapSnapshotFeature
    from app.services.road_source_filter import filter_road_source
    from app.services.road_graph_builder import compile_local_graph
    from app.services.road_graph_artifact import install_graph_artifact
    from app.services.case_road_artifact_service import read_road_artifact
    from app.tasks import case_road_tasks

    db = ready
    source = tmp_path / 'source.osm.pbf'
    points = {1: (124.999, 46.), 2: (125., 46.), 3: (125.002, 46.),
              4: (125., 46.002), 5: (125.002, 46.002), 6: (125.003, 46.)}
    with osmium.SimpleWriter(str(source)) as writer:
        for identifier, coordinates in points.items():
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=coordinates, version=1))
        for identifier, nodes in ((1, [1, 2]), (10, [2, 3]), (20, [2, 4, 5, 3]), (30, [3, 6])):
            writer.add_way(osmium.osm.mutable.Way(id=identifier, nodes=nodes, version=1,
                tags={'highway': 'residential', 'motor_vehicle': 'yes', 'maxspeed': '30'}))
    filtered = filter_road_source(source, tmp_path / 'filtered', excluded_way_ids={10} if closed else set(),
        expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    compiled = compile_local_graph(tmp_path / 'filtered' / 'eligible.osm.pbf', tmp_path / 'compiled',
        expected_source_sha256=filtered['output_sha256'])
    key = install_graph_artifact(tmp_path / 'compiled' / 'tiles', tmp_path / 'road-graphs',
        expected_sha256=compiled['graph_sha256'])
    graph = db.get(RoadNetworkVersion, 'graph-1')
    graph.engine_version, graph.graph_sha256, graph.artifact_key = '3.8.3', key, key
    graph.valid_from = datetime(2020, 1, 1, tzinfo=timezone.utc)
    profile, run, _ = result_data
    profile.payload = {**profile.payload, 'analysis_facts': {'latitude': 46., 'longitude': 124.9995}}
    if truck:
        from app.models.case import Case, CaseVehicle
        from app.services.case_pipeline_service import CasePipelineService
        db.add(CaseVehicle(case_id=1, vehicle_type='重型挂车', road_vehicle_kind='truck',
                           height_m=3.2, gross_weight_t=12.5))
        db.flush()
        conditions = CasePipelineService.build_profile_payload(db, db.get(Case, 1))['semantics']
        profile.payload = {**profile.payload, 'semantics': conditions}
        graph.source_manifest = {**graph.source_manifest, 'vehicle': {
            'kind': 'truck', 'height_m': 3.2, 'weight_t': 12.5, 'source': 'case_record'}}
    feature = db.scalar(select(MapSnapshotFeature).where(MapSnapshotFeature.asset_id == 1))
    feature.latitude, feature.longitude = 46., 125.0025
    db.commit()
    result_id, _ = CaseResultService.freeze_completed_inputs(db, profile, run)
    db.commit()
    frozen_source = deepcopy(CaseResultService.read(db, result_id)['content'])
    from app.services.case_road_vehicle import frozen_road_vehicle
    jobs.enqueue_comparison(db, result_id=result_id, analysis_at=datetime.now(timezone.utc),
        vehicle=frozen_road_vehicle(frozen_source), engine_version='3.8.3')
    db.commit()
    monkeypatch.setattr(case_road_tasks, 'SessionLocal', sessionmaker(bind=db.bind, autoflush=False))
    monkeypatch.setattr(case_road_tasks.settings, 'MAP_PACKAGE_ROOT', str(tmp_path))
    if closed:
        # The original durable job survives a missing installed graph; retry
        # after restoration must not require another user action or new event.
        tiles = tmp_path / 'road-graphs' / key / 'tiles'
        unavailable = tiles.with_name('temporarily-unavailable-tiles')
        tiles.rename(unavailable)
        try:
            failed = case_road_tasks.process_next_comparison.run()
            assert failed['status'] == 'retry'
            assert db.query(CaseRoadArtifact).count() == 0
            pending = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == jobs.EVENT_TYPE))
            original_job_id = pending.id
            assert pending.error == 'road_job_failed'
            pending.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        finally:
            unavailable.rename(tiles)
    response = case_road_tasks.process_next_comparison.run()
    assert response.get('outcome') == 'calculated', response
    if closed:
        assert response['event_id'] == original_job_id
    artifact = read_road_artifact(db, response['artifact']['id'])
    matrix = artifact['content']['matrix']
    assert matrix['vehicle']['kind'] == ('truck' if truck else 'auto')
    if truck:
        assert matrix['vehicle']['weight_t'] == 12.5 and matrix['vehicle']['height_m'] == 3.2
    assert matrix['engine_version'] == '3.8.3' and matrix['graph_sha256'] == key
    assert artifact['content']['targets'][0]['evidence_ref'] == 'map_asset:1@snapshot:map-1'
    distance = matrix['cells'][0]['distance_m']
    assert (600 < distance < 1000) if closed else (150 < distance < 350)
    assert CaseResultService.read(db, result_id)['content'] == frozen_source
    assert db.query(CaseRoadArtifact).count() == 1
    assert case_road_tasks.process_next_comparison.run() == {'selected': 0}
