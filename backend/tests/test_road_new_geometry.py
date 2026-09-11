import os

import pytest

pytest.importorskip('osmium')

from app.services.internal_road_service import ingest_roads
from app.services.road_access_policy import VehicleAssumption
from app.services.road_build_plan import filter_current_road_source
from test_map_foundation import db_session, _client  # noqa: F401
from test_internal_road_import import source, collection  # noqa: F401
from test_road_build_inputs import prepared  # noqa: F401
from test_road_multipart_overlay import source_fixture
from test_road_access_policy import AT


def build_inputs(prepared, tmp_path, *, closed=False, mismatch=False):
    db, road, _ = prepared
    pbf = tmp_path / 'public.osm.pbf'
    digest, _ = source_fixture(pbf)
    road['geometry'] = {'type': 'LineString', 'coordinates': [
        [125.001, 46.0001 if mismatch else 46.], [125.001, 46.001], [125.001, 46.002]]}
    if closed:
        road['properties']['conditions']['gate'] = 'closed'
    batch, _ = ingest_roads(db, 1, collection(road), 1)
    db.commit()
    payload = {'input_sha256': batch['input_sha256'], 'request_key': 'new-road-review',
        'previous_review_id': None, 'decision': 'verified', 'note': '合成新建内部路',
        'evidence_reference': 'synthetic-endpoint-survey', 'connection_evidence': {
            'kind': 'new_road', 'public_source_sha256': digest,
            'connections': [{'component': 0, 'endpoint': 'start', 'osm_node_id': 2}]}}
    url = f"/api/map-sources/1/roads/imports/{batch['id']}/features/road-1/reviews"
    response = _client(db).post(url, json=payload)
    assert response.status_code == 201, response.text
    assert _client(db, 'analyst').post(url, json=payload).status_code == 403
    return db, pbf, digest


@pytest.mark.parametrize('closed,mismatch', [(False, False), (True, False), (False, True)])
def test_reviewed_geometry_enters_graph_only_with_permission_and_exact_connection(prepared, tmp_path, closed, mismatch):
    db, pbf, digest = build_inputs(prepared, tmp_path, closed=closed, mismatch=mismatch)
    kwargs = dict(source_pbf=pbf, output=tmp_path / 'out', source_ids=[1], group_id=1,
        at=AT, vehicle=VehicleAssumption(kind='auto', source='case_record'), public_source_sha256=digest)
    if mismatch:
        with pytest.raises(ValueError, match='connection_mismatch'):
            filter_current_road_source(db, **kwargs)
        assert not (tmp_path / 'out/eligible.osm.pbf').exists()
        return
    result = filter_current_road_source(db, **kwargs)
    assert result['counts']['ways'] == (2 if closed else 3)
    if not closed:
        component = result['new_internal_components'][0]
        assert component['node_ids'][0] == 2
        assert component['way_id'] == 21
    else:
        assert result['governance_plan']['new_roads'] == []


@pytest.mark.skipif(os.environ.get('AIC_BUILD_ROAD_CONDITIONS') != '1', reason='optional real compiler')
def test_native_route_uses_reviewed_new_internal_road(prepared, tmp_path):
    from app.services.road_graph_builder import compile_local_graph
    from app.services.vehicle_router import VehicleRouter, RoadLocation

    db, pbf, digest = build_inputs(prepared, tmp_path)
    vehicle = VehicleAssumption(kind='auto', source='case_record')
    result = filter_current_road_source(db, source_pbf=pbf, output=tmp_path / 'out',
        source_ids=[1], group_id=1, at=AT, vehicle=vehicle, public_source_sha256=digest)
    compile_local_graph(tmp_path / 'out/eligible.osm.pbf', tmp_path / 'compiled',
        expected_source_sha256=result['output_sha256'])
    router = VehicleRouter(tmp_path / 'compiled/tiles')
    route = router.route(RoadLocation(longitude=125.0002, latitude=46.),
        RoadLocation(longitude=125.001, latitude=46.0015), vehicle)
    assert set(route['way_ids']) == {10, 21}
    assert route['distance_m'] > 200
