"""v9 question completion, historical availability and safe reuse regressions."""
from copy import deepcopy
from datetime import datetime

import pytest

from app.models.agent_run import AgentRun
from app.models.case_source import EvidenceObject
from app.models.map_foundation import UserAreaScope
from app.services import intelligent_query_tasks as tasks
from app.services.intelligent_query_document import build_query_document
from app.services.intelligent_query_tools import execute_tool
from app.services.question_contract import make_question_spec
from app.services.query_snapshot_availability import freeze_validated_business_snapshot, snapshot_availability
from tests.test_intelligent_query_tasks import query_db, search_db, add_case  # noqa: F401
from tests.test_query_followup import call, model_for, FINISH


CONTEXT = {'as_of': '2026-10-08T00:00:00+08:00'}


async def answered(db):
    run = tasks.create_query(db, '近期情况', question_type='recent_changes', source_context=CONTEXT)
    await tasks.execute_query(db, run['id'])
    return tasks.read_query(db, run['id'])


@pytest.mark.asyncio
async def test_normal_revision_keeps_frozen_material_but_revocation_does_not(query_db):
    case = add_case(query_db, 'FROZEN', discovered_at=datetime(2026, 10, 1), description='原始登记')
    query_db.commit()
    original = await answered(query_db)
    snapshot = deepcopy(original['result'])
    case.description = '核实后正常更正'
    query_db.commit()
    historical = tasks.read_query(query_db, original['id'])
    assert historical['availability']['state'] == 'historical'
    assert historical['result'] == snapshot
    assert any('冻结内容' in str(block) for block in build_query_document(historical).blocks)
    query_db.query(UserAreaScope).filter_by(user_id=1).delete()
    query_db.commit()
    with pytest.raises(PermissionError):
        tasks.read_query(query_db, original['id'])


@pytest.mark.asyncio
async def test_legacy_or_tampered_snapshot_cannot_gain_historical_read(query_db):
    case = add_case(query_db, 'LEGACY', description='旧案', discovered_at=datetime(2026, 10, 1))
    query_db.commit()
    original = await answered(query_db)
    row = query_db.get(AgentRun, original['id'])
    result = deepcopy(row.result_summary)
    result['answer']['direct_answer'] = '无来源结论'
    row.result_summary = result
    query_db.commit()
    with pytest.raises(PermissionError, match='snapshot_incomplete'):
        tasks.read_query(query_db, row.id)
    result = deepcopy(original['result'])
    result.pop('frozen_source_receipt')
    row.result_summary = result
    case.description = '新事实不能反填旧答案'
    query_db.commit()
    with pytest.raises(PermissionError):
        tasks.read_query(query_db, row.id)


@pytest.mark.asyncio
async def test_withdrawn_record_cannot_be_read_as_merely_historical(query_db):
    case = add_case(query_db, 'DELETE', discovered_at=datetime(2026, 10, 1))
    query_db.commit()
    original = await answered(query_db)
    query_db.delete(case)
    query_db.commit()
    with pytest.raises(PermissionError):
        tasks.read_query(query_db, original['id'])


def test_revoked_original_blocks_historical_receipt(query_db):
    evidence = EvidenceObject(storage_key='v9-test-metadata', availability='metadata_only')
    query_db.add(evidence)
    query_db.commit()
    result = {'answer': {'answer_contract_version': 'answer-snapshot-9.3-1',
        'question_type': 'attention', 'time_scope_versions': {'answered_at': '2026-10-09'}},
        'cards': [{'tool': 'business_recent_changes', 'data': {}}],
        'source_manifest': [{'kind': 'evidence_object', 'id': evidence.id}]}
    freeze_validated_business_snapshot(query_db, result)
    evidence.availability = 'revoked'
    query_db.commit()
    with pytest.raises(PermissionError, match='withdrawn'):
        snapshot_availability(query_db, result)


@pytest.mark.asyncio
async def test_same_sources_reuse_pending_and_completed_without_duplicate_events(query_db):
    add_case(query_db, 'ONE', discovered_at=datetime(2026, 10, 1))
    query_db.commit()
    first = tasks.create_query(query_db, '近期情况', question_type='recent_changes', source_context=CONTEXT)
    duplicate = tasks.create_query(query_db, '近期情况', question_type='recent_changes', source_context=CONTEXT)
    assert duplicate['id'] == first['id'] and duplicate['reused']
    await tasks.execute_query(query_db, first['id'])
    duplicate = tasks.create_query(query_db, '近期情况', question_type='recent_changes', source_context=CONTEXT)
    assert duplicate['id'] == first['id'] and duplicate['reused']
    add_case(query_db, 'TWO', discovered_at=datetime(2026, 10, 2))
    query_db.commit()
    current = tasks.create_query(query_db, '近期情况', question_type='recent_changes', source_context=CONTEXT)
    assert current['id'] != first['id']
    changed = tasks.create_query(query_db, '近期情况', question_type='recent_changes',
        source_context={**CONTEXT, 'time_basis': 'entry'})
    assert changed['id'] != current['id']
    query_db.info['principal_user_id'] = 2
    other = tasks.create_query(query_db, '近期情况', question_type='recent_changes', source_context=CONTEXT)
    assert other['id'] not in {first['id'], current['id']}


@pytest.mark.asyncio
async def test_literal_business_question_uses_same_rule_path_without_model(query_db, monkeypatch):
    monkeypatch.setattr('app.services.intelligent_query_loop.create_query_model',
        lambda db: (_ for _ in ()).throw(AssertionError('must not call a model')))
    run = tasks.create_query(query_db, '最近发生了哪些实质变化？')
    assert run['question_type'] == 'recent_changes'
    await tasks.execute_query(query_db, run['id'])
    answer = tasks.read_query(query_db, run['id'])['result']['answer']
    assert answer['answer_contract_version'] == 'answer-snapshot-9.3-1'
    assert answer['question_spec']['goal'] == 'recent_changes'
    assert answer['capabilities']['model_enhancement'] == 'not_used'


def test_literal_shortcut_never_discards_existing_filter(query_db):
    run = tasks.create_query(query_db, '最近发生了哪些实质变化？',
        initial_context={'filters': {'keyword': '明确条件'}})
    assert run['question_type'] is None
    assert run['initial_context']['conditions']['case_filters']['keyword'] == '明确条件'


def test_time_basis_filters_unknown_without_substitution(query_db):
    add_case(query_db, 'OLD-LATE', occurred_time=datetime(2000, 1, 1),
        discovered_at=datetime(2000, 1, 1), created_at=datetime(2026, 10, 1))
    add_case(query_db, 'UNKNOWN', occurred_time=None, discovered_at=None, created_at=datetime(2026, 10, 1))
    query_db.commit()
    args = {'start_date': '2026-10-01T00:00:00Z', 'end_date': '2026-10-03T00:00:00Z'}
    assert execute_tool(query_db, 'count_cases', {**args, 'time_basis': 'entry'})['data']['count'] == 2
    assert execute_tool(query_db, 'count_cases', {**args, 'time_basis': 'discovery'})['data']['count'] == 0
    assert execute_tool(query_db, 'count_cases', {**args, 'time_basis': 'incident'})['data']['count'] == 0


def test_list_and_map_read_identical_explicit_time_scope(search_db):
    from tests.test_case_search_page import client_for
    late = add_case(search_db, 'OLD-LATE', occurred_time=datetime(2000, 1, 1),
        discovered_at=datetime(2026, 10, 1), created_at=datetime(2026, 10, 2))
    add_case(search_db, 'UNKNOWN', occurred_time=datetime(2026, 10, 1), time_precision='unknown', discovered_at=None)
    search_db.commit()
    client = client_for(search_db)
    params = {'start_date': '2026-10-01T00:00:00Z', 'end_date': '2026-10-03T00:00:00Z', 'time_basis': 'discovery'}
    page = client.get('/api/cases/page', params=params)
    mapped = client.get('/api/cases/', params={**params, 'end_exclusive': True})
    assert page.status_code == mapped.status_code == 200
    assert [item['id'] for item in page.json()['items']] == [late.id]
    assert [item['id'] for item in mapped.json()] == [late.id]
    assert client.get('/api/cases/', params={**params, 'time_basis': 'incident'}).json() == []


@pytest.mark.asyncio
async def test_wrong_successful_tool_requests_bounded_supplement_then_partial(query_db):
    run = tasks.create_query(query_db, '比较两个周期的数量差异')
    model = model_for(call('count_cases', {}), FINISH, FINISH)
    await tasks.execute_query(query_db, run['id'], model=model)
    result = tasks.read_query(query_db, run['id'])['result']
    assert result['status'] == 'degraded'
    assert result['error_code'] == 'query_answer_incomplete'
    assert result['answer']['completeness'] == 'partial'
    assert 'comparable_values' in result['answer']['answer_requirements']['missing']
    assert model.prompts[-1]['tool_feedback'][-1]['error_code'] == 'answer_requirements_missing'


def test_question_spec_keeps_explicit_time_scope():
    value = make_question_spec('统计', preset={'name': 'case_count',
        'arguments': {'time_basis': 'discovery', 'start_date': '2026-10-01T00:00:00Z'}})
    assert value['time_scope']['time_basis'] == 'discovery'
    assert value['time_scope']['start'] == '2026-10-01T00:00:00Z'
