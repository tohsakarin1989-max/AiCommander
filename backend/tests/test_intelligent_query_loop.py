import asyncio
from types import SimpleNamespace

import pytest

from app.services.intelligent_query_loop import create_query_model, run_query
from tests.test_case_search_page import search_db, add_case  # noqa: F401


@pytest.mark.asyncio
async def test_model_selects_tools_but_cannot_supply_answer_or_evidence(search_db):
    add_case(search_db, 'ONE')
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    steps = iter([
        '{"action":"call","tool":"count_cases","arguments":{}}',
        '{"action":"finish","reason":"completed"}'])
    class Model:
        async def ainvoke(self, prompt):
            return SimpleNamespace(content=next(steps))
    result = await run_query(search_db, '有多少案件', Model())
    assert result['status'] == 'completed'
    assert result['cards'][0]['data']['count'] == 1
    assert result['trace'][0]['tool'] == 'count_cases'


@pytest.mark.asyncio
async def test_invalid_model_tool_fails_closed(search_db):
    search_db.info['authorized_area_ids'] = (1,)
    class Model:
        async def ainvoke(self, prompt):
            return SimpleNamespace(content='{"action":"call","tool":"shell","arguments":{"command":"whoami"}}')
    result = await run_query(search_db, '任意执行', Model())
    assert result['status'] == 'failed'
    assert result['cards'] == []
    assert result['error_code'] == 'query_plan_invalid'


@pytest.mark.asyncio
async def test_step_budget_and_cancellation(search_db):
    search_db.info['authorized_area_ids'] = (1,)
    class Model:
        async def ainvoke(self, prompt):
            return SimpleNamespace(content='{"action":"call","tool":"count_cases","arguments":{}}')
    result = await run_query(search_db, '统计', Model())
    assert result['status'] == 'degraded'
    assert len(result['cards']) == len(result['trace']) == 8
    result = await run_query(search_db, '统计', Model(), cancelled=lambda: True)
    assert result['status'] == 'cancelled'
    assert result['trace'] == []


@pytest.mark.asyncio
async def test_timeout_preserves_explicit_error(search_db):
    search_db.info['authorized_area_ids'] = (1,)
    class Model:
        async def ainvoke(self, prompt):
            await asyncio.sleep(1)
    result = await run_query(search_db, '统计', Model(), timeout_seconds=0.01)
    assert result['status'] == 'degraded'
    assert result['error_code'] == 'query_timeout'


@pytest.mark.asyncio
async def test_bad_answer_cannot_become_a_result(search_db):
    search_db.info['authorized_area_ids'] = (1,)
    class Model:
        async def ainvoke(self, prompt):
            return SimpleNamespace(content='{"action":"finish","reason":"completed","answer":"已认定嫌疑人"}')
    result = await run_query(search_db, '统计', Model())
    assert result['status'] == 'failed'
    assert '已认定' not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('content', [None, 'x' * 17000,
    '{"action":"finish","reason":"insufficient_data"}',
    '{"action":"finish","reason":"completed"}'])
async def test_missing_evidence_and_malformed_response_are_not_success(search_db, content):
    search_db.info['authorized_area_ids'] = (1,)
    class Model:
        async def ainvoke(self, prompt):
            return SimpleNamespace(content=content)
    assert (await run_query(search_db, '统计', Model()))['status'] != 'completed'


@pytest.mark.asyncio
async def test_model_error_does_not_leak_internal_details(search_db):
    search_db.info['authorized_area_ids'] = (1,)
    class Model:
        async def ainvoke(self, prompt):
            raise RuntimeError('secret key and private path')
    result = await run_query(search_db, '统计', Model())
    assert result['error_code'] == 'query_unavailable'
    assert 'secret' not in str(result)


def test_model_registry_missing_disabled_and_external_fail_closed(search_db, monkeypatch):
    from app.config import settings
    from app.models.ai_model import AIModel
    monkeypatch.setattr(settings, 'AGENT_MODEL_ID', None)
    with pytest.raises(ValueError, match='query_model_not_configured'):
        create_query_model(search_db)
    monkeypatch.setattr(settings, 'AGENT_MODEL_ID', 1)
    with pytest.raises(ValueError, match='query_model_not_configured'):
        create_query_model(search_db)
    model = AIModel(id=1, name='test', provider='openai-compatible', model_name='test',
                    api_key='fixture', role='moderator', is_active=True,
                    config={'api_base': 'https://external.invalid/v1'})
    search_db.add(model)
    search_db.commit()
    with pytest.raises(ValueError, match='禁止发送外部模型'):
        create_query_model(search_db)
    model.is_active = False
    search_db.commit()
    with pytest.raises(ValueError, match='query_model_not_configured'):
        create_query_model(search_db)


@pytest.mark.asyncio
async def test_late_finish_cannot_be_marked_completed(search_db, monkeypatch):
    from app.services import intelligent_query_loop as loop
    search_db.info['authorized_area_ids'] = (1,)
    clock = [0]
    monkeypatch.setattr(loop, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    class Model:
        calls = 0
        async def ainvoke(self, prompt):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(content='{"action":"call","tool":"count_cases","arguments":{}}')
            clock[0] = 2
            return SimpleNamespace(content='{"action":"finish","reason":"completed"}')
    result = await run_query(search_db, '统计', Model(), timeout_seconds=1)
    assert result['status'] == 'degraded'
    assert result['error_code'] == 'query_timeout'
    assert len(result['cards']) == 1
