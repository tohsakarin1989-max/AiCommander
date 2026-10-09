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


def test_scoped_map_exception_does_not_unlock_originals_or_roads():
    from app.security import SCOPED_MAP_MAINTENANCE
    assert SCOPED_MAP_MAINTENANCE.fullmatch('/api/map-sources/1/jobs')
    assert SCOPED_MAP_MAINTENANCE.fullmatch('/api/map-ingest-runs/abc/control')
    for path in ('/api/map-ingest-runs/abc/original', '/api/map-sources/1/roads/ingest',
                 '/api/map-snapshots/1/publish', '/api/auth/users', '/api/operational-areas'):
        assert not SCOPED_MAP_MAINTENANCE.fullmatch(path)
