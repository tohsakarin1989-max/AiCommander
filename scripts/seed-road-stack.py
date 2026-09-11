"""Register fixed PUBLIC map fixtures and one synthetic well in an owned empty stack."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, '/app')

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.case import Case
from app.models.user import User
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import OperationalArea, PublicMapBundle, MapPackageArtifact
from app.models.road_network import RoadAccessGroup, RoadAccessMembership, RoadNetworkVersion
from app.services.map_package_install import install_assets
from app.services.map_asset_layout import storage_key
from app.services.offline_map_service import OfflineMapService
from app.services.road_graph_artifact import install_graph_artifact


def main():
    project = os.environ.get('AIC_DISPOSABLE_STACK_PROJECT', '')
    url = make_url(settings.DATABASE_URL)
    assert project.startswith('aic-road-stack-') and url.database == project.replace('-', '_')
    assert url.host == 'postgres' and url.get_backend_name() == 'postgresql'
    with SessionLocal() as db:
        assert db.scalar(select(Case.id).limit(1)) is None
        assert db.scalar(select(PublicMapBundle.id).limit(1)) is None
        user = db.scalar(select(User).where(User.username == 'synthetic-stack-admin', User.role == 'admin'))
        assert user is not None
        area = db.scalar(select(OperationalArea).where(OperationalArea.is_default.is_(True)))
        assert area is not None
        db.info.update(principal_user_id=user.id, authorized_area_ids=(area.id,), area_access_levels={area.id: 'manage'})
        # Reuse the immutable public graph catalog previously built/published in isolation.
        source = create_engine('sqlite:///file:/fixtures/catalog.sqlite?mode=ro&uri=true')
        with Session(source) as catalog:
            public = catalog.scalar(select(PublicMapBundle))
            graph = catalog.scalar(select(RoadNetworkVersion).where(RoadNetworkVersion.status == 'ready'))
            assert public and graph and graph.source_manifest['internal_area_ids'] == []
            public_values = {column.name: getattr(public, column.name) for column in public.__table__.columns}
            graph_values = {column.name: getattr(graph, column.name) for column in graph.__table__.columns}
        source.dispose()
        db.add(PublicMapBundle(**public_values))
        db.add(RoadAccessGroup(id=graph_values['group_id'], name='合成部署公共道路组', policy_revision=1))
        db.flush()
        db.add(RoadAccessMembership(group_id=graph_values['group_id'], user_id=user.id,
            valid_from=datetime.now(timezone.utc) - timedelta(days=1)))
        install_graph_artifact(Path('/fixtures/graph'), Path(settings.MAP_PACKAGE_ROOT) / 'road-graphs',
                               expected_sha256=graph_values['graph_sha256'])
        db.add(RoadNetworkVersion(**graph_values))
        assembly = Path('/fixtures/assembly')
        installed = install_assets(assembly, Path(settings.MAP_PACKAGE_ROOT))
        assert installed['package_hash'] == 'd4ab1cf9b73f4352b437f81939aed2a86f2afd313fc12185690bb3af772ede48'
        manifest = json.loads((assembly / 'manifest.json').read_text())
        map_bundle = PublicMapBundle(id=public_values['id'] + 1, bundle_id=manifest['bundle_id'],
            provider=manifest['provider'], source_version=manifest['source_version'],
            license_record=manifest['license'], bounds=manifest['bounds'], manifest=manifest,
            package_hash=installed['package_hash'], status='accepted')
        db.add(map_bundle)
        db.flush()
        for asset in manifest['assets']:
            db.add(MapPackageArtifact(public_bundle_id=map_bundle.id,
                artifact_kind='mbtiles' if asset['role'] == 'vector' else asset['role'],
                storage_key=storage_key(map_bundle.package_hash, asset, manifest),
                sha256=asset['sha256'], size_bytes=asset['size_bytes']))
        db.add(JurisdictionAsset(name='合成部署测试井（不是真实井场）', asset_type='well',
            operational_area_id=area.id, latitude=46.5444392, longitude=125.18509545,
            source='synthetic', status='active', verified=True,
            attributes={'oil_type': '原油', 'production_output': 90}))
        db.commit()
        snapshot, _ = OfflineMapService.build_snapshot(db, operational_area_id=area.id,
            public_bundle_id=map_bundle.id, built_by=user.id)
        OfflineMapService.publish_snapshot(db, snapshot.id)
        db.execute(text("SELECT setval(pg_get_serial_sequence('public_map_bundles','id'), (SELECT max(id) FROM public_map_bundles))"))
        db.commit()
        print(json.dumps({'area_id': area.id, 'snapshot_id': snapshot.id,
                          'graph_sha256': graph_values['graph_sha256'], 'fixture_catalog': True}), flush=True)


if __name__ == '__main__':
    main()
