"""Freeze actual persisted attachments, never recompute a route in a topic GET.

Fixed input: area 1, user/group 1, graph-1 / c*64, policy 1, AT,
explicit reference auto, empty synthetic matrix. This tests version/permission
integration, not road-engine calculation accuracy (unchanged in v5.3).
"""
import pytest

from app.models.case import Case
from app.models.map_foundation import MapSnapshot
from app.models.road_network import RoadAccessMembership
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_result_service import CaseResultService
from app.services.case_road_artifact_service import freeze_road_artifact
from app.services import analysis_topic_service as topics
from app.services.topic_document import build_topic_document
from test_case_results import db_session, result_data  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_road_access_policy import AT


@pytest.fixture
def topic_road(ready, result_data):
    db = ready
    case = db.get(Case, 1)
    case.description, case.latitude, case.longitude = '井场发现软管。', 46.5, 125.1
    payload = CasePipelineService.build_profile_payload(db, case)
    profile = result_data[0]
    profile.payload, profile.source_hash = payload, payload['source_hash']
    profile.dictionary_version = payload['dictionary_version']
    db.get(MapSnapshot, 'map-1').status = 'current'
    db.commit()
    source, _ = CaseResultService.create_current(db, 1)
    content = {'schema_version': 'case-road-comparison-4.2.0-1', 'result_id': source['id'],
        'content_sha256': source['content_sha256'], 'map_snapshot_id': 'map-1',
        'targets': [], 'information_gaps': ['合成附件只验证版本绑定，不证明道路可达'], 'boundary': '合成附件',
        'matrix': {'network_id': 'graph-1', 'graph_sha256': 'c' * 64, 'policy_revision': 1,
            'analysis_at': AT.isoformat(), 'vehicle': {'kind': 'auto', 'source': 'explicit_reference_assumption'},
            'cells': []}}
    road = freeze_road_artifact(db, content)
    db.commit()
    topic = topics.create_topic(db, '冻结道路专题', {'operational_area_id': 1})
    topics.refresh_topic(db, topic['id'])
    return db, topic['id'], source, road


def test_topic_reuses_exact_road_and_map_then_keeps_old_map_after_publication(topic_road, monkeypatch):
    db, identifier, source, road = topic_road
    def forbidden(*args, **kwargs):
        raise AssertionError('GET must not generate another analysis')
    monkeypatch.setattr(CaseResultService, 'create_current', forbidden)
    first = topics.read_topic_views(db, identifier, revision=1)
    assert first['roads'][0]['id'] == road['id']
    assert first['roads'][0]['content']['result_id'] == source['id']
    assert first['roads'][0]['content']['matrix']['network_id'] == 'graph-1'
    assert first['map']['versions'][0]['id'] == 'map-1'
    db.get(MapSnapshot, 'map-1').status = 'superseded'
    db.add(MapSnapshot(id='map-2', version='synthetic-2', operational_area_id=1,
        public_bundle_id=1, manifest={}, feature_watermark='2', status='current'))
    db.commit()
    assert topics.read_topic_views(db, identifier, revision=1) == first
    document = build_topic_document(db, identifier, 1)
    assert document.content_sha256 == first['content_sha256']
    assert road['id'] in str(document.blocks)
    assert 'map-2' not in str(document.blocks)


def test_topic_cannot_serve_a_frozen_road_after_passage_permission_is_revoked(topic_road):
    db, identifier, _, _ = topic_road
    topics.read_topic_views(db, identifier, revision=1)
    db.query(RoadAccessMembership).delete()
    db.commit()
    for read in (topics.read_topic, topics.read_topic_views, build_topic_document):
        with pytest.raises((PermissionError, ValueError)):
            read(db, identifier, revision=1)
