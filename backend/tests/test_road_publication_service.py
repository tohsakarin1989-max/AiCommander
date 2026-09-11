import os

import pytest
from sqlalchemy import update

pytest.importorskip('osmium', reason='optional PBF fixture dependency')

from app.models.road_network import RoadAccessGroup, RoadNetworkVersion
from app.models.user import User
from app.services import road_build_job, road_publication_service as service
from app.services.road_graph_artifact import graph_inventory_sha256
from test_road_build_job import job  # noqa: F401
from test_road_build_inputs import prepared  # noqa: F401
from test_map_foundation import db_session  # noqa: F401
from test_internal_road_import import source  # noqa: F401


@pytest.fixture
def candidate(job, monkeypatch, tmp_path):
    db, arguments = job
    def compile_fixture(source, output, *, expected_source_sha256):
        tiles = output / 'tiles'
        tiles.mkdir(parents=True)
        (tiles / '001.gph').write_bytes(b'publication unit fixture, not real routing graph')
        return {'graph_sha256': graph_inventory_sha256(tiles),
                'source_sha256': expected_source_sha256, 'status': 'built_not_published'}
    monkeypatch.setattr(road_build_job, 'compile_local_graph', compile_fixture)
    built = road_build_job.run_road_build_job(db, **arguments)
    return db, built['id'], {'work_root': arguments['work_root'], 'artifact_root': tmp_path / 'artifacts'}


def test_publish_installs_before_ready_and_repeat_is_idempotent(candidate):
    db, identifier, paths = candidate
    first = service.publish_road_candidate(db, identifier, **paths)
    assert first['created'] is True
    row = db.get(RoadNetworkVersion, identifier, populate_existing=True)
    assert row.status == 'ready'
    assert graph_inventory_sha256(paths['artifact_root'] / row.artifact_key / 'tiles') == row.graph_sha256
    assert row.source_manifest['publication']['published_by'] == 1
    # Retention of temporary build output is not required for an idempotent
    # repeat: the immutable installed artifact is the authoritative copy.
    directory = paths['work_root'] / identifier
    directory.rename(paths['work_root'] / 'archived-build-output')
    second = service.publish_road_candidate(db, identifier, **paths)
    assert second['created'] is False and second['artifact_key'] == first['artifact_key']


@pytest.mark.parametrize('change', ['copy_failure', 'policy', 'role'])
def test_failed_or_revoked_publication_never_marks_candidate_ready(candidate, monkeypatch, change):
    db, identifier, paths = candidate
    original = service.install_graph_artifact
    def interrupted(*args, **kwargs):
        assert not db.in_transaction()
        if change == 'copy_failure':
            raise OSError('simulated disk failure')
        key = original(*args, **kwargs)
        if change == 'policy':
            db.execute(update(RoadAccessGroup).values(policy_revision=2))
        else:
            db.execute(update(User).where(User.id == 1).values(role='analyst'))
        db.commit()
        return key
    monkeypatch.setattr(service, 'install_graph_artifact', interrupted)
    with pytest.raises((OSError, ValueError, PermissionError)):
        service.publish_road_candidate(db, identifier, **paths)
    row = db.get(RoadNetworkVersion, identifier, populate_existing=True)
    assert row.status == 'building' and row.artifact_key is None
    assert row.source_manifest['build_status'] == 'built_not_published'


def test_unauthorized_publish_does_not_copy_files(candidate):
    db, identifier, paths = candidate
    db.info['authorized_area_ids'] = ()
    with pytest.raises(PermissionError):
        service.publish_road_candidate(db, identifier, **paths)
    assert not paths['artifact_root'].exists()


@pytest.mark.skipif(os.environ.get('AIC_BUILD_ROAD_CONDITIONS') != '1', reason='optional real compiler')
def test_real_build_publish_and_route_from_installed_package(job, tmp_path, monkeypatch):
    from app.services.vehicle_router import VehicleRouter, RoadLocation, RoadCalculationError
    db, arguments = job
    built = road_build_job.run_road_build_job(db, **arguments)
    root = tmp_path / 'road-graphs'
    result = service.publish_road_candidate(db, built['id'], work_root=arguments['work_root'], artifact_root=root)
    router = VehicleRouter(root / result['artifact_key'] / 'tiles')
    origin = RoadLocation(longitude=125.0002, latitude=46.)
    destination = RoadLocation(longitude=125.0008, latitude=46.)
    assert router.route(origin, destination, arguments['vehicle'])['way_ids'] == [10]
    with pytest.raises(RoadCalculationError, match='road_engine_calculation_failed'):
        router.route(origin, RoadLocation(longitude=125.0025, latitude=46.), arguments['vehicle'])
    from datetime import timedelta
    from app.models.road_network import RoadAccessMembership
    from app.services import road_network_service
    from app.api.road_analysis import settings
    from test_road_analysis_api import client
    monkeypatch.setattr(road_network_service, '_now', lambda: arguments['at'])
    monkeypatch.setattr(settings, 'MAP_PACKAGE_ROOT', str(tmp_path))
    db.add(RoadAccessMembership(group_id=1, user_id=1, valid_from=arguments['at'] - timedelta(days=1)))
    db.commit()
    response = client(db).post('/api/road-analysis/routes', json={
        'vehicle': {'kind': 'auto'}, 'analysis_at': arguments['at'].isoformat(),
        'start': origin.model_dump(), 'end': destination.model_dump()})
    assert response.status_code == 200, response.text
    assert response.json()['network_id'] == built['id']
    assert response.json()['way_ids'] == [10]
    for metric, budget in [('distance', {'distance_m': 500}), ('time', {'seconds': 60})]:
        preview = client(db).post('/api/road-analysis/reachability-previews', json={
            'vehicle': {'kind': 'auto'}, 'analysis_at': arguments['at'].isoformat(),
            'metric': metric, 'origin': origin.model_dump(), **budget})
        assert preview.status_code == 200, preview.text
        assert preview.json()['network_id'] == built['id']
        assert preview.json()['graph_sha256'] == result['artifact_key']
        assert preview.json()['status'] == 'partial_reference'
        assert preview.json()['roads']['features']
