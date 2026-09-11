from copy import deepcopy
from datetime import timedelta

import pytest

from app.models.internal_roads import InternalRoadImport, InternalRoadReview
from app.models.road_network import RoadAccessGrant, RoadAccessGroup
from app.models.user import User
from app.services.internal_road_service import ingest_roads
from app.services.road_access_policy import VehicleAssumption
from app.services.road_build_inputs import freeze_internal_road_inputs
from test_map_foundation import db_session  # noqa: F401
from test_internal_road_import import source, feature, collection  # noqa: F401
from test_road_access_policy import AT


@pytest.fixture
def prepared(db_session, source):
    db_session.get(User, 1).role = 'admin'
    db_session.add(RoadAccessGroup(id=1, name='测试通行组'))
    db_session.commit()
    db_session.info.update(principal_user_id=1, area_access_levels={1: 'manage'})
    road = feature()
    road['properties']['conditions'] = {'direction': 'both', 'access': 'permitted', 'gate': 'open'}
    batch, _ = ingest_roads(db_session, source, collection(road), 1)
    db_session.add(InternalRoadReview(import_id=batch['id'], operational_area_id=1, feature_id='road-1',
        sequence=1, request_key='review-1', decision='verified', note='合成核验',
        evidence_reference='synthetic-review', created_by=1))
    db_session.add(RoadAccessGrant(group_id=1, policy_revision=1, source_id=source, feature_id='road-1',
        decision='allow', evidence_reference='synthetic-permit', created_by=1))
    db_session.commit()
    return db_session, road, batch['id']


def freeze(db):
    return freeze_internal_road_inputs(db, source_ids=[1], group_id=1, at=AT,
        vehicle=VehicleAssumption(kind='auto', source='explicit_reference_assumption'))


def test_public_only_build_does_not_require_dummy_internal_source(db_session, source):
    db_session.get(User, 1).role = 'admin'
    db_session.add(RoadAccessGroup(id=1, name='公共路网测试组'))
    db_session.commit()
    db_session.info.update(principal_user_id=1)
    result = freeze_internal_road_inputs(db_session, source_ids=[], group_id=1, at=AT,
        vehicle=VehicleAssumption(kind='auto', source='explicit_reference_assumption'))
    assert result['source_ids'] == result['included'] == result['excluded'] == []


def test_empty_selection_cannot_bypass_known_internal_road_even_outside_scope(prepared):
    db, _, _ = prepared
    db.info['authorized_area_ids'] = ()
    with pytest.raises(ValueError, match='catalog_incomplete'):
        freeze_internal_road_inputs(db, source_ids=[], group_id=1, at=AT,
            vehicle=VehicleAssumption(kind='auto', source='explicit_reference_assumption'))


def test_freeze_is_deterministic_detached_and_does_not_write_source(prepared):
    db, road, batch_id = prepared
    before = deepcopy(db.get(InternalRoadImport, batch_id).features)
    first = freeze(db)
    assert first == freeze(db)
    assert len(first['included']) == 1 and first['excluded'] == []
    assert first['included'][0]['geometry'] == road['geometry']
    assert first['graph_ready'] is False
    first['included'][0]['geometry']['coordinates'][0][0][0] = 0
    assert db.get(InternalRoadImport, batch_id).features == before
    assert not db.new and not db.dirty


@pytest.mark.parametrize('change', ['new_unverified', 'closed', 'no_grant', 'review_revoked', 'policy_changed'])
def test_latest_source_or_authority_changes_do_not_revive_old_road(prepared, change):
    db, road, batch_id = prepared
    before = freeze(db)
    if change in ('new_unverified', 'closed'):
        road['properties']['name'] = '新版本道路'
        if change == 'closed':
            road['properties']['conditions']['gate'] = 'closed'
        ingest_roads(db, 1, collection(road), 1)
    elif change == 'no_grant':
        db.query(RoadAccessGrant).delete()
    elif change == 'policy_changed':
        db.get(RoadAccessGroup, 1).policy_revision = 2
    else:
        db.add(InternalRoadReview(import_id=batch_id, operational_area_id=1, feature_id='road-1',
            sequence=2, request_key='review-2', decision='rejected', note='撤回合成核验',
            evidence_reference='synthetic-revoke', created_by=1))
    db.commit()
    after = freeze(db)
    assert not after['included'] and len(after['excluded']) == 1
    assert before['manifest_sha256'] != after['manifest_sha256']


def test_build_requires_current_admin_and_source_scope(prepared):
    db, _, _ = prepared
    db.info['authorized_area_ids'] = ()
    with pytest.raises(PermissionError):
        freeze(db)
    db.info['authorized_area_ids'] = (1,)
    db.get(User, 1).role = 'analyst'
    db.commit()
    with pytest.raises(PermissionError):
        freeze(db)


def test_even_excluded_future_opening_bounds_graph_lifetime(prepared):
    db, road, _ = prepared
    opening = AT + timedelta(hours=1)
    road['properties']['conditions']['valid_from'] = opening.isoformat()
    ingest_roads(db, 1, collection(road), 1)
    db.commit()
    result = freeze(db)
    assert not result['included']
    assert result['next_condition_change_at'] == opening.isoformat()
