import io
import shutil
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree

import pytest

from app.models.map_foundation import UserAreaScope
from app.services import analysis_topic_service as topics
from app.services import intelligent_query_tasks as queries
from app.services import topic_document as documents
from app.services.topic_query_bridge import query_topic, save_query_as_topic
from tests.test_analysis_topics import seed, client_for
from tests.test_case_search_page import add_case
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_query_followup import model_for, call, FINISH
from tests.test_query_profiles import profile


@pytest.mark.asyncio
async def test_save_query_and_topic_followup_preserve_semantic_filters(query_db):
    case = seed(query_db)
    other = add_case(query_db, 'OTHER', description='未发现软管。')
    profile(query_db, other)
    conditions = [{'category': 'tool', 'value': '软管', 'kind': 'stated'}]
    run = queries.create_query(query_db, '统计明确出现软管的案件')
    await queries.execute_query(query_db, run['id'], model=model_for(
        call('aggregate_case_profiles', {'conditions': conditions}), FINISH))
    with client_for(query_db) as client:
        response = client.post('/api/analysis-topics/from-query', json={'query_id': run['id'], 'title': '软管专题'})
        assert response.status_code == 201
        topic = response.json()
    assert topic['filters']['conditions'] == conditions
    topics.refresh_topic(query_db, topic['id'])
    assert topics.read_topic(query_db, topic['id'])['snapshot']['aggregate']['total'] == 1
    child = query_topic(query_db, topic['id'], 1, '这些案件的画像统计是什么？')
    await queries.execute_query(query_db, child['id'], model=model_for(call('aggregate_case_profiles', {}), FINISH))
    result = queries.read_query(query_db, child['id'])
    assert result['result']['cards'][0]['data']['items'][0]['case_id'] == case.id
    next_run = queries.create_query(query_db, '继续查看条件分布', child['id'])
    assert next_run['followup_context']['topic_source']['revision'] == 1
    query_db.query(UserAreaScope).filter_by(user_id=1).delete()
    query_db.commit()
    with pytest.raises(PermissionError):
        queries.read_query(query_db, next_run['id'])


@pytest.mark.asyncio
async def test_similarity_query_cannot_silently_become_unfiltered_topic(query_db):
    seed(query_db)
    run = queries.create_query(query_db, '查找历史软管案件')
    await queries.execute_query(query_db, run['id'], model=model_for(
        call('find_history', {'query': '软管'}), FINISH))
    with pytest.raises(ValueError, match='topic_query_conditions_unsupported'):
        save_query_as_topic(query_db, run['id'], '不能扩大范围')
    with client_for(query_db) as client:
        response = client.post('/api/analysis-topics/from-query', json={'query_id': run['id'], 'title': '不能扩大范围'})
        assert response.status_code == 422
        assert '不能等价' in response.json()['detail']


@pytest.mark.asyncio
async def test_place_query_cannot_become_an_unfiltered_case_topic(query_db):
    seed(query_db)
    run = queries.create_query(query_db, '查找井场地点')
    await queries.execute_query(query_db, run['id'], model=model_for(
        call('find_places', {'keyword': '井场'}), FINISH))
    with pytest.raises(ValueError, match='topic_query_conditions_unsupported'):
        save_query_as_topic(query_db, run['id'], '不能将地点查询变成全部案件')


def test_views_use_historical_profile_coordinates_and_selected_revision(query_db):
    case = add_case(query_db, 'MAP', description='井场发现软管。', latitude=46.5, longitude=125.1)
    profile(query_db, case)
    topic = topics.create_topic(query_db, '地图专题', {})
    topics.refresh_topic(query_db, topic['id'])
    first = topics.read_topic_views(query_db, topic['id'], revision=1)
    assert first['map']['points'][0]['latitude'] == 46.5
    assert first['graph']['case_ids'] == [case.id]
    assert first['graph']['groups']
    case.latitude = 47.0
    query_db.commit()
    assert topics.read_topic_views(query_db, topic['id'], revision=1) == first
    with client_for(query_db) as client:
        url = f"/api/analysis-topics/{topic['id']}/views"
        assert client.get(url, params={'revision': 1}).json()['snapshot_id'] == first['snapshot_id']
        assert client.get(url, params={'revision': 99}).status_code == 404
    assert not query_db.new and not query_db.dirty


def test_topic_docx_uses_frozen_count_and_matches_views_digest(query_db):
    seed(query_db)
    topic = topics.create_topic(query_db, '井场专题', {})
    topics.refresh_topic(query_db, topic['id'])
    add_case(query_db, 'LATER')
    query_db.commit()
    document, data = documents.export_topic_document(query_db, topic['id'], 1, 'docx')
    views = topics.read_topic_views(query_db, topic['id'], revision=1)
    assert document.content_sha256 == views['content_sha256']
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        text = archive.read('word/document.xml').decode()
    assert '井场专题' in text and document.content_sha256 in text
    tree = ElementTree.fromstring(text)
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    rows = [[ ''.join(cell.itertext()) for cell in row.findall('w:tc', ns)] for row in tree.findall('.//w:tr', ns)]
    assert ['候选范围案件数', '1'] in rows
    assert 'LATER' not in text
    with client_for(query_db) as client:
        url = f"/api/analysis-topics/{topic['id']}/document.docx"
        response = client.get(url, params={'revision': 1})
        assert response.status_code == 200
        assert response.headers['x-result-content-sha256'] == document.content_sha256
        assert client.get(url, params={'revision': 99}).status_code == 404


def test_topic_export_rechecks_permission_after_render(query_db, monkeypatch):
    seed(query_db)
    topic = topics.create_topic(query_db, '专题', {})
    topics.refresh_topic(query_db, topic['id'])
    def revoke(_document):
        query_db.query(UserAreaScope).filter_by(user_id=1).delete()
        query_db.commit()
        return b'PK'
    monkeypatch.setattr(documents, 'render_docx', revoke)
    with pytest.raises(PermissionError):
        documents.export_topic_document(query_db, topic['id'], 1, 'docx')


def test_reuses_existing_case_result_and_brief_without_new_analysis(query_db):
    from app.models.case_result import CaseResultSnapshot
    from app.models.deployment_advisor import SituationBrief
    from app.services.case_result_service import CaseResultService
    case = seed(query_db)
    result, _ = CaseResultService.create_current(query_db, case.id)
    brief = SituationBrief(id='existing-daily', operational_area_id=1, period_type='daily',
        period_start=datetime(2026, 9, 9, tzinfo=timezone.utc),
        period_end=datetime(2026, 9, 10, tzinfo=timezone.utc), input_fingerprint='f' * 64,
        status='completed', summary='已有合成日报，不是专题统计', evidence_refs=[f'case:{case.id}'],
        information_gaps=[], comparison_snapshot={'previous': {'case_ids': []},
            'current': {'case_ids': [case.id]}})
    query_db.add(brief)
    query_db.commit()
    topic = topics.create_topic(query_db, '复用专题', {})
    topics.refresh_topic(query_db, topic['id'])
    view = topics.read_topic_views(query_db, topic['id'], revision=1)
    assert view['case_results'][0]['id'] == result['id']
    assert view['period_materials'][0]['id'] == brief.id
    assert query_db.query(CaseResultSnapshot).count() == 1
    assert query_db.query(SituationBrief).count() == 1
    brief.summary = '后来变化的内容'
    query_db.commit()
    with pytest.raises(PermissionError):
        topics.read_topic_views(query_db, topic['id'], revision=1)


@pytest.mark.skipif(not shutil.which('soffice'), reason='PDF runtime not installed')
def test_topic_pdf_uses_real_local_converter(query_db):
    seed(query_db)
    topic = topics.create_topic(query_db, '合成专题报告', {})
    topics.refresh_topic(query_db, topic['id'])
    document, data = documents.export_topic_document(query_db, topic['id'], 1, 'pdf')
    assert data.startswith(b'%PDF-') and b'%%EOF' in data[-1024:]
    assert document.content_sha256 == topics.read_topic(query_db, topic['id'])['snapshot']['content_sha256']
