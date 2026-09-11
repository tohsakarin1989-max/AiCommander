from datetime import datetime, timedelta, timezone

import pytest

from app.models.case_pipeline import OutboxEvent
from app.models.case_road_artifact import CaseRoadArtifact
from app.models.road_network import RoadAccessMembership
from app.models.user import User
from app.services.case_road_artifact_service import freeze_road_artifact
from app.services.case_road_status import automatic_comparison_status
from app.services.case_road_jobs import EVENT_TYPE
from test_case_road_artifacts import artifact_input  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401
from test_road_analysis_api import client


def endpoint(content):
    return f"/api/road-analysis/case-results/{content['result_id']}/automatic-comparison"


def test_get_reads_saved_artifact_without_creating_work(artifact_input):
    db, content = artifact_input
    api = client(db)
    assert api.get(endpoint(content)).json()['status'] == 'not_available'
    saved = freeze_road_artifact(db, content)
    db.commit()
    for _ in range(2):
        response = api.get(endpoint(content))
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        assert response.json()['artifact']['id'] == saved['id']
        assert response.json()['status'] == 'completed'
    assert db.query(OutboxEvent).count() == 0
    assert db.query(CaseRoadArtifact).count() == 1


@pytest.mark.parametrize('state,error,expected', [('pending', None, 'processing'),
    ('retry', 'sensitive error', 'processing'), ('processing', None, 'processing'),
    ('failed', 'sensitive error', 'unavailable'), ('cancelled', None, 'unavailable'),
    ('waiting_dependency', 'road_trigger_waiting_network', 'waiting_network'),
    ('completed', 'road_job_information_missing', 'information_missing')])
def test_job_states_never_masquerade_as_success_or_leak_payload(artifact_input, state, error, expected):
    db, content = artifact_input
    freeze_road_artifact(db, content)
    db.add(OutboxEvent(id='job', event_type=EVENT_TYPE, aggregate_type='case_result',
        aggregate_id=content['result_id'], payload={'user_id': 1, 'scope': [999]},
        idempotency_key='job', status=state, error=error))
    db.commit()
    response = client(db).get(endpoint(content))
    assert response.status_code == 200
    value = response.json()
    assert value['status'] == expected and value['artifact'] is None
    assert 'sensitive' not in response.text and '999' not in response.text


def test_revoked_latest_artifact_does_not_fall_back_to_older_content(artifact_input):
    db, content = artifact_input
    first = freeze_road_artifact(db, content)
    second = freeze_road_artifact(db, {**content, 'boundary': 'newer'})
    db.commit()
    row = db.get(CaseRoadArtifact, second['id'])
    row.created_at = datetime.now(timezone.utc) + timedelta(seconds=10)
    row.content = {**row.content, 'boundary': 'tampered'}
    db.commit()
    value = automatic_comparison_status(db, content['result_id'])
    assert value['status'] == 'unavailable' and value['artifact'] is None
    assert db.get(CaseRoadArtifact, first['id']) is not None


def test_authentication_live_role_and_road_permissions_are_required(artifact_input):
    db, content = artifact_input
    assert client(db, None).get(endpoint(content)).status_code == 401
    freeze_road_artifact(db, content)
    db.commit()
    db.query(RoadAccessMembership).delete()
    db.commit()
    assert client(db).get(endpoint(content)).json()['status'] == 'unavailable'
    db.get(User, 1).role = 'viewer'
    db.commit()
    assert client(db).get(endpoint(content)).status_code == 404
