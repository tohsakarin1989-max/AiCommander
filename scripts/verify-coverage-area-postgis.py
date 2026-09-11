"""Owned temporary PostGIS, synthetic geometry only; no existing DB URL accepted."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.coverage_area_service import coverage_area


def run(*command):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=30).stdout.strip()


def main():
    if os.environ.get('AIC_DISPOSABLE_AREA_PG') != '1':
        raise RuntimeError('explicit_disposable_opt_in_required')
    marker = uuid.uuid4().hex
    image = run('docker', 'image', 'inspect', '--format', '{{.Id}}', 'postgis/postgis:16-3.4-alpine')
    container = run('docker', 'run', '--rm', '-d', '--label', f'aic.area-check={marker}',
        '-e', 'POSTGRES_PASSWORD=temporary-synthetic-only', '-e', 'POSTGRES_DB=area_check',
        '-p', '127.0.0.1::5432', image)
    assert re.fullmatch('[a-f0-9]{64}', container)
    report = {'passed': False, 'image_id': image, 'synthetic_only': True}
    try:
        for attempt in range(60):
            try:
                run('docker', 'exec', container, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres')
                break
            except subprocess.CalledProcessError:
                time.sleep(.5)
        else:
            raise RuntimeError('temporary_postgis_not_ready')
        endpoint = run('docker', 'port', container, '5432')
        assert re.fullmatch(r'127\.0\.0\.1:\d+', endpoint)
        engine = create_engine(f'postgresql://postgres:temporary-synthetic-only@{endpoint}/area_check')
        try:
            with Session(engine) as db:
                db.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
                db.commit()
                boundary = [124.98, 46.98, 125.02, 47.02]
                point = {'longitude': 125., 'latitude': 47., 'coverage_radius_m': 200.}
                one = coverage_area(db, boundary, [point], incomplete=False)
                assert one['state'] == 'calculated', one
                assert 120000 < one['known_covered_area_m2'] < 130000, one
                triple = coverage_area(db, boundary, [point] * 3, incomplete=False)
                assert abs(triple['known_covered_area_m2'] - one['known_covered_area_m2']) < .01
                assert abs(triple['unique_overlap_area_m2'] - one['known_covered_area_m2']) < .01
                geometry = triple['map_geometry']
                assert geometry['type'] == 'FeatureCollection'
                layers = {feature['properties']['kind']: feature['geometry'] for feature in geometry['features']}
                assert set(layers) == {'registered_boundary', 'known_coverage', 'unique_overlap'}
                assert all(layer['type'] in ('Polygon', 'MultiPolygon') for layer in layers.values())
                assert db.execute(text('SELECT ST_Equals(ST_GeomFromGeoJSON(:covered), ST_GeomFromGeoJSON(:overlap))'),
                    {'covered': json.dumps(layers['known_coverage']),
                     'overlap': json.dumps(layers['unique_overlap'])}).scalar_one()
                separated = coverage_area(db, boundary, [point, {**point, 'longitude': 125.01}], incomplete=False)
                assert separated['unique_overlap_area_m2'] == 0
                assert abs(separated['known_covered_area_m2'] / one['known_covered_area_m2'] - 2) < .01
                outside = coverage_area(db, boundary, [{**point, 'longitude': 126.}], incomplete=False)
                assert outside['known_covered_area_m2'] == 0
                partial = coverage_area(db, boundary, [point], incomplete=True)
                assert partial['state'] == 'partial' and partial['uncovered_area_m2'] is None
                invalid = {'type': 'Polygon', 'coordinates': [[[125, 47], [125.1, 47.1], [125.1, 47], [125, 47.1], [125, 47]]]}
                assert coverage_area(db, invalid, [point], incomplete=False)['state'] == 'unavailable'
                assert db.execute(text('SELECT 1')).scalar_one() == 1
                report.update(passed=True, single_circle_m2=one['known_covered_area_m2'],
                    triple_overlap_counted_once=True, disconnected_coverage_summed=True,
                    boundary_clip=True, missing_data_not_uncovered=True, invalid_boundary_rejected=True,
                    measured_geometry_returned=True,
                    postgis_version=db.execute(text('SELECT postgis_lib_version()')).scalar_one())
        finally:
            engine.dispose()
    finally:
        assert run('docker', 'inspect', '--format', '{{ index .Config.Labels "aic.area-check" }}', container) == marker
        run('docker', 'stop', container)
        report['owned_container_removed'] = True
        output = Path(__file__).resolve().parents[1] / 'output' / f'coverage-area-{marker}.json'
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({**report, 'evidence': str(output)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
