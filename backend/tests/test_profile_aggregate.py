from copy import deepcopy
from time import monotonic

import pytest

from app.services.intelligent_query_tools import AggregateProfiles, execute_tool
from app.services.intelligent_query_context import empty_conditions, inherit, remember
from app.services.profile_aggregate import build_aggregate
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_case_search_page import add_case
from tests.test_query_profiles import profile
from tests.test_query_followup import model_for, call, FINISH
from app.services import intelligent_query_tasks as query_tasks


def aggregate(db, **kwargs):
    return execute_tool(db, 'aggregate_case_profiles', kwargs)


def test_whole_corpus_and_patterns_are_independent_of_page(query_db):
    for index in range(105):
        profile(query_db, add_case(query_db, f'CASE-{index}', description='井场发现软管。携带软管。'))
    profile(query_db, add_case(query_db, 'HIDDEN', operational_area_id=2, description='保密地点发现软管'))
    first = aggregate(query_db, page_size=1)['data']
    last = aggregate(query_db, page=6, page_size=20)['data']
    assert first['total'] == last['total'] == 105
    assert first['statistics'] == last['statistics']
    assert first['coverage'] == last['coverage']
    assert first['coverage']['complete'] is True
    assert len(first['items']) == 1 and len(last['items']) == 5
    snapshot = build_aggregate(query_db, AggregateProfiles())
    hose = next(p for p in snapshot['patterns'] if p['value'] == '软管')
    assert hose['case_count'] == 105  # mentions do not inflate case counts
    assert len(hose['case_ids']) == 105
    assert not query_db.new and not query_db.dirty and not query_db.deleted


def test_and_conditions_separate_counterexamples_unknown_and_conflicts(query_db):
    for title, description in [
        ('YES', '井场发现软管。'), ('NO', '井场未发现软管。'),
        ('MAYBE', '井场可能有软管。'), ('CONFLICT', '井场发现软管。未发现软管。'),
        ('UNKNOWN', '井场发现油桶。'), ('OTHER', '河边发现软管。'),
    ]:
        profile(query_db, add_case(query_db, title, description=description))
    data = aggregate(query_db, conditions=[
        {'category': 'tool', 'value': '软管'}, {'category': 'place_condition', 'value': '井场'},
    ])['data']
    assert data['statistics']['matched'] == 1
    assert data['statistics']['unmatched'] == 3
    assert data['statistics']['unknown'] == 2
    assert data['condition_statistics'][0]['matched'] == 2
    all_patterns = build_aggregate(query_db, AggregateProfiles())['patterns']
    hose = [p for p in all_patterns if p['value'] == '软管']
    assert {p['kind']: p['case_count'] for p in hose} == {
        'stated': 2, 'negated': 1, 'uncertain': 1, 'conflicting': 1}


def test_missing_stale_and_invalid_profiles_have_separate_denominators(query_db):
    profile(query_db, add_case(query_db, 'READY', description='井场发现油桶。'))
    stale = add_case(query_db, 'STALE', description='发现软管。')
    profile(query_db, stale)
    stale.description = '未发现软管'
    invalid = profile(query_db, add_case(query_db, 'BAD', description='发现软管。'))
    payload = deepcopy(invalid.payload)
    payload['semantics']['assertions'][0]['reference']['quote'] = '虚构'
    invalid.payload = payload
    add_case(query_db, 'MISSING')
    query_db.commit()
    data = aggregate(query_db, conditions=[{'category': 'tool', 'value': '软管', 'kind': 'missing'}])
    assert data['state'] == 'partial'
    assert data['data']['statistics']['matched'] == 1
    assert data['data']['statistics']['unknown'] == 3
    assert data['data']['statistics']['unavailable_profile_ratio'] == 0.75
    assert data['data']['coverage']['profile_states'] == {'ready': 1, 'missing': 1, 'stale': 1, 'invalid': 1}
    assert all(row['denominator'] == 1 for row in data['data']['missingness'])


def test_partial_scan_and_cancellation_do_not_claim_census(query_db):
    add_case(query_db, 'EXISTS')
    query_db.commit()
    result = build_aggregate(query_db, AggregateProfiles(), deadline=monotonic() - 1)
    assert result['coverage']['authorized_cases'] == 1
    assert result['coverage']['scanned_cases'] == 0
    assert result['coverage']['complete'] is False
    assert result['statistics']['unavailable_profile_ratio'] is None
    with pytest.raises(PermissionError, match='cancelled'):
        build_aggregate(query_db, AggregateProfiles(), cancelled=lambda: True)


def test_semantic_filters_are_inherited_and_cannot_be_dropped(query_db):
    condition = {'category': 'tool', 'value': '软管', 'kind': 'negated'}
    context = remember(empty_conditions(), 'aggregate_case_profiles', {'conditions': [condition]})
    values, changes = inherit('aggregate_case_profiles', {'page': 2}, context, question='下一页')
    assert values['conditions'] == [condition] and not changes
    for tool in ('find_cases', 'count_cases', 'find_history', 'find_places', 'find_case_profiles'):
        with pytest.raises(ValueError, match='cannot_preserve'):
            inherit(tool, {}, context, question='统计这些案件')
    with pytest.raises(ValueError, match='change_basis_required'):
        inherit('aggregate_case_profiles', {'conditions': []}, context, question='继续')
    values, changes = inherit('aggregate_case_profiles', {'conditions': []}, context,
                             question='取消软管条件', change_basis='取消软管条件')
    assert values['conditions'] == [] and changes


def test_explicit_scope_and_schema_boundary(query_db):
    with pytest.raises(PermissionError):
        aggregate(query_db, operational_area_id=2)
    for args in ({'sql': 'SELECT 1'}, {'conditions': [{'category': 'sql', 'value': 'SELECT 1'}]},
                 {'conditions': [{'category': 'tool', 'kind': 'confirmed_gang'}]}):
        with pytest.raises(ValueError):
            aggregate(query_db, **args)
    query_db.info.pop('authorized_area_ids')
    with pytest.raises(PermissionError):
        aggregate(query_db)


def test_existing_model_candidates_are_grounded_but_not_counted_as_rule_facts(query_db):
    from app.services import analysis_topic_service as topics
    from app.services.case_semantic_evidence import freeze_sources, grounded_assertion, TextReference
    from app.services.topic_model_evidence import model_evidence
    case = add_case(query_db, 'MODEL', description='疑似特殊集装设施。', oil_type=None)
    row = profile(query_db, case)
    source = freeze_sources({'description': case.description})[0]
    ref = TextReference(source.field, source.sha256, 0, len(source.text), source.text)
    candidate = grounded_assertion(source, ref, category='facility', normalized_value=source.text, kind='uncertain')
    candidate['judgment_status'] = 'model_candidate'
    payload = deepcopy(row.payload)
    payload['semantics']['model_extraction'] = {'status': 'ready', 'version': 'fixture-local-extractor', 'items': [candidate]}
    row.payload = payload
    query_db.commit()
    data = build_aggregate(query_db, AggregateProfiles())
    assert data['model_extraction']['candidate_count'] == 1
    assert data['model_extraction']['profile_states'] == {'ready': 1}
    assert not any(item['value'] == source.text for item in data['patterns'])
    topic = topics.create_topic(query_db, '已有模型片段', {})
    topics.refresh_topic(query_db, topic['id'])
    evidence = topics.read_topic_evidence(query_db, topic['id'], case.id, revision=1)
    assert evidence['model_extraction']['items'][0]['reference']['quote'] == source.text
    assert 'model_candidate' in evidence['model_extraction']['items'][0]['evidence_ref']
    payload = deepcopy(row.payload)
    payload['semantics']['model_extraction']['items'][0]['reference']['quote'] = '编造片段'
    row.payload = payload
    query_db.commit()
    assert model_evidence(row, 'ready')['state'] == 'invalid'
    assert model_evidence(row, 'ready')['items'] == []
    with pytest.raises(PermissionError):
        topics.read_topic_evidence(query_db, topic['id'], case.id, revision=1)


@pytest.mark.asyncio
async def test_query_job_followup_and_export_reuse_aggregate_filters(query_db):
    profile(query_db, add_case(query_db, 'NEGATED', description='未发现软管。'))
    profile(query_db, add_case(query_db, 'STATED', description='发现软管。'))
    condition = {'category': 'tool', 'value': '软管', 'kind': 'negated'}
    parent = query_tasks.create_query(query_db, '统计否定软管的案件')
    await query_tasks.execute_query(query_db, parent['id'], model=model_for(
        call('aggregate_case_profiles', {'conditions': [condition]}), FINISH))
    child = query_tasks.create_query(query_db, '继续查看这些条件', parent['id'])
    await query_tasks.execute_query(query_db, child['id'], model=model_for(
        call('aggregate_case_profiles', {}), FINISH))
    result = query_tasks.read_query(query_db, child['id'])['result']
    assert result['cards'][0]['data']['total'] == 1
    assert result['cards'][0]['data']['coverage']['authorized_cases'] == 2
    assert result['trace'][0]['arguments']['conditions'] == [condition]
    from app.services.intelligent_query_document import export_query_document
    document, content = export_query_document(query_db, child['id'], 'docx')
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        text = archive.read('word/document.xml').decode()
    assert '全库画像条件统计' in text and 'negated' in text
    assert '不同或相反表述' in text and document.result_id == child['id']
