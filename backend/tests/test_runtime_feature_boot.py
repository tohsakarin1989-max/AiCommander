"""Verify startup configuration without inheriting .env or pytest's global fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(('legacy', 'agent', 'mode', 'query_scheduled'), [
    (None, 'false', 'off', False), ('false', 'true', 'off', False),
    ('true', 'true', 'shadow', True), ('false', 'true', 'assist', True),
])
def test_fresh_process_registers_only_explicit_optional_routes_and_schedules(
        tmp_path, legacy, agent, mode, query_scheduled):
    environment = {
        'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
        'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
        'SECRET_KEY': 'synthetic-runtime-boot-only', 'DATABASE_URL': 'sqlite://',
        'ENVIRONMENT': 'test', 'AUTO_CREATE_TABLES': 'false', 'AUTH_REQUIRED': 'false',
        'ENABLE_VECTOR_DB': 'false', 'ENABLE_AGENT_LAB': agent, 'AGENT_MODE': mode,
    }
    if legacy is not None:
        environment['ENABLE_LEGACY_OPERATIONS_MODULES'] = 'false'
        environment['AIC_TEST_FORCE_LEGACY'] = legacy
    result = subprocess.run([sys.executable, '-c', '''
import json
import os
from app.config import settings
settings.ENABLE_LEGACY_OPERATIONS_MODULES = os.environ.get('AIC_TEST_FORCE_LEGACY') == 'true'
from app.main import app
from app.database import Base
from app.tasks.celery_app import celery_app
from app.tasks.intelligent_query_tasks import process_query
paths = app.openapi()['paths']
print(json.dumps({
    'legacy': settings.ENABLE_LEGACY_OPERATIONS_MODULES,
    'legacy_routes': [any(path.startswith(prefix) for path in paths)
                      for prefix in ('/api/patrols', '/api/personnel', '/api/key-locations', '/api/gangs')],
    'core_routes': all(path in paths for path in ('/api/cases/', '/api/analysis-topics', '/api/events/')),
    'tables': sorted(Base.metadata.tables),
    'query_scheduled': 'process-intelligent-query' in celery_app.conf.beat_schedule,
    'query_registered': process_query.name in celery_app.tasks,
    'approval_scheduled': 'expire-agent-approvals' in celery_app.conf.beat_schedule,
}))
'''], cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30, check=True)
    payload = json.loads(result.stdout)
    expected_legacy = legacy == 'true'
    assert payload['legacy'] is expected_legacy
    assert payload['legacy_routes'] == [False] * 4
    assert payload['core_routes'] is True
    assert 'patrol_records' in payload['tables']
    assert 'security_personnel' in payload['tables']
    assert 'key_locations' in payload['tables']
    assert payload['query_scheduled'] is query_scheduled
    assert payload['query_registered'] is True
    assert payload['approval_scheduled'] is True
