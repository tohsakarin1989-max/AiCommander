from datetime import timedelta

import pytest
from sqlalchemy import update

from app.models.road_network import RoadAccessGroup, RoadAccessMembership, RoadNetworkVersion
from app.models.user import User
from app.services.road_access_policy import VehicleAssumption
from app.services import road_network_service as service
from test_case_results import db_session, result_data  # noqa: F401
from test_road_access_policy import AT
from test_road_network_models import network


@pytest.fixture
def ready(db_session, result_data, monkeypatch):
    monkeypatch.setattr(service, '_now', lambda: AT)
    db_session.add(User(id=1, username='road-reader', display_name='合成账号', password_hash='not-a-login', role='admin', is_active=True))
    db_session.add(RoadAccessGroup(id=1, name='合成通行组'))
    db_session.commit()
    db_session.add(RoadAccessMembership(group_id=1, user_id=1, valid_from=AT - timedelta(days=1)))
    db_session.add(network(status='ready', graph_sha256='c' * 64, artifact_key='c' * 64,
                           source_manifest={'internal_area_ids': [1], 'vehicle': {
                               'kind': 'auto', 'source': 'explicit_reference_assumption'}}))
    db_session.commit()
    db_session.info.update(principal_user_id=1, authorized_area_ids=(1,))
    return db_session


def test_binding_and_cache_change_with_current_data_scope(ready):
    binding = service.resolve_network(ready, 'graph-1', analysis_at=AT)
    service.recheck_network(ready, binding, analysis_at=AT)
    ready.info['authorized_area_ids'] = (1, 2)
    assert service.resolve_network(ready, 'graph-1', analysis_at=AT).cache_key != binding.cache_key
    with pytest.raises(service.RoadNetworkUnavailable, match='road_network_changed'):
        service.recheck_network(ready, binding, analysis_at=AT)


@pytest.mark.parametrize('change', ['membership', 'expired_membership', 'policy', 'disabled_user'])
def test_cached_objects_cannot_bypass_current_revocation(ready, change):
    binding = service.resolve_network(ready, 'graph-1', analysis_at=AT)
    ready.get(RoadAccessGroup, 1)
    ready.get(RoadNetworkVersion, 'graph-1')
    if change == 'membership':
        ready.query(RoadAccessMembership).delete()
    elif change == 'expired_membership':
        ready.execute(update(RoadAccessMembership).values(valid_until=AT))
    elif change == 'policy':
        ready.execute(update(RoadAccessGroup).values(policy_revision=2))
    else:
        ready.execute(update(User).values(is_active=False))
    ready.commit()
    with pytest.raises(service.RoadNetworkUnavailable):
        service.recheck_network(ready, binding, analysis_at=AT)


def test_historical_time_never_falls_back_to_current_graph(ready):
    with pytest.raises(service.RoadNetworkUnavailable, match='road_conditions_not_available_for_time'):
        service.resolve_network(ready, 'graph-1', analysis_at=AT - timedelta(days=2))
    with pytest.raises(ValueError):
        service.resolve_network(ready, 'graph-1', analysis_at=AT.replace(tzinfo=None))


def test_graph_expiry_and_untrusted_resource_key(ready):
    ready.execute(update(RoadNetworkVersion).values(valid_until=AT + timedelta(seconds=1)))
    ready.commit()
    with pytest.raises(service.RoadNetworkUnavailable):
        service.resolve_network(ready, 'graph-1', analysis_at=AT + timedelta(seconds=1))
    ready.execute(update(RoadNetworkVersion).values(artifact_key='../../private'))
    ready.commit()
    with pytest.raises(service.RoadNetworkUnavailable, match='integrity_metadata'):
        service.resolve_network(ready, 'graph-1', analysis_at=AT)


def test_unbound_principal_or_other_user_not_authorized(ready):
    ready.info['principal_user_id'] = 2
    with pytest.raises(service.RoadNetworkUnavailable):
        service.resolve_network(ready, 'graph-1', analysis_at=AT)
    ready.info.pop('principal_user_id')
    with pytest.raises(service.RoadNetworkUnavailable):
        service.resolve_network(ready, 'graph-1', analysis_at=AT)


def test_passage_group_does_not_expose_other_area_internal_geometry(ready):
    ready.info['authorized_area_ids'] = (2,)
    with pytest.raises(service.RoadNetworkUnavailable):
        service.resolve_network(ready, 'graph-1', analysis_at=AT)
    # A certified public-only graph carries an explicit empty internal-area list.
    ready.execute(update(RoadNetworkVersion).values(source_manifest={'internal_area_ids': []}))
    ready.commit()
    assert service.resolve_network(ready, 'graph-1', analysis_at=AT)


def test_vehicle_bound_result_rechecks_metadata_and_is_not_inventory_cache(ready):
    vehicle = VehicleAssumption(kind='auto', source='case_record')
    binding = service.resolve_network(ready, 'graph-1', analysis_at=AT, vehicle=vehicle)
    inventory = service.resolve_network(ready, 'graph-1', analysis_at=AT)
    assert binding.cache_key != inventory.cache_key
    service.recheck_network(ready, binding, analysis_at=AT, vehicle=vehicle)
    ready.execute(update(RoadNetworkVersion).values(source_manifest={'internal_area_ids': [1],
        'vehicle': {'kind': 'truck', 'height_m': 3., 'weight_t': 10., 'source': 'explicit_reference_assumption'}}))
    ready.commit()
    with pytest.raises(service.RoadNetworkUnavailable, match='vehicle_mismatch'):
        service.recheck_network(ready, binding, analysis_at=AT, vehicle=vehicle)
