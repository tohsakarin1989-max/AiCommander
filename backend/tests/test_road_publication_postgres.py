"""Explicit real PostgreSQL publication race; only an empty disposable database."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(os.environ.get('AIC_ROAD_PUBLISH_PG') != '1', reason='requires disposable PostgreSQL and native compiler')
pytest.importorskip('osmium')

from app.database import Base
from app.models.user import User
from app.models.road_network import RoadNetworkVersion
from app.services import road_publication_service as publication
from app.services.road_build_job import run_road_build_job
from app.services.vehicle_router import VehicleRouter, RoadLocation
from test_internal_road_import import source  # noqa: F401
from test_road_build_inputs import prepared  # noqa: F401
from test_road_build_job import job  # noqa: F401


@pytest.fixture
def db_session():
    url = make_url(os.environ['AIC_ROAD_PUBLISH_PG_URL'])
    assert url.host == '127.0.0.1' and url.database == 'aic_publish_test' and url.get_backend_name() == 'postgresql'
    engine = create_engine(url, connect_args={'options': '-c statement_timeout=15000 -c lock_timeout=10000'})
    assert not inspect(engine).has_table('users'), 'requires new disposable DB'
    with engine.begin() as connection:
        connection.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
    Base.metadata.create_all(engine)
    try:
        with Session(engine, autoflush=False) as db:
            db.add(User(id=1, username='synthetic-map-admin', display_name='合成管理员',
                        password_hash='not-a-login', role='admin'))
            db.commit()
            yield db
    finally:
        engine.dispose()


def test_four_publishers_commit_once_and_installed_native_graph_routes(job, tmp_path, monkeypatch):
    db, arguments = job
    built = run_road_build_job(db, **arguments)
    engine = db.get_bind()
    root = tmp_path / 'installed-graphs'
    barrier = Barrier(4, timeout=15)
    original_install = publication.install_graph_artifact

    def synchronized_install(*args, **kwargs):
        # Ensure all four requests read "building" before the first can commit.
        barrier.wait()
        return original_install(*args, **kwargs)

    monkeypatch.setattr(publication, 'install_graph_artifact', synchronized_install)
    def publish(_):
        with Session(engine) as session:
            session.info.update(principal_user_id=1, authorized_area_ids=(1,), area_access_levels={1: 'manage'})
            return publication.publish_road_candidate(session, built['id'],
                work_root=arguments['work_root'], artifact_root=root)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(publish, range(4)))
    assert sum(response['created'] for response in responses) == 1
    assert len({response['artifact_key'] for response in responses}) == 1
    row = db.get(RoadNetworkVersion, built['id'], populate_existing=True)
    assert row.status == 'ready' and row.source_manifest['build_status'] == 'published'
    assert row.source_manifest['publication']['artifact_key'] == responses[0]['artifact_key']
    router = VehicleRouter(root / row.artifact_key / 'tiles')
    route = router.route(RoadLocation(longitude=125.0002, latitude=46),
                         RoadLocation(longitude=125.0008, latitude=46), arguments['vehicle'])
    assert route['way_ids'] == [10] and route['distance_m'] > 0
    # Repeated publish must rely on the installed package, not temporary output.
    (arguments['work_root'] / built['id']).rename(arguments['work_root'] / 'archived-build')
    repeated = publish(0)
    assert not repeated['created'] and repeated['artifact_key'] == row.artifact_key
