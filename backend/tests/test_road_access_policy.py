from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.services.road_access_policy import InternalRoadConditions, VehicleAssumption, internal_road_eligibility


AT = datetime(2026, 9, 11, tzinfo=timezone.utc)


def decide(overrides=None, **kwargs):
    conditions = InternalRoadConditions(**{'direction': 'both', 'gate': 'open', 'access': 'permitted', **(overrides or {})})
    return internal_road_eligibility(conditions=conditions,
        vehicle=kwargs.pop('vehicle', VehicleAssumption(kind='auto', source='explicit_reference_assumption')),
        verified=kwargs.pop('verified', True), traversal_permitted=kwargs.pop('traversal_permitted', True),
        at=kwargs.pop('at', AT), **kwargs)


@pytest.mark.parametrize('conditions,reason', [
    ({'gate': 'closed'}, 'explicitly_closed'), ({'access': 'prohibited'}, 'explicitly_closed'),
    ({'gate': 'unknown'}, 'conditions_unknown'), ({'direction': 'unknown'}, 'conditions_unknown'),
    ({'access': 'unknown'}, 'conditions_unknown'),
    ({'valid_until': AT}, 'conditions_expired'),
    ({'valid_from': AT + timedelta(seconds=1)}, 'conditions_not_yet_valid'),
    ({'max_height_m': 3.0}, 'vehicle_dimensions_missing'),
])
def test_hard_exclusions_are_not_penalties(conditions, reason):
    result = decide(conditions)
    assert not result.include and result.reason == reason and result.direction is None


def test_permission_separate_from_verified_data_and_never_coerced():
    assert decide(traversal_permitted=False).reason == 'traversal_permission_denied'
    assert decide(verified=False).reason == 'source_unverified'
    with pytest.raises(ValueError):
        decide(traversal_permitted=1)


def test_known_vehicle_limits_and_historical_condition_time():
    vehicle = VehicleAssumption(kind='truck', height_m=3.5, weight_t=10.0, source='case_record')
    assert not decide({'max_height_m': 3.4}, vehicle=vehicle).include
    assert not decide({'max_weight_t': 9.0}, vehicle=vehicle).include
    result = decide({'max_height_m': 3.5, 'max_weight_t': 10.0, 'direction': 'reverse',
                     'valid_until': AT + timedelta(seconds=1)}, vehicle=vehicle)
    assert result.include and result.direction == 'reverse'
    assert result.reason == 'eligible_not_connectivity_confirmation'


@pytest.mark.parametrize('values', [{'ignore_restrictions': True}, {'max_height_m': True},
    {'max_weight_t': float('nan')}, {'max_weight_t': -1}, {'valid_from': AT.replace(tzinfo=None)},
    {'valid_from': AT, 'valid_until': AT}])
def test_invalid_conditions_rejected(values):
    with pytest.raises(ValidationError):
        InternalRoadConditions(**values)


def test_unknown_conditions_and_naive_analysis_time_are_not_assumed_safe():
    result = internal_road_eligibility(conditions=InternalRoadConditions(),
        vehicle=VehicleAssumption(kind='auto', source='explicit_reference_assumption'),
        verified=True, traversal_permitted=True, at=AT)
    assert not result.include
    with pytest.raises(ValueError):
        decide(at=AT.replace(tzinfo=None))
