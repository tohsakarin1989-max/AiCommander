from datetime import timedelta

import pytest
from sqlalchemy import update

from app.models.road_network import RoadAccessGroup, RoadAccessMembership, RoadNetworkVersion
from app.models.user import User
from app.models.map_foundation import UserAreaScope
from app.services.road_access_policy import VehicleAssumption
from app.services.road_network_service import select_network, resolve_network, recheck_network, RoadNetworkUnavailable
from test_case_results import db_session, result_data  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_road_network_models import network
from test_road_access_policy import AT


VEHICLE = VehicleAssumption(kind='auto', source='case_record')


def select(db, at=AT):
    return select_network(db, analysis_at=at, vehicle=VEHICLE, engine_version='3.8.3')


def prepare(db):
    db.execute(update(RoadNetworkVersion).values(engine_version='3.8.3'))
    db.commit()


def newer(**changes):
    return network(**{'id': 'newer', 'input_sha256': 'd' * 64, 'engine_version': '3.8.3', 'status': 'ready',
        'graph_sha256': 'c' * 64, 'artifact_key': 'c' * 64,
        'valid_from': AT + timedelta(hours=1),
        'source_manifest': {'internal_area_ids': [1], 'vehicle': VEHICLE.model_dump()}, **changes})


def test_latest_applicable_graph_is_selected_without_resource_choice(ready):
    prepare(ready)
    ready.add(newer())
    ready.commit()
    assert select(ready).network_id == 'graph-1'
    assert select(ready, AT + timedelta(hours=2)).network_id == 'newer'
    with pytest.raises(RoadNetworkUnavailable, match='road_compatible_network_unavailable'):
        select(ready, AT - timedelta(days=2))


@pytest.mark.parametrize('unusable', ['other_vehicle', 'other_area', 'expired', 'other_group', 'old_engine'])
def test_newer_incompatible_catalog_entry_does_not_hide_applicable_graph(ready, unusable):
    prepare(ready)
    value = newer()
    if unusable == 'other_vehicle':
        value.source_manifest = {'internal_area_ids': [1], 'vehicle': {
            'kind': 'truck', 'height_m': 3., 'weight_t': 8., 'source': 'case_record'}}
    elif unusable == 'other_area':
        value.source_manifest = {'internal_area_ids': [2], 'vehicle': VEHICLE.model_dump()}
    elif unusable == 'expired':
        value.valid_until = AT + timedelta(hours=2)
    elif unusable == 'other_group':
        ready.add(RoadAccessGroup(id=2, name='不属于该用户的组'))
        ready.flush()
        value.group_id = 2
    else:
        value.engine_version = 'incompatible'
    ready.add(value)
    ready.commit()
    assert select(ready, AT + timedelta(hours=3)).network_id == 'graph-1'


def test_corrupt_newest_graph_metadata_is_not_hidden_by_fallback(ready):
    prepare(ready)
    ready.add(newer(artifact_key='not-an-approved-path'))
    ready.commit()
    with pytest.raises(RoadNetworkUnavailable, match='integrity_metadata_invalid'):
        select(ready, AT + timedelta(hours=2))


def test_no_membership_never_infers_permission_from_admin_role(ready):
    prepare(ready)
    ready.query(RoadAccessMembership).delete()
    ready.commit()
    with pytest.raises(RoadNetworkUnavailable, match='road_compatible_network_unavailable'):
        select(ready)


def test_demotion_invalidates_old_request_scope_and_binding(ready):
    prepare(ready)
    ready.info['authorized_area_ids'] = None
    binding = resolve_network(ready, 'graph-1', analysis_at=AT, vehicle=VEHICLE)
    ready.execute(update(User).where(User.id == 1).values(role='analyst'))
    ready.commit()
    # db.info deliberately remains the old admin scope: fresh authorization
    # must not keep trusting it when the long-running calculation returns.
    assert ready.info['authorized_area_ids'] is None
    with pytest.raises(RoadNetworkUnavailable):
        recheck_network(ready, binding, analysis_at=AT, vehicle=VEHICLE)


def test_area_grant_revocation_invalidates_running_result_without_new_request(ready):
    prepare(ready)
    ready.execute(update(User).where(User.id == 1).values(role='analyst'))
    ready.add(UserAreaScope(user_id=1, operational_area_id=1, access_level='read'))
    ready.commit()
    binding = resolve_network(ready, 'graph-1', analysis_at=AT, vehicle=VEHICLE)
    ready.query(UserAreaScope).filter_by(user_id=1).delete()
    ready.commit()
    assert ready.info['authorized_area_ids'] == (1,)
    with pytest.raises(RoadNetworkUnavailable):
        recheck_network(ready, binding, analysis_at=AT, vehicle=VEHICLE)


def test_selector_does_not_truncate_incompatible_first_page(ready):
    prepare(ready)
    for index in range(101):
        value = newer()
        value.id = f'newer-{index}'
        value.input_sha256 = f'{index + 1000:064x}'
        value.source_manifest = {'internal_area_ids': [2], 'vehicle': VEHICLE.model_dump()}
        ready.add(value)
    ready.commit()
    assert select(ready, AT + timedelta(hours=2)).network_id == 'graph-1'
