from datetime import datetime, timedelta, timezone
import json

from app.models.map_package_import import MapPackageImport
from app.services import map_package_import_worker as worker
from app.services.map_package_import_service import create_import, put_chunk, submit_import
from tests.test_map_package_imports import db_session, source
from pathlib import Path
from app.config import settings


def queued(db, source):
    directory, manifest = source
    next(a for a in manifest['assets'] if a['role'] == 'glyphs')['name'] = 'glyphs-0-255.pbf'
    row = create_import(db, json.dumps(manifest).encode(), user_id=None)
    for asset in manifest['assets']:
        for chunk in asset['chunks']:
            put_chunk(db, row.id, chunk['file'], (directory / chunk['file']).read_bytes())
    submit_import(db, row.id)
    return row.id


def test_queue_claim_and_render_result_are_not_publication(db_session, source, monkeypatch):
    run_id = queued(db_session, source)
    monkeypatch.setattr(worker, '_validate', lambda path: {'status': 'render_content_validated', 'publish_ready': False})
    result = worker.process_next(db_session)
    assert result['status'] == 'render_validated'
    row = db_session.get(MapPackageImport, run_id)
    assert row.report['publish_ready'] is False
    installation = row.report['installation']
    assert installation['status'] == 'installed_integrity_verified'
    assert installation['publish_ready'] is False
    for asset in installation['assets']:
        assert (Path(settings.MAP_PACKAGE_ROOT) / asset['storage_key']).is_file()
    assert row.lease_token is None
    assert worker.process_next(db_session) is None


def test_storage_failure_does_not_report_success(db_session, source, monkeypatch):
    run_id = queued(db_session, source)
    monkeypatch.setattr(worker, '_validate', lambda path: {'status': 'render_content_validated', 'publish_ready': False})
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(worker, 'install_assets', fail)
    assert worker.process_next(db_session)['status'] == 'failed'
    assert db_session.get(MapPackageImport, run_id).report is None


def test_bad_content_records_failure_keeps_core_map_untouched(db_session, source):
    run_id = queued(db_session, source)
    # Input has transport-valid bytes but is not a real MBTiles database.
    result = worker.process_next(db_session)
    assert result['status'] == 'failed'
    assert db_session.get(MapPackageImport, run_id).error_code == 'map_content_validation_failed'


def test_abandoned_lease_can_be_reclaimed(db_session, source, monkeypatch):
    run_id = queued(db_session, source)
    row = db_session.get(MapPackageImport, run_id)
    row.status = 'validating'
    row.lease_token = 'old'
    row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    db_session.commit()
    assert worker.process_next(db_session) is None
    row.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    monkeypatch.setattr(worker, '_validate', lambda path: {'status': 'render_content_validated', 'publish_ready': False})
    assert worker.process_next(db_session)['status'] == 'render_validated'


def test_old_worker_cannot_overwrite_reclaimed_lease(db_session, source, monkeypatch):
    run_id = queued(db_session, source)

    def steal(directory):
        row = db_session.get(MapPackageImport, run_id)
        row.lease_token = 'new-owner'
        db_session.commit()
        return {'status': 'render_content_validated', 'publish_ready': False}

    monkeypatch.setattr(worker, '_validate', steal)
    assert worker.process_next(db_session)['status'] == 'lease_lost'
    row = db_session.get(MapPackageImport, run_id)
    assert row.status == 'validating'
    assert row.lease_token == 'new-owner'


def test_upload_receipts_do_not_skip_rechecking_bytes(db_session, source, monkeypatch):
    run_id = queued(db_session, source)
    path = Path(settings.MAP_PACKAGE_ROOT) / 'imports' / run_id / 'chunks' / 'vector-0.part'
    path.chmod(0o600)
    path.write_bytes(b'wrong')
    def must_not_run(directory):
        raise AssertionError('corrupt transport must fail before semantic validation')
    monkeypatch.setattr(worker, '_validate', must_not_run)
    assert worker.process_next(db_session)['status'] == 'failed'


def test_expired_worker_cannot_complete_even_before_reclaim(db_session, source, monkeypatch):
    run_id = queued(db_session, source)
    def expire(directory):
        row = db_session.get(MapPackageImport, run_id)
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()
        return {'status': 'render_content_validated', 'publish_ready': False}
    monkeypatch.setattr(worker, '_validate', expire)
    assert worker.process_next(db_session)['status'] == 'lease_lost'
