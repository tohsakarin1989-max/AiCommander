"""The query tool boundary is read-only, scoped and independent of a model."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.jurisdiction import JurisdictionAsset
from app.services.intelligent_query_tools import execute_tool, tool_catalog
from tests.test_case_search_page import search_db, add_case  # noqa: F401


def test_catalog_has_only_registered_read_tools():
    assert set(tool_catalog()) == {'find_cases', 'find_places', 'count_cases',
                                   'compare_periods', 'summarize_results', 'find_road_results', 'find_case_profiles', 'find_history'}


@pytest.mark.parametrize('tool,args', [
    ('sql', {'query': 'select * from cases'}),
    ('find_cases', {'sql': 'select * from cases'}),
    ('find_cases', {'page_size': 10000}),
    ('find_places', {'keyword': '井', 'url': 'https://example.org'}),
    ('compare_periods', {'start': '2026-09-10T00:00:00Z', 'end': '2026-09-01T00:00:00Z'}),
    ('compare_periods', {'start': '2026-09-01', 'end': '2026-09-10'}),
    ('compare_periods', {'start': '0001-01-01T00:00:00Z', 'end': '0001-01-02T00:00:00Z'}),
    ('find_cases', {'start_date': '0001-01-01T00:00:00+08:00'}),
    ('summarize_results', {'completed_before': '9999-12-31T23:00:00-08:00'}),
])
def test_unknown_tools_and_unsafe_or_invalid_arguments_rejected(search_db, tool, args):
    search_db.info['authorized_area_ids'] = (1,)
    with pytest.raises((ValueError, ValidationError)):
        execute_tool(search_db, tool, args)


def test_requires_explicit_scope_and_denies_requested_other_area(search_db):
    with pytest.raises(PermissionError):
        execute_tool(search_db, 'count_cases', {})
    search_db.info['authorized_area_ids'] = (1,)
    with pytest.raises(PermissionError):
        execute_tool(search_db, 'count_cases', {'operational_area_id': 2})


def test_full_authorized_search_and_count_are_consistent(search_db):
    for index in range(110):
        add_case(search_db, f'C-{index}')
    add_case(search_db, 'PRIVATE', operational_area_id=2)
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    found = execute_tool(search_db, 'find_cases', {'page': 6, 'page_size': 20})
    count = execute_tool(search_db, 'count_cases', {})
    assert found['data']['total'] == count['data']['count'] == 110
    assert len(found['data']['items']) == 10
    assert 'PRIVATE' not in str(found)
    assert found['evidence']['source'] == 'cases'
    assert count['evidence']['scope'] == [1]
    assert not search_db.new and not search_db.dirty and not search_db.deleted


def test_equal_length_comparison_uses_occurrence_half_open_windows(search_db):
    for label, date in [('previous', 1), ('current', 8), ('end', 15)]:
        add_case(search_db, label, occurred_time=datetime(2026, 9, date))
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    result = execute_tool(search_db, 'compare_periods', {
        'start': '2026-09-08T00:00:00Z', 'end': '2026-09-15T00:00:00Z'})
    assert result['data']['current_count'] == result['data']['previous_count'] == 1
    assert result['data']['change'] == 0


def test_facility_search_scoped_and_literal(search_db):
    search_db.add_all([
        JurisdictionAsset(name='油井%一', asset_type='well', operational_area_id=1),
        JurisdictionAsset(name='油井二', asset_type='well', operational_area_id=1),
        JurisdictionAsset(name='秘密井%', asset_type='well', operational_area_id=2)])
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    result = execute_tool(search_db, 'find_places', {'keyword': '%'})
    assert [r['name'] for r in result['data']['items']] == ['油井%一']


def test_no_results_is_explicit_not_generated_conclusion(search_db):
    search_db.info['authorized_area_ids'] = ()
    result = execute_tool(search_db, 'summarize_results', {})
    assert result['data']['total'] == 0
    assert result['state'] == 'empty'
    assert result['information_gaps']


def test_public_index_failure_is_not_empty_result(search_db, monkeypatch):
    from app.services import intelligent_query_tools as tools
    search_db.info['authorized_area_ids'] = (1,)
    def unavailable(*args, **kwargs):
        raise ValueError('private filesystem diagnostics')
    monkeypatch.setattr(tools, 'search_places', unavailable)
    result = execute_tool(search_db, 'find_places', {'keyword': '大庆', 'include_public_places': True})
    assert result['state'] == 'partial'
    assert result['data']['public_places']['state'] == 'unavailable'
    assert 'filesystem' not in str(result)


def test_public_index_uses_current_authorized_snapshot(search_db, monkeypatch):
    from app.services import intelligent_query_tools as tools
    search_db.info['authorized_area_ids'] = (1,)
    def public(db, snapshot, keyword, **kwargs):
        assert snapshot == 'current' and keyword == '大庆'
        assert kwargs == {'limit': 20, 'area_id': 1}
        return {'items': [{'name': '大庆'}], 'snapshot_id': 'verified-snapshot'}
    monkeypatch.setattr(tools, 'search_places', public)
    result = execute_tool(search_db, 'find_places', {
        'keyword': '大庆', 'include_public_places': True, 'operational_area_id': 1})
    assert result['state'] == 'ready'


def test_result_counts_follow_current_scope_and_completed_time(search_db):
    from app.models.case_insight import CaseAnalysisRun
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.models.map_foundation import MapSnapshot, PublicMapBundle
    bundle = PublicMapBundle(bundle_id='query-fixture', provider='test', source_version='1',
        license_record='test', bounds=[], manifest={}, package_hash='b' * 64)
    search_db.add(bundle)
    search_db.flush()
    for area in (1, 2):
        case = add_case(search_db, f'CASE-{area}', operational_area_id=area)
        snapshot = MapSnapshot(id=f's-{area}', version=f's-{area}', operational_area_id=area,
            public_bundle_id=bundle.id, manifest={}, feature_watermark='1')
        profile = CaseAnalysisProfile(id=f'p-{area}', case_id=case.id, profile_version=1,
            source_hash='a' * 64, schema_version='1', dictionary_version='1', payload={},
            quality_score=50, analysis_readiness='ready')
        search_db.add_all([snapshot, profile])
        search_db.flush()
        for index, status in enumerate(('completed', 'degraded', 'failed')):
            search_db.add(CaseAnalysisRun(id=f'r-{area}-{index}', case_id=case.id,
                case_profile_id=profile.id, map_snapshot_id=snapshot.id, algorithm_version=str(index),
                status=status, information_gaps=[], completed_at=datetime(2026, 9, 10, 0, 30, tzinfo=timezone.utc)))
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    args = {'completed_after': '2026-09-10T08:00:00+08:00',
            'completed_before': '2026-09-10T09:00:00+08:00', 'operational_area_id': 1}
    result = execute_tool(search_db, 'summarize_results', args)
    assert result['data']['total'] == 2
    assert result['data']['by_status'] == {'completed': 1, 'degraded': 1}
    assert all(r['map_snapshot_id'] == 's-1' for r in result['data']['items'])
    search_db.info['authorized_area_ids'] = ()
    assert execute_tool(search_db, 'summarize_results', {})['data']['total'] == 0


def insight_fixture(db):
    from app.models.case_insight import CaseAnalysisRun, CaseHypothesis
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.models.map_foundation import MapSnapshot, PublicMapBundle
    case = add_case(db, 'VISIBLE')
    hidden = add_case(db, 'HIDDEN', operational_area_id=2)
    bundle = PublicMapBundle(bundle_id='content-fixture', provider='test', source_version='1',
        license_record='test', bounds=[], manifest={}, package_hash='c' * 64)
    db.add(bundle)
    db.flush()
    snapshot = MapSnapshot(id='content-map', version='content-map', operational_area_id=1,
        public_bundle_id=bundle.id, manifest={}, feature_watermark='1')
    profile = CaseAnalysisProfile(id='content-profile', case_id=case.id, profile_version=1,
        source_hash='a' * 64, schema_version='1', dictionary_version='1', payload={},
        quality_score=50, analysis_readiness='ready')
    db.add_all([snapshot, profile])
    db.flush()
    run = CaseAnalysisRun(id='content-run', case_id=case.id, case_profile_id=profile.id,
        map_snapshot_id=snapshot.id, algorithm_version='1', status='completed',
        summary='已有候选摘要', information_gaps=['缺少现场核验'],
        completed_at=datetime(2026, 9, 10))
    db.add(run)
    db.flush()
    candidate = CaseHypothesis(id='content-candidate', analysis_run_id=run.id, case_id=case.id,
        hypothesis_type='activity', rank=1, title='活动区域候选', claim='需核查区域关联',
        score=60, confidence=.8, evidence_refs=[f'case_profile:{profile.id}', f'case:{case.id}'],
        supporting_evidence=['已有同类案件'], counter_evidence=['可能只是生产设施集中'],
        information_gaps=['缺少现场核验'], score_components={}, status='candidate',
        boundary='不是正式事实')
    db.add(candidate)
    db.commit()
    return run, candidate, hidden, snapshot


def test_summary_contains_existing_content_and_evidence_not_just_metadata(search_db):
    run, candidate, _, _ = insight_fixture(search_db)
    search_db.info['authorized_area_ids'] = (1,)
    result = execute_tool(search_db, 'summarize_results', {})
    item = result['data']['items'][0]
    assert item['summary'] == run.summary
    assert item['content_state'] == 'ready'
    assert item['hypotheses'][0]['claim'] == candidate.claim
    assert item['hypotheses'][0]['supporting_evidence'] == candidate.supporting_evidence
    assert item['hypotheses'][0]['counter_evidence'] == candidate.counter_evidence
    assert item['hypotheses'][0]['rule_support'] == 60
    assert 'confidence' not in item['hypotheses'][0]
    assert not search_db.new and not search_db.dirty and not search_db.deleted


@pytest.mark.parametrize('invalid_ref', ['hidden_case', 'unknown:1', 'case:999999', 'case_profile:missing'])
def test_summary_withholds_unverifiable_candidate_and_derived_summary(search_db, invalid_ref):
    run, candidate, hidden, _ = insight_fixture(search_db)
    candidate.evidence_refs = [f'case:{hidden.id}' if invalid_ref == 'hidden_case' else invalid_ref]
    run.summary = candidate.claim = '不可泄漏正文'
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    result = execute_tool(search_db, 'summarize_results', {})
    item = result['data']['items'][0]
    assert item['hypotheses'] == [] and item['summary'] is None
    assert item['content_state'] == 'partial'
    assert '不可泄漏正文' not in str(result)


def test_summary_rechecks_map_scope_even_when_snapshot_is_identity_cached(search_db):
    _, _, _, snapshot = insight_fixture(search_db)
    snapshot.operational_area_id = 2
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    result = execute_tool(search_db, 'summarize_results', {})
    item = result['data']['items'][0]
    assert item['hypotheses'] == [] and item['summary'] is None
    assert item['content_state'] == 'unavailable'


@pytest.mark.parametrize('changed_scope', ['none', 'asset', 'feature', 'wrong_snapshot'])
def test_summary_map_evidence_requires_live_and_frozen_current_scope(search_db, changed_scope):
    from app.models.map_foundation import MapSnapshotFeature
    _, candidate, _, snapshot = insight_fixture(search_db)
    asset = JurisdictionAsset(name='冻结设施', asset_type='well', operational_area_id=1)
    search_db.add(asset)
    search_db.flush()
    feature = MapSnapshotFeature(snapshot_id=snapshot.id, asset_id=asset.id,
        operational_area_id=1, name='冻结设施', asset_type='well', geometry_type='Point',
        status='active', verified=True)
    search_db.add(feature)
    candidate.evidence_refs = [f'map_asset:{asset.id}@snapshot:{snapshot.id}']
    if changed_scope == 'asset':
        asset.operational_area_id = 2
    if changed_scope == 'feature':
        feature.operational_area_id = 2
    if changed_scope == 'wrong_snapshot':
        candidate.evidence_refs = [f'map_asset:{asset.id}@snapshot:wrong-map']
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    item = execute_tool(search_db, 'summarize_results', {})['data']['items'][0]
    assert bool(item['hypotheses']) == (changed_scope == 'none')
    assert (item['summary'] is not None) == (changed_scope == 'none')
