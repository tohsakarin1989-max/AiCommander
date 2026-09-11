#!/usr/bin/env python3
"""Build and route the downloaded public source in an owned, isolated catalog.

Run with backend Python and optional native dependencies on PYTHONPATH. Never
uses DATABASE_URL, current map pointers, business cases or production catalogs.
Keeps artifacts and a report under output/validation for release evidence.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
# Do not initialize the application's global engine against a business database.
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SECRET_KEY'] = secrets.token_urlsafe(48)

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.database import Base
from app.models.map_foundation import PublicMapBundle
from app.models.road_network import RoadAccessGroup, RoadAccessMembership, RoadNetworkVersion
from app.models.user import User
from app.services.road_access_policy import VehicleAssumption
from app.services.road_build_job import BUILDER_VERSION, run_road_build_job
from app.services.road_calculation_service import calculate_reference_route, calculate_distance_matrix
from app.services.road_publication_service import publish_road_candidate
from app.services.vehicle_router import RoadLocation


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    source_root = ROOT / 'backups/map-foundation/v4-source/20260908'
    road_manifest = json.loads((source_root / 'two-city-roads-v1/road-manifest.json').read_text())
    parent_path = source_root / 'complete-candidate-v1/map-assembly-fiee3l3i/manifest.json'
    parent = json.loads(parent_path.read_text())
    parent_road = next(asset for asset in parent['assets'] if asset['role'] == 'road_source')
    source = source_root / 'two-city-roads-v1/roads.osm.pbf'
    source_sha = digest(source)
    assert source_sha == road_manifest['artifact']['sha256']
    assert road_manifest['source_sha256'] == parent_road['sha256']
    assert parent_road['license'] and parent_road['attribution']
    output_base = ROOT / 'output/validation'
    output_base.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='two-city-governed-', dir=output_base))
    print(str(output), flush=True)
    report = {'passed': False, 'builder_version': BUILDER_VERSION,
              'source_sha256': source_sha, 'changes_business_catalog': False,
              'scope': 'isolated public-road build/publication and sample route; not full coverage acceptance'}
    engine = create_engine('sqlite:///' + str(output / 'catalog.sqlite'))
    try:
        Base.metadata.create_all(engine)
        at = datetime.now(timezone.utc)
        manifest = {'assets': [{'role': 'road_source', 'sha256': source_sha,
                    'license': parent_road['license'], 'attribution': parent_road['attribution']}],
                    'parent_manifest_sha256': digest(parent_path), 'extraction': road_manifest}
        package_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        vehicle = VehicleAssumption(kind='auto', source='explicit_reference_assumption')
        with Session(engine) as db:
            db.info.update(principal_user_id=1, authorized_area_ids=())
            db.add(User(id=1, username='isolated-road-admin', display_name='Isolated verifier',
                        password_hash='disabled-test-account', role='admin', is_active=True))
            db.add(RoadAccessGroup(id=1, name='Isolated public-road verification'))
            db.add(PublicMapBundle(id=1, bundle_id='isolated-two-city-extract',
                provider=parent_road['attribution'], source_version=parent['source_version'],
                license_record=parent_road['license'], bounds=parent['bounds'],
                manifest=manifest, package_hash=package_hash, status='accepted'))
            db.commit()
            db.add(RoadAccessMembership(group_id=1, user_id=1, valid_from=at - timedelta(minutes=1)))
            db.commit()
            candidate = run_road_build_job(db, source_pbf=source, work_root=output / 'jobs',
                source_ids=[], group_id=1, at=at, vehicle=vehicle, public_bundle_id=1)
            report['candidate'] = candidate
            print('native graph built; publishing in isolated catalog', flush=True)
            report['publication'] = publish_road_candidate(db, candidate['id'],
                work_root=output / 'jobs', artifact_root=output / 'artifacts')
            start = RoadLocation(longitude=125.1852727, latitude=46.54446175)
            end = RoadLocation(longitude=125.18509545, latitude=46.5444392)
            args = dict(analysis_at=at, vehicle=vehicle, artifact_root=output / 'artifacts')
            route = calculate_reference_route(db, start=start, end=end, **args)
            matrix = calculate_distance_matrix(db, sources=[start], targets=[end], **args)
            assert route['distance_m'] > 0
            assert matrix['cells'][0]['status'] == 'calculated'
            assert abs(route['distance_m'] - matrix['cells'][0]['distance_m']) <= 5
            report.update(route=route, matrix=matrix,
                filter_result=db.get(RoadNetworkVersion, candidate['id']).source_manifest['filter_result'])
            report['passed'] = True
    except Exception as error:
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        engine.dispose()
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(str(output / 'report.json'), flush=True)


if __name__ == '__main__':
    main()
