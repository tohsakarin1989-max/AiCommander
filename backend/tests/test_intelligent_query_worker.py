from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.config import settings
from app.models.agent_run import AgentRun
from app.models.user import User
from app.services.intelligent_query_tasks import create_query, read_query
from app.services.intelligent_query_worker import process_next
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, 'ENABLE_AGENT_LAB', True)
    monkeypatch.setattr(settings, 'AGENT_MODE', 'shadow')


@pytest.mark.asyncio
async def test_queued_database_job_runs_without_submission_dispatch(query_db, monkeypatch):
    from app.services import intelligent_query_loop
    run = create_query(query_db, '统计')
    steps = iter(['{"action":"call","tool":"count_cases","arguments":{}}',
                  '{"action":"finish","reason":"completed"}'])
    class Model:
        async def ainvoke(self, prompt):
            return SimpleNamespace(content=next(steps))
    monkeypatch.setattr(intelligent_query_loop, 'create_query_model', lambda db: Model())
    query_db.info.clear()
    assert (await process_next(query_db))['status'] == 'completed'
    assert read_query(query_db, run['id'])['result']['cards'][0]['data']['count'] == 0
    assert await process_next(query_db) is None


@pytest.mark.asyncio
async def test_disabled_worker_leaves_job_queued(query_db, monkeypatch):
    run = create_query(query_db, '统计')
    monkeypatch.setattr(settings, 'AGENT_MODE', 'off')
    assert await process_next(query_db) is None
    assert query_db.get(AgentRun, run['id']).status == 'queued'


@pytest.mark.asyncio
async def test_disabled_owner_job_is_cancelled(query_db):
    run = create_query(query_db, '统计')
    query_db.get(User, 1).is_active = False
    query_db.commit()
    assert (await process_next(query_db))['status'] == 'cancelled'
    assert query_db.get(AgentRun, run['id']).result_summary == {}


@pytest.mark.asyncio
async def test_abandoned_running_job_expires_after_worker_restart(query_db):
    run = create_query(query_db, '统计')
    row = query_db.get(AgentRun, run['id'])
    row.status = 'running'
    row.started_at = datetime.now(timezone.utc) - timedelta(minutes=3)
    query_db.commit()
    assert (await process_next(query_db))['status'] == 'expired'
