import json
from types import SimpleNamespace

import pytest

from app.models.agent_run import AgentRun
from app.models.map_foundation import UserAreaScope
from app.services import intelligent_query_tasks as tasks
from app.services.intelligent_query_context import empty_conditions, inherit, remember
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_case_search_page import add_case


def model_for(*decisions):
    steps = iter(decisions)
    class Model:
        prompts = []
        async def ainvoke(self, prompt):
            self.prompts.append(json.loads(prompt))
            return SimpleNamespace(content=json.dumps(next(steps)))
    return Model()


def call(tool, arguments, **extra):
    return {'action': 'call', 'tool': tool, 'arguments': arguments, **extra}


FINISH = {'action': 'finish', 'reason': 'completed'}


@pytest.mark.asyncio
async def test_followup_persists_and_inherits_filters_across_tools(query_db):
    add_case(query_db, 'MATCH')
    add_case(query_db, 'OTHER')
    query_db.commit()
    parent = tasks.create_query(query_db, '查找MATCH案件')
    await tasks.execute_query(query_db, parent['id'], model=model_for(
        call('find_cases', {'keyword': 'MATCH', 'operational_area_id': 1}), FINISH))
    followup = tasks.create_query(query_db, '这些案件一共有多少？', parent['id'])
    query_db.expire_all()
    model = model_for(call('count_cases', {}), FINISH)
    await tasks.execute_query(query_db, followup['id'], model=model)
    result = tasks.read_query(query_db, followup['id'])
    assert result['result']['cards'][0]['data']['count'] == 1
    assert result['result']['trace'][0]['arguments'] == {'keyword': 'MATCH', 'operational_area_id': 1}
    assert model.prompts[0]['followup_context']['previous_question'] == '查找MATCH案件'
    assert 'cards' not in model.prompts[0]['followup_context']
    assert result['followup_context']['parent_query_id'] == parent['id']


@pytest.mark.asyncio
async def test_context_change_needs_question_quote_and_is_traced(query_db):
    add_case(query_db, 'MATCH')
    add_case(query_db, 'OTHER')
    query_db.commit()
    parent = tasks.create_query(query_db, '统计MATCH')
    await tasks.execute_query(query_db, parent['id'], model=model_for(call('count_cases', {'keyword': 'MATCH'}), FINISH))
    child = tasks.create_query(query_db, '取消关键词限制，统计全部案件', parent['id'])
    model = model_for(call('count_cases', {'keyword': None}),
                      call('count_cases', {'keyword': None}, change_basis='取消关键词限制'), FINISH)
    await tasks.execute_query(query_db, child['id'], model=model)
    result = tasks.read_query(query_db, child['id'])['result']
    assert result['cards'][0]['data']['count'] == 2
    assert len(result['cards']) == 1  # Rejected plan never executes a query.
    assert result['trace'][0]['error_code'] == 'query_context_change_basis_required'
    assert result['trace'][1]['condition_changes'] == [
        {'field': 'keyword', 'previous': 'MATCH', 'current': None, 'basis': '取消关键词限制'}]


@pytest.mark.asyncio
async def test_followup_cannot_borrow_other_owner_or_revoked_scope(query_db):
    parent = tasks.create_query(query_db, '统计')
    with pytest.raises(ValueError, match='query_parent_not_ready'):
        tasks.create_query(query_db, '继续', parent['id'])
    await tasks.execute_query(query_db, parent['id'], model=model_for(call('count_cases', {}), FINISH))
    query_db.info['principal_user_id'] = 2
    with pytest.raises(ValueError, match='query_not_found'):
        tasks.create_query(query_db, '继续', parent['id'])
    query_db.info['principal_user_id'] = 1
    child = tasks.create_query(query_db, '继续', parent['id'])
    query_db.query(UserAreaScope).filter_by(user_id=1).delete()
    query_db.commit()
    for run in (parent, child):
        with pytest.raises(PermissionError, match='query_scope_changed'):
            tasks.read_query(query_db, run['id'])


@pytest.mark.asyncio
async def test_changed_parent_cannot_be_silently_reused(query_db):
    parent = tasks.create_query(query_db, '统计')
    await tasks.execute_query(query_db, parent['id'], model=model_for(call('count_cases', {}), FINISH))
    child = tasks.create_query(query_db, '继续', parent['id'])
    row = query_db.get(AgentRun, parent['id'])
    row.result_summary = {'status': 'completed', 'cards': [{'data': {'count': 999}}]}
    query_db.commit()
    with pytest.raises(PermissionError, match='query_context_changed'):
        tasks.claim_query(query_db, child['id'])


def test_comparison_cannot_drop_conditions_it_cannot_represent():
    conditions = remember(empty_conditions(), 'find_cases', {'keyword': 'MATCH'})
    with pytest.raises(ValueError, match='query_context_tool_cannot_preserve_filters'):
        inherit('compare_periods', {'start': '2026-08-01T00:00:00Z', 'end': '2026-09-01T00:00:00Z'},
                conditions, question='比较数量')


def test_time_window_survives_comparison_to_case_lookup():
    conditions = remember(empty_conditions(), 'compare_periods',
        {'start': '2026-08-01T00:00:00Z', 'end': '2026-09-01T00:00:00Z', 'operational_area_id': 1})
    arguments, changes = inherit('find_cases', {}, conditions, question='列出这些案件')
    assert arguments['start_date'] == '2026-08-01T00:00:00Z'
    assert arguments['end_date'] == '2026-09-01T00:00:00Z'
    assert not changes
