from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.models.internal_roads import InternalRoadImport
from app.models.internal_roads import InternalRoadReview
from app.models.map_foundation import MapSource
from app.models.user import User
from app.services.road_situation_changes import road_source_changes, road_sources_visible
from app.services.situation_change_service import closed_window
from tests.test_case_search_page import search_db  # noqa: F401

WINDOW = closed_window(datetime(2026, 9, 11, tzinfo=timezone.utc), 'daily')


def seed(db):
    db.info['authorized_area_ids'] = (1,)
    db.add(User(id=1, username='synthetic-road-author', display_name='合成测试', password_hash='not-a-login', role='admin'))
    db.flush()
    source = MapSource(source_key='roads', name='合成道路', source_type='internal_gis', operational_area_id=1)
    db.add(source)
    db.flush()
    road = {'id': 'r1', 'type': 'Feature', 'geometry': {'type': 'LineString',
        'coordinates': [[125, 47], [125.01, 47]]},
        'properties': {'name': '道路甲', 'kind': 'road', 'conditions': {'gate': 'open'}}}
    entrance = {'id': 'e1', 'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [125, 47]},
        'properties': {'name': '入口甲', 'kind': 'entrance', 'road_id': 'r1', 'conditions': {}}}
    previous = InternalRoadImport(source_id=source.id, operational_area_id=1, input_sha256='a'*64,
        schema_version='test', features=[road, entrance], warnings=[], created_by=1,
        created_at=WINDOW.previous_start)
    db.add(previous)
    db.flush()
    changed = deepcopy(road)
    changed['properties']['conditions']['gate'] = 'closed'
    current = InternalRoadImport(source_id=source.id, operational_area_id=1, input_sha256='b'*64,
        schema_version='test', features=[changed], warnings=[], created_by=1, created_at=WINDOW.current_start)
    db.add(current)
    db.commit()
    return source, previous, current


def test_incremental_omission_is_not_deletion_and_future_does_not_leak(search_db):
    source, old, new = seed(search_db)
    result = road_source_changes(search_db, 1, WINDOW)
    assert result['previous_feature_count'] == result['current_feature_count'] == 2
    assert len(result['items']) == 1
    item = result['items'][0]
    assert item['changed_fields'] == ['properties.conditions']
    assert item['previous_conditions']['gate'] == 'open'
    assert item['current_conditions']['gate'] == 'closed'
    assert item['routing_available'] is None
    assert item['evidence_refs'] == [f'internal_road_import:{old.id}', f'internal_road_import:{new.id}']
    new.created_at = WINDOW.current_end
    search_db.commit()
    historical = road_source_changes(search_db, 1, WINDOW)
    assert historical['items'] == []
    assert historical['input_digest'] != result['input_digest']


def test_scope_revocation_and_explicit_budget(search_db, monkeypatch):
    import app.services.road_situation_changes as service
    source, _, _ = seed(search_db)
    result = road_source_changes(search_db, 1, WINDOW)
    assert road_sources_visible(search_db, result, 1)
    source.status = 'inactive'
    search_db.commit()
    assert not road_sources_visible(search_db, result, 1)
    source.status = 'active'
    search_db.commit()
    monkeypatch.setattr(service, 'MAX_FEATURES', 1)
    limited = road_source_changes(search_db, 1, WINDOW)
    assert limited['state'] == 'unavailable' and limited['items'] == []
    search_db.info['authorized_area_ids'] = ()
    with pytest.raises(PermissionError):
        road_source_changes(search_db, 1, WINDOW)


def test_brief_retains_evidence_and_hides_revoked_source(search_db):
    from app.services.deployment_advisor_service import DeploymentAdvisorService
    source, _, _ = seed(search_db)
    brief, reused = DeploymentAdvisorService.generate_brief(search_db, operational_area_id=1,
        period_type='daily', as_of=datetime(2026, 9, 11, tzinfo=timezone.utc))
    assert not reused
    result = DeploymentAdvisorService.brief_to_dict(search_db, brief)
    assert len(result['comparison_snapshot']['roads']['items']) == 1
    assert '道路/入口资料变化 1 项' in result['summary']
    assert result['recommendations'] == []
    source.status = 'inactive'
    search_db.commit()
    hidden = DeploymentAdvisorService.brief_to_dict(search_db, brief)
    assert hidden['status'] == 'unavailable'
    assert hidden['comparison_snapshot'] is None


def test_expiry_and_review_changes_without_a_new_import(search_db):
    from datetime import timedelta
    _, old, new = seed(search_db)
    # The newer version belongs to the future; compare the same source twice.
    new.created_at = WINDOW.current_end
    features = deepcopy(old.features)
    features[0]['properties']['conditions'].update(
        valid_from=WINDOW.previous_start.isoformat(),
        valid_until=(WINDOW.current_start + timedelta(hours=1)).isoformat())
    old.features = features
    review = InternalRoadReview(import_id=old.id, operational_area_id=1, feature_id='r1',
        sequence=1, request_key='first', decision='verified', note='合成', evidence_reference='fixture',
        created_by=1, created_at=WINDOW.current_start)
    search_db.add(review)
    search_db.commit()
    result = road_source_changes(search_db, 1, WINDOW)
    item = result['items'][0]
    assert item['changed_fields'] == ['condition_validity', 'source_review']
    assert item['previous_status']['validity'] == 'within_recorded_interval'
    assert item['current_status']['validity'] == 'expired'
    assert item['previous_status']['review_state'] == 'unreviewed'
    assert item['current_status']['review_state'] == 'verified'
    assert result['review_ids'] == [review.id]
    assert item['routing_available'] is None
    review.created_at = WINDOW.current_end
    search_db.commit()
    later = road_source_changes(search_db, 1, WINDOW)
    assert later['items'][0]['changed_fields'] == ['condition_validity']
    assert later['review_ids'] == []
