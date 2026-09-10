"""Registration transactions only; mocked content report is not release evidence."""
from pathlib import Path

import pytest

from app.config import settings
from app.models.map_foundation import MapPackageArtifact, PublicMapBundle, MapSnapshot
from app.models.map_package_import import MapPackageImport
from app.services import map_package_import_worker as worker
from app.services.map_package_registration import register_display_bundle
from tests.test_map_package_import_worker import queued
from tests.test_map_package_imports import db_session, source


def validated(db, source, monkeypatch):
    run_id = queued(db, source)
    manifest = source[1]
    monkeypatch.setattr(worker, '_validate', lambda path: {
        'status': 'render_content_validated', 'publish_ready': False,
        'bundle_id': manifest['bundle_id'], 'style_syntax_verified': True,
        'label_codepoint_coverage_verified': True,
        'primary_place_font_coverage_verified': True})
    assert worker.process_next(db)['status'] == 'render_validated'
    return run_id


def test_registration_idempotent_without_publishing(db_session, source, monkeypatch):
    run_id = validated(db_session, source, monkeypatch)
    first = register_display_bundle(db_session, run_id, user_id=None)
    second = register_display_bundle(db_session, run_id, user_id=None)
    assert first['public_bundle_id'] == second['public_bundle_id']
    assert not first['reused'] and second['reused']
    assert first['acceptance_scope'] == 'offline_display'
    assert first['routing_available'] is False
    assert first['current_changed'] is False
    assert db_session.query(PublicMapBundle).count() == 1
    assert db_session.query(MapPackageArtifact).count() == len(source[1]['assets'])
    assert db_session.query(MapSnapshot).count() == 0


@pytest.mark.parametrize('damage', ['queued', 'flag', 'digest', 'file', 'report_bundle'])
def test_invalid_registration_rolls_back_all_records(db_session, source, monkeypatch, damage):
    run_id = validated(db_session, source, monkeypatch)
    row = db_session.get(MapPackageImport, run_id)
    report = dict(row.report)
    if damage == 'queued':
        row.status = 'queued'
    elif damage == 'flag':
        report['label_codepoint_coverage_verified'] = False
    elif damage == 'digest':
        report['installation'] = {**report['installation'], 'package_hash': '0' * 64}
    elif damage == 'report_bundle':
        report['bundle_id'] = 'different'
    else:
        asset = report['installation']['assets'][0]
        path = Path(settings.MAP_PACKAGE_ROOT) / asset['storage_key']
        path.chmod(0o600)
        path.write_bytes(b'x' * asset['size_bytes'])
    row.report = report
    db_session.commit()
    with pytest.raises(ValueError):
        register_display_bundle(db_session, run_id, user_id=None)
    assert db_session.query(PublicMapBundle).count() == 0
    assert db_session.query(MapPackageArtifact).count() == 0
    assert db_session.query(MapSnapshot).count() == 0


def test_repeat_registration_rechecks_installed_bytes(db_session, source, monkeypatch):
    run_id = validated(db_session, source, monkeypatch)
    register_display_bundle(db_session, run_id, user_id=None)
    artifact = db_session.query(MapPackageArtifact).first()
    path = Path(settings.MAP_PACKAGE_ROOT) / artifact.storage_key
    path.chmod(0o600)
    path.write_bytes(b'x' * artifact.size_bytes)
    with pytest.raises(ValueError, match='bundle_artifact_missing'):
        register_display_bundle(db_session, run_id, user_id=None)
