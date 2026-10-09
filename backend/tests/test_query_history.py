import io
import json
from datetime import datetime
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from sqlalchemy import event
from sqlalchemy.orm.attributes import flag_modified

from app.models.knowledge_asset import KnowledgeAsset
from app.services.case_history_retrieval import CaseHistoryRetrieval
from app.services.intelligent_query_context import empty_conditions, inherit, remember
from app.services.intelligent_query_document import build_query_document
from app.services.intelligent_query_history import validate_history_query_evidence
from app.services.intelligent_query_tools import execute_tool
from app.services import intelligent_query_tasks as tasks
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_case_search_page import add_case
from tests.test_query_followup import call, model_for, FINISH
from tests.history_index_helpers import build_history_index


def history_cases(db):
    old = add_case(db, 'OLD-HISTORY', description='夜间打眼盗油使用胶管。', occurred_time=datetime(2000, 1, 1))
    other = add_case(db, 'OTHER', description='未转运。', occurred_time=datetime(2026, 1, 1))
    add_case(db, 'HIDDEN', description='夜间打眼盗油使用胶管。', operational_area_id=2)
    db.commit()
    build_history_index(db)
    return old, other


def test_tool_uses_same_authorized_retrieval_and_does_not_write(search_db):
    old, _ = history_cases(search_db)
    search_db.info['authorized_area_ids'] = (1,)
    statements = []
    def capture(conn, cursor, sql, params, context, many):
        statements.append(sql.lstrip().split()[0].lower())
    event.listen(search_db.bind, 'before_cursor_execute', capture)
    try:
        card = execute_tool(search_db, 'find_history', {'query': '打孔盗油软管',
            'end_date': '2010-01-01T00:00:00Z'})
        direct = CaseHistoryRetrieval.search(search_db, query='打孔盗油软管',
            filters={'end_date': datetime(2010, 1, 1)})
    finally:
        event.remove(search_db.bind, 'before_cursor_execute', capture)
    assert card['data']['items'] == direct['items']
    assert card['data']['items'][0]['case_id'] == old.id
    assert card['data']['coverage']['authorized_cases'] == 1
    assert card['state'] == 'ready'
    assert 'HIDDEN' not in str(card)
    assert not {'insert', 'update', 'delete'}.intersection(statements)
    assert card['evidence']['tool_version'] == 'v6.3-history-fragments-read-1'


@pytest.mark.parametrize('args', [
    {}, {'query': '软管', 'sql': 'SELECT * FROM cases'}, {'query': '软管', 'limit': 4},
    {'query': '软管', 'source_case_id': True}, {'query': '软管', 'operational_area_id': 2},
])
def test_history_schema_and_authorization_reject_uncontrolled_arguments(search_db, args):
    search_db.info['authorized_area_ids'] = (1,)
    with pytest.raises((ValueError, PermissionError)):
        execute_tool(search_db, 'find_history', args)


@pytest.mark.parametrize('timeout', ['negative_budget', 'elapsed_clock'])
def test_partial_empty_is_not_complete_no_match(search_db, monkeypatch, timeout):
    history_cases(search_db)
    search_db.info['authorized_area_ids'] = (1,)
    if timeout == 'negative_budget':
        monkeypatch.setattr('app.services.case_history_retrieval.SCAN_SECONDS', -1)
    else:
        # Simulate a delayed database read without waiting or enlarging the
        # production five-second budget. An empty partial result has no hit
        # whose subsequent content change could invalidate cached evidence.
        readings = iter([100.0])
        monkeypatch.setattr('app.services.case_history_fragment_search.time',
            SimpleNamespace(monotonic=lambda: next(readings, 106.0)))
    card = execute_tool(search_db, 'find_history', {'query': '软管'})
    assert card['state'] == 'partial'
    assert card['data']['items'] == []
    assert not card['data']['coverage']['complete']
    assert not card['data']['coverage']['scan_complete']
    if timeout == 'elapsed_clock':
        assert card['data']['coverage']['budget_seconds'] == 5.0


@pytest.mark.asyncio
async def test_model_finish_cannot_mark_incomplete_history_as_completed(query_db, monkeypatch):
    history_cases(query_db)
    monkeypatch.setattr('app.services.case_history_retrieval.SCAN_SECONDS', -1)
    run = tasks.create_query(query_db, '查询历史软管资料')
    await tasks.execute_query(query_db, run['id'], model=model_for(call('find_history', {'query': '软管'}), FINISH))
    result = tasks.read_query(query_db, run['id'])
    assert result['status'] == 'degraded'
    assert result['result']['error_code'] == 'query_partial_results'


def test_candidate_filters_are_not_silently_reinterpreted_as_source_selection():
    state = remember(empty_conditions(), 'find_cases', {'case_id': 1, 'case_types': ['涉油盗窃']})
    args, _ = inherit('find_history', {'source_case_id': 1}, state, question='找本案的历史相似案件')
    assert args['case_id'] == 1 and args['source_case_id'] == 1
    with pytest.raises(ValueError, match='change_basis_required'):
        inherit('find_history', {'source_case_id': 1, 'case_id': None}, state, question='找本案的历史相似案件')
    args, changes = inherit('find_history', {'source_case_id': 1, 'case_id': None}, state,
                           question='找本案的历史相似案件', change_basis='历史相似案件')
    assert args['case_types'] == ['涉油盗窃']
    assert changes == [{'field': 'case_id', 'previous': 1, 'current': None, 'basis': '历史相似案件'}]
    state = remember(state, 'find_history', args)
    with pytest.raises(ValueError, match='cannot_preserve_filters'):
        inherit('count_cases', {}, state, question='这些相似案例总共有多少')


@pytest.mark.asyncio
async def test_source_case_to_history_followup_and_frozen_word_share_evidence(query_db):
    old, _ = history_cases(query_db)
    source = add_case(query_db, 'SOURCE', description='夜间打孔盗油使用软管。')
    query_db.commit()
    parent = tasks.create_query(query_db, '找本案的历史相似案件', initial_context={'source_case_id': source.id, 'filters': {}})
    await tasks.execute_query(query_db, parent['id'], model=model_for(
        call('find_history', {'source_case_id': source.id, 'case_id': None}, change_basis='历史相似案件'), FINISH))
    result = tasks.read_query(query_db, parent['id'])
    assert result['status'] == 'completed'
    card = result['result']['cards'][0]
    assert card['data']['items'][0]['case_id'] == old.id
    assert card['evidence']['filters']['operational_area_id'] == 1
    assert result['result']['trace'][0]['condition_changes'][0]['field'] == 'case_id'
    child = tasks.create_query(query_db, '继续查看相似条件和差异', parent_query_id=parent['id'])
    model = model_for(call('find_history', {}), FINISH)
    await tasks.execute_query(query_db, child['id'], model=model)
    child_result = tasks.read_query(query_db, child['id'])
    assert child_result['result']['cards'][0]['data']['items'] == card['data']['items']
    assert child_result['result']['trace'][0]['arguments']['source_case_id'] == source.id
    from app.services.case_result_export import render_docx
    document = build_query_document(child_result)
    with ZipFile(io.BytesIO(render_docx(document))) as archive:
        xml = archive.read('word/document.xml').decode()
    assert '历史案件与经验参考' in xml and 'OLD-HISTORY' in xml
    assert '实际检索覆盖' in xml and '不是准确概率' in xml
    assert card['data']['items'][0]['versions']['source_text_hash'] in xml


@pytest.mark.asyncio
async def test_saved_history_is_withheld_after_case_edit(query_db):
    old, _ = history_cases(query_db)
    parent = tasks.create_query(query_db, '查找软管历史资料')
    await tasks.execute_query(query_db, parent['id'], model=model_for(call('find_history', {'query': '软管'}), FINISH))
    assert tasks.read_query(query_db, parent['id'])['result']['cards']
    old.description = '已修改的原文'
    query_db.commit()
    for action in (lambda: tasks.read_query(query_db, parent['id']),
                   lambda: tasks.create_query(query_db, '继续', parent_query_id=parent['id'])):
        with pytest.raises(PermissionError, match='history_evidence_changed'):
            action()


@pytest.mark.parametrize('mutation', ['archive', 'content', 'evidence', 'scope'])
def test_cached_experience_rechecks_manual_state_content_refs_and_current_scope(search_db, mutation, monkeypatch):
    case, _ = history_cases(search_db)
    timestamp = datetime(2026, 10, 9, 12)
    asset = KnowledgeAsset(asset_type='experience_card', source_case_id=case.id, version=1,
        title='已确认经验', content={'summary': '特殊储存条件经验'}, evidence_refs=[{'id': f'case:{case.id}'}],
        source_signature='a' * 64, source_data_version='b' * 64, status='confirmed',
        created_at=timestamp, updated_at=timestamp)
    search_db.add(asset)
    search_db.commit()
    build_history_index(search_db)
    search_db.info['authorized_area_ids'] = (1,)
    # This test checks current evidence, not retrieval latency. Freeze only
    # preparation; a busy runner must not turn it into a vacuous empty check.
    with monkeypatch.context() as preparation:
        preparation.setattr('app.services.case_history_fragment_search.time',
            SimpleNamespace(monotonic=lambda: 100.0))
        result = {'cards': [execute_tool(search_db, 'find_history', {'query': '特殊储存'})]}
    assert [(item['source_type'], item['source_id']) for item in result['cards'][0]['data']['items']] == [
        ('experience_card', asset.id)]
    validate_history_query_evidence(search_db, result)
    if mutation == 'archive':
        asset.status = 'archived'
    elif mutation == 'content':
        asset.content = {'summary': '已更新'}
        # Preserve even the database timestamp: invalidation must be based on
        # current content, not clock resolution or an incidental onupdate value.
        asset.updated_at = timestamp
        flag_modified(asset, 'updated_at')
    elif mutation == 'evidence':
        asset.evidence_refs = [{'id': 'case:999999'}]
    else:
        search_db.info['authorized_area_ids'] = ()
    search_db.commit()
    if mutation == 'content':
        assert asset.updated_at == timestamp
        assert asset.content == {'summary': '已更新'}
    with pytest.raises(PermissionError, match='history_evidence_changed'):
        validate_history_query_evidence(search_db, result)
