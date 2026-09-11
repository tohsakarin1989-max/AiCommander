import math

import pytest

from app.services.coverage_area_service import _geometry, coverage_area
from tests.test_case_search_page import search_db  # noqa: F401


def test_bbox_is_not_claimed_as_exact_boundary_and_sqlite_does_not_fake_area(search_db):
    shape, kind = _geometry([124.9, 46.9, 125.1, 47.1])
    assert shape['type'] == 'Polygon' and 'not_exact' in kind
    result = coverage_area(search_db, shape, [], incomplete=True)
    assert result['state'] == 'unavailable'
    assert 'known_covered_area_m2' not in result


@pytest.mark.parametrize('boundary', [None, [1, 2, 0, 3], [0, 0, math.nan, 3],
    {'type': 'Polygon', 'coordinates': [[[125, 47], [126, 47], [126, 48]]]},
    {'type': 'Polygon', 'coordinates': [[[0, 0], [30, 0], [30, 1], [0, 0]]]}])
def test_invalid_or_unpartitioned_boundaries_not_measured(search_db, boundary):
    assert coverage_area(search_db, boundary, [], incomplete=False)['state'] == 'unavailable'
