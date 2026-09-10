"""Orchestration tests; transport fixture report is not real content evidence."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.config import settings, Settings
from app.models.map_foundation import MapSnapshot
from app.models.map_package_import import MapPackageImport
from app.services.auth_service import AuthService
from app.services.map_auto_publication import publish_next
from tests.test_map_package_imports import db_session, source
from tests.test_map_package_registration import validated
from tests.test_offline_maps import _default_area


def prepare(db, source, monkeypatch):
    area = _default_area(db)
    user = AuthService.create_user(db, username='auto-map-admin', display_name='test',
        password='Isolated-map-test-123!', role='admin')
    run_id = validated(db, source, monkeypatch)
    db.get(MapPackageImport, run_id).created_by = user.id
    db.commit()
    monkeypatch.setattr(settings, 'MAP_AUTO_PUBLISH_AREA_IDS', str(area.id))
    return run_id, area, user


def test_opt_in_publishes_once(db_session, source, monkeypatch):
    run_id, area, _ = prepare(db_session, source, monkeypatch)
    result = publish_next(db_session)
    assert result['areas'][0]['status'] == 'published'
    assert db_session.query(MapSnapshot).filter_by(status='current', operational_area_id=area.id).count() == 1
    assert publish_next(db_session) is None
    assert db_session.get(MapPackageImport, run_id).lease_token is None


def test_disabled_does_not_register_or_publish(db_session, source, monkeypatch):
    prepare(db_session, source, monkeypatch)
    monkeypatch.setattr(settings, 'MAP_AUTO_PUBLISH_AREA_IDS', '')
    assert publish_next(db_session) is None
    assert db_session.query(MapSnapshot).count() == 0


def test_revoked_permission_is_reported_without_publishing(db_session, source, monkeypatch):
    _, _, user = prepare(db_session, source, monkeypatch)
    user.is_active = False
    db_session.commit()
    result = publish_next(db_session)
    assert result['areas'][0]['code'] == 'map_publish_permission_revoked'
    assert db_session.query(MapSnapshot).count() == 0


def test_other_area_failure_does_not_undo_success(db_session, source, monkeypatch):
    _, area, _ = prepare(db_session, source, monkeypatch)
    monkeypatch.setattr(settings, 'MAP_AUTO_PUBLISH_AREA_IDS', f'{area.id},99999')
    result = publish_next(db_session)
    assert [entry['status'] for entry in result['areas']] == ['published', 'attention_required']
    assert db_session.query(MapSnapshot).filter_by(status='current').count() == 1


def test_expired_publication_lease_is_recoverable(db_session, source, monkeypatch):
    run_id, _, _ = prepare(db_session, source, monkeypatch)
    row = db_session.get(MapPackageImport, run_id)
    row.lease_token = 'old-worker'
    row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    db_session.commit()
    assert publish_next(db_session) is None
    row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert publish_next(db_session)['areas'][0]['status'] == 'published'


@pytest.mark.parametrize('lost', ['reclaimed', 'expired'])
def test_old_worker_cannot_publish_after_losing_lease(db_session, source, monkeypatch, lost):
    from app.services import map_auto_publication as publication
    run_id, _, _ = prepare(db_session, source, monkeypatch)
    original = publication.register_display_bundle
    def lose_lease(*args, **kwargs):
        result = original(*args, **kwargs)
        row = db_session.get(MapPackageImport, run_id)
        if lost == 'reclaimed':
            row.lease_token = 'new-worker-token'
        else:
            row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()
        return result
    monkeypatch.setattr(publication, 'register_display_bundle', lose_lease)
    result = publish_next(db_session)
    assert result['recorded'] is False
    assert result['areas'][0]['code'] == 'map_publication_lease_lost'
    assert db_session.query(MapSnapshot).filter_by(status='current').count() == 0


@pytest.mark.parametrize('new_version,provider,expected', [
    ('2026-09-08T00:00:00Z', 'OSM public source', 'attention_required'),
    ('2026-09-09T00:00:00Z', 'OSM public source', 'attention_required'),
    ('2026-09-10T00:00:00Z', 'different-provider', 'attention_required'),
    ('2026-09-10T00:00:00Z', 'OSM public source', 'published'),
])
def test_automatic_updates_do_not_regress_or_switch_source(db_session, source, monkeypatch,
                                                         new_version, provider, expected):
    source[1]['source_version'] = '2026-09-09T00:00:00Z'
    _, _, user = prepare(db_session, source, monkeypatch)
    old = publish_next(db_session)['areas'][0]['snapshot_id']
    source[1].update(bundle_id='second-package', source_version=new_version, provider=provider)
    run_id = validated(db_session, source, monkeypatch)
    db_session.get(MapPackageImport, run_id).created_by = user.id
    db_session.commit()
    result = publish_next(db_session)
    assert result['areas'][0]['status'] == expected
    current = db_session.query(MapSnapshot).filter_by(status='current').one()
    if expected == 'attention_required':
        assert result['areas'][0]['code'] == 'map_source_not_newer'
        assert current.id == old
    else:
        assert current.id != old


@pytest.mark.parametrize('value', ['0', '-1', '1,1', 'abc', '1,', ','.join(map(str, range(1,18)))])
def test_invalid_auto_area_configuration_rejected(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, SECRET_KEY='test', MAP_AUTO_PUBLISH_AREA_IDS=value)
