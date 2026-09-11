from datetime import timedelta

import pytest
from sqlalchemy import update

from app.models.internal_roads import InternalRoadReview
from app.models.map_foundation import MapSource, PublicMapBundle
from app.models.road_network import RoadAccessGrant, RoadAccessMembership
from app.models.road_public_alias import RoadPublicAlias
from app.services.internal_road_service import ingest_roads
from app.services.road_access_policy import VehicleAssumption
from app.services.road_build_plan import freeze_road_build_plan
from app.services.road_network_service import resolve_network, recheck_network, RoadNetworkUnavailable
from app.services.road_public_alias_service import record_alias_decision
from app.services.road_source_revision import source_revision
from app.services.public_road_access import NODE_POLICY_VERSION
from test_map_foundation import db_session  # noqa: F401
from test_internal_road_import import source, collection  # noqa: F401
from test_road_build_inputs import prepared  # noqa: F401
from test_road_network_models import network
from test_road_public_alias import decision
from test_road_access_policy import AT


VEHICLE = VehicleAssumption(kind='auto', source='case_record')


def test_public_only_revision_invalidates_after_first_internal_import(db_session, source):
    from app.models.road_network import RoadAccessGroup
    from test_internal_road_import import feature

    db = db_session
    db.info.update(principal_user_id=1, area_access_levels={1: 'manage'})
    db.add(RoadAccessGroup(id=1, name='Public bootstrap'))
    db.add(PublicMapBundle(id=991, bundle_id='public-bootstrap', provider='synthetic',
        source_version='1', license_record='synthetic fixture', bounds=[125, 46, 126, 47],
        manifest={'assets': [{'role': 'road_source', 'sha256': 'a' * 64}]},
        package_hash='e' * 64, status='accepted'))
    db.commit()
    args = dict(source_ids=[], group_id=1, public_bundle_id=991, public_source_sha256='a' * 64)
    before = source_revision(db, **args)
    assert source_revision(db, **args) == before
    ingest_roads(db, source, collection(feature()), 1)
    db.commit()
    # A scope change must not conceal the new restriction from an old graph.
    db.info['authorized_area_ids'] = ()
    assert db.query(MapSource).count() == 0
    with pytest.raises(ValueError, match='catalog_incomplete'):
        source_revision(db, **args)


@pytest.fixture
def governed(prepared, monkeypatch):
    from app.services import road_network_service
    monkeypatch.setattr(road_network_service, '_now', lambda: AT)
    db, road, batch = prepared
    db.add(PublicMapBundle(id=991, bundle_id='revision-fixture', provider='synthetic', source_version='1',
        license_record='synthetic fixture', bounds=[125, 46, 126, 47],
        manifest={'assets': [{'role': 'road_source', 'sha256': 'a' * 64}]}, package_hash='e' * 64, status='accepted'))
    db.add(RoadAccessMembership(group_id=1, user_id=1, valid_from=AT - timedelta(days=1)))
    db.commit()
    record_alias_decision(db, decision(batch))
    db.commit()
    plan = freeze_road_build_plan(db, source_ids=[1], group_id=1, at=AT, vehicle=VEHICLE,
                                  public_source_sha256='a' * 64)
    revision = source_revision(db, source_ids=[1], group_id=1, public_bundle_id=991, public_source_sha256='a' * 64)
    # Catalog-only unit fixture, not an engine-validated publication.
    db.add(network(public_bundle_id=991, status='ready', graph_sha256='c' * 64, artifact_key='c' * 64,
        engine_version='3.8.3', builder_version='governed-road-builder-4.2.0-1', source_manifest={
        'internal_area_ids': [1], 'vehicle': VEHICLE.model_dump(), 'governance_plan': plan, 'source_revision': revision,
        'filter_result': {'public_node_access_policy_version': NODE_POLICY_VERSION}}))
    db.commit()
    return db, road, batch, revision


def test_unchanged_revision_is_deterministic_and_read_only(governed):
    db, _, _, revision = governed
    assert source_revision(db, source_ids=[1], group_id=1, public_bundle_id=991,
                           public_source_sha256='a' * 64) == revision
    binding = resolve_network(db, 'graph-1', analysis_at=AT, vehicle=VEHICLE)
    recheck_network(db, binding, analysis_at=AT, vehicle=VEHICLE)
    assert not db.new and not db.dirty


@pytest.mark.parametrize('filter_result', [None, [], 'invalid', {},
    {'public_node_access_policy_version': 'old-version'}])
def test_legacy_graph_without_node_policy_must_be_rebuilt(governed, filter_result):
    from app.models.road_network import RoadNetworkVersion
    db, _, _, _ = governed
    row = db.get(RoadNetworkVersion, 'graph-1')
    row.source_manifest = {**row.source_manifest, 'filter_result': filter_result}
    db.commit()
    with pytest.raises(RoadNetworkUnavailable, match='road_node_policy_rebuild_required'):
        resolve_network(db, 'graph-1', analysis_at=AT, vehicle=VEHICLE)


@pytest.mark.parametrize('change', ['new_import', 'review', 'alias', 'grant', 'source', 'bundle'])
def test_source_change_invalidates_old_graph_before_rebuild_even_with_cached_objects(governed, change):
    db, road, batch, _ = governed
    binding = resolve_network(db, 'graph-1', analysis_at=AT, vehicle=VEHICLE)
    # Warm the identity map, then bypass ORM synchronization to exercise fresh
    # column reads rather than an already-refreshed Python instance.
    db.get(MapSource, 1)
    db.query(RoadPublicAlias).all()
    if change == 'new_import':
        road['properties']['conditions']['gate'] = 'closed'
        ingest_roads(db, 1, collection(road), 1)
    elif change == 'review':
        db.execute(update(InternalRoadReview).where(InternalRoadReview.import_id == batch)
                   .values(decision='rejected').execution_options(synchronize_session=False))
    elif change == 'alias':
        db.execute(update(RoadPublicAlias).values(decision='revoked').execution_options(synchronize_session=False))
    elif change == 'grant':
        db.execute(update(RoadAccessGrant).values(decision='deny').execution_options(synchronize_session=False))
    elif change == 'source':
        db.execute(update(MapSource).where(MapSource.id == 1).values(status='inactive').execution_options(synchronize_session=False))
    else:
        db.execute(update(PublicMapBundle).values(status='revoked').execution_options(synchronize_session=False))
    # Deliberately no commit/expiration: same-session stale objects cannot pass.
    with pytest.raises(RoadNetworkUnavailable, match='road_network_sources_changed'):
        recheck_network(db, binding, analysis_at=AT, vehicle=VEHICLE)


def test_governed_graph_without_revision_cannot_bypass_check(governed):
    from app.models.road_network import RoadNetworkVersion
    db, _, _, _ = governed
    row = db.get(RoadNetworkVersion, 'graph-1')
    row.source_manifest = {key: value for key, value in row.source_manifest.items() if key != 'source_revision'}
    db.commit()
    with pytest.raises(RoadNetworkUnavailable, match='source_revision_unavailable'):
        resolve_network(db, 'graph-1', analysis_at=AT, vehicle=VEHICLE)


def test_authorized_analyst_can_check_revision_without_build_admin_privilege(governed):
    from app.models.map_foundation import UserAreaScope
    from app.models.user import User
    from app.services.road_build_inputs import freeze_internal_road_inputs
    db, _, _, _ = governed
    db.execute(update(User).where(User.id == 1).values(role='analyst'))
    db.add(UserAreaScope(user_id=1, operational_area_id=1, access_level='read'))
    db.commit()
    assert resolve_network(db, 'graph-1', analysis_at=AT, vehicle=VEHICLE).network_id == 'graph-1'
    with pytest.raises(PermissionError, match='road_build_not_authorized'):
        freeze_internal_road_inputs(db, source_ids=[1], group_id=1, at=AT, vehicle=VEHICLE)


def test_new_road_source_in_compiled_area_cannot_be_silently_omitted(governed):
    db, road, _, _ = governed
    binding = resolve_network(db, 'graph-1', analysis_at=AT, vehicle=VEHICLE)
    db.add(MapSource(id=2, source_key='new-internal-roads', name='新增生产道路来源',
                     source_type='production_ledger', operational_area_id=1, status='active'))
    db.commit()
    ingest_roads(db, 2, collection(road), 1)
    db.commit()
    with pytest.raises(RoadNetworkUnavailable, match='source_revision_unavailable'):
        recheck_network(db, binding, analysis_at=AT, vehicle=VEHICLE)
