"""关闭可选智能能力只取消空查询轮询，不停日常派生任务或历史清理。"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import settings
from app.models.agent_run import AgentApproval, AgentArtifact, AgentRun
from app.services.intelligent_query_worker import process_next
from app.tasks import agent_tasks, intelligent_query_tasks
from app.tasks.celery_app import build_beat_schedule, celery_app
from tests.test_agent_lab_runtime import agent_db  # noqa: F401


@pytest.mark.parametrize(('enabled', 'mode', 'scheduled'), [
    (False, 'off', False), (True, 'off', False),
    (True, 'shadow', True), (True, 'assist', True),
    # Config validation rejects these combinations; scheduling remains fail closed.
    (False, 'shadow', False), (False, 'assist', False),
])
def test_optional_query_schedule_preserves_all_other_tasks(enabled, mode, scheduled):
    config = SimpleNamespace(ENABLE_AGENT_LAB=enabled, AGENT_MODE=mode, AGENT_REDIS_QUEUE='isolated-agents')
    actual = build_beat_schedule(config)
    expected = build_beat_schedule(SimpleNamespace(
        ENABLE_AGENT_LAB=True, AGENT_MODE='shadow', AGENT_REDIS_QUEUE='isolated-agents'))
    query = expected.pop('process-intelligent-query')
    assert ('process-intelligent-query' in actual) is scheduled
    if scheduled:
        assert actual.pop('process-intelligent-query') == query
        assert query['schedule'] == 5.0
        assert query['options'] == {'queue': 'isolated-agents', 'expires': 5}
    assert actual == expected
    assert len(actual) == 15
    assert actual['expire-agent-approvals']['task'] == agent_tasks.expire_agent_approvals_task.name
    assert actual['expire-agent-approvals']['options']['queue'] == 'isolated-agents'
    assert actual['process-analysis-topic']['task'] == 'aicommander.topics.process_next'
    assert actual['process-case-pipeline']['task'] == 'aicommander.case_pipeline.process_pending'


def test_query_task_registration_and_queue_route_survive_disabled_schedule():
    assert intelligent_query_tasks.process_query.name in celery_app.tasks
    route = celery_app.amqp.router.route(
        intelligent_query_tasks.process_query._get_exec_options(),
        intelligent_query_tasks.process_query.name, (), {})
    assert route['queue'].name == settings.AGENT_REDIS_QUEUE
    assert 'app.tasks.intelligent_query_tasks' in celery_app.conf.include
    assert 'app.tasks.agent_tasks' in celery_app.conf.include


@pytest.mark.asyncio
async def test_disabling_does_not_delete_pending_query_or_mutate_running_query(agent_db, monkeypatch):
    monkeypatch.setattr(settings, 'ENABLE_AGENT_LAB', False)
    monkeypatch.setattr(settings, 'AGENT_MODE', 'off')
    for status in ('queued', 'running'):
        agent_db.add(AgentRun(id=f'historical-{status}', task_type='intelligent_query', query='合成测试',
            status=status, data_version='fixture', started_at=datetime.utcnow() - timedelta(minutes=3)))
    agent_db.commit()
    assert await process_next(agent_db) is None
    assert {row.id: row.status for row in agent_db.query(AgentRun)} == {
        'historical-queued': 'queued', 'historical-running': 'running'}


def test_approval_expiry_task_still_processes_history_with_agent_disabled(agent_db, monkeypatch):
    monkeypatch.setattr(settings, 'ENABLE_AGENT_LAB', False)
    monkeypatch.setattr(settings, 'AGENT_MODE', 'off')
    run = AgentRun(id='historical-approval', task_type='map_data_quality', query='合成测试',
                   status='waiting_approval', data_version='fixture', mode='assist')
    artifact = AgentArtifact(id='historical-artifact', run_id=run.id, artifact_type='candidate_patch',
                             source_signature='fixture')
    agent_db.add(run)
    agent_db.flush()
    agent_db.add(artifact)
    agent_db.flush()
    approval = AgentApproval(id='expired-approval', run_id=run.id, artifact_id=artifact.id,
        action_type='asset_patch', target_type='jurisdiction_asset', target_id=999,
        candidate_patch={'name': '不可执行'}, source_signature='fixture', status='pending',
        idempotency_key='fixture-expiry', expires_at=datetime.utcnow() - timedelta(seconds=1))
    agent_db.add(approval)
    agent_db.commit()
    monkeypatch.setattr(agent_tasks, 'SessionLocal', lambda: agent_db)

    assert agent_tasks.expire_agent_approvals_task.run() == 1
    expired = agent_db.get(AgentApproval, 'expired-approval')
    assert expired.status == 'expired'
    assert expired.execution_result == {'applied': False, 'reason': 'approval_expired'}
    assert agent_db.get(AgentRun, 'historical-approval').status == 'expired'
    assert agent_tasks.expire_agent_approvals_task.run() == 0
