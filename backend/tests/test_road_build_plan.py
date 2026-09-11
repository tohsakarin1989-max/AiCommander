import pytest

from app.models.road_network import RoadAccessGrant, RoadAccessGroup
from app.services.internal_road_service import ingest_roads
from app.services.road_access_policy import VehicleAssumption
from app.services.road_build_plan import freeze_road_build_plan, recheck_build_plan, filter_current_road_source
from app.services.road_public_alias_service import record_alias_decision
from test_map_foundation import db_session  # noqa: F401
from test_internal_road_import import source, collection  # noqa: F401
from test_road_build_inputs import prepared  # noqa: F401
from test_road_public_alias import decision
from test_road_access_policy import AT


def arguments(**changes):
    return {'source_ids': [1], 'group_id': 1, 'at': AT,
            'vehicle': VehicleAssumption(kind='auto', source='explicit_reference_assumption'),
            'public_source_sha256': 'a' * 64, **changes}


def test_missing_correspondence_never_becomes_unrestricted_public_graph(prepared, tmp_path):
    db, _, _ = prepared
    plan = freeze_road_build_plan(db, **arguments())
    assert plan['status'] == 'correspondence_pending' and plan['graph_ready'] is False
    assert plan['unresolved'][0]['feature_id'] == 'road-1'
    with pytest.raises(ValueError, match='correspondence_pending'):
        filter_current_road_source(db, source_pbf=tmp_path / 'not-read', output=tmp_path / 'not-created', **arguments())
    assert not (tmp_path / 'not-created').exists()


def test_revocation_and_policy_change_invalidate_frozen_exclusions(prepared):
    db, _, batch = prepared
    row, _ = record_alias_decision(db, decision(batch))
    initial = freeze_road_build_plan(db, **arguments())
    assert not initial['excluded_public_way_ids']
    assert initial['internal_geometry_and_conditions_overlay_required']
    db.query(RoadAccessGrant).delete()
    db.commit()
    denied = freeze_road_build_plan(db, **arguments())
    assert denied['excluded_public_way_ids'] == [12345678901]
    assert not denied['internal_geometry_and_conditions_overlay_required']
    with pytest.raises(ValueError, match='plan_changed'):
        recheck_build_plan(db, initial)
    record_alias_decision(db, decision(batch, decision='revoked', request_key='revoke', previous_id=row.id))
    db.commit()
    with pytest.raises(ValueError, match='plan_changed'):
        recheck_build_plan(db, denied)
    assert freeze_road_build_plan(db, **arguments())['status'] == 'correspondence_pending'


def test_new_internal_or_public_version_requires_its_own_correspondence(prepared):
    db, road, batch = prepared
    record_alias_decision(db, decision(batch))
    assert freeze_road_build_plan(db, **arguments(public_source_sha256='b' * 64))['status'] == 'correspondence_pending'
    road['properties']['conditions']['gate'] = 'closed'
    ingest_roads(db, 1, collection(road), 1)
    db.commit()
    plan = freeze_road_build_plan(db, **arguments())
    assert plan['status'] == 'correspondence_pending'
    assert plan['aliases'] == []


@pytest.mark.parametrize('changed_during_filter', [False, True])
def test_database_governance_drives_real_pbf_exclusion(prepared, tmp_path, monkeypatch, changed_during_filter):
    osmium = pytest.importorskip('osmium', reason='requires offline PBF dependency')
    from test_road_source_filter import fixture as public_fixture
    from app.services import road_source_filter
    db, _, batch = prepared
    source_pbf = tmp_path / 'public.osm.pbf'
    source_hash = public_fixture(source_pbf)
    record_alias_decision(db, decision(batch, public_source_sha256=source_hash, osm_way_id=20))
    db.query(RoadAccessGrant).delete()
    db.commit()
    original = road_source_filter.filter_road_source

    def filter_then_change(*args, **kwargs):
        result = original(*args, **kwargs)
        if changed_during_filter:
            db.get(RoadAccessGroup, 1).policy_revision = 2
            db.commit()
        return result

    monkeypatch.setattr(road_source_filter, 'filter_road_source', filter_then_change)
    output = tmp_path / 'out'
    if changed_during_filter:
        with pytest.raises(ValueError, match='plan_changed'):
            filter_current_road_source(db, source_pbf=source_pbf, output=output,
                                       **arguments(public_source_sha256=source_hash))
        assert not (output / 'governance-filter-manifest.json').exists()
    else:
        result = filter_current_road_source(db, source_pbf=source_pbf, output=output,
                                            **arguments(public_source_sha256=source_hash))
        assert result['excluded_way_ids'] == [20]
        assert result['governance_plan']['aliases'][0]['excluded'] is True
        assert result['status'] == 'filtered_not_published'
    found = []
    class Read(osmium.SimpleHandler):
        def way(self, way):
            found.append(way.id)
    Read().apply_file(str(output / 'eligible.osm.pbf'))
    assert found == [10, 30]


def test_reviewed_full_way_conditions_reach_filtered_source(prepared, tmp_path):
    osmium = pytest.importorskip('osmium', reason='requires offline PBF dependency')
    from app.models.internal_roads import InternalRoadReview
    from test_road_source_filter import fixture as public_fixture
    db, road, _ = prepared
    road['geometry'] = {'type': 'LineString', 'coordinates': [[125.002, 46.], [125.003, 46.]]}
    road['properties']['conditions'] = {'direction': 'forward', 'gate': 'open', 'access': 'permitted',
                                        'max_height_m': 3., 'max_weight_t': 10.}
    batch, _ = ingest_roads(db, 1, collection(road), 1)
    db.add(InternalRoadReview(import_id=batch['id'], operational_area_id=1, feature_id='road-1',
        sequence=1, request_key='conditions-review', decision='verified', note='合成完整线形核验',
        evidence_reference='synthetic-full-way', created_by=1))
    db.commit()
    source_pbf = tmp_path / 'public.osm.pbf'
    source_hash = public_fixture(source_pbf)
    record_alias_decision(db, decision(batch['id'], public_source_sha256=source_hash, osm_way_id=20))
    db.commit()
    result = filter_current_road_source(db, source_pbf=source_pbf, output=tmp_path / 'out',
        **arguments(public_source_sha256=source_hash,
                    vehicle=VehicleAssumption(kind='truck', height_m=2.5, weight_t=8., source='case_record')))
    assert result['condition_overlay_way_ids'] == [20]
    assert result['internal_geometry_and_conditions_overlay_required'] is False
    assert result['governance_plan']['graph_ready'] is False
    assert result['overlay_scope'] == 'exact_full_way_correspondence_only'
    found = {}
    class Read(osmium.SimpleHandler):
        def way(self, way):
            found[way.id] = dict(way.tags)
    Read().apply_file(str(tmp_path / 'out' / 'eligible.osm.pbf'))
    assert found[20]['oneway'] == 'yes'
    assert found[20]['maxheight'] == '3' and found[20]['maxweight'] == '10'


def test_reviewed_multiline_aliases_are_all_compiled_without_user_selecting_segments(prepared, tmp_path):
    pytest.importorskip('osmium', reason='requires offline PBF dependency')
    from app.models.internal_roads import InternalRoadReview
    from test_road_multipart_overlay import source_fixture
    db, road, _ = prepared
    source_pbf = tmp_path / 'public.osm.pbf'
    source_hash, overlay = source_fixture(source_pbf)
    road['geometry'], road['properties']['conditions'] = overlay['geometry'], overlay['conditions']
    batch, _ = ingest_roads(db, 1, collection(road), 1)
    db.add(InternalRoadReview(import_id=batch['id'], operational_area_id=1, feature_id='road-1',
        sequence=1, request_key='multiline-review', decision='verified', note='合成多段核验',
        evidence_reference='synthetic-multiline', created_by=1))
    db.commit()
    for identifier in (10, 20):
        record_alias_decision(db, decision(batch['id'], public_source_sha256=source_hash,
                              osm_way_id=identifier, request_key=f'multipart-{identifier}'))
    db.commit()
    result = filter_current_road_source(db, source_pbf=source_pbf, output=tmp_path / 'out',
                                        **arguments(public_source_sha256=source_hash))
    assert result['condition_overlay_way_ids'] == [10, 20]
    assert [item['component_index'] for item in result['component_references']] == [0, 1]
    assert result['internal_geometry_and_conditions_overlay_required'] is False
