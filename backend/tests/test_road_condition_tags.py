import pytest

from app.services.road_condition_tags import compile_condition_tags, match_geometry_component


POINTS = [[125., 46.], [125.001, 46.]]


def overlay(direction='forward', *, reverse=False, **conditions):
    return {'geometry': {'type': 'LineString', 'coordinates': list(reversed(POINTS)) if reverse else POINTS},
            'conditions': {'direction': direction, 'gate': 'open', 'access': 'permitted', **conditions}}


def test_verified_geometry_direction_is_relative_to_osm_node_order():
    assert compile_condition_tags({}, POINTS, overlay())['oneway'] == 'yes'
    assert compile_condition_tags({}, POINTS, overlay(reverse=True))['oneway'] == '-1'
    assert compile_condition_tags({}, POINTS, overlay('reverse', reverse=True))['oneway'] == 'yes'


def test_limits_intersect_and_existing_mode_tags_cannot_bypass_oneway():
    tags = {'maxheight': '2.5 m', 'maxweight': '20', 'oneway:motor_vehicle': 'no', 'access': 'private'}
    result = compile_condition_tags(tags, POINTS, overlay(max_height_m=3., max_weight_t=8.))
    assert result == {'maxheight': '2.5', 'maxweight': '8', 'oneway': 'yes',
                      'oneway:motor_vehicle': 'yes', 'access': 'private'}
    assert tags['maxweight'] == '20'


@pytest.mark.parametrize('tags, conditions', [
    ({'oneway': '-1'}, {}),
    ({'oneway': 'reversible'}, {}),
    ({'junction': 'roundabout'}, {}),
    ({'oneway:conditional': 'no @ (Mo-Fr)'}, {}),
    ({'maxheight': '10 feet'}, {'max_height_m': 3.}),
    ({'maxweight:conditional': '5 @ (wet)'}, {'max_weight_t': 10.}),
    ({'maxweight:hgv': '20'}, {'max_weight_t': 10.}),
])
def test_unresolved_or_conflicting_public_conditions_are_not_overwritten(tags, conditions):
    with pytest.raises(ValueError):
        compile_condition_tags(tags, POINTS, overlay(**conditions))


def test_nearby_or_partial_geometry_is_not_assumed_to_be_full_correspondence():
    value = overlay()
    value['geometry']['coordinates'] = [[125., 46.], [125.0009, 46.]]
    with pytest.raises(ValueError, match='road_overlay_full_geometry_required'):
        compile_condition_tags({}, POINTS, value)


def test_closed_or_unknown_gate_cannot_be_compiled_as_permission():
    with pytest.raises(ValueError, match='road_overlay_not_permitted'):
        compile_condition_tags({}, POINTS, overlay(gate='closed'))


def test_multiline_components_have_independent_directions():
    value = overlay()
    other = [[126., 46.], [126.001, 46.]]
    value['geometry'] = {'type': 'MultiLineString', 'coordinates': [POINTS, list(reversed(other))]}
    assert match_geometry_component(value['geometry'], other) == (1, True, 2)
    assert compile_condition_tags({}, POINTS, value)['oneway'] == 'yes'
    assert compile_condition_tags({}, other, value)['oneway'] == '-1'


def test_duplicate_geometry_components_are_ambiguous_not_two_confirmed_segments():
    geometry = {'type': 'MultiLineString', 'coordinates': [POINTS, list(reversed(POINTS))]}
    with pytest.raises(ValueError, match='full_geometry_required'):
        match_geometry_component(geometry, POINTS)
