from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import update

from app.models.case_road_artifact import CaseRoadArtifact
from app.models.road_network import RoadAccessMembership
from app.services.case_road_artifact_service import freeze_road_artifact, road_artifact_history
from test_case_road_artifacts import artifact_input  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401
from test_road_access_policy import AT
from test_road_analysis_api import client


def seed(db, content, count=3):
    ids = []
    for index in range(count):
        ids.append(freeze_road_artifact(db, {**deepcopy(content), 'boundary': f'合成版本{index}'})['id'])
    db.commit()
    return ids


def test_history_keyset_ties_and_new_insert_do_not_duplicate_old_rows(artifact_input):
    db, content = artifact_input
    ids = seed(db, content)
    db.execute(update(CaseRoadArtifact).values(created_at=AT))
    db.commit()
    first = road_artifact_history(db, content['result_id'], limit=1)
    assert first['items'][0]['id'] == max(ids)
    newer = freeze_road_artifact(db, {**content, 'boundary': 'later inserted'})['id']
    db.execute(update(CaseRoadArtifact).where(CaseRoadArtifact.id == newer).values(created_at=AT + timedelta(seconds=1)))
    db.commit()
    second = road_artifact_history(db, content['result_id'], limit=2, before_id=first['next_before_id'])
    assert {item['id'] for item in first['items'] + second['items']} == set(ids)
    assert second['next_before_id'] is None
    assert all('content' not in item for item in second['items'])


def test_http_read_and_revocation_hide_all_sensitive_history_details(artifact_input):
    db, content = artifact_input
    identifier = seed(db, content, 1)[0]
    api = client(db)
    history = f"/api/road-analysis/case-results/{content['result_id']}/artifacts"
    detail = f'/api/road-analysis/artifacts/{identifier}'
    response = api.get(detail)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json()['content']['result_id'] == content['result_id']
    assert response.json()['created_at'].endswith(('+00:00', 'Z'))
    assert api.get(history).json()['items'][0]['operation'] == 'comparison'
    db.query(RoadAccessMembership).delete()
    db.commit()
    assert api.get(detail).status_code == 404
    assert api.get(history).json()['items'] == [{'id': identifier, 'availability': 'unavailable'}]


def test_history_validation_login_and_absent_cursor(artifact_input):
    db, content = artifact_input
    history = f"/api/road-analysis/case-results/{content['result_id']}/artifacts"
    assert client(db, None).get(history).status_code == 401
    api = client(db)
    assert api.get(history, params={'limit': 21}).status_code == 422
    assert api.get(history, params={'before_id': 'other-result-cursor'}).status_code == 409
    db.info.pop('principal_user_id')
    with pytest.raises(PermissionError):
        road_artifact_history(db, content['result_id'])
