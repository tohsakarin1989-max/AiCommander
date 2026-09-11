from copy import deepcopy
import json
from threading import Event

import pytest
from sqlalchemy import select, update

from app.models.case import Case
from app.models.case_result import CaseResultSnapshot
from app.models.case_road_artifact import CaseRoadArtifact
from app.models.road_network import RoadAccessMembership
from app.services.case_result_service import CaseResultService
from app.services.case_road_artifact_service import freeze_road_artifact, read_road_artifact
from test_road_network_service import ready  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401
from test_road_access_policy import AT


@pytest.fixture
def artifact_input(ready):
    source, _ = CaseResultService.create_current(ready, 1)
    ready.commit()
    content = {'schema_version': 'case-road-comparison-4.2.0-1', 'result_id': source['id'],
        'content_sha256': source['content_sha256'], 'map_snapshot_id': source['content']['versions']['map_snapshot_id'],
        'targets': [], 'information_gaps': [], 'boundary': '合成存储测试，不验证计算正确性',
        'matrix': {'network_id': 'graph-1', 'graph_sha256': 'c' * 64, 'policy_revision': 1,
            'analysis_at': AT.isoformat(), 'vehicle': {'kind': 'auto', 'source': 'explicit_reference_assumption'},
            'cells': []}}
    return ready, content


def test_attachment_is_idempotent_detached_and_never_changes_frozen_case(artifact_input):
    db, content = artifact_input
    original_case = db.get(Case, 1).description
    original_result = deepcopy(db.get(CaseResultSnapshot, content['result_id']).content)
    first = freeze_road_artifact(db, content)
    second = freeze_road_artifact(db, content)
    assert first['created'] and not second['created'] and first['id'] == second['id']
    db.commit()
    content['boundary'] = 'caller later changed this'
    read = read_road_artifact(db, first['id'])
    assert read['content']['boundary'] != content['boundary']
    assert db.get(Case, 1).description == original_case
    assert db.get(CaseResultSnapshot, content['result_id']).content == original_result


def test_attachment_obeys_outer_rollback(artifact_input):
    db, content = artifact_input
    item = freeze_road_artifact(db, content)
    db.rollback()
    assert db.scalar(select(CaseRoadArtifact.id).where(CaseRoadArtifact.id == item['id'])) is None


@pytest.mark.parametrize('change', ['road_permission', 'case_scope', 'corrupt_content'])
def test_stored_attachment_does_not_bypass_current_access_or_integrity(artifact_input, change):
    db, content = artifact_input
    item = freeze_road_artifact(db, content)
    db.commit()
    read_road_artifact(db, item['id'])  # Prime ORM identity map before revocation.
    if change == 'road_permission':
        db.query(RoadAccessMembership).delete()
        db.commit()
    elif change == 'case_scope':
        db.info['authorized_area_ids'] = ()
    else:
        db.execute(update(CaseRoadArtifact).values(content={**content, 'boundary': 'changed'}))
        db.commit()
    with pytest.raises((PermissionError, ValueError)):
        read_road_artifact(db, item['id'])


@pytest.mark.parametrize('cancel_during_save', [False, True])
def test_api_success_retains_automatically_and_cancelled_save_rolls_back(artifact_input, monkeypatch, cancel_during_save):
    from app.api.road_analysis import _calculate, CalculationRequest, ReferenceVehicle
    from app.services import case_road_artifact_service
    db, content = artifact_input
    cancelled = Event()
    original = case_road_artifact_service.freeze_road_artifact
    def freeze(*args):
        value = original(*args)
        if cancel_during_save:
            cancelled.set()
        return value
    monkeypatch.setattr(case_road_artifact_service, 'freeze_road_artifact', freeze)
    response = _calculate(lambda *args, **kwargs: content, db,
        CalculationRequest(analysis_at=AT, vehicle=ReferenceVehicle(kind='auto')), cancel_event=cancelled)
    if cancel_during_save:
        assert response.status_code == 409
        assert db.query(CaseRoadArtifact).count() == 0
    else:
        assert response.status_code == 200
        saved = json.loads(response.body)['artifact']
        assert read_road_artifact(db, saved['id'])['content'] == content
