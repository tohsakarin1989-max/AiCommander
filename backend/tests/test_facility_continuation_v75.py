"""Real isolated SQL checkpoints; matrix values are deterministic test doubles."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Event
import json
import hashlib

import pytest
from sqlalchemy import select

from app.models.case_pipeline import OutboxEvent
from app.models.case_road_artifact import CaseRoadArtifact
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import UserAreaScope
from app.models.user import User
from app.services import case_road_jobs as jobs
from app.services import facility_candidate_pool as pools
from app.services import facility_dependency_guard as dependencies
from app.services import facility_job_checkpoint as checkpoints
from app.services import facility_road_batches as batches
from app.services.case_road_status import automatic_comparison_status
from app.services.case_road_artifact_service import read_road_artifact
from app.services.scorers.facility_roads_v63 import FacilityEvidence
from app.services.vehicle_router import RoadLocation
from test_case_facility_comparison import prepared, VEHICLE  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_road_access_policy import AT


def enqueue(db, source):
    value = jobs.enqueue_comparison(db, result_id=source['id'], analysis_at=AT,
        vehicle=VEHICLE, engine_version='valhalla-test', include_facility_pool=True)
    db.commit()
    return value['event_id']


def due(db, identifier):
    db.get(OutboxEvent, identifier, populate_existing=True).available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()


def test_scanning_cursor_rebuilds_identical_frozen_pool_without_revisiting_rows(prepared, monkeypatch):
    db, source, _ = prepared
    states, visited = [], []
    original = pools._production_context
    def record(session, asset_id, **kwargs):
        visited.append(asset_id)
        return original(session, asset_id, **kwargs)
    monkeypatch.setattr(pools, '_production_context', record)
    kwargs = dict(result_id=source['id'], network_id='graph-1', analysis_at=AT, vehicle=VEHICLE)
    result = pools.freeze_facility_pool(db, **kwargs, scan_limit=3,
        on_scan_checkpoint=lambda value: states.append(deepcopy(value)))
    initial = deepcopy(states[0])
    assert result['pending'] and states[-1]['cursor'] == 4
    while result.get('pending'):
        result = pools.freeze_facility_pool(db, **kwargs, scan_limit=3, scan_state=states[-1],
            on_scan_checkpoint=lambda value: states.append(deepcopy(value)))
    assert visited == list(range(2, 14))
    full = pools.freeze_facility_pool(db, **kwargs, scan_state=initial)
    assert result == full
    assert result['coverage']['scan_complete'] and result['coverage']['entrance_check_complete']


def test_durable_matrix_resume_preserves_successes_and_matches_one_shot(prepared, monkeypatch, tmp_path):
    db, source, calls = prepared
    monkeypatch.setattr(checkpoints, 'ROAD_BATCH_LIMIT', 1)
    identifier = enqueue(db, source)
    assert jobs.process_comparison(db, identifier, artifact_root=tmp_path)['status'] == 'pending'
    checkpoint = deepcopy(db.get(OutboxEvent, identifier, populate_existing=True).payload['facility_checkpoint'])
    assert checkpoints.progress(checkpoint)['road_targets_completed'] == 10
    assert db.query(CaseRoadArtifact).count() == 0
    status = automatic_comparison_status(db, source['id'])
    assert status['progress']['candidate_pool_size'] == 12
    due(db, identifier)
    answer = jobs.process_comparison(db, identifier, artifact_root=tmp_path)
    assert answer['status'] == 'completed'
    assert [len(call['targets']) for call in calls] == [10, 2]
    content = read_road_artifact(db, answer['artifact']['id'])['content']
    pool = checkpoint['pool']
    full = batches.compare_facility_pool(db, origin=RoadLocation(**pool['origin']),
        evidence=[FacilityEvidence(**{**row, 'attribute_refs': tuple(row['attribute_refs'])}) for row in pool['evidence']],
        entrances={int(key): [RoadLocation(**point) for point in values] for key, values in pool['entrances'].items()},
        network_id='graph-1', analysis_at=AT, vehicle=VEHICLE, artifact_root=tmp_path,
        source_versions={**pool['versions'], 'pool_sha256': pool['input_sha256']}, recall_complete=True)
    assert content['result']['scoring_evidence'] == json.loads(json.dumps(full['scoring_evidence']))
    assert content['result']['entrance_results'] == full['entrance_results']
    assert content['result']['road_completion'] == full['road_completion']
    assert [(row['asset_id'], row['score']) for row in content['result']['candidates']] == [
        (row['asset_id'], row['score']) for row in full['candidates']]


def test_crash_after_committed_batch_recovers_without_repeating_it(prepared, monkeypatch, tmp_path):
    db, source, calls = prepared
    identifier = enqueue(db, source)
    original = batches.calculate_distance_matrix
    count = 0
    def crash(session, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise SystemExit('worker process stopped')
        return original(session, **kwargs)
    monkeypatch.setattr(batches, 'calculate_distance_matrix', crash)
    with pytest.raises(SystemExit):
        jobs.process_comparison(db, identifier, artifact_root=tmp_path)
    db.rollback()
    row = db.get(OutboxEvent, identifier, populate_existing=True)
    assert row.payload['facility_checkpoint']['roads']['next_offset'] == 10
    row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    monkeypatch.setattr(batches, 'calculate_distance_matrix', original)
    assert jobs.process_comparison(db, identifier, artifact_root=tmp_path)['status'] == 'completed'
    assert [len(call['targets']) for call in calls] == [10, 2]


@pytest.mark.parametrize('change', ['new_object', 'field', 'natural_expiry', 'scope', 'tamper', 'cancel'])
def test_resume_fences_changed_sources_permissions_expiry_and_cancel(prepared, monkeypatch, tmp_path, change):
    db, source, calls = prepared
    clock = datetime.now(timezone.utc)
    monkeypatch.setattr(dependencies, '_now', lambda: clock)
    if change == 'natural_expiry':
        db.get(JurisdictionAsset, 2).valid_to = clock + timedelta(hours=1)
        db.commit()
    monkeypatch.setattr(checkpoints, 'ROAD_BATCH_LIMIT', 1)
    identifier = enqueue(db, source)
    assert jobs.process_comparison(db, identifier, artifact_root=tmp_path)['status'] == 'pending'
    cancel = Event()
    if change == 'new_object':
        db.add(JurisdictionAsset(id=999, operational_area_id=1, name='新增未入选设施', asset_type='well'))
    elif change == 'field':
        db.get(JurisdictionAsset, 2).attributes = {'oil_type': '新生产资料'}
    elif change == 'natural_expiry':
        clock += timedelta(hours=2)
    elif change == 'scope':
        db.get(User, 1).role = 'analyst'
        db.query(UserAreaScope).delete()
    elif change == 'tamper':
        row = db.get(OutboxEvent, identifier, populate_existing=True)
        value = deepcopy(row.payload)
        value['facility_checkpoint']['roads']['next_offset'] = 12
        row.payload = value
    else:
        cancel.set()
    db.commit()
    if change not in ('cancel',):
        assert 'progress' not in automatic_comparison_status(db, source['id'])
    due(db, identifier)
    result = jobs.process_comparison(db, identifier, artifact_root=tmp_path, cancel_event=cancel)
    assert result['status'] == ('cancelled' if change == 'cancel' else 'superseded')
    assert len(calls) == 1 and db.query(CaseRoadArtifact).count() == 0
    if change in ('new_object', 'field', 'natural_expiry'):
        assert enqueue(db, source) != identifier  # New dependency identity, no stale dedup barrier.


def test_dependency_clock_only_changes_at_declared_boundary_and_excludes_other_areas(prepared):
    db, _, _ = prepared
    now = datetime.now(timezone.utc)
    db.get(JurisdictionAsset, 2).valid_to = now + timedelta(hours=1)
    db.commit()
    first = dependencies.dependency_signature(db, now=now)
    assert dependencies.dependency_signature(db, now=now + timedelta(minutes=30))['sha256'] == first['sha256']
    assert dependencies.dependency_signature(db, now=now + timedelta(hours=1))['sha256'] != first['sha256']
    db.add(JurisdictionAsset(id=999, operational_area_id=2, name='其他厂区设施', asset_type='well'))
    db.commit()
    assert dependencies.dependency_signature(db, now=now)['sha256'] == first['sha256']


def test_expired_lease_without_takeover_cannot_publish(prepared, monkeypatch, tmp_path):
    from app.services.outbox_claim_service import OutboxClaimLostError
    db, source, _ = prepared
    identifier = enqueue(db, source)
    original = batches.calculate_distance_matrix
    def expire(session, **kwargs):
        result = original(session, **kwargs)
        session.query(OutboxEvent).filter_by(id=identifier).update({
            'lease_until': datetime.now(timezone.utc) - timedelta(seconds=1)})
        session.commit()
        return result
    monkeypatch.setattr(batches, 'calculate_distance_matrix', expire)
    with pytest.raises(OutboxClaimLostError):
        jobs.process_comparison(db, identifier, artifact_root=tmp_path)
    assert db.query(CaseRoadArtifact).count() == 0


def test_budget_yields_do_not_exhaust_failure_retries(prepared, monkeypatch, tmp_path):
    from app.services.vehicle_router import RoadCalculationError
    db, source, calls = prepared
    monkeypatch.setattr(checkpoints, 'SCAN_LIMIT', 2)
    identifier = enqueue(db, source)
    for _ in range(5):
        assert jobs.process_comparison(db, identifier, artifact_root=tmp_path)['status'] == 'pending'
        due(db, identifier)
    assert not calls
    def unavailable(*args, **kwargs):
        raise RoadCalculationError('road_engine_unavailable')
    monkeypatch.setattr(batches, 'calculate_distance_matrix', unavailable)
    for expected in ('retry', 'retry', 'failed'):
        assert jobs.process_comparison(db, identifier, artifact_root=tmp_path)['status'] == expected
        due(db, identifier)
    row = db.get(OutboxEvent, identifier, populate_existing=True)
    assert row.attempts == 8 and row.payload['ordinary_failures'] == 3
    assert row.payload['facility_checkpoint']['pool']['coverage']['scan_complete']
    assert db.query(CaseRoadArtifact).count() == 0


def test_historical_graph_unavailable_is_not_reported_as_no_path(prepared):
    from app.services.road_network_contracts import RoadNetworkUnavailable
    db, source, calls = prepared
    with pytest.raises(RoadNetworkUnavailable):
        jobs.enqueue_comparison(db, result_id=source['id'], analysis_at=AT - timedelta(days=1000),
            vehicle=VEHICLE, engine_version='valhalla-test', include_facility_pool=True)
    assert not calls and db.query(CaseRoadArtifact).count() == 0


@pytest.mark.parametrize('legacy', ['missing', 'old_schema'])
def test_old_facility_job_format_is_superseded_not_failed(prepared, tmp_path, legacy):
    db, source, calls = prepared
    identifier = enqueue(db, source)
    row = db.get(OutboxEvent, identifier)
    value = deepcopy(row.payload)
    if legacy == 'missing':
        value.pop('dependencies')
    else:
        value['dependencies']['schema'] = 'obsolete-schema'
    row.payload = value
    legacy_identity = {key: item for key, item in value.items()
                       if key not in ('analysis_at', 'dependencies', 'dependency_sha256')}
    row.idempotency_key = hashlib.sha256(json.dumps(legacy_identity, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    db.commit()
    assert jobs.process_comparison(db, identifier, artifact_root=tmp_path)['status'] == 'superseded'
    assert db.get(OutboxEvent, identifier, populate_existing=True).attempts == 1
    assert not calls and db.query(CaseRoadArtifact).count() == 0
    assert enqueue(db, source) != identifier
