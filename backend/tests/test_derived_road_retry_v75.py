"""Directory/retry share the original road delegation and dependency fence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.jurisdiction import JurisdictionAsset
from app.models.road_network import RoadAccessMembership
from app.models.user import AuditLog, User
from app.services import derived_operations as operations
from app.services import facility_dependency_guard as dependencies
from app.services.case_road_jobs import enqueue_comparison
from app.services.case_result_service import CaseResultService
from app.services.case_pipeline_service import CASE_PROFILE_SCHEMA_VERSION
from app.services.case_local_semantic_model import resolve_model_plan
from tests.test_case_facility_comparison import prepared, VEHICLE  # noqa: F401
from tests.test_case_results import db_session, result_data  # noqa: F401
from tests.test_road_network_service import ready  # noqa: F401
from tests.test_road_access_policy import AT


def failed_job(db, source):
    # The retained road fixture deliberately uses historical profile versions.
    # Freeze a current synthetic result instead of weakening the retry gate.
    profile = db.get(CaseAnalysisProfile, 'profile-1')
    profile.schema_version = CASE_PROFILE_SCHEMA_VERSION
    profile.dictionary_version = resolve_model_plan(db).version
    db.commit()
    source, _ = CaseResultService.create_current(db, 1)
    db.commit()
    assert CaseResultService.latest_base(db, 1)['freshness'] == 'current'
    job = enqueue_comparison(db, result_id=source['id'], analysis_at=AT,
        vehicle=VEHICLE, engine_version='valhalla-test', include_facility_pool=True)
    row = db.get(OutboxEvent, job['event_id'])
    row.status, row.attempts = 'failed', 3
    db.add(User(id=2, username='recovery-admin', display_name='合成恢复管理员',
                password_hash='synthetic-only', role='admin'))
    db.commit()
    db.info['principal_user_id'] = 2
    return row


def test_current_road_retry_retains_original_scope_and_does_not_route(prepared):
    db, source, calls = prepared
    row = failed_job(db, source)
    original = deepcopy(row.payload)
    assert operations.directory(db)['items'][0]['retryable']
    assert operations.retry_failed(db, row.id, expected_attempts=3, request_id=str(uuid4()))['accepted']
    db.refresh(row)
    assert row.status == 'retry'
    assert row.payload == {**original, 'ordinary_failures': 0}
    assert db.info['principal_user_id'] == 2 and not calls
    assert db.query(AuditLog).filter_by(action=operations.ACTION).count() == 1


@pytest.mark.parametrize('change', ['facility', 'natural_expiry', 'algorithm', 'legacy', 'tamper', 'revoked'])
def test_stale_or_unauthorized_road_job_is_not_advertised_or_retried(prepared, monkeypatch, change):
    db, source, calls = prepared
    clock = datetime.now(timezone.utc)
    monkeypatch.setattr(dependencies, '_now', lambda: clock)
    if change == 'natural_expiry':
        db.get(JurisdictionAsset, 2).valid_to = clock + timedelta(hours=1)
        db.commit()
    row = failed_job(db, source)
    assert operations.directory(db)['items'][0]['retryable']
    if change == 'facility':
        db.get(JurisdictionAsset, 2).attributes = {'oil_type': '后来更正'}
    elif change == 'natural_expiry':
        clock += timedelta(hours=2)
    elif change == 'algorithm':
        row.payload = {**row.payload, 'facility_versions': {'scorer': 'obsolete'}}
    elif change == 'legacy':
        row.payload = {key: value for key, value in row.payload.items() if key != 'dependencies'}
    elif change == 'tamper':
        row.payload = {**row.payload, 'facility_checkpoint': {'version': 'forged', 'sha256': '0' * 64}}
    else:
        db.query(RoadAccessMembership).filter_by(user_id=1).delete()
    db.commit()
    before = deepcopy(row.payload)
    assert not operations.directory(db)['items'][0]['retryable']
    with pytest.raises((ValueError, PermissionError)):
        operations.retry_failed(db, row.id, expected_attempts=3, request_id=str(uuid4()))
    db.refresh(row)
    assert row.status == 'failed' and row.payload == before and not calls
    assert db.info['principal_user_id'] == 2
    assert db.query(AuditLog).filter_by(action=operations.ACTION).count() == 0
