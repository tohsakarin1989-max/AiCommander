from copy import deepcopy
import pytest

from app.services.case_road_vehicle import frozen_road_vehicle
from app.services.case_semantic_service import build_semantic_profile


def content(record=None, text=''):
    return {'semantics': build_semantic_profile({'description': text}, structured={'vehicle_info': record})}


def test_explicit_total_mass_and_height_are_kept_from_one_frozen_vehicle():
    result = content({'type': '罐车', 'height_m': 3.2, 'gross_weight_t': 12.5}, '现场查获罐车')
    before = deepcopy(result)
    vehicle = frozen_road_vehicle(result)
    assert vehicle.kind == 'truck' and vehicle.height_m == 3.2 and vehicle.weight_t == 12.5
    assert vehicle.source == 'case_record' and result == before


@pytest.mark.parametrize('record', [
    {'type': '罐车'}, {'type': '罐车', 'height_m': 3., '载重': 10.},
    {'type': '货车', 'height_m': 3., 'weight_t': 10.},
    {'type': '货车', 'height_m': True, 'gross_weight_t': 10.},
    {'type': '货车', 'height_m': '3米', 'gross_weight_t': 10.},
    {'type': '货车', 'height_m': 3., 'gross_weight_t': -1},
    [{'type': '货车'}, {'height_m': 3., 'gross_weight_t': 10.}],
    {'type': '摩托车'}, {'type': '货车', 'vehicle_type': '小客车'},
])
def test_missing_ambiguous_or_unsupported_conditions_do_not_become_cars(record):
    assert frozen_road_vehicle(content(record)) is None


@pytest.mark.parametrize('text', ['现场查获罐车', '疑似货车', '未见罐车，但发现货车'])
def test_text_truck_mention_without_dimensions_is_a_gap(text):
    assert frozen_road_vehicle(content(text=text)) is None


def test_unknown_and_negated_vehicle_are_not_positive_truck_facts():
    for text in ('', '未见罐车'):
        vehicle = frozen_road_vehicle(content(text=text))
        assert vehicle.kind == 'auto' and vehicle.source == 'explicit_reference_assumption'
    assert frozen_road_vehicle(content({'type': '小客车'})).source == 'case_record'


def test_contradictions_and_source_tampering_are_not_accepted():
    assert frozen_road_vehicle(content({'type': '小客车'}, '现场查获罐车')) is None
    value = content({'type': '货车', 'height_m': 3., 'gross_weight_t': 10.})
    value['semantics']['structured_sources']['snapshots'][0]['value']['height_m'] = 2.
    with pytest.raises(ValueError, match='hash_mismatch'):
        frozen_road_vehicle(value)


@pytest.mark.parametrize('structured', [
    {'case_vehicles': [{'vehicle_type': '货车'}]},
    {'case_vehicles': [{'vehicle_type': '货车'}, {'vehicle_type': '小客车'}]},
    {'vehicle_info': {'type': '货车', 'height_m': 3., 'gross_weight_t': 10.},
     'case_vehicles': [{'vehicle_type': '小客车'}]},
    {'vehicle_info': float('nan')},
])
def test_relational_or_invalid_sources_do_not_disappear_into_default_car(structured):
    result = {'semantics': build_semantic_profile({}, structured=structured)}
    assert frozen_road_vehicle(result) is None


def test_empty_relational_source_does_not_mask_complete_legacy_vehicle():
    result = {'semantics': build_semantic_profile({}, structured={
        'case_vehicles': [], 'vehicle_info': {'type': '货车', 'height_m': 3., 'gross_weight_t': 10.}})}
    assert frozen_road_vehicle(result).kind == 'truck'
