"""页面初始选择采用真实 DB 与只读工具；计划模型仅使用测试注入，无网络调用。"""
import json

import pytest
from pydantic import ValidationError

from app.api.intelligent_queries import QueryCreate
from app.config import settings
from app.models.agent_run import AgentRun
from app.models.case import Case
from app.services import intelligent_query_tasks as tasks
from app.services.intelligent_query_context import empty_conditions, inherit, remember
from app.services.intelligent_query_tools import execute_tool
from tests.test_case_search_page import add_case
from tests.test_intelligent_query_api import client_for
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_intelligent_query_tools import insight_fixture
from tests.test_query_followup import model_for, call, FINISH


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, 'ENABLE_AGENT_LAB', True)
    monkeypatch.setattr(settings, 'AGENT_MODE', 'shadow')


def test_creation_freezes_exact_old_case_and_filters_without_raw_content_or_model(query_db):
    selected = add_case(query_db, 'OLD', description='敏感原文不属于页面上下文')
    for index in range(60):
        add_case(query_db, f'NEW-{index}')
    query_db.commit()
    with client_for(query_db) as client:
        response = client.post('/api/intelligent-queries', json={
            'query': '读取当前案件画像', 'initial_context': {
                'source_case_id': selected.id, 'filters': {'statuses': ['pending'], 'oil_types': ['原油']},
            },
        })
        assert response.status_code == 201, response.text
        created = response.json()
        assert created['status'] == 'queued' and created['result'] == {}
        initial = created['initial_context']
        assert initial['source_case']['case_id'] == selected.id
        assert len(initial['source_case']['source_hash']) == 64
        assert initial['conditions']['case_filters'] == {
            'case_id': selected.id, 'statuses': ['pending'], 'oil_types': ['原油'], 'operational_area_id': 1,
        }
        assert initial['conditions']['area'] == 1
        assert '敏感原文' not in json.dumps(initial, ensure_ascii=False)
        assert client.get(response.headers['location']).json()['initial_context'] == initial
    row = query_db.get(AgentRun, created['id'])
    assert row.attempt_count == 0
    assert row.input_payload['initial_context'] == initial
    assert query_db.query(Case).filter(Case.id == selected.id).one().description == selected.description


@pytest.mark.parametrize('initial', [
    {}, {'source_case_id': 0}, {'source_case_id': True}, {'source_case_id': '1'},
    {'source_case_id': 1, 'filters': {'case_id': 2}},
    {'source_case_id': 1, 'filters': {'sql': 'SELECT 1'}},
    {'source_case_id': 1, 'source_hash': 'client-supplied'},
    {'filters': {'statuses': []}}, {'filters': {'keyword': '   '}},
    {'filters': {'start_date': '2026-09-10T00:00:00Z', 'end_date': '2026-09-01T00:00:00Z'}},
])
def test_invalid_or_extra_initial_context_is_rejected(initial):
    with pytest.raises(ValidationError):
        QueryCreate.model_validate({'query': '统计', 'initial_context': initial})


def test_parent_and_initial_context_are_mutually_exclusive(query_db):
    case = add_case(query_db, 'SELECTED')
    query_db.commit()
    with client_for(query_db) as client:
        response = client.post('/api/intelligent-queries', json={
            'query': '继续', 'parent_query_id': '11111111-1111-4111-8111-111111111111',
            'initial_context': {'source_case_id': case.id},
        })
        assert response.status_code == 422
    with pytest.raises(ValueError, match='query_context_conflict'):
        tasks.create_query(query_db, '继续', 'anything', {'source_case_id': case.id})
    assert query_db.query(AgentRun).count() == 0


def test_unauthorized_or_missing_case_and_area_never_create_a_query(query_db):
    hidden = add_case(query_db, 'DO-NOT-DISCLOSE', operational_area_id=2)
    query_db.commit()
    with client_for(query_db) as client:
        for initial in ({'source_case_id': hidden.id}, {'source_case_id': 9999},
                        {'filters': {'operational_area_id': 2}}):
            response = client.post('/api/intelligent-queries', json={'query': '统计', 'initial_context': initial})
            assert response.status_code == 403
            assert 'DO-NOT-DISCLOSE' not in response.text
    assert query_db.query(AgentRun).count() == 0


def test_contradictory_case_and_filters_are_not_silently_dropped(query_db):
    case = add_case(query_db, 'SELECTED', status='pending')
    query_db.commit()
    with client_for(query_db) as client:
        response = client.post('/api/intelligent-queries', json={
            'query': '统计', 'initial_context': {'source_case_id': case.id, 'filters': {'statuses': ['closed']}},
        })
        assert response.status_code == 422
    assert query_db.query(AgentRun).count() == 0


@pytest.mark.asyncio
async def test_initial_case_is_inherited_by_actual_cases_count_profile_road_and_summary_tools(query_db):
    run, _, _, _ = insight_fixture(query_db)
    add_case(query_db, 'UNRELATED')
    query_db.commit()
    request = tasks.create_query(query_db, '查看当前案件的画像、道路和已有成果', initial_context={
        'source_case_id': run.case_id, 'filters': {'case_types': ['盗油']},
    })
    model = model_for(
        call('find_cases', {}), call('count_cases', {}), call('find_case_profiles', {}),
        call('find_road_results', {}), call('summarize_results', {}), FINISH,
    )
    await tasks.execute_query(query_db, request['id'], model=model)
    result = tasks.read_query(query_db, request['id'])['result']
    assert result['status'] == 'completed'
    cards = {card['tool']: card for card in result['cards']}
    assert cards['find_cases']['data']['total'] == 1
    assert cards['count_cases']['data']['count'] == 1
    assert cards['find_case_profiles']['data']['total'] == 1
    assert cards['find_road_results']['data']['items'] == []
    assert cards['summarize_results']['data']['total'] == 1
    assert cards['summarize_results']['data']['items'][0]['case_id'] == run.case_id
    assert all(step['arguments']['case_id'] == run.case_id for step in result['trace'])
    assert all(step['arguments']['case_types'] == ['盗油'] for step in result['trace'])
    assert 'raw_case' not in model.prompts[0]['followup_context']


@pytest.mark.asyncio
async def test_initial_filters_without_case_survive_followup_and_need_no_user_reselection(query_db):
    add_case(query_db, 'MATCH', status='closed')
    add_case(query_db, 'OTHER', status='pending')
    query_db.commit()
    parent = tasks.create_query(query_db, '统计这些案件', initial_context={'filters': {
        'statuses': ['closed'], 'start_date': '2026-09-01T08:00:00+08:00',
        'end_date': '2026-10-01T08:00:00+08:00',
    }})
    await tasks.execute_query(query_db, parent['id'], model=model_for(call('count_cases', {}), FINISH))
    child = tasks.create_query(query_db, '列出这些案件', parent['id'])
    await tasks.execute_query(query_db, child['id'], model=model_for(call('find_cases', {}), FINISH))
    read = tasks.read_query(query_db, child['id'])
    assert read['initial_context'] is None
    assert read['result']['cards'][0]['data']['total'] == 1
    assert read['result']['cards'][0]['data']['items'][0]['case_number'] == 'MATCH'
    filters = read['followup_context']['conditions']['case_filters']
    assert filters['statuses'] == ['closed']
    assert filters['start_date'] == '2026-09-01T00:00:00Z'


@pytest.mark.asyncio
async def test_area_only_context_can_use_place_tool_without_losing_authorized_scope(query_db):
    request = tasks.create_query(query_db, '查找本辖区井场', initial_context={
        'filters': {'operational_area_id': 1},
    })
    await tasks.execute_query(query_db, request['id'], model=model_for(
        call('find_places', {'keyword': '井场'}), FINISH,
    ))
    result = tasks.read_query(query_db, request['id'])['result']
    assert result['status'] == 'completed'
    assert result['trace'][0]['arguments']['operational_area_id'] == 1
    assert result['cards'][0]['tool'] == 'find_places'


@pytest.mark.asyncio
async def test_source_change_invalidates_initial_and_followup_but_cancel_remains_available(query_db):
    case = add_case(query_db, 'SOURCE', description='版本一')
    query_db.commit()
    parent = tasks.create_query(query_db, '统计当前案件', initial_context={'source_case_id': case.id})
    await tasks.execute_query(query_db, parent['id'], model=model_for(call('count_cases', {}), FINISH))
    child = tasks.create_query(query_db, '继续查看', parent['id'])
    assert child['followup_context']['source_case'] == parent['initial_context']['source_case']
    case.description = '版本二'
    query_db.commit()
    for item in (parent, child):
        with pytest.raises(PermissionError, match='query_initial_context_changed'):
            tasks.read_query(query_db, item['id'])
    with pytest.raises(PermissionError):
        tasks.claim_query(query_db, child['id'])
    assert tasks.cancel_query(query_db, child['id']) == {'id': child['id'], 'status': 'cancelled'}


@pytest.mark.asyncio
async def test_inexpressible_or_implicitly_removed_filters_never_execute_broad_queries(query_db):
    case = add_case(query_db, 'SOURCE')
    add_case(query_db, 'OTHER')
    query_db.commit()
    request = tasks.create_query(query_db, '查看当前案件', initial_context={'source_case_id': case.id})
    model = model_for(
        call('find_places', {'keyword': '井'}),
        call('compare_periods', {'start': '2026-08-01T00:00:00Z', 'end': '2026-09-01T00:00:00Z'}),
        call('count_cases', {'case_id': None}),
        call('count_cases', {}), FINISH,
    )
    await tasks.execute_query(query_db, request['id'], model=model)
    result = tasks.read_query(query_db, request['id'])['result']
    assert len(result['cards']) == 1 and result['cards'][0]['data']['count'] == 1
    assert [step.get('error_code') for step in result['trace'][:3]] == [
        'query_context_tool_cannot_preserve_filters', 'query_context_tool_cannot_preserve_filters',
        'query_context_change_basis_required',
    ]


def test_summary_filters_use_case_time_and_preserve_completed_time_separately(query_db):
    run, _, _, _ = insight_fixture(query_db)
    query_db.info['authorized_area_ids'] = (1,)
    assert execute_tool(query_db, 'summarize_results', {
        'case_id': run.case_id, 'statuses': ['closed'],
    })['data']['total'] == 0
    assert execute_tool(query_db, 'summarize_results', {
        'case_id': run.case_id, 'start_date': '2026-09-10T00:00:00Z',
    })['data']['total'] == 0
    conditions = remember(empty_conditions(), 'summarize_results', {
        'case_id': run.case_id, 'completed_after': '2026-09-01T00:00:00Z',
    })
    with pytest.raises(ValueError, match='query_context_tool_cannot_preserve_filters'):
        inherit('count_cases', {}, conditions, question='继续统计')
