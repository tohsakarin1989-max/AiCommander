from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.runtime_capabilities import query_creation_enabled
from app.tasks.celery_app import build_beat_schedule
from tests.test_intelligent_query_api import client_for
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from app.models.agent_run import AgentRun, AgentEvent
from app.services.intelligent_query_worker import expire_abandoned_queries
from datetime import datetime, timedelta, timezone


@pytest.mark.parametrize('flag,lab,mode,expected', [
    (None, False, 'off', False), (None, True, 'shadow', True),
    (False, True, 'assist', False), (True, False, 'off', True),
])
def test_query_capability_does_not_require_lab(flag, lab, mode, expected):
    config = SimpleNamespace(ENABLE_INTELLIGENT_QUERY=flag, ENABLE_AGENT_LAB=lab,
                             AGENT_MODE=mode, AGENT_REDIS_QUEUE='agent_lab')
    assert query_creation_enabled(config) is expected
    assert ('process-intelligent-query' in build_beat_schedule(config)) is expected


def test_query_history_and_cancel_survive_switch_off(query_db, monkeypatch):
    monkeypatch.setattr(settings, 'ENABLE_INTELLIGENT_QUERY', True)
    monkeypatch.setattr(settings, 'ENABLE_AGENT_LAB', False)
    monkeypatch.setattr(settings, 'AGENT_MODE', 'off')
    with client_for(query_db) as client:
        result = client.post('/api/intelligent-queries', json={'query': '统计'})
        assert result.status_code == 201
        url = result.headers['location']
        monkeypatch.setattr(settings, 'ENABLE_INTELLIGENT_QUERY', False)
        assert client.post('/api/intelligent-queries', json={'query': '新查询'}).status_code == 404
        assert client.get(url).status_code == 200
        assert client.post(url + '/cancel').json()['status'] == 'cancelled'
    with client_for(query_db, uid=2) as other:
        assert other.get(url).status_code == 404
        assert other.post(url + '/cancel').status_code == 404


def test_cleanup_is_idempotent_when_new_queries_disabled(query_db, monkeypatch):
    monkeypatch.setattr(settings, 'ENABLE_INTELLIGENT_QUERY', False)
    old = datetime.now(timezone.utc) - timedelta(days=2)
    query_db.add_all([AgentRun(id='stuck', created_by=1, task_type='intelligent_query', query='合成',
        status='running', data_version='test', started_at=old),
        AgentRun(id='queued-old', created_by=1, task_type='intelligent_query', query='合成',
        status='queued', data_version='test', created_at=old)])
    query_db.commit()
    assert expire_abandoned_queries(query_db) == 2
    assert expire_abandoned_queries(query_db) == 0
    assert query_db.query(AgentEvent).filter_by(event_type='query_expired').count() == 2
    assert 'expire-intelligent-queries' in build_beat_schedule(settings)


def test_runtime_declares_current_code_without_registering_legacy_evaluation(monkeypatch):
    from app.services.governance_service import GovernanceService, ALGORITHMS
    from app.services.case_pipeline_service import CASE_PROFILE_SCHEMA_VERSION
    from app.services.case_insight_service import CASE_INSIGHT_ALGORITHM_VERSION
    from app.services.case_result_composition import COMPOSITION_SCHEMA_VERSION

    def forbidden(*args, **kwargs):
        raise AssertionError("GET must not register evaluation versions")

    monkeypatch.setattr(GovernanceService, 'ensure_versions', forbidden)
    versions = {item['component']: item['version']
                for item in GovernanceService.declared_versions()['algorithms']}
    assert versions['case-profile'] == CASE_PROFILE_SCHEMA_VERSION
    assert versions['dual-domain'] == CASE_INSIGHT_ALGORITHM_VERSION
    assert versions['case-result-composition'] == COMPOSITION_SCHEMA_VERSION
    assert ALGORITHMS['dual-domain'][0] == 'dual-domain-3.4.0'
