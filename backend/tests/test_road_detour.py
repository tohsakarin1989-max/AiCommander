import pytest
from app.services.road_detour import detour_reference


def test_reference_uses_route_endpoints_and_geodesic_units():
    result = detour_reference([[0., 0.], [.01, 0.]], 2200.)
    assert result['basis'] == 'route_geometry_endpoints'
    assert result['straight_distance_m'] == pytest.approx(1111.95, abs=.1)
    assert result['ratio'] == pytest.approx(1.9785, abs=.001)
    assert result['additional_distance_m'] == pytest.approx(1088.05, abs=.1)


def test_close_endpoints_do_not_create_huge_or_infinite_ratio():
    for end in ([0., 0.], [.00001, 0.]):
        result = detour_reference([[0., 0.], end], 600.)
        assert result['ratio'] is None and result['status'] == 'endpoints_too_close'


def test_rounding_does_not_fabricate_negative_detour():
    result = detour_reference([[0., 0.], [.01, 0.]], 1111.)
    assert result['status'] == 'rounding_limited' and result['ratio'] is None
    with pytest.raises(ValueError, match='inconsistent'):
        detour_reference([[0., 0.], [.01, 0.]], 100.)
