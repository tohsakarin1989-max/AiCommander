#!/usr/bin/env python3
"""Run inside the fixed synthetic map-test container, never a business server.

Back up its SQLite snapshot and immutable installed bundle files, restore into a
new temporary directory and exercise existing map services against that copy.
The resulting synthetic archive is retained under /tmp for controlled export.
"""
from contextlib import closing
import hashlib
import gzip
import json
from pathlib import Path
import shutil
import sqlite3
import tarfile
import tempfile


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    from app.config import settings
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.map_foundation import MapSnapshot, PublicMapBundle, MapPackageArtifact
    from app.services.map_bundle_inventory import verify_bundle_inventory
    from app.services.map_render_service import read_style
    from app.services.map_place_service import search_places
    from app.services.offline_map_service import OfflineMapService

    source_db = Path('/var/lib/aicommander/maps/queue-smoke.sqlite')
    source_root = Path('/var/lib/aicommander/maps/queue-store')
    if (settings.DATABASE_URL != f'sqlite:///{source_db}'
            or Path(settings.MAP_PACKAGE_ROOT) != source_root):
        raise RuntimeError('refuse_non_disposable_configuration')
    snapshot_id = 'bac4827d-f543-44a0-8d92-e65e61a27937'
    with closing(sqlite3.connect(f'file:{source_db}?mode=ro', uri=True)) as source:
        assert source.execute("SELECT count(*) FROM users WHERE username='queue-map-test'").fetchone()[0] == 1
        assert source.execute("SELECT case_number FROM cases").fetchall() == [('SYNTHETIC-DASHBOARD-001',)]
        assert source.execute("SELECT id FROM map_snapshots WHERE status='current'").fetchall() == [(snapshot_id,)]
        # Refuse an in-progress importer instead of racing a publishing worker.
        assert source.execute("SELECT count(*) FROM map_package_imports WHERE status NOT IN ('published','failed','cancelled','render_validated')").fetchone()[0] == 0
        archive_dir = Path(tempfile.mkdtemp(prefix='aic-map-restore-evidence-'))
        archive = archive_dir / 'synthetic-map-backup.tar'
        with tempfile.TemporaryDirectory(prefix='aic-map-restore-work-') as work:
            work = Path(work)
            staged = work / 'backup'
            staged.mkdir()
            with closing(sqlite3.connect(staged / 'database.sqlite')) as target:
                source.backup(target)
            records = {}
            for path in sorted((source_root / 'bundles').rglob('*')):
                if path.is_symlink():
                    raise ValueError('bundle_symlink_rejected')
                if not path.is_file():
                    continue
                relative = path.relative_to(source_root)
                target = staged / 'maps' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                before = digest(path)
                shutil.copyfile(path, target)
                assert digest(target) == before == digest(path), 'bundle_changed_during_backup'
                records[str(relative)] = {'sha256': before, 'bytes': path.stat().st_size}
            assert records, 'empty_backup'
            (staged / 'file-inventory.json').write_text(json.dumps(records, sort_keys=True))
            with tarfile.open(archive, 'w') as output:
                for path in sorted(staged.rglob('*')):
                    if path.is_file():
                        output.add(path, arcname=str(path.relative_to(staged)), recursive=False)
            restored = work / 'restored'
            restored.mkdir()
            with tarfile.open(archive) as backup:
                assert all(member.isfile() for member in backup.getmembers())
                backup.extractall(restored, filter='data')
            for relative, entry in records.items():
                assert digest(restored / 'maps' / relative) == entry['sha256']
            assert digest(restored / 'database.sqlite') == digest(staged / 'database.sqlite')
            engine = create_engine(f'sqlite:///{restored / "database.sqlite"}')
            previous_root = settings.MAP_PACKAGE_ROOT
            try:
                settings.MAP_PACKAGE_ROOT = str(restored / 'maps')
                with sessionmaker(bind=engine)() as db:
                    db.info['authorized_area_ids'] = (1,)
                    snapshot = db.query(MapSnapshot).filter_by(status='current').one()
                    assert snapshot.id == snapshot_id
                    bundle = db.query(PublicMapBundle).filter_by(id=snapshot.public_bundle_id).one()
                    assert verify_bundle_inventory(db, bundle, restored / 'maps', verify_hash=True)
                    style = read_style(db, snapshot_id)
                    places = search_places(db, snapshot_id, '大庆')
                    assert places['items'], 'restored_place_search_empty'
                    artifact = db.query(MapPackageArtifact).filter_by(
                        public_bundle_id=bundle.id, artifact_kind='mbtiles').first()
                    with closing(sqlite3.connect(f'file:{restored / "maps" / artifact.storage_key}?mode=ro', uri=True)) as tiles:
                        z, x, tms_y, expected_tile = tiles.execute('SELECT zoom_level,tile_column,tile_row,tile_data FROM tiles WHERE length(tile_data)>100 LIMIT 1').fetchone()
                    tile, content_type = OfflineMapService.read_tile(db, snapshot_id, z, x, (1 << z) - 1 - tms_y)
                    if expected_tile.startswith(b'\x1f\x8b'):
                        expected_tile = gzip.decompress(expected_tile)
                    assert tile == expected_tile and content_type == 'application/vnd.mapbox-vector-tile'
                    original_style = json.dumps(style, sort_keys=True)
                    # Damage only a restored byte copy. Runtime must reject it;
                    # the valid archive and original source remain intact.
                    style_record = db.query(MapPackageArtifact).filter_by(
                        public_bundle_id=bundle.id, artifact_kind='style').one()
                    style_path = restored / 'maps' / style_record.storage_key
                    original = style_path.read_bytes()
                    style_path.write_bytes(b'corrupt')
                    assert not verify_bundle_inventory(db, bundle, restored / 'maps', verify_hash=True)
                    try:
                        read_style(db, snapshot_id)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('corrupt_restored_style_accepted')
                    style_path.write_bytes(original)
                    assert json.dumps(read_style(db, snapshot_id), sort_keys=True) == original_style
                    assert verify_bundle_inventory(db, bundle, restored / 'maps', verify_hash=True)
            finally:
                settings.MAP_PACKAGE_ROOT = previous_root
                engine.dispose()
            # The original live snapshot has not been switched or overwritten.
            assert source.execute("SELECT id FROM map_snapshots WHERE status='current'").fetchall() == [(snapshot_id,)]
            for relative, entry in records.items():
                assert digest(source_root / relative) == entry['sha256']
            report = {'status': 'passed', 'snapshot_id': snapshot_id,
                      'archive': str(archive), 'archive_sha256': digest(archive),
                      'files': len(records), 'bytes': sum(item['bytes'] for item in records.values()),
                      'restored_style_layers': len(style['layers']), 'place_search_count': len(places['items']),
                      'tile_bytes': len(tile), 'corrupt_restored_file_rejected': True,
                      'original_map_unchanged': True, 'postgresql_volume_test': False,
                      'target_server_verified': False}
            (archive_dir / 'report.json').write_text(json.dumps(report, indent=2))
            print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
