#!/usr/bin/env python3
"""Disposable v7.2 browser fixtures; never loads user/demo data or external models.

The chunk fixture is transport-valid but deliberately not a real map: the real
worker must reject its content without changing the previously published map.
"""
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    if os.environ.get('AIC_V72_SYNTHETIC_ONLY') != '1':
        raise RuntimeError('explicit_disposable_verification_required')
    repository = Path(__file__).resolve().parents[1]
    lookup_fixtures = os.environ.get('AIC_V73_LOOKUP_FIXTURES') == '1'
    if sys.argv[1:] not in ([], ['--v74'], ['--v75']):
        raise RuntimeError('supported_mode_is_v74_v75_or_no_arguments')
    material_fixtures = sys.argv[1:] == ['--v74']
    derived_fixtures = sys.argv[1:] == ['--v75']
    sys.path.insert(0, str(repository / 'backend'))
    with tempfile.TemporaryDirectory(prefix='aic-v72-browser-') as directory:
        root = Path(directory)
        os.chdir(root)
        retained = {key: os.environ[key] for key in ('PATH', 'LANG', 'TMPDIR') if key in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        os.environ.update(
            DATABASE_URL=f'sqlite:///{root}/synthetic.sqlite', MAP_PACKAGE_ROOT=f'{root}/maps',
            SECRET_KEY='isolated-v72-browser-only', ENVIRONMENT='test', AUTH_REQUIRED='true',
            AUTO_CREATE_TABLES='false', ENABLE_VECTOR_DB='false', ENABLE_LEGACY_OPERATIONS_MODULES='false',
            ENABLE_AGENT_LAB='false', AGENT_MODE='off', AGENT_USE_EXTERNAL_MODEL='false',
            AGENT_PROVIDER='deterministic', REDIS_URL=f'unix://{root}/disabled.sock',
            CELERY_BROKER_URL='memory://', CELERY_RESULT_BACKEND='cache+memory://',
            SESSION_COOKIE_SECURE='false', SESSION_COOKIE_NAME='aic_v72_verification',
            FRONTEND_URL='http://127.0.0.1:13065', CORS_ORIGINS='http://127.0.0.1:13065',
            ALLOWED_HOSTS='127.0.0.1,localhost',
        )
        import app.models  # noqa: F401
        from app.database import Base, engine, SessionLocal
        from app.models.map_foundation import OperationalArea
        from app.services.auth_service import AuthService
        from app.services.offline_map_service import OfflineMapService
        from app.services.map_package_import_worker import process_next
        from tests.test_offline_maps import _bundle_bytes
        from tests.test_map_package_set import package
        from openpyxl import Workbook
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            db.add(OperationalArea(id=1, code='v72-synthetic', name='合成验证厂区', is_default=True,
                boundary={'type': 'Polygon', 'coordinates': [[[124.5, 46.2], [125.5, 46.2], [125.5, 46.8], [124.5, 46.8], [124.5, 46.2]]]}))
            db.flush()
            for role in ('admin', 'analyst', 'viewer'):
                AuthService.create_user(db, username=f'v72-{role}', display_name=f'合成验证{role}',
                    password='Disposable-V72-Only!', role=role)
            db.commit()
            if lookup_fixtures:
                from app.models.jurisdiction import JurisdictionAsset
                from app.models.map_foundation import MapSource, JurisdictionAssetVersion
                source = MapSource(source_key='v73-synthetic-history', name='合成旧名来源', source_type='production', operational_area_id=1)
                db.add(source); db.flush()
                target = JurisdictionAsset(name='合成当前登记井', external_id='SYN-OLD-001', asset_type='well', operational_area_id=1,
                    latitude=46.5, longitude=125.1, source='manual', status='active', attributes={'source_id': source.id})
                db.add(target); db.flush()
                db.add(JurisdictionAssetVersion(asset_id=target.id, version=1, change_type='update',
                    snapshot={'name': '合成早期旧井名', 'operational_area_id': 1, 'attributes': {'source_id': source.id}}))
                for index in range(65):
                    db.add(JurisdictionAsset(name=f'合成普通设施{index}', asset_type='well', operational_area_id=1,
                        source='manual', status='active', latitude=46.45, longitude=125.05))
                db.commit()
            bundle, _ = OfflineMapService.import_bundle(db, filename='synthetic-map.zip',
                content=_bundle_bytes(root, attribution='合成一像素验包底图，不代表真实地图覆盖'), imported_by=1)
            snapshot, _ = OfflineMapService.build_snapshot(db, operational_area_id=1, public_bundle_id=bundle.id, built_by=1)
            OfflineMapService.publish_snapshot(db, snapshot.id)
            if material_fixtures:
                from v74_material_fixtures import seed_v74
                print('V74_SYNTHETIC_FIXTURES=' + json.dumps(seed_v74(db), ensure_ascii=False), flush=True)
            if derived_fixtures:
                from v75_derived_fixtures import seed_v75
                print('V75_SYNTHETIC_FIXTURES=' + json.dumps(seed_v75(db, snapshot, root), ensure_ascii=False), flush=True)
            initial_snapshot_id = snapshot.id
        headers = ['井号', '井名', '类型', '经度', '纬度', '产量', '产量单位', '产量周期', '产量口径']
        for filename, rows in (
            ('initial.xlsx', [['SYN-001', '合成生产井甲', 'well', 125.1, 46.5, 8, '吨', '日', '净油'],
                              ['SYN-002', '合成生产井乙', 'well', 999, 46.6, 6, '吨', '日', '净油']]),
            ('update.xlsx', [['SYN-001', '合成生产井甲', 'well', 125.1, 46.5, 12, '吨', '日', '净油']]),
        ):
            book = Workbook()
            book.active.title = '说明'
            book.active.append(['合成测试文件，不含真实生产资料'])
            sheet = book.create_sheet('生产')
            sheet.append(['v7.2 合成台账']); sheet.append([]); sheet.append(headers)
            for row in rows:
                sheet.append(row)
            book.save(root / filename)
        chunks = root / 'chunks'; chunks.mkdir()
        manifest = package(chunks)
        manifest['bundle_id'] = 'v72-synthetic-invalid-content'
        next(item for item in manifest['assets'] if item['role'] == 'glyphs')['name'] = 'glyphs-0-255.pbf'
        (chunks / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        print(f'V72_SYNTHETIC_DIRECTORY={root}', flush=True)
        print(f'V72_INITIAL_CURRENT={initial_snapshot_id}', flush=True)
        from app.main import app
        from threading import Event, Thread
        import uvicorn
        stopped = Event()

        def worker():
            while not stopped.wait(0.5):
                try:
                    with SessionLocal() as db:
                        result = process_next(db)
                        if result:
                            print(f'V72_SYNTHETIC_MAP_WORKER={result}', flush=True)
                except Exception as error:
                    print(f'V72_SYNTHETIC_WORKER_ERROR={type(error).__name__}: {error}', flush=True)

        thread = Thread(target=worker, daemon=True)
        thread.start()
        try:
            uvicorn.run(app, host='127.0.0.1', port=18065, access_log=False)
        finally:
            stopped.set(); thread.join(timeout=5); engine.dispose()


if __name__ == '__main__':
    main()
