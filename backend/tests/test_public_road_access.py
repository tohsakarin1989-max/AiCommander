import pytest

from app.services.public_road_access import public_way_access


@pytest.mark.parametrize('value', ['private', 'no', 'destination', 'customers', 'delivery', 'permit', 'unknown'])
def test_no_unproven_individual_permission(value):
    assert public_way_access({'access': value}, 'auto')['include'] is False


def test_mode_specific_permission_precedence_is_not_blanket_denial():
    assert public_way_access({'access': 'no', 'motor_vehicle': 'yes'}, 'auto')['include'] is True
    assert public_way_access({'access': 'yes', 'motor_vehicle': 'no'}, 'auto')['include'] is False
    tags = {'motor_vehicle': 'yes', 'hgv': 'no'}
    assert public_way_access(tags, 'auto')['include'] is True
    assert public_way_access(tags, 'truck')['include'] is False


def test_conditions_remain_distinct_from_confirmed_denial():
    result = public_way_access({'access': 'yes', 'motor_vehicle:conditional': 'no @ (Mo-Fr)'}, 'auto')
    assert result == {'include': False, 'reason': 'public_access_condition_unresolved'}
    assert public_way_access({'access:forward': 'no'}, 'auto')['reason'] == 'public_access_condition_unresolved'
    assert public_way_access({'bicycle:conditional': 'no @ (Mo-Fr)'}, 'auto')['include'] is True


def test_missing_access_tags_use_engine_highway_defaults_not_invented_permission():
    assert public_way_access({'highway': 'footway'}, 'auto') == {'include': True, 'reason': 'native_highway_defaults'}
