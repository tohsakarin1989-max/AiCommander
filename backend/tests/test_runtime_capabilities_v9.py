from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.api import runtime


def request(role='admin'):
    return SimpleNamespace(state=SimpleNamespace(principal=SimpleNamespace(role=role, user_id=1)))


def test_capabilities_do_not_call_model_or_promote_configuration(db_session, monkeypatch):
    monkeypatch.setattr(runtime, '_redis_status', lambda: 'ok')
    result = runtime.runtime_capabilities(request(), db_session)
    items = {row['key']: row for row in result['capabilities']}
    assert items['model_queries']['state'] == 'disabled'
    assert 'Worker' in items['background']['basis']
    assert result['model_probes_performed'] is False
    assert result['queue_connection_probed'] is True
    assert result['live_business_verified'] is False
    assert not db_session.new and not db_session.dirty
    assert 'api_key' not in str(result) and '127.0.0.1' not in str(result)


def test_capabilities_are_admin_only(db_session):
    with pytest.raises(HTTPException) as exc:
        runtime.runtime_capabilities(request('analyst'), db_session)
    assert exc.value.status_code == 403


@pytest.mark.parametrize('provider', ['openai-compatible', 'OpenAI-Compatible', ' OPENAI-COMPATIBLE '])
def test_model_capability_uses_same_provider_normalization_as_execution(db_session, monkeypatch, provider):
    from app.ai.model_factory import ModelFactory
    from app.models.ai_model import AIModel
    model = AIModel(name='capability-fixture', provider=provider, model_name='synthetic-only',
        api_key='', role='analyst', config={'api_base': 'http://127.0.0.1:9999/v1'})
    db_session.add(model)
    db_session.commit()
    monkeypatch.setattr(runtime.settings, 'AGENT_MODEL_ID', model.id)
    monkeypatch.setattr(runtime.settings, 'TRUSTED_LOCAL_MODEL_HOSTS', '127.0.0.1')
    monkeypatch.setattr(runtime, '_redis_status', lambda: 'ok')
    # Capabilities are observations, not a model probe or live acceptance.
    sentinel = object()
    calls = []
    def create(_):
        calls.append('created')
        return sentinel
    monkeypatch.setattr('app.ai.model_factory.LLMProvider.create_openai_like_llm', create)
    result = runtime.runtime_capabilities(request(), db_session)
    items = {row['key']: row for row in result['capabilities']}
    assert items['model_queries']['state'] == 'configured_unverified'
    assert not calls and result['model_probes_performed'] is False
    assert ModelFactory().create_llm(model, data_classification='raw') is sentinel
    assert calls == ['created']


@pytest.mark.parametrize('provider,endpoint', [('OpenAI-Compatible', 'https://external.invalid/v1'),
                                             ('unsupported', 'http://127.0.0.1:9999/v1')])
def test_provider_normalization_does_not_expand_endpoint_or_protocol_trust(db_session, monkeypatch, provider, endpoint):
    from app.ai.model_factory import ModelFactory
    from app.models.ai_model import AIModel
    model = AIModel(name='untrusted-fixture', provider=provider, model_name='synthetic-only',
        api_key='', role='analyst', config={'api_base': endpoint})
    db_session.add(model)
    db_session.commit()
    monkeypatch.setattr(runtime.settings, 'AGENT_MODEL_ID', model.id)
    monkeypatch.setattr(runtime.settings, 'TRUSTED_LOCAL_MODEL_HOSTS', '127.0.0.1')
    monkeypatch.setattr(runtime, '_redis_status', lambda: 'ok')
    result = runtime.runtime_capabilities(request(), db_session)
    assert next(row for row in result['capabilities'] if row['key'] == 'model_queries')['state'] == 'disabled'
    with pytest.raises(ValueError, match='原始案件'):
        ModelFactory().create_llm(model, data_classification='raw')


def test_scoped_map_exception_does_not_unlock_originals_or_roads():
    from app.security import SCOPED_MAP_MAINTENANCE
    assert SCOPED_MAP_MAINTENANCE.fullmatch('/api/map-sources/1/jobs')
    assert SCOPED_MAP_MAINTENANCE.fullmatch('/api/map-ingest-runs/abc/control')
    for path in ('/api/map-ingest-runs/abc/original', '/api/map-sources/1/roads/ingest',
                 '/api/map-snapshots/1/publish', '/api/auth/users', '/api/operational-areas'):
        assert not SCOPED_MAP_MAINTENANCE.fullmatch(path)
