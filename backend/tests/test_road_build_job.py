import hashlib
import os

import pytest
from sqlalchemy import update

pytest.importorskip('osmium', reason='optional local PBF dependency')

from app.models.internal_roads import InternalRoadReview
from app.models.map_foundation import PublicMapBundle
from app.models.road_network import RoadAccessGroup, RoadNetworkVersion
from app.services import road_build_job as service
from app.services.internal_road_service import ingest_roads
from app.services.road_access_policy import VehicleAssumption
from app.services.road_graph_artifact import graph_inventory_sha256
from app.services.road_network_service import select_network, RoadNetworkUnavailable
from app.services.road_public_alias_service import record_alias_decision
from test_map_foundation import db_session  # noqa: F401
from test_internal_road_import import source, collection  # noqa: F401
from test_road_build_inputs import prepared  # noqa: F401
from test_road_public_alias import decision
from test_road_multipart_overlay import source_fixture
from test_road_access_policy import AT


@pytest.fixture
def job(prepared, tmp_path):
    db, road, _ = prepared
    source_pbf = tmp_path / 'source.osm.pbf'
    source_hash, overlay = source_fixture(source_pbf)
    road['geometry'], road['properties']['conditions'] = overlay['geometry'], overlay['conditions']
    batch, _ = ingest_roads(db, 1, collection(road), 1)
    db.add(InternalRoadReview(import_id=batch['id'], operational_area_id=1, feature_id='road-1',
        sequence=1, request_key='build-job-review', decision='verified', note='合成多段核验',
        evidence_reference='synthetic-build-job', created_by=1))
    db.add(PublicMapBundle(id=991, bundle_id='synthetic-road-job', provider='synthetic', source_version='1',
        license_record='synthetic fixture, not public production data', bounds=[125, 46, 126, 47],
        manifest={'assets': [{'role': 'road_source', 'sha256': source_hash}]}, package_hash='e' * 64,
        status='accepted'))
    db.commit()
    for identifier in (10, 20):
        record_alias_decision(db, decision(batch['id'], public_source_sha256=source_hash,
            osm_way_id=identifier, request_key=f'job-alias-{identifier}'))
    db.commit()
    arguments = dict(source_pbf=source_pbf, work_root=tmp_path / 'jobs', source_ids=[1], group_id=1,
                     at=AT, vehicle=VehicleAssumption(kind='auto', source='case_record'), public_bundle_id=991)
    return db, arguments


@pytest.mark.parametrize('change', ['none', 'policy', 'bundle', 'native_failure'])
def test_build_job_commits_before_native_work_and_registers_only_current_candidate(job, monkeypatch, change):
    db, arguments = job
    calls = []
    def compile_fixture(source, output, *, expected_source_sha256):
        assert not db.in_transaction(), 'native compilation must not hold a database transaction'
        assert hashlib.sha256(source.read_bytes()).hexdigest() == expected_source_sha256
        calls.append(True)
        if change == 'native_failure':
            raise RuntimeError('private file and configuration must not be persisted in public failure code')
        if change == 'policy':
            db.execute(update(RoadAccessGroup).values(policy_revision=2))
            db.commit()
        elif change == 'bundle':
            db.execute(update(PublicMapBundle).values(status='revoked'))
            db.commit()
        tiles = output / 'tiles'
        tiles.mkdir(parents=True)
        (tiles / '001.gph').write_bytes(b'unit-test fake graph: not a native routing fixture')
        return {'graph_sha256': graph_inventory_sha256(tiles), 'source_sha256': expected_source_sha256,
                'status': 'built_not_published'}
    monkeypatch.setattr(service, 'compile_local_graph', compile_fixture)
    if change == 'none':
        result = service.run_road_build_job(db, **arguments)
        assert result['build_status'] == 'built_not_published'
        assert result['status'] == 'building' and result['routing_available'] is False
        assert result['graph_sha256']
        repeat = service.run_road_build_job(db, **arguments)
        assert repeat['id'] == result['id'] and repeat['created'] is False
        assert len(calls) == 1
    else:
        with pytest.raises((ValueError, RuntimeError)):
            service.run_road_build_job(db, **arguments)
        row = db.query(RoadNetworkVersion).one()
        assert row.status == 'failed' and row.artifact_key is None
        assert 'private' not in row.source_manifest['failure_code']
    assert db.query(RoadNetworkVersion).filter_by(status='ready').count() == 0


def test_missing_source_binding_creates_no_job_or_files(job):
    db, arguments = job
    db.execute(update(PublicMapBundle).values(manifest={'assets': []}))
    db.commit()
    with pytest.raises(ValueError, match='source_binding_missing'):
        service.run_road_build_job(db, **arguments)
    assert db.query(RoadNetworkVersion).count() == 0
    assert not arguments['work_root'].exists()


def test_failed_new_build_does_not_replace_existing_catalog_version(job, monkeypatch):
    from test_road_network_models import network
    db, arguments = job
    old = network(id='previous-graph', public_bundle_id=991, status='ready',
                  graph_sha256='c' * 64, artifact_key='c' * 64)
    db.add(old)
    db.commit()
    def fail(*args, **kwargs):
        raise ValueError('road_graph_build_failed')
    monkeypatch.setattr(service, 'compile_local_graph', fail)
    with pytest.raises(ValueError, match='road_graph_build_failed'):
        service.run_road_build_job(db, **arguments)
    db.refresh(old)
    assert old.status == 'ready' and old.graph_sha256 == 'c' * 64 and old.artifact_key == 'c' * 64
    assert db.query(RoadNetworkVersion).filter_by(status='failed').count() == 1


@pytest.mark.skipif(os.environ.get('AIC_BUILD_ROAD_CONDITIONS') != '1', reason='optional real compiler')
def test_real_governed_source_to_registered_graph_candidate(job):
    db, arguments = job
    result = service.run_road_build_job(db, **arguments)
    tiles = arguments['work_root'] / result['build_directory_key'] / 'compiled' / 'tiles'
    assert graph_inventory_sha256(tiles) == result['graph_sha256']
    assert result['build_status'] == 'built_not_published'
    assert not result['routing_available']
    row = db.get(RoadNetworkVersion, result['id'])
    assert row.source_manifest['filter_result']['condition_overlay_way_ids'] == [10, 20]
    assert row.source_manifest['vehicle'] == arguments['vehicle'].model_dump()
    with pytest.raises(RoadNetworkUnavailable):
        select_network(db, analysis_at=AT, vehicle=arguments['vehicle'], engine_version='3.8.3')
