"""Isolated persistence/authorization and fixed inputs; native matrix is synthetic."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.internal_roads import InternalRoadReview
from app.models.map_foundation import JurisdictionAssetVersion
from app.models.road_network import RoadAccessMembership, RoadNetworkVersion
from app.services import case_road_scenarios as service
from app.services import case_road_scenario_jobs as jobs
from app.services.case_facility_comparison import compare_case_facilities
from app.services.case_result_service import CaseResultService
from app.services.case_road_artifact_service import freeze_road_artifact
from app.services.facility_temporal_conditions import resolve_conditions
from case_v80_fixtures import rebuild_applicable_profile
from test_case_facility_comparison import prepared, VEHICLE  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401
from test_road_access_policy import AT


@pytest.fixture
def baseline(prepared, tmp_path):
    db, _, calls = prepared
    rebuild_applicable_profile(db, db.get(CaseAnalysisProfile, 'profile-1'))
    source, _ = CaseResultService.create_current(db, 1)
    db.commit()
    content = compare_case_facilities(db, result_id=source['id'], network_id='graph-1',
        analysis_at=AT, vehicle=VEHICLE, artifact_root=tmp_path)
    saved = freeze_road_artifact(db, content)
    db.commit()
    return db, {**saved, 'content': content}, calls


def options(db, saved, kind='extra_entrance_exclusion'):
    return [row for row in service.scenario_options(db, saved['id'])['options'] if row['kind'] == kind]


def submit(db, saved, selected=None):
    selected = selected or [options(db, saved)[0]['id']]
    return jobs.enqueue(db, saved['id'], saved['content_sha256'], selected)


def test_known_options_strict_selection_and_transactional_identity(baseline):
    db, saved, _ = baseline
    catalog = service.scenario_options(db, saved['id'])
    assert catalog['max_scenarios'] == 3 and catalog['baseline_included']
    assert catalog['road_exclusions']['state'] == 'not_ready'
    selected = options(db, saved)[0]['id']
    for invalid in ([], [selected] * 2, [selected] * 3, ['unknown'], [123]):
        with pytest.raises(ValueError):
            service.freeze_inputs(db, saved['id'], saved['content_sha256'], invalid)
    first, second = submit(db, saved), submit(db, saved)
    assert first['created'] and not second['created'] and first['event_id'] == second['event_id']
    db.rollback()
    assert db.query(OutboxEvent).filter_by(event_type=jobs.EVENT_TYPE).count() == 0


def test_entrance_exclusion_changes_only_declared_condition_no_native_or_business_writes(baseline, tmp_path):
    db, saved, calls = baseline
    before_case = db.get(Case, 1).description
    before_reviews = [(row.id, row.decision) for row in db.query(InternalRoadReview).all()]
    choice = options(db, saved)[0]
    count = len(calls)
    event_id = submit(db, saved, [choice['id']])['event_id']
    db.commit()
    assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'completed'
    artifact = jobs.read_job(db, event_id)['artifact']
    assert len(artifact['scenarios']) == 2
    assert artifact['frozen']['pool_sha256'] == saved['content']['pool']['input_sha256']
    base, variant = artifact['scenarios']
    affected = choice['parameters']['asset_id']
    assert next(row for row in variant['rows'] if row['asset_id'] == affected)['eligibility'] == 'excluded'
    assert [row['asset_id'] for row in variant['rows']] == [row['asset_id'] for row in base['rows']]
    assert len(calls) == count
    assert db.get(Case, 1).description == before_case
    assert before_reviews == [(row.id, row.decision) for row in db.query(InternalRoadReview).all()]
    assert not artifact['execution_task_created']
    assert not jobs.process(db, event_id, artifact_root=tmp_path)['claimed']


def test_two_variants_checkpoint_and_resume_keep_same_candidates(baseline, tmp_path):
    db, saved, _ = baseline
    choices = options(db, saved)[:2]
    event_id = submit(db, saved, [row['id'] for row in choices])['event_id']
    db.commit()
    assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'pending'
    status = jobs.read_job(db, event_id)
    assert status['artifact'] is None and status['progress']['scenarios_completed'] == 2
    event = db.get(OutboxEvent, event_id)
    event.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'completed'
    artifact = jobs.read_job(db, event_id)['artifact']
    assert len(artifact['scenarios']) == 3
    assert len({row['id'] for row in artifact['scenarios']}) == 3


def test_registered_period_uses_same_known_cutoff_and_never_claims_incident_period(baseline, tmp_path):
    db, saved, _ = baseline
    choice = options(db, saved, 'production_period')[0]
    frozen = service.freeze_inputs(db, saved['id'], saved['content_sha256'], [choice['id']])
    assert frozen['known_at'] == saved['content']['pool']['production_known_at']
    assert frozen['algorithm_versions'] == saved['content']['algorithm_versions']
    event_id = submit(db, saved, [choice['id']])['event_id']
    db.commit()
    assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'completed'
    artifact = jobs.read_job(db, event_id)['artifact']
    assert artifact['scenarios'][1]['parameters'] == choice['parameters']
    assert '完整案发区间' not in str(artifact['scenarios'][1]['rows'])


def test_production_period_recalculates_real_versioned_matches_with_frozen_roads(prepared, tmp_path):
    db, _, calls = prepared
    case = db.get(Case, 1)
    case.occurred_time, case.time_precision = AT, 'exact'
    case.oil_type, case.facility_type = '原油', '井口'
    original = db.query(JurisdictionAssetVersion).filter_by(asset_id=13).one()
    later_from, later_to = AT + timedelta(days=1), AT + timedelta(days=2)
    original.valid_to = later_from
    snapshot = deepcopy(original.snapshot)
    snapshot['attributes']['oil_type'] = '柴油'
    later = JurisdictionAssetVersion(asset_id=13, version=original.version + 1,
        change_type='synthetic_declared', temporal_status='declared', known_at=AT - timedelta(hours=1),
        valid_from=later_from, valid_to=later_to, snapshot=snapshot)
    db.add(later)
    db.flush()
    rebuild_applicable_profile(db, db.get(CaseAnalysisProfile, 'profile-1'))
    source, _ = CaseResultService.create_current(db, 1)
    db.commit()
    content = compare_case_facilities(db, result_id=source['id'], network_id='graph-1',
        analysis_at=AT, vehicle=VEHICLE, artifact_root=tmp_path)
    saved = freeze_road_artifact(db, content)
    db.commit()
    choice = next(row for row in options(db, saved, 'production_period')
                  if row['parameters']['valid_from'] == later_from.isoformat()
                  and row['parameters']['valid_to'] == later_to.isoformat())
    count = len(calls)
    event_id = submit(db, saved, [choice['id']])['event_id']
    db.commit()
    assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'completed'
    artifact = jobs.read_job(db, event_id)['artifact']
    baseline, variant = artifact['scenarios']
    base_row = next(row for row in baseline['rows'] if row['asset_id'] == 13)
    changed_row = next(row for row in variant['rows'] if row['asset_id'] == 13)
    base_oil = next(row for row in base_row['conditions'] if row['key'] == 'oil')
    changed_oil = next(row for row in changed_row['conditions'] if row['key'] == 'oil')
    assert base_oil['state'] == 'supported' and base_oil['value']['facility'] == '原油'
    assert changed_oil['state'] == 'different' and changed_oil['value']['facility'] == '柴油'
    assert f'asset_version:{original.id}' in base_oil['evidence_refs']
    assert f'asset_version:{later.id}' in changed_oil['evidence_refs']
    assert changed_row['score'] < base_row['score']
    assert artifact['frozen']['algorithm_versions'] == content['algorithm_versions']
    assert artifact['frozen']['known_at'] == content['pool']['production_known_at']
    assert baseline['calculation'] == variant['calculation']
    assert [row['asset_id'] for row in baseline['rows']] == [row['asset_id'] for row in variant['rows']]
    assert [next(c['value'] for c in row['conditions'] if c['key'] == 'road') for row in baseline['rows']] == [
        next(c['value'] for c in row['conditions'] if c['key'] == 'road') for row in variant['rows']]
    assert len(calls) == count
    assert db.get(Case, 1).oil_type == '原油'


def test_ledger_half_open_period_preserves_case_closed_interval_and_exact_endpoint_contract(prepared):
    db, _, _ = prepared
    version = db.query(JurisdictionAssetVersion).filter_by(asset_id=13).one()
    start = version.valid_from.replace(tzinfo=timezone.utc)
    end = version.valid_to.replace(tzinfo=timezone.utc)
    closed = resolve_conditions(db, 13, valid_from=start, valid_to=end, known_at=AT)
    ledger = resolve_conditions(db, 13, valid_from=start, valid_to=end, known_at=AT, end_inclusive=False)
    assert closed['groups']['details']['coverage'] == 'partial'
    assert closed['groups']['details']['segments'][-1]['end_inclusive'] is True
    assert closed['query_interval'] == {'from': start.isoformat(), 'to': end.isoformat()}
    assert ledger['groups']['details']['coverage'] == 'full'
    assert ledger['query_interval'] == {'from': start.isoformat(), 'to': end.isoformat(), 'end_inclusive': False}
    assert all(not row['end_inclusive'] for row in ledger['groups']['details']['segments'])
    assert resolve_conditions(db, 13, valid_at=start, known_at=AT)['groups']['details']['coverage'] == 'full'
    assert resolve_conditions(db, 13, valid_at=end, known_at=AT)['groups']['details']['coverage'] == 'unknown'
    assert resolve_conditions(db, 13, valid_from=start, valid_to=start, known_at=AT)['groups']['details']['coverage'] == 'full'
    with pytest.raises(ValueError, match='half_open_interval_required'):
        resolve_conditions(db, 13, valid_from=start, valid_to=start, known_at=AT, end_inclusive=False)
    with pytest.raises(ValueError, match='half_open_interval_required'):
        resolve_conditions(db, 13, valid_at=start, known_at=AT, end_inclusive=False)


@pytest.mark.parametrize('change', ['cancel', 'scope', 'integrity'])
def test_cancel_scope_and_tampering_do_not_publish(baseline, tmp_path, change):
    db, saved, _ = baseline
    event_id = submit(db, saved)['event_id']
    db.commit()
    if change == 'cancel':
        jobs.cancel(db, event_id)
        assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'cancelled'
    elif change == 'scope':
        db.query(RoadAccessMembership).delete()
        db.commit()
        assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'superseded'
        with pytest.raises(PermissionError):
            jobs.read_job(db, event_id)
    else:
        event = db.get(OutboxEvent, event_id)
        payload = deepcopy(event.payload)
        payload['inputs']['variants'][0]['assets'][0]['name'] = 'tampered'
        event.payload = payload
        db.commit()
        assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'superseded'
    assert 'artifact' not in db.get(OutboxEvent, event_id, populate_existing=True).payload


def test_api_rejects_unregistered_parameters_and_returns_no_store(baseline):
    from app.main import app
    from app.api.road_analysis import read_session
    db, saved, _ = baseline
    app.dependency_overrides[read_session] = lambda: db
    try:
        with TestClient(app) as client:
            url = f"/api/road-analysis/artifacts/{saved['id']}/scenarios"
            response = client.post(url, json={'artifact_sha256': saved['content_sha256'],
                'option_ids': [options(db, saved)[0]['id']]})
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'no-store'
            assert client.post(url, json={'artifact_sha256': saved['content_sha256'],
                'option_ids': ['a' * 64], 'ignore_restrictions': True}).status_code == 422
            assert client.post(url, json={'artifact_sha256': saved['content_sha256'],
                'option_ids': ['a' * 64]}).status_code == 409
    finally:
        app.dependency_overrides.pop(read_session, None)


def test_fresh_worker_session_reconstructs_current_identity(baseline, tmp_path):
    from sqlalchemy.orm import Session
    db, saved, _ = baseline
    event_id = submit(db, saved)['event_id']
    db.commit()
    with Session(bind=db.bind) as worker:
        assert not worker.info
        assert jobs.process(worker, event_id, artifact_root=tmp_path)['status'] == 'completed'
        assert not worker.info


def test_registered_vehicle_recalculates_same_pool_and_keeps_road_failures_unknown(baseline, monkeypatch, tmp_path):
    from test_road_network_models import network
    from app.services.vehicle_router import RoadCalculationError
    db, saved, _ = baseline
    manifest = deepcopy(db.get(RoadNetworkVersion, 'graph-1').source_manifest)
    manifest['vehicle'] = {'kind': 'truck', 'source': 'explicit_reference_assumption', 'height_m': 3.5, 'weight_t': 10.0}
    db.add(network(id='truck-graph', status='ready', input_sha256='d' * 64, graph_sha256='d' * 64,
        artifact_key='d' * 64, source_manifest=manifest))
    db.commit()
    choice = options(db, saved, 'reference_vehicle')[0]
    event_id = submit(db, saved, [choice['id']])['event_id']
    db.commit()
    def failed_matrix(_db, **kwargs):
        assert kwargs['network_id'] == 'truck-graph'
        assert kwargs['vehicle'].kind == 'truck' and kwargs['vehicle'].height_m == 3.5
        raise RoadCalculationError('road_engine_unavailable')
    monkeypatch.setattr('app.services.facility_road_batches.calculate_distance_matrix', failed_matrix)
    assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'completed'
    artifact = jobs.read_job(db, event_id)['artifact']
    variant = artifact['scenarios'][1]
    assert variant['state'] == 'partial'
    assert all(row['eligibility'] == 'unresolved' for row in variant['rows'])
    assert all(next(c for c in row['conditions'] if c['key'] == 'road')['value']['state'] == 'calculation_failed' for row in variant['rows'])
    assert all(row['classification'] == 'insufficient_data' for row in artifact['observations'])


def test_applicability_rechecked_without_injecting_permissive_masks(baseline, tmp_path):
    from app.models.case_source import CaseLocation
    from app.services.case_pipeline_service import CasePipelineService
    from app.services.case_source_service import CaseSourceService
    from app.services.case_analysis_applicability import allows
    db, saved, _ = baseline
    event_id = submit(db, saved)['event_id']
    db.commit()
    case = db.get(Case, 1)
    case.description = '现场查获运输车辆，盗取来源未知。'
    for point in db.query(CaseLocation).filter_by(case_id=1).all():
        point.role = 'discovery'
    db.flush()
    CaseSourceService.capture_change(db, case)
    payload = CasePipelineService.build_profile_payload(db, case)
    assert not allows(payload, 'road_analysis')
    profile = db.get(CaseAnalysisProfile, 'profile-1')
    profile.payload, profile.source_hash, profile.source_revision_id = payload, payload['source_hash'], payload['source_revision_id']
    db.commit()
    assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'superseded'
    assert 'artifact' not in db.get(OutboxEvent, event_id).payload


def register_synthetic_road(db):
    graph = db.get(RoadNetworkVersion, 'graph-1')
    manifest = deepcopy(graph.source_manifest)
    manifest['filter_result'].update(output_sha256='9' * 64,
        new_internal_components=[{'source_id': 10, 'import_id': 100, 'feature_id': 'road', 'way_id': 500}])
    graph.source_manifest = manifest
    db.commit()


def test_registered_road_missing_retained_source_is_not_ready_not_soft_avoidance(baseline, tmp_path):
    db, saved, calls = baseline
    register_synthetic_road(db)
    choice = options(db, saved, 'extra_road_exclusion')[0]
    assert choice['parameters']['way_ids'] == [500]
    assert not choice['source_retained']
    event_id = submit(db, saved, [choice['id']])['event_id']
    db.commit()
    count = len(calls)
    assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'completed'
    artifact = jobs.read_job(db, event_id)['artifact']
    variant = artifact['scenarios'][1]
    assert artifact['state'] == 'partial' and variant['availability'] == 'not_ready'
    assert variant['unavailable_reason'] == 'road_scenario_source_not_retained'
    assert variant['execution'] == 'network_not_ready'
    assert len(calls) == count
    assert db.query(RoadNetworkVersion).count() == 1
    assert all(next(c for c in row['conditions'] if c['key'] == 'road')['value']['state'] == 'network_missing' for row in variant['rows'])
    retry = submit(db, saved, [choice['id']])
    duplicate = submit(db, saved, [choice['id']])
    db.commit()
    assert retry['created'] and retry['event_id'] != event_id
    assert not duplicate['created'] and duplicate['event_id'] == retry['event_id']
    assert jobs.read_job(db, event_id)['artifact'] == artifact  # The prior snapshot is not overwritten.


def test_private_preparation_checkpoints_before_matrix_and_resumes_same_pool(baseline, monkeypatch, tmp_path):
    """Queue orchestration only; strict source/graph validation has native tests."""
    from app.services import road_scenario_networks
    db, saved, calls = baseline
    register_synthetic_road(db)
    choice = options(db, saved, 'extra_road_exclusion')[0]
    preparations = []
    def prepare(session, network_id, graph_hash, **kwargs):
        preparations.append(kwargs)
        assert kwargs['registered_road_id'] == choice['parameters']['registered_road_id']
        assert kwargs['scenario_id'] == f"{saved['id']}:{choice['id']}"
        assert network_id == 'graph-1' and graph_hash == 'c' * 64
        # Do not claim this fixture built a strict child graph. It isolates the
        # queue continuation contract from separately tested native preparation.
        return {'state': 'ready', 'network_id': 'graph-1', 'graph_sha256': 'c' * 64}
    monkeypatch.setattr(road_scenario_networks, 'prepare_private_network', prepare)
    event_id = submit(db, saved, [choice['id']])['event_id']
    db.commit()
    count = len(calls)
    assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'pending'
    assert len(calls) == count and len(preparations) == 1
    assert jobs.read_job(db, event_id)['progress']['scenarios_completed'] == 1
    event = db.get(OutboxEvent, event_id)
    event.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert jobs.process(db, event_id, artifact_root=tmp_path)['status'] == 'completed'
    artifact = jobs.read_job(db, event_id)['artifact']
    assert len(preparations) == 1 and len(calls) > count
    assert artifact['scenarios'][1]['execution'] == 'recalculated_same_frozen_pool'
    assert artifact['frozen']['pool_sha256'] == saved['content']['pool']['input_sha256']


def test_period_outside_known_cutoff_not_offered(baseline):
    from app.models.map_foundation import JurisdictionAssetVersion
    db, saved, _ = baseline
    cutoff = service._at(saved['content']['pool']['production_known_at'])
    version = JurisdictionAssetVersion(asset_id=13, version=900, change_type='later_synthetic', temporal_status='declared',
        known_at=cutoff + timedelta(days=10), valid_from=AT - timedelta(days=500), valid_to=AT - timedelta(days=499),
        snapshot={'id': 13, 'operational_area_id': 1, 'asset_type': 'well', 'verified': True, 'status': 'active', 'attributes': {}})
    db.add(version)
    db.commit()
    periods = options(db, saved, 'production_period')
    assert not any(row['parameters']['valid_from'] == (AT - timedelta(days=500)).isoformat() for row in periods)
