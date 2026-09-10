import pytest

from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature
from app.services.case_result_access import CaseResultAccessError
from app.services.case_result_map import frozen_result_map_input, load_result_map_context
from app.services.case_result_service import CaseResultService
from app.services.case_result_snapshot import assemble_case_result
from test_case_result_snapshot import inputs
from test_case_results import db_session, prepare, result_data  # noqa: F401


@pytest.mark.parametrize("latitude,longitude", [(None, None), (False, 125), (46, True), ("46", "125"), (91, 125), (46, 181)])
def test_invalid_recorded_coordinates_are_not_coerced_or_replaced_with_origin(latitude, longitude):
    profile, _, _ = inputs()
    profile.payload["analysis_facts"] = {"latitude": latitude, "longitude": longitude}
    content = assemble_case_result(profile, None, [])["content"]
    spec = frozen_result_map_input(content)
    assert spec["case_marker"] is None
    assert "待核验" in spec["warnings"][0]
    assert spec["map_snapshot_id"] is None


def test_valid_zero_coordinate_remains_zero_and_candidate_inputs_are_copied():
    profile, run, candidate = inputs()
    profile.payload["analysis_facts"] = {"latitude": 0, "longitude": 0}
    candidate.region = {"type": "circle", "center": [125.1, 46.6], "radius_m": 500}
    content = assemble_case_result(profile, run, [candidate])["content"]
    spec = frozen_result_map_input(content)
    assert spec["case_marker"]["latitude"] == 0
    spec["candidates"][0]["region"]["center"][0] = 0
    assert content["candidates"][0]["region"]["center"][0] == 125.1


def test_map_context_pins_historical_layers_and_never_reads_current_coordinates(db_session, result_data):
    prepare(db_session)
    profile, _, _ = result_data
    profile.payload = {**profile.payload, "analysis_facts": {"latitude": 46.6, "longitude": 125.1}}
    db_session.execute(MapSnapshotFeature.__table__.update().values(latitude=46.61, longitude=125.11))
    db_session.commit()
    saved, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    db_session.execute(MapSnapshot.__table__.update().values(status="superseded"))
    db_session.add(MapSnapshot(id="map-new", version="new", operational_area_id=1, public_bundle_id=1,
                               status="current", manifest={}, feature_watermark="2"))
    db_session.execute(Case.__table__.update().where(Case.id == 1).values(latitude=10, longitude=20))
    db_session.execute(JurisdictionAsset.__table__.update().values(latitude=11, longitude=21, name="后改设施名"))
    db_session.commit()
    context = load_result_map_context(db_session, saved["id"])
    assert context["map"]["map_snapshot_id"] == "map-1"
    assert context["map"]["case_marker"]["latitude"] == 46.6
    assert context["basemap"]["snapshot_id"] == "map-1"
    assert context["basemap"]["tile_url"].startswith("/api/maps/tiles/map-1/")
    assert context["production"]["features"][0]["geometry"]["coordinates"] == [125.11, 46.61]
    assert "后改设施名" not in str(context)
    assert context["content_sha256"] == saved["content_sha256"]


def test_map_context_rechecks_current_asset_scope(db_session, result_data):
    prepare(db_session)
    saved, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    db_session.execute(JurisdictionAsset.__table__.update().values(operational_area_id=2))
    db_session.commit()
    with pytest.raises(CaseResultAccessError):
        load_result_map_context(db_session, saved["id"])
