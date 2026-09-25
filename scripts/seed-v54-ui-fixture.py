#!/usr/bin/env python3
"""Create only a disposable, synthetic SQLite browser fixture (never demo data)."""
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from uuid import uuid4


def main():
    if os.environ.get('AIC_DISPOSABLE_FACILITIES_UI') != '1':
        raise RuntimeError('explicit_disposable_test_required')
    root = Path(__file__).resolve().parents[1]
    directory = Path(sys.argv[1]).resolve()
    if not directory.is_dir() or any(directory.iterdir()):
        raise RuntimeError('empty_temporary_directory_required')
    if not str(directory).startswith(('/private/tmp/', '/tmp/', '/private/var/folders/')):
        raise RuntimeError('temporary_directory_required')
    password = os.environ['AIC_FIXTURE_PASSWORD']
    os.environ.update(DATABASE_URL=f'sqlite:///{directory}/fixture.sqlite', ENVIRONMENT='test',
        SECRET_KEY='synthetic-ui-v54-only-not-a-deployment-key', ENABLE_VECTOR_DB='false',
        ENABLE_AGENT_LAB='false', AGENT_MODE='off', AGENT_USE_EXTERNAL_MODEL='false',
        AGENT_PROVIDER='deterministic', MAP_PACKAGE_ROOT=str(directory / 'maps'), AUTH_REQUIRED='true',
        SESSION_COOKIE_SECURE='false')
    os.chdir(directory)
    sys.path.insert(0, str(root / 'backend'))
    import app.models  # noqa: F401
    from app.database import Base, engine, SessionLocal
    from app.models.case import Case
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.models.event import Event
    from app.models.map_foundation import OperationalArea
    from app.services.auth_service import AuthService
    from app.services.case_pipeline_service import CasePipelineService
    from app.services.jurisdiction_service import JurisdictionService
    from app.services.offline_map_service import OfflineMapService
    from app.services.facility_summary_service import reconcile_catalog
    from tests.test_offline_maps import _bundle_bytes
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        user = AuthService.create_user(db, username='v54-review', display_name='合成验收用户', password=password, role='analyst')
        area = db.query(OperationalArea).filter_by(is_default=True).one()
        area.name = '合成验收一区'
        area.boundary = {'type': 'Polygon', 'coordinates': [[[124.5, 46.2], [125.5, 46.2], [125.5, 46.8], [124.5, 46.8], [124.5, 46.2]]]}
        db.commit()
        # Same display name, different identities; nothing here is a real well.
        assets = []
        for index in (1, 2):
            asset = JurisdictionService.create_asset(db, {
                'name': '合成示例井', 'asset_type': 'well', 'external_id': f'SYNTHETIC-WELL-{index}',
                'operational_area_id': area.id, 'latitude': 46.55, 'longitude': 125.0 + index * .003,
                'source': 'manual', 'status': 'active', 'verified': True,
                'attributes': {'oil_type': '原油', 'owner_unit': '合成生产单位', 'production_output': 12,
                    'place_conditions': ['井场'], 'production_valid_from': '2026-01-01T00:00:00Z',
                    'production_valid_to': '2026-12-31T00:00:00Z'}})
            assets.append(asset)
        cases = []
        for index in range(1, 4):
            case = Case(case_number=f'SYNTHETIC-UI-{index}', operational_area_id=area.id,
                occurred_time=datetime(2026, 9, 20 + index, 10, tzinfo=timezone.utc),
                case_type='盗油', facility_type='井口', oil_type='原油', modus_operandi='破坏井口',
                location='合成井场', description='井场发现软管和油桶。未发现罐车。',
                latitude=46.55 if index < 3 else None, longitude=125.005 if index < 3 else None)
            db.add(case)
            db.flush()
            payload = CasePipelineService.build_profile_payload(db, case)
            db.add(CaseAnalysisProfile(id=str(uuid4()), case_id=case.id, profile_version=1,
                source_hash=payload['source_hash'], schema_version=payload['schema_version'],
                dictionary_version=payload['dictionary_version'], payload=payload,
                quality_score=50, analysis_readiness='partial', is_current=True))
            cases.append(case)
        db.flush()
        db.add_all([
            Event(event_number='SYNTHETIC-RECORDED', event_type='oil_trace', operational_area_id=area.id,
                title='合成记录：双外键关联', occurred_time=datetime(2026, 9, 22, 10),
                related_case_id=cases[0].id, related_asset_id=assets[0].id, review_status='confirmed',
                latitude=46.55, longitude=125.003),
            Event(event_number='SYNTHETIC-INDEPENDENT', event_type='tool_trace', operational_area_id=area.id,
                title='合成独立事件', occurred_time=datetime(2026, 9, 22, 11), latitude=46.55, longitude=125.005),
        ])
        db.commit()
        bundle, _ = OfflineMapService.import_bundle(db, filename='synthetic.zip',
            content=_bundle_bytes(directory, bundle_id='synthetic-v54-ui', attribution='合成验收底图，非真实地图'), imported_by=user.id)
        snapshot, _ = OfflineMapService.build_snapshot(db, operational_area_id=area.id, public_bundle_id=bundle.id, built_by=user.id)
        OfflineMapService.publish_snapshot(db, snapshot.id)
        reconcile_catalog(db)
        print({'fixture': str(directory), 'area_id': area.id, 'asset_ids': [row.id for row in assets],
               'case_ids': [row.id for row in cases], 'snapshot_id': snapshot.id})


if __name__ == '__main__':
    main()
