"""Showcase runs real services, but never receives a business database/session."""
import pytest

from app.services.showcase_execution import execute_scenario


def test_real_pipeline_returns_evidence_and_keeps_original_facts(monkeypatch):
    from app.services.case_service import CaseService

    def external_index_forbidden(*args, **kwargs):
        raise AssertionError('showcase must not index into shared vector storage')

    monkeypatch.setattr(CaseService, 'finish_created_case', external_index_forbidden)
    result = execute_scenario('normal')
    assert result['dataset_kind'] == 'synthetic'
    assert result['execution_kind'] == 'live_deterministic'
    assert result['original_facts_unchanged'] is True
    assert result['profile']['payload']
    assert 1 <= len(result['analysis']['hypotheses']) <= 3
    assert all(item['evidence_refs'] for item in result['analysis']['hypotheses'])
    assert all(item['counter_evidence'] or item['information_gaps']
               for item in result['analysis']['hypotheses'])
    assert result['brief']['evidence_refs']
    assert f"case_hypothesis:{result['analysis']['hypotheses'][0]['id']}" in result['brief']['evidence_refs']
    assert [step['service'] for step in result['trace']] == [
        'CaseTableParser', 'CaseService', 'CasePipelineService', 'CaseInsightService', 'DeploymentAdvisorService']
    assert result['import']['rows'] == 1
    assert result['import']['field_mapping']['案发时间'] == 'occurred_time'
    assert result['import']['sha256']
    assert '案情描述' in result['import']['csv']


def test_insufficient_coordinates_does_not_invent_candidates():
    result = execute_scenario('missing_location')
    assert result['analysis']['hypotheses'] == []
    assert result['analysis']['information_gaps']
    assert result['original_facts_unchanged'] is True
    assert result['trace'][3]['result_status'] == 'degraded'


def test_fault_injection_exercises_actual_model_fallback():
    result = execute_scenario('model_unavailable')
    assert result['fault']['kind'] == 'injected_model_timeout'
    assert result['fault']['calls'] == 1
    assert result['fault']['status'] == 'degraded'
    assert result['fault']['fallback_mode'] == 'deterministic_fallback'
    assert result['analysis']['hypotheses']
    assert result['trace'][-1]['result_status'] == 'degraded'


def test_each_execution_is_isolated_and_input_is_whitelisted():
    first = execute_scenario('normal')
    second = execute_scenario('normal')
    assert first['input_digest'] == second['input_digest']
    assert first['case']['id'] == second['case']['id'] == 1
    assert first['analysis']['id'] != second['analysis']['id']
    with pytest.raises(ValueError, match='unsupported_showcase_scenario'):
        execute_scenario('production-case:1')
