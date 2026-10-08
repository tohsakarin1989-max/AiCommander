from datetime import datetime, timedelta, timezone

import pytest

from app.models.agent_run import AgentRun, AgentEvent
from app.models.map_foundation import UserAreaScope
from app.services import intelligent_query_tasks as tasks
from tests.test_intelligent_query_tasks import query_db, search_db, add_case  # noqa: F401
from tests.test_intelligent_query_api import client_for


AS_OF = '2026-10-08T00:00:00+08:00'


def create(db, kind, context=None, parent=None):
    return tasks.create_query(db, '规则业务问题', parent_query_id=parent,
                              question_type=kind, source_context=context)


async def execute(db, run):
    await tasks.execute_query(db, run['id'])
    return tasks.read_query(db, run['id'])


@pytest.mark.asyncio
async def test_recent_changes_uses_discovery_and_never_calls_model(query_db, monkeypatch):
    def forbidden(*args):
        raise AssertionError('model must not be called')
    monkeypatch.setattr('app.services.intelligent_query_loop.create_query_model', forbidden)
    add_case(query_db, 'OLD', discovered_at=datetime(2026, 6, 1), created_at=datetime(2026, 10, 1))
    add_case(query_db, 'NEW', discovered_at=datetime(2026, 10, 1), created_at=datetime(2026, 10, 1))
    query_db.commit()
    run = create(query_db, 'recent_changes', {'as_of': AS_OF})
    assert run['source_context']['area_id'] == 1
    result = (await execute(query_db, run))['result']
    # Counts are known, but no semantic profiles exist for condition changes.
    assert result['answer']['completeness'] == 'partial'
    assert '补录历史情况 1 起' in result['answer']['direct_answer']
    assert result['cards'][0]['data']['current']['case_count'] == 1
    assert result['usage']['model_requests'] == 0
    assert result['chain_usage']['tool_steps'] == 1
    assert result['answer']['time_scope_versions']['scope_version']


@pytest.mark.asyncio
async def test_unknown_discovery_does_not_become_entry_time_or_complete(query_db):
    add_case(query_db, 'UNKNOWN', discovered_at=None, created_at=datetime(2026, 10, 1))
    query_db.commit()
    result = (await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF})))['result']
    assert result['answer']['completeness'] == 'partial'
    assert result['cards'][0]['data']['current']['case_count'] == 0


@pytest.mark.asyncio
async def test_equal_case_counts_still_answer_grounded_condition_changes(query_db):
    from tests.test_situation_semantic_changes import profile
    previous = add_case(query_db, 'BEFORE', discovered_at=datetime(2026, 8, 20),
                        description='未使用车辆转运')
    current = add_case(query_db, 'AFTER', discovered_at=datetime(2026, 10, 1),
                       description='车辆转运。河岸。')
    query_db.commit()
    profile(query_db, previous)
    profile(query_db, current)
    run = await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF}))
    answer = run['result']['answer']
    assert answer['completeness'] == 'answered'
    assert '变化 +0 起' in answer['direct_answer']
    assert '车辆转运' in answer['direct_answer']
    assert '表述数量变化' in answer['direct_answer']
    changes = {item['semantic_change']['kind']: item for item in answer['differences']
               if item.get('semantic_change', {}).get('value') == '车辆转运'}
    assert set(changes) == {'stated', 'negated'}
    assert changes['stated']['semantic_change']['current_count'] == 1
    assert changes['negated']['semantic_change']['previous_count'] == 1
    assert f'case:{current.id}' in changes['stated']['evidence_refs']
    assert f'case:{previous.id}' in changes['negated']['evidence_refs']
    assert changes['stated']['references'][0]['reference']['quote']
    assert '原文明示否定' in changes['negated']['text']
    current.description = '资料已改，未重建画像'
    query_db.commit()
    stale = await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF}))
    assert stale['result']['answer']['completeness'] == 'partial'
    assert not any(item.get('semantic_change') for item in stale['result']['answer']['differences'])


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['attention', 'recent_changes'])
async def test_empty_success_is_not_answered(query_db, kind):
    result = (await execute(query_db, create(query_db, kind, {'as_of': AS_OF})))['result']
    assert result['answer']['completeness'] == 'insufficient_data'
    assert result['status'] == 'degraded'


@pytest.mark.asyncio
async def test_history_missing_index_is_explicit_partial_or_insufficient(query_db):
    source = add_case(query_db, 'SOURCE', description='夜间发现油罐车，来源未知')
    query_db.commit()
    run = create(query_db, 'case_history', {'case_id': source.id})
    result = (await execute(query_db, run))['result']
    assert result['answer']['completeness'] == 'insufficient_data'
    assert result['cards'][0]['tool'] == 'find_history'
    assert result['usage']['model_requests'] == 0


@pytest.mark.asyncio
async def test_service_failure_is_not_no_matches_and_is_sanitized(query_db, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError('secret internal path')
    monkeypatch.setattr('app.services.situation_temporal_changes.case_changes', broken)
    result = (await execute(query_db, create(query_db, 'recent_changes')))['result']
    assert result['answer']['completeness'] == 'service_unavailable'
    assert result['cards'] == []
    assert 'secret' not in str(result)


@pytest.mark.asyncio
async def test_clarification_wait_has_no_lease_and_exact_retry_is_idempotent(query_db):
    case = add_case(query_db, 'SOURCE')
    query_db.commit()
    run = create(query_db, 'case_history')
    assert run['status'] == 'waiting_clarification'
    assert run['clarification']['field'] == 'case_id'
    assert tasks.claim_query(query_db, run['id']) is None
    assert query_db.get(AgentRun, run['id']).started_at is None
    payload = {'clarification_id': run['clarification']['id'], 'request_id': 'retry-12345', 'value': case.id}
    assert tasks.clarify_query(query_db, run['id'], payload)['status'] == 'queued'
    assert tasks.clarify_query(query_db, run['id'], payload)['status'] == 'queued'
    before = query_db.query(AgentEvent).filter_by(run_id=run['id']).count()
    with pytest.raises(ValueError, match='conflict'):
        tasks.clarify_query(query_db, run['id'], {**payload, 'request_id': 'different-key'})
    query_db.rollback()
    result = (await execute(query_db, run))['result']
    assert tasks.clarify_query(query_db, run['id'], payload)['result'] == result
    assert result['chain_usage']['tool_steps'] == 1
    assert query_db.query(AgentEvent).filter_by(run_id=run['id']).count() == before + 2


def test_waiting_expiry_read_and_resume(query_db):
    case = add_case(query_db, 'SOURCE')
    query_db.commit()
    run = create(query_db, 'case_history')
    row = query_db.get(AgentRun, run['id'])
    pending = {**row.runtime_state['clarification'], 'expires_at': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    row.runtime_state = {**row.runtime_state, 'clarification': pending}
    query_db.commit()
    assert tasks.read_query(query_db, row.id)['status'] == 'expired'
    assert tasks.clarify_query(query_db, row.id, {'clarification_id': pending['id'],
        'request_id': 'retry-12345', 'value': case.id})['status'] == 'expired'


def test_multiple_areas_requires_one_clarification_and_rechecks_scope(query_db):
    query_db.add(UserAreaScope(user_id=1, operational_area_id=2, access_level='read'))
    query_db.commit()
    run = create(query_db, 'attention')
    assert run['clarification']['field'] == 'area_id'
    query_db.query(UserAreaScope).filter_by(user_id=1, operational_area_id=2).delete()
    query_db.commit()
    with pytest.raises(PermissionError):
        tasks.clarify_query(query_db, run['id'], {'clarification_id': run['clarification']['id'],
            'request_id': 'retry-12345', 'value': 2})


@pytest.mark.asyncio
async def test_source_change_during_queue_rebases_but_old_answer_is_hidden(query_db):
    case = add_case(query_db, 'SOURCE')
    query_db.commit()
    run = create(query_db, 'case_history', {'case_id': case.id})
    case.description = '补充来源未知'
    query_db.commit()
    result = (await execute(query_db, run))['result']
    assert any('来源版本已变化' in text for text in result['answer']['unanswered'])
    case.description = '再次更正'
    query_db.commit()
    with pytest.raises(PermissionError):
        tasks.read_query(query_db, run['id'])


@pytest.mark.asyncio
async def test_followup_inherits_frozen_context_and_cumulative_budget(query_db):
    run = await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF}))
    for step in range(2, 10):
        child = tasks.create_query(query_db, '继续', parent_query_id=run['id'])
        assert child['source_context'] == run['source_context']
        run = await execute(query_db, child)
        assert run['result']['chain_usage']['tool_steps'] == min(step, 8)
    assert run['result']['answer']['completeness'] == 'service_unavailable'
    assert run['result']['error_code'] == 'query_budget_exhausted'


@pytest.mark.asyncio
async def test_active_time_budget_and_cancel_prevent_execution(query_db):
    run = create(query_db, 'recent_changes')
    row = query_db.get(AgentRun, run['id'])
    row.runtime_state = {'consumed': {'tool_steps': 1, 'active_ms': 120000}}
    query_db.commit()
    result = (await execute(query_db, run))['result']
    assert result['usage']['tool_calls'] == 0
    assert result['error_code'] == 'query_budget_exhausted'
    wait = create(query_db, 'case_history')
    tasks.cancel_query(query_db, wait['id'])
    assert (await tasks.execute_query(query_db, wait['id']))['status'] == 'cancelled'


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['validation', 'encoding', 'publication'])
async def test_business_finish_deadline_rolls_back_late_answer(query_db, monkeypatch, phase):
    from app.services import business_query_budget
    tick = [100.0]
    monkeypatch.setattr(business_query_budget, 'clock', lambda: tick[0])
    add_case(query_db, 'SOURCE', discovered_at=datetime(2026, 10, 1))
    query_db.commit()
    if phase == 'validation':
        original = tasks.validate_answer
        def delay(db, result):
            original(db, result)
            if result.get('answer') and db.info.get('business_execution_budget'):
                tick[0] += 121
        monkeypatch.setattr(tasks, 'validate_answer', delay)
    elif phase == 'encoding':
        original = tasks.jsonable_encoder
        def delay(result):
            encoded = original(result)
            tick[0] += 121
            return encoded
        monkeypatch.setattr(tasks, 'jsonable_encoder', delay)
    else:
        original = tasks._event
        def delay(db, row, name):
            original(db, row, name)
            if name == 'query_finished':
                tick[0] += 121
        monkeypatch.setattr(tasks, '_event', delay)
    run = await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF}))
    assert run['status'] != 'completed'
    assert run['result']['error_code'] == 'query_budget_exhausted'
    assert run['result']['cards'] == []
    assert run['result']['source_manifest'] == []
    assert not query_db.query(AgentEvent).filter_by(run_id=run['id'], event_type='query_finished').count()


@pytest.mark.asyncio
async def test_business_cancel_during_finish_does_not_publish(query_db, monkeypatch):
    original = tasks.jsonable_encoder
    def cancelled(result):
        encoded = original(result)
        row = query_db.query(AgentRun).filter_by(status='running').one()
        row.status = 'cancelled'
        query_db.flush()
        return encoded
    monkeypatch.setattr(tasks, 'jsonable_encoder', cancelled)
    run = create(query_db, 'recent_changes', {'as_of': AS_OF})
    await tasks.execute_query(query_db, run['id'])
    row = query_db.get(AgentRun, run['id'])
    assert row.status == 'cancelled'
    assert not row.result_summary.get('cards')
    assert not row.result_summary.get('answer')


@pytest.mark.parametrize('status,error_code', [('cancelled', 'query_access_changed'), ('degraded', 'query_budget_exhausted')])
def test_business_finish_accepts_terminal_results_without_answer_body(query_db, status, error_code):
    run = create(query_db, 'recent_changes', {'as_of': AS_OF})
    attempt = tasks.claim_query(query_db, run['id'])
    result = {'status': status, 'error_code': error_code, 'cards': [], 'trace': []}
    assert tasks.finish_query(query_db, run['id'], attempt, result)
    row = query_db.get(AgentRun, run['id'])
    assert row.status == status
    assert row.result_summary['cards'] == []
    if status == 'cancelled':
        assert 'answer' not in row.result_summary
    else:
        assert row.result_summary['answer']['completeness'] == 'service_unavailable'


@pytest.mark.asyncio
async def test_rule_permission_cancellation_without_answer_stays_cancelled(query_db, monkeypatch):
    def cancel(*args, **kwargs):
        return {'status': 'cancelled', 'cards': [], 'trace': [], 'error_code': 'query_access_changed'}
    monkeypatch.setattr('app.services.business_answer.run_business_answer', cancel)
    run = create(query_db, 'recent_changes')
    assert (await tasks.execute_query(query_db, run['id']))['status'] == 'cancelled'
    assert query_db.get(AgentRun, run['id']).result_summary == {}


def test_batched_source_hashing_stops_on_active_deadline(query_db, monkeypatch):
    from app.agent_runtime.execution_contract import ExecutionBudget
    from app.services import business_answer, business_query_budget
    from app.services.case_source_service import CaseSourceService
    cases = [add_case(query_db, f'HASH-{index}') for index in range(110)]
    query_db.commit()
    tick, batches = [0.0], []
    original = CaseSourceService.source_payloads
    def delay(db, rows):
        batches.append(len(rows))
        result = original(db, rows)
        tick[0] = 121
        return result
    monkeypatch.setattr(CaseSourceService, 'source_payloads', delay)
    budget = ExecutionBudget(120, clock=lambda: tick[0])
    with business_query_budget.bind(query_db, budget), pytest.raises(TimeoutError):
        business_answer._case_versions(query_db, cases)
    assert batches == [100]


def test_api_contract_rejects_arbitrary_conditions_and_unsafe_context(query_db, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, 'ENABLE_INTELLIGENT_QUERY', True)
    with client_for(query_db) as client:
        for context in ({'area_id': True}, {'case_id': -1}, {'url': 'https://example.com'},
                        {'as_of': '2026-10-08T00:00:00'}, {'start_date': '2026-01-01'}):
            assert client.post('/api/intelligent-queries', json={
                'query': '规则', 'question_type': 'attention', 'source_context': context}).status_code == 422
        run = client.post('/api/intelligent-queries', json={'query': '查历史', 'question_type': 'case_history'}).json()
        assert run['status'] == 'waiting_clarification'
        url = f"/api/intelligent-queries/{run['id']}/clarifications"
        assert client.post(url, json={'clarification_id': run['clarification']['id'],
            'request_id': 'retry-12345', 'value': True}).status_code == 422


@pytest.mark.asyncio
async def test_positive_history_and_contrast_keep_original_versions(query_db):
    from app.services.case_source_service import CaseSourceService
    from tests.history_index_helpers import build_history_index
    source = add_case(query_db, 'CURRENT', description='夜间。使用软管。')
    positive = add_case(query_db, 'SIMILAR', description='夜里。使用胶管。')
    query_db.add(UserAreaScope(user_id=1, operational_area_id=2, access_level='read'))
    opposite = add_case(query_db, 'DIFFERENT', description='夜间。未使用胶管。', operational_area_id=2)
    for row in (source, positive, opposite):
        CaseSourceService.capture_change(query_db, row)
    query_db.commit()
    build_history_index(query_db)
    run = create(query_db, 'case_history', {'case_id': source.id})
    read = await execute(query_db, run)
    result = read['result']
    assert result['answer']['completeness'] == 'answered'
    assert {item['case_id'] for item in result['cards'][0]['data']['items']} == {positive.id, opposite.id}
    assert any(row.get('contrast_evidence') for row in result['answer']['differences'])
    limited = await execute(query_db, create(query_db, 'case_history', {'case_id': source.id, 'area_id': 1}))
    assert {item['case_id'] for item in limited['result']['cards'][0]['data']['items']} == {positive.id}
    assert limited['result']['answer']['time_scope_versions']['selection'] == 'explicit_area_history'
    opposite.description = '原资料已更正'
    query_db.commit()
    with pytest.raises(PermissionError):
        tasks.read_query(query_db, run['id'])


@pytest.mark.asyncio
async def test_attention_real_profiles_and_asset_context_are_usable(query_db):
    from app.models.jurisdiction import JurisdictionAsset
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.services.case_pipeline_service import CasePipelineService
    asset = JurisdictionAsset(id=501, name='甲井', asset_type='well', operational_area_id=1,
        latitude=46, longitude=125, status='active', verified=True,
        attributes={'historical_methods': ['打孔盗油']})
    query_db.add(asset)
    for number in ('A', 'B'):
        case = add_case(query_db, number, description='夜间打孔盗油', discovered_at=datetime(2026, 10, 6))
        payload = CasePipelineService.build_profile_payload(query_db, case)
        query_db.add(CaseAnalysisProfile(id=f'profile-{number}', case_id=case.id, profile_version=1,
            source_hash=payload['source_hash'], schema_version='8.0.0', dictionary_version='test',
            quality_score=1, analysis_readiness='ready', is_current=True, payload=payload))
    query_db.commit()
    run = create(query_db, 'attention', {'asset_id': asset.id, 'as_of': AS_OF})
    result = (await execute(query_db, run))['result']
    assert result['answer']['completeness'] == 'answered'
    assert result['cards'][0]['data']['items'][0]['state'] == 'repeated_conditions'
    assert result['source_manifest']
    asset.name = '已更正设施名'
    query_db.commit()
    with pytest.raises(PermissionError):
        tasks.read_query(query_db, run['id'])


@pytest.mark.asyncio
async def test_explicit_time_followup_changes_are_preserved_without_scope_expansion(query_db):
    parent = await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF}))
    child = tasks.create_query(query_db, '按明确条件续查', parent_query_id=parent['id'],
        source_context={'time_basis': 'entry', 'period': 'weekly'})
    assert child['source_context']['time_basis'] == 'entry'
    assert child['source_context']['area_id'] == 1
    result = (await execute(query_db, child))['result']
    assert any('不同条件' in text for text in result['answer']['unanswered'])
    with pytest.raises(ValueError, match='context_changed'):
        tasks.create_query(query_db, '继续', parent_query_id=parent['id'], source_context={'area_id': 2})


@pytest.mark.asyncio
async def test_derived_quality_refresh_keeps_snapshot_but_source_details_invalidate(query_db):
    from app.models.case_source import CaseLocation
    case = add_case(query_db, 'SOURCE', discovered_at=datetime(2026, 10, 1))
    query_db.commit()
    run = await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF}))
    case.quality_score = 0.9
    case.quality_issues = ['后台刷新']
    case.features = {'intelligence': {'derived': 'new'}}
    query_db.commit()
    assert tasks.read_query(query_db, run['id'])['result'] == run['result']
    query_db.add(CaseLocation(case_id=case.id, role='discovery', precision='exact',
                              geometry={'type': 'Point', 'coordinates': [125, 46]}))
    query_db.commit()
    with pytest.raises(PermissionError):
        tasks.read_query(query_db, run['id'])


@pytest.mark.asyncio
async def test_changed_inputs_cannot_be_published_under_new_source_version(query_db, monkeypatch):
    from app.services import situation_temporal_changes
    case = add_case(query_db, 'SOURCE', discovered_at=datetime(2026, 10, 1))
    query_db.commit()
    original = situation_temporal_changes.case_changes
    def changed(db, *args):
        result = original(db, *args)
        case.discovered_at = datetime(2000, 1, 1)
        db.flush()
        return result
    monkeypatch.setattr(situation_temporal_changes, 'case_changes', changed)
    run = create(query_db, 'recent_changes', {'as_of': AS_OF})
    assert (await tasks.execute_query(query_db, run['id']))['status'] == 'cancelled'
    assert query_db.get(AgentRun, run['id']).result_summary == {}


def test_clarification_endpoint_success_and_no_worker_expiry(query_db, monkeypatch):
    from app.config import settings
    from app.services.intelligent_query_worker import expire_abandoned_queries
    monkeypatch.setattr(settings, 'ENABLE_INTELLIGENT_QUERY', True)
    case = add_case(query_db, 'SOURCE')
    query_db.commit()
    with client_for(query_db) as client:
        run = client.post('/api/intelligent-queries', json={'query': '历史参考', 'question_type': 'case_history'}).json()
        response = client.post(f"/api/intelligent-queries/{run['id']}/clarifications", json={
            'clarification_id': run['clarification']['id'], 'request_id': 'api-retry-key', 'value': case.id})
        assert response.status_code == 200 and response.json()['status'] == 'queued'
    waiting = create(query_db, 'case_history')
    query_db.get(AgentRun, waiting['id']).created_at = datetime.now(timezone.utc) - timedelta(hours=25)
    query_db.commit()
    assert expire_abandoned_queries(query_db) == 1
    assert query_db.get(AgentRun, waiting['id']).status == 'expired'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['case_history', 'attention', 'recent_changes'])
async def test_all_rule_cards_export_the_frozen_answer_without_reanalysis(query_db, kind):
    from app.services.intelligent_query_document import build_query_document
    from app.services.case_result_export import render_docx
    case = add_case(query_db, 'SOURCE', description='现场情况待核')
    query_db.commit()
    context = {'case_id': case.id, 'as_of': AS_OF} if kind == 'case_history' else {'as_of': AS_OF}
    run = await execute(query_db, create(query_db, kind, context))
    document = build_query_document(run)
    assert run['result']['answer']['direct_answer'] in [block.text for block in document.blocks]
    assert {'差异或反向情况', '尚不能回答的部分'} <= {block.text for block in document.blocks}
    assert render_docx(document).startswith(b'PK')
    assert all(0 <= row['card_index'] < len(run['result']['cards']) for row in run['result']['answer']['findings'])
    assert run['result']['answer']['map_context'] == run['result']['cards'][0]['data']['map_context']


def add_map(db):
    from app.models.map_foundation import PublicMapBundle, MapSnapshot
    bundle = PublicMapBundle(id=701, bundle_id='business-map', provider='isolated-test', source_version='test',
        license_record='synthetic', bounds=[124, 45, 127, 48], manifest={}, package_hash='a' * 64, status='accepted')
    db.add(bundle)
    db.flush()
    snapshot = MapSnapshot(id='business-map-current', version='map-test-8.4', operational_area_id=1,
        public_bundle_id=bundle.id, status='current', manifest={}, feature_watermark='test')
    db.add(snapshot)
    db.commit()
    return snapshot


@pytest.mark.asyncio
async def test_map_freezes_only_typed_points_and_rechecks_location_access(query_db):
    from app.models.case_source import CaseLocation
    snapshot = add_map(query_db)
    case = add_case(query_db, 'SOURCE', discovered_at=datetime(2026, 10, 1), latitude=1, longitude=2)
    location = CaseLocation(case_id=case.id, role='discovery', precision='exact',
                            geometry={'type': 'Point', 'coordinates': [125, 46]})
    query_db.add(location)
    query_db.commit()
    run = await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF}))
    mapped = run['result']['answer']['map_context']
    assert mapped['points'][0]['latitude'] == 46
    assert mapped['points'][0]['role'] == 'discovery'
    assert mapped['points'][0]['map_snapshot_id'] == snapshot.id
    snapshot.status = 'superseded'
    query_db.commit()
    assert tasks.read_query(query_db, run['id'])['result']['answer']['map_context'] == mapped
    location.geometry = {'type': 'Point', 'coordinates': [126, 47]}
    query_db.commit()
    with pytest.raises(PermissionError):
        tasks.read_query(query_db, run['id'])


@pytest.mark.asyncio
async def test_map_missing_or_failed_does_not_remove_text_answer(query_db, monkeypatch):
    add_case(query_db, 'SOURCE', discovered_at=datetime(2026, 10, 1), latitude=46, longitude=125)
    query_db.commit()
    run = await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF}))
    assert run['result']['answer']['map_context']['state'] == 'unavailable'
    assert run['result']['answer']['map_context']['points'] == []
    def fail(*args):
        raise RuntimeError('internal-map-path')
    monkeypatch.setattr('app.services.business_answer_map.build_map_context', fail)
    another = await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF}))
    assert '本期登记 1 起' in another['result']['answer']['direct_answer']
    assert 'internal-map-path' not in str(another)


def test_map_facility_uses_published_feature_not_current_asset_point(query_db):
    from app.models.jurisdiction import JurisdictionAsset
    from app.models.map_foundation import MapSnapshotFeature
    from app.services.business_answer_map import build_map_context
    snapshot = add_map(query_db)
    asset = JurisdictionAsset(id=888, name='新名称', asset_type='well', operational_area_id=1,
        latitude=47, longitude=126, status='active', verified=True, attributes={})
    feature = MapSnapshotFeature(snapshot_id=snapshot.id, asset_id=888, operational_area_id=1,
        name='冻结名称', asset_type='well', geometry_type='Point', latitude=46, longitude=125,
        geometry={'type': 'Point', 'coordinates': [125, 46]}, status='active', verified=True, attributes={})
    query_db.add_all([asset, feature])
    query_db.commit()
    result, bindings = build_map_context(query_db, 'attention', {'area_id': 1},
        {'source_bindings': {'case_ids': [], 'asset_ids': [888]}})
    assert result['points'][0]['latitude'] == 46
    assert result['points'][0]['label'] == '冻结名称'
    assert {row['kind'] for row in bindings} >= {'asset', 'map_feature', 'map_snapshot', 'area'}


def test_map_cap_does_not_guess_legacy_or_expand_answer_records(query_db):
    from app.models.case_source import CaseLocation
    from app.services.business_answer_map import build_map_context
    add_map(query_db)
    identifiers = []
    for number in range(102):
        case = add_case(query_db, f'MAP-{number}')
        identifiers.append(case.id)
        query_db.add(CaseLocation(case_id=case.id, role='discovery', precision='exact',
            geometry={'type': 'Point', 'coordinates': [125, 46]}))
    query_db.commit()
    result, _ = build_map_context(query_db, 'recent_changes', {'area_id': 1},
        {'current': {'case_ids': identifiers}, 'previous': {'case_ids': []}})
    assert result['coverage'] == {'point_limit': 100, 'shown': 100, 'truncated': True}
    assert all(row['object_id'] in identifiers for row in result['points'])
