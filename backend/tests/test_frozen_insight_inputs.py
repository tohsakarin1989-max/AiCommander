from copy import deepcopy

import pytest

from app.models.case_pipeline import CaseAnalysisProfile
from app.models.map_foundation import MapSnapshotFeature
from app.models.jurisdiction import JurisdictionAsset
from app.repositories.spatial_repository import SpatialRepository
from app.services.case_insight_service import CaseInsightService
from app.services.frozen_insight_inputs import capture_inputs, replay_inputs, checksum
from tests.test_case_insights import db_session, _case, _current_map, _freeze_assets  # noqa: F401


def test_replay_uses_production_scorer_without_live_queries(db_session, monkeypatch):
    area, snapshot = _current_map(db_session)
    case = _case(db_session, 'FREEZE-1')
    case.operational_area_id = area.id
    assets = [JurisdictionAsset(operational_area_id=area.id, name=f'测试{kind}', asset_type=kind,
        latitude=46.602, longitude=125.102, status='active', verified=True,
        attributes={'oil_type': '原油', 'production_output': 90}) for kind in ('well', 'storage', 'road')]
    db_session.add_all(assets)
    db_session.flush()
    _freeze_assets(db_session, snapshot, assets)
    profile = db_session.query(CaseAnalysisProfile).filter_by(case_id=case.id, is_current=True).one()
    db_session.info['authorized_area_ids'] = (case.operational_area_id,)
    original = CaseInsightService._build_candidates(db_session, case, profile, snapshot)
    assert len(original) == 3
    frozen = capture_inputs(db_session, case_id=case.id, profile_id=profile.id, snapshot_id=snapshot.id)
    assert frozen['payload']['classification'] == 'internal_sensitive'
    assert replay_inputs(frozen)['candidates'] == original
    case.oil_type = '后来修改的油品'
    case.latitude = 0
    for asset in db_session.query(MapSnapshotFeature).all():
        asset.name = '后来修改的地图名'
    db_session.commit()
    def forbidden(*args, **kwargs):
        raise AssertionError('replay must not query live business data')
    monkeypatch.setattr(SpatialRepository, 'nearby_assets', forbidden)
    monkeypatch.setattr(SpatialRepository, 'nearby_cases', forbidden)
    assert replay_inputs(frozen)['candidates'] == original
    damaged = deepcopy(frozen)
    damaged['payload']['case']['latitude'] = 1
    with pytest.raises(ValueError, match='checksum'):
        replay_inputs(damaged)
    missing = deepcopy(frozen)
    missing['payload']['queries'] = {}
    missing['checksum'] = checksum(missing['payload'])
    with pytest.raises(ValueError, match='query_not_captured'):
        replay_inputs(missing)
    different_code = deepcopy(frozen)
    different_code['payload']['scorer_checksum'] = '0' * 64
    different_code['checksum'] = checksum(different_code['payload'])
    with pytest.raises(ValueError, match='algorithm_unavailable'):
        replay_inputs(different_code)
    assert replay_inputs(different_code, scorer_policy='current_candidate')['candidates'] == original
    with pytest.raises(ValueError, match='query_not_captured'):
        replay_inputs(missing, scorer_policy='current_candidate')
    # A later default can be absent from this deployment while the captured
    # version remains executable through the explicit installed registry.
    import app.services.frozen_insight_inputs as replay_module
    monkeypatch.setattr(replay_module, 'CASE_INSIGHT_ALGORITHM_VERSION', 'future-not-installed')
    assert replay_inputs(frozen)['candidates'] == original
    with pytest.raises(ValueError, match='algorithm_unavailable'):
        replay_inputs(frozen, scorer_policy='current_candidate')


def test_missing_coordinates_are_empty_not_successful_predictions(db_session):
    area, snapshot = _current_map(db_session)
    case = _case(db_session, 'FREEZE-EMPTY', None, None)
    case.operational_area_id = area.id
    db_session.flush()
    profile = db_session.query(CaseAnalysisProfile).filter_by(case_id=case.id, is_current=True).one()
    db_session.info['authorized_area_ids'] = (case.operational_area_id,)
    frozen = capture_inputs(db_session, case_id=case.id, profile_id=profile.id, snapshot_id=snapshot.id)
    result = replay_inputs(frozen)
    assert result['status'] == 'empty' and result['candidates'] == []
    db_session.info['authorized_area_ids'] = ()
    with pytest.raises(PermissionError):
        capture_inputs(db_session, case_id=case.id, profile_id=profile.id, snapshot_id=snapshot.id)
