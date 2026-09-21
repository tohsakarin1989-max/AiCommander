from datetime import datetime
import json

import pytest

from app.models.analysis_topic import TopicSnapshot
from app.models.knowledge_asset import KnowledgeAsset
from app.services import analysis_topic_service as topics
from app.services.case_history_index_service import CaseHistoryIndexService
from app.services.case_history_retrieval import CaseHistoryRetrieval
from app.services.topic_document import build_topic_document
from tests.test_analysis_topics import seed
from tests.test_case_search_page import add_case
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_query_profiles import profile


def test_topic_reuses_old_history_and_confirmed_experience_without_extraction(query_db, monkeypatch):
    current = seed(query_db)
    old = add_case(query_db, 'OLD-2000', occurred_time=datetime(2000, 1, 1), description='井场发现软管。')
    profile(query_db, old)
    asset = KnowledgeAsset(asset_type='experience_card', source_case_id=old.id, version=1,
        title='旧案已确认经验', content={'summary': '井场软管使用条件须核对来源，不能据此认定关联。'},
        evidence_refs=[{'id': f'case:{old.id}'}], source_signature='a' * 64,
        source_data_version='b' * 64, status='confirmed')
    query_db.add(asset)
    query_db.flush()
    for case in (old, current):
        CaseHistoryIndexService.rebuild_case(query_db, case)
    query_db.commit()
    def forbidden(*args, **kwargs):
        raise AssertionError('topic must not extract source text again')
    monkeypatch.setattr('app.services.case_history_retrieval.build_semantic_profile', forbidden)
    monkeypatch.setattr(CaseHistoryIndexService, 'rebuild_case', forbidden)
    topic = topics.create_topic(query_db, '本期软管专题', {
        'start_date': '2026-09-01T00:00:00Z',
        'conditions': [{'category': 'tool', 'value': '软管', 'kind': 'stated'}]})
    assert topics.refresh_topic(query_db, topic['id'])['status'] == 'updated'
    read = topics.read_topic(query_db, topic['id'])
    assert read['snapshot']['aggregate']['total'] == 1  # old reference is not a period member
    history = topics.read_topic_views(query_db, topic['id'], revision=1)['history']
    assert history['state'] == 'ready'
    assert history['result']['coverage']['scanned_cases'] == 2
    assert any(item['case_id'] == old.id and item['source_type'] == 'case' for item in history['result']['items'])
    assert any(item['source_id'] == asset.id and item['source_type'] == 'experience_card' for item in history['result']['items'])
    assert 'source_text' not in history['result']
    assert '不计入本期统计' in str(build_topic_document(query_db, topic['id'], 1).blocks)
    topics.request_refresh(query_db, topic['id'])
    assert topics.refresh_topic(query_db, topic['id'])['status'] == 'unchanged'
    assert query_db.query(TopicSnapshot).count() == 1
    asset.status = 'draft'
    query_db.commit()
    with pytest.raises(PermissionError):
        topics.read_topic_views(query_db, topic['id'], revision=1)
    with pytest.raises(PermissionError):
        build_topic_document(query_db, topic['id'], 1)


def test_reuse_only_missing_index_is_partial_lexical_not_fresh_extraction(query_db, monkeypatch):
    add_case(query_db, 'MISSING', description='特殊软管资料')
    def forbidden(*args, **kwargs):
        raise AssertionError('no extraction')
    monkeypatch.setattr('app.services.case_history_retrieval.build_semantic_profile', forbidden)
    result = CaseHistoryRetrieval.search(query_db, query='软管', reuse_only=True,
        query_conditions={('tool', '软管', 'stated')})
    assert result['coverage']['scan_complete'] is True
    assert result['coverage']['complete'] is False
    assert result['state'] == 'partial'
    assert result['coverage']['missing_derived_sources'] == 1
    assert result['items'][0]['profile_state'] == 'lexical_only'
    assert not result['items'][0]['shared_conditions']
    assert not query_db.new and not query_db.dirty


def test_topic_history_rechecks_old_source_outside_current_period(query_db):
    seed(query_db)
    old = add_case(query_db, 'OLD', occurred_time=datetime(2000, 1, 1), description='井场软管。')
    profile(query_db, old)
    topic = topics.create_topic(query_db, '本期', {'start_date': '2026-09-01T00:00:00Z'})
    topics.refresh_topic(query_db, topic['id'])
    assert 'OLD' in json.dumps(topics.read_topic_views(query_db, topic['id'], revision=1))
    old.operational_area_id = 2
    query_db.commit()
    with pytest.raises(PermissionError):
        topics.read_topic(query_db, topic['id'])


def test_topic_without_reliable_conditions_does_not_invent_history_query(query_db):
    case = add_case(query_db, 'NO-CONDITIONS', description='资料不详', location='未知', oil_type=None)
    profile(query_db, case)
    topic = topics.create_topic(query_db, '空条件', {})
    topics.refresh_topic(query_db, topic['id'])
    history = topics.read_topic_views(query_db, topic['id'], revision=1)['history']
    assert history['state'] == 'insufficient_conditions'
    assert history['result'] is None
