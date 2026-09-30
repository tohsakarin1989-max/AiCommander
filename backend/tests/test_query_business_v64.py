"""Actual synthetic business reads and durable no-model query execution."""
from datetime import datetime, timezone
from types import SimpleNamespace
import json
import threading
import time

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text

from app.agent_runtime.execution_contract import ExecutionBudget, ExecutionCancelled, sql_budget
from app.config import settings
from app.models.agent_run import AgentRun, AgentUsageRecord
from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import JurisdictionAssetVersion
from app.services import intelligent_query_tasks as tasks
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_service import CaseService
from app.services.intelligent_query_answers import compose_answer
from app.services.intelligent_query_business import validate_business_query_evidence
from app.services.intelligent_query_context import empty_conditions, inherit, remember
from app.services.intelligent_query_loop import run_query
from app.services.intelligent_query_presets import QueryPreset
from app.services.intelligent_query_tools import execute_tool, tool_declarations
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_case_search_page import add_case
from tests.test_spatial_coverage import inventory, AS_OF


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    monkeypatch.setattr(settings, 'AGENT_MODEL_ID', None)
    monkeypatch.setattr(settings, 'CASE_SEMANTIC_MODEL_ID', None)


def ready_case(db):
    from app.models.map_foundation import UserAreaScope
    db.query(UserAreaScope).filter_by(user_id=1, operational_area_id=1).one().access_level = 'write'
    db.commit()
    db.info['area_access_levels'] = {1: 'write'}
    case = CaseService.create_case(db, case_number='R11-SYNTHETIC', operational_area_id=1,
                                   description='未转运原油120升。从东井场转运至西村屯。')
    event = db.query(OutboxEvent).filter_by(aggregate_id=str(case.id), event_type='case.analysis.requested').one()
    CasePipelineService.process_event(db, event.id)
    return case


@pytest.mark.asyncio
async def test_no_model_preset_executes_business_and_persists_answer(query_db, monkeypatch):
    add_case(query_db, 'ONE'); add_case(query_db, 'HIDDEN', operational_area_id=2)
    query_db.commit()
    monkeypatch.setattr('app.services.intelligent_query_loop.create_query_model', lambda *_: pytest.fail('preset called model'))
    task = tasks.create_query(query_db, '统计本辖区案件', preset={'name': 'case_count', 'arguments': {}})
    assert await tasks.execute_query(query_db, task['id']) == {'id': task['id'], 'status': 'completed'}
    result = tasks.read_query(query_db, task['id'])['result']
    assert result['cards'][0]['data']['count'] == 1
    assert '1 起' in result['answer']['findings'][0]['text']
    assert result['execution_mode'] == 'deterministic_preset'
    assert result['task_envelope']['principal_user_id'] == 1
    assert result['usage']['model_requests'] == 0 and result['usage']['token_state'] == 'not_used'
    assert query_db.query(AgentUsageRecord).filter_by(run_id=task['id']).one().request_count == 0
    assert query_db.query(Case).count() == 1  # Current scope, not a global count.


@pytest.mark.asyncio
async def test_process_preset_preserves_negation_quotes_and_source_revision(query_db):
    case = ready_case(query_db)
    task = tasks.create_query(query_db, '当前案件过程', preset={'name': 'case_process', 'arguments': {'case_id': case.id}})
    outcome = await tasks.execute_query(query_db, task['id'])
    assert outcome['status'] == 'completed'
    result = tasks.read_query(query_db, task['id'])['result']
    process = result['cards'][0]['data']['process']
    assert process['source_revision_id']
    assert process['events'][0]['statement_kind'] == 'negated'
    assert '未转运原油120升' in json.dumps(result['answer'], ensure_ascii=False)
    assert case.description == '未转运原油120升。从东井场转运至西村屯。'
    assert all(finding['evidence_refs'] for finding in result['answer']['findings'])


def test_process_and_initial_context_reject_same_hash_different_revision(query_db):
    case = ready_case(query_db)
    task = tasks.create_query(query_db, '当前过程', preset={'name': 'case_process', 'arguments': {'case_id': case.id}})
    original = case.description
    CaseService.update_case(query_db, case.id, description='改写测试资料。')
    CaseService.update_case(query_db, case.id, description=original)
    with pytest.raises(PermissionError, match='query_initial_context_changed'):
        tasks.read_query(query_db, task['id'])
    assert execute_tool(query_db, 'read_case_process', {'case_id': case.id})['state'] == 'partial'
    profile = execute_tool(query_db, 'find_case_profiles', {'case_id': case.id})
    assert profile['data']['items'][0]['assertions'] == []


def test_missing_profile_or_result_never_generates_or_mutates(query_db):
    case = add_case(query_db, 'MISSING'); query_db.commit()
    before = query_db.query(CaseAnalysisProfile).count()
    for tool in ('read_case_process', 'explain_case_result'):
        card = execute_tool(query_db, tool, {'case_id': case.id})
        assert card['state'] == 'partial'
        assert card['information_gaps']
    assert query_db.query(CaseAnalysisProfile).count() == before
    assert not query_db.new and not query_db.dirty


def test_current_and_historical_result_are_same_frozen_business_source(query_db):
    case = ready_case(query_db)
    card = execute_tool(query_db, 'explain_case_result', {'case_id': case.id})
    assert card['data']['result']['content_sha256']
    historical = execute_tool(query_db, 'explain_case_result', {'case_id': case.id, 'result_id': card['data']['result']['id']})
    assert historical['data']['result']['content_sha256'] == card['data']['result']['content_sha256']
    validate_business_query_evidence(query_db, {'cards': [historical]})


def test_facility_dossier_and_historical_time_use_real_version_service(query_db):
    asset = JurisdictionAsset(name='合成生产井', asset_type='well', operational_area_id=1,
        latitude=47, longitude=124, geometry_type='point', status='active', verified=True)
    query_db.add(asset); query_db.flush()
    version = JurisdictionAssetVersion(asset_id=asset.id, version=1, change_type='manual',
        temporal_status='declared', valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        known_at=datetime(2026, 1, 10, tzinfo=timezone.utc), snapshot={
            'name': '历史名称', 'operational_area_id': 1, 'attributes': {}, 'verified': True, 'status': 'active'})
    query_db.add(version); query_db.commit()
    dossier = execute_tool(query_db, 'read_facility_dossier', {'asset_id': asset.id})
    assert dossier['data']['dossier']['facility']['name'] == asset.name
    validate_business_query_evidence(query_db, {'cards': [dossier]})
    args = {'asset_id': asset.id, 'valid_at': '2026-01-02T00:00:00Z', 'known_at': '2026-01-11T00:00:00Z'}
    history = execute_tool(query_db, 'read_facility_at', args)
    assert history['data']['historical']['snapshot']['name'] == '历史名称'
    before = execute_tool(query_db, 'read_facility_at', {**args, 'known_at': '2026-01-09T00:00:00Z'})
    assert before['state'] == 'partial' and before['data']['historical']['snapshot'] is None
    validate_business_query_evidence(query_db, {'cards': [history]})


@pytest.mark.asyncio
async def test_real_scenario_disables_existing_resources_without_changing_assets(query_db):
    assets = inventory(query_db)
    task = tasks.create_query(query_db, '假设两处设备停用，比较名义覆盖', preset={
        'name': 'coverage_scenario', 'arguments': {'operational_area_id': 1, 'as_of': AS_OF.isoformat(),
            'disabled_resource_ids': [assets[0].id, assets[1].id]}})
    outcome = await tasks.execute_query(query_db, task['id'])
    assert outcome['status'] == 'completed'
    result = tasks.read_query(query_db, task['id'])['result']
    comparison = result['cards'][0]['data']['comparison']
    assert comparison['baseline']['covered_count'] == 1 and comparison['scenario']['covered_count'] == 0
    assert comparison['execution_task_created'] is False and comparison['persisted'] is False
    assert assets[0].attributes['operational_status'] == 'online'
    assert any('名义覆盖' in finding['text'] for finding in result['answer']['findings'])


def test_scenario_movement_changes_real_geometry_coverage(query_db):
    assets = inventory(query_db)
    result = execute_tool(query_db, 'compare_coverage_scenario', {'operational_area_id': 1,
        'as_of': AS_OF.isoformat(), 'movements': [{'resource_id': assets[1].id, 'latitude': 47.01, 'longitude': 124.0}]})
    value = result['data']['comparison']
    assert value['scenario']['covered_count'] == 2 and value['scenario']['overlap_count'] == 0
    assert assets[1].latitude == 47


@pytest.mark.parametrize('preset', [
    {'name': 'shell', 'arguments': {}},
    {'name': 'case_count', 'arguments': {'sql': 'SELECT 1'}},
    {'name': 'facility_history', 'arguments': {'asset_id': 1}},
    {'name': 'coverage_scenario', 'arguments': {'operational_area_id': 1, 'as_of': '2026-01-01'}},
    {'name': 'case_process', 'arguments': {'case_id': True}},
])
def test_presets_reject_untyped_or_executable_arguments(preset):
    with pytest.raises(ValidationError):
        QueryPreset.model_validate(preset)


def test_business_tools_reject_hidden_targets_and_resource_creation(query_db):
    case = add_case(query_db, 'HIDDEN', operational_area_id=2); query_db.commit()
    with pytest.raises(PermissionError):
        execute_tool(query_db, 'read_case_process', {'case_id': case.id})
    with pytest.raises(PermissionError):
        execute_tool(query_db, 'compare_coverage_scenario', {'operational_area_id': 1,
            'as_of': AS_OF.isoformat(), 'disabled_resource_ids': [999]})
    with pytest.raises(ValidationError):
        execute_tool(query_db, 'read_business_result', {'kind': 'query', 'identifier': 'self'})
    assert all(item['runtime'] == 'intelligent_query' for item in tool_declarations().values())
    assert 'map_data_quality' not in tool_declarations()


def test_followup_keeps_facility_and_temporal_conditions_without_silent_broadening():
    args = {'asset_id': 3, 'valid_at': '2026-01-01T00:00:00Z', 'known_at': '2026-02-01T00:00:00Z'}
    state = remember(empty_conditions(), 'read_facility_at', args)
    inherited, changes = inherit('read_facility_at', {}, state, question='解释历史资料')
    assert inherited['asset_id'] == 3 and inherited['valid_at'] == args['valid_at']
    assert changes == []
    with pytest.raises(ValueError, match='cannot_preserve_filters'):
        inherit('count_cases', {}, state, question='统计')


@pytest.mark.asyncio
async def test_model_metering_is_actual_metadata_or_explicit_unknown(query_db):
    class Model:
        calls = 0
        async def ainvoke(self, prompt):
            self.calls += 1
            content = '{"action":"call","tool":"count_cases","arguments":{}}' if self.calls == 1 else '{"action":"finish","reason":"completed"}'
            return SimpleNamespace(content=content, usage_metadata={'input_tokens': 5, 'output_tokens': 3})
    result = await run_query(query_db, '统计', Model())
    assert result['usage']['input_tokens'] == 10 and result['usage']['output_tokens'] == 6
    assert result['usage']['model_requests'] == 2 and result['usage']['tool_calls'] == 1
    assert result['usage']['token_state'] == 'known'
    from tests.test_query_followup import model_for, call, FINISH
    missing = await run_query(query_db, '统计', model_for(call('count_cases', {}), FINISH))
    assert missing['usage']['input_tokens'] is None and missing['usage']['token_state'] == 'unavailable'


def test_sqlite_actual_expensive_statement_is_interrupted_and_connection_reusable(query_db):
    budget = ExecutionBudget(time.monotonic() + .02)
    with pytest.raises(TimeoutError):
        with sql_budget(query_db, budget):
            query_db.scalar(text('WITH RECURSIVE counter(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM counter WHERE x<100000000) SELECT sum(x) FROM counter'))
    query_db.rollback()
    assert query_db.scalar(text('SELECT 7')) == 7


def test_sqlite_actual_statement_cancellation_uses_external_probe(query_db):
    cancel = threading.Event()
    query_db.info['execution_cancel_probe'] = cancel.is_set
    timer = threading.Timer(.02, cancel.set); timer.start()
    try:
        with pytest.raises(ExecutionCancelled):
            with sql_budget(query_db, ExecutionBudget(time.monotonic() + 2)):
                query_db.scalar(text('WITH RECURSIVE counter(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM counter WHERE x<100000000) SELECT sum(x) FROM counter'))
    finally:
        timer.join(); query_db.info.pop('execution_cancel_probe', None); query_db.rollback()
    assert query_db.scalar(text('SELECT 8')) == 8


def test_api_preset_is_typed_and_authorized_before_enqueue(query_db, monkeypatch):
    from tests.test_intelligent_query_api import client_for
    monkeypatch.setattr(settings, 'ENABLE_INTELLIGENT_QUERY', True)
    with client_for(query_db) as client:
        created = client.post('/api/intelligent-queries', json={'query': '统计本辖区',
            'preset': {'name': 'case_count', 'arguments': {}}})
        assert created.status_code == 201
        assert created.json()['preset']['name'] == 'case_count'
        assert client.post('/api/intelligent-queries', json={'query': '执行',
            'preset': {'name': 'case_count', 'arguments': {'sql': 'SELECT 1'}}}).status_code == 422
    with client_for(query_db, role='viewer') as client:
        assert client.post('/api/intelligent-queries', json={'query': '统计',
            'preset': {'name': 'case_count', 'arguments': {}}}).status_code == 403


def test_business_result_reader_uses_catalog_and_cannot_recurse_into_query(query_db):
    case = ready_case(query_db)
    original = execute_tool(query_db, 'explain_case_result', {'case_id': case.id})['data']['result']
    card = execute_tool(query_db, 'read_business_result', {'kind': 'case', 'identifier': original['id']})
    assert card['data']['business_result']['content_sha256'] == original['content_sha256']
    validate_business_query_evidence(query_db, {'cards': [card]})
    listing = execute_tool(query_db, 'find_business_results', {'kind': 'case'})
    assert any(item['id'] == original['id'] for item in listing['data']['catalog']['items'])
    assert all(item['kind'] != 'query' for item in listing['data']['catalog']['items'])


@pytest.mark.asyncio
async def test_process_preset_keeps_existing_case_filters(query_db):
    case = ready_case(query_db)
    task = tasks.create_query(query_db, '当前过程', initial_context={
        'source_case_id': case.id, 'filters': {'statuses': [case.status]}},
        preset={'name': 'case_process', 'arguments': {'case_id': case.id}})
    assert (await tasks.execute_query(query_db, task['id']))['status'] == 'completed'
    assert tasks.read_query(query_db, task['id'])['result']['trace'][0]['arguments']['statuses'] == [case.status]


def test_only_published_partial_scan_creates_durable_continuation(query_db):
    from app.services.intelligent_query_answers import compose_answer
    task = tasks.create_query(query_db, '统计全部画像')
    attempt = tasks.claim_query(query_db, task['id'])
    card = {'tool': 'aggregate_case_profiles', 'state': 'partial',
        'data': {'coverage': {'complete': False}},
        'evidence': {'filters': {}}, 'information_gaps': []}
    result = {'status': 'degraded', 'cards': [card], 'trace': [], 'answer': compose_answer([card])}
    assert tasks.finish_query(query_db, task['id'], attempt, result)
    read = tasks.read_query(query_db, task['id'])
    continuation = read['result']['cards'][0]['continuation']
    assert continuation['status'] == 'pending'
    assert query_db.query(OutboxEvent).filter_by(id=continuation['id']).one().payload['query_id'] == task['id']
    assert not tasks.finish_query(query_db, task['id'], attempt, result)
    assert query_db.query(OutboxEvent).filter_by(event_type='topic.aggregate.requested').count() == 1


def test_postgresql_deadline_and_explicit_cancel_use_real_statement():
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    value = os.environ.get('AIC_R11_PG_URL')
    if not value:
        pytest.skip('disposable PostgreSQL not requested')
    url = make_url(value)
    assert url.host == '127.0.0.1' and url.database.startswith('aic_')
    assert os.environ.get('AIC_DISPOSABLE_R11') == '1'
    engine = create_engine(value)
    try:
        with Session(engine) as db:
            with pytest.raises(TimeoutError):
                with sql_budget(db, ExecutionBudget(time.monotonic() + .05)):
                    db.execute(text('SELECT pg_sleep(5)'))
            db.rollback()
            assert db.scalar(text('SELECT 1')) == 1
            cancel = threading.Event()
            db.info['execution_cancel_probe'] = cancel.is_set
            timer = threading.Timer(.03, cancel.set); timer.start()
            try:
                with pytest.raises(ExecutionCancelled):
                    with sql_budget(db, ExecutionBudget(time.monotonic() + 5)):
                        db.execute(text('SELECT pg_sleep(10)'))
            finally:
                timer.join(); db.rollback()
            assert db.scalar(text('SELECT 2')) == 2
    finally:
        engine.dispose()
