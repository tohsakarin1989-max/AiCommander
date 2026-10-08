"""Source-bound two-sided comparisons; synthetic cases, no external models."""
from copy import deepcopy
from uuid import uuid4

import pytest

from app.models.case_pipeline import CaseAnalysisProfile
from app.services.case_history_retrieval import CaseHistoryRetrieval, source_values
from app.services.case_history_fragments import process_comparison_input
from app.services.case_history_process_comparison import compare_processes
from app.services.case_semantic_service import build_semantic_profile, TEXT_FIELDS, SEMANTIC_RULE_VERSION
from app.services.case_source_service import CaseSourceService
from app.services.intelligent_query_history import validate_history_query_evidence
from tests.test_case_history_index import db, make_case  # noqa: F401
from tests.history_index_helpers import build_history_index


def recorded(db, number, text):
    case = make_case(db, number)
    case.description, case.location = text, None
    revision, _ = CaseSourceService.capture_change(db, case)
    semantics = build_semantic_profile({key: value for key, value in source_values(case).items() if key in TEXT_FIELDS},
        source_revision_id=revision.id, source_hash=revision.source_hash, source_payload=revision.payload)
    db.add(CaseAnalysisProfile(id=str(uuid4()), case_id=case.id, profile_version=1,
        source_hash=revision.source_hash, source_revision_id=revision.id, schema_version='6.3.0',
        dictionary_version=SEMANTIC_RULE_VERSION, payload={'semantics': semantics},
        analysis_readiness='partial', is_current=True))
    db.commit()
    return case


def prepared(db):
    current = recorded(db, 'CURRENT', '抽取原油。随后转运。可能储存原油。未销售原油。')
    old = recorded(db, 'HISTORY', '抽油原油。未转运。储存柴油。未销售原油。装油柴油。')
    build_history_index(db)
    db.info['authorized_area_ids'] = (1,)
    return current, old


def test_both_source_spans_canonical_actions_and_polarities_are_separate(db, monkeypatch):
    current, old = prepared(db)
    def no_extract(_values):
        raise AssertionError('existing profiles must not be re-extracted')
    monkeypatch.setattr('app.services.case_history_retrieval.build_semantic_profile', no_extract)
    result = CaseHistoryRetrieval.search(db, source_case_id=current.id)
    comparison = result['items'][0]['process_comparison']
    assert comparison['current']['case_id'] == current.id and comparison['historical']['case_id'] == old.id
    assert {(pair['action'], pair['relation']) for pair in comparison['pairs']} >= {
        ('抽取', 'stated_match'), ('转运', 'counter'), ('储存', 'uncertain'), ('销售', 'negated_match')}
    storage = next(pair for pair in comparison['pairs'] if pair['action'] == '储存')
    assert ['oil', '柴油', 'stated'] in storage['historical_only_conditions']
    assert all(pair['action'] != '装载' for pair in comparison['pairs'])
    assert any(row['actions'][0]['value'] == '装载' for row in comparison['unmatched_historical'])
    for pair in comparison['pairs']:
        for label, case in [('current', current), ('historical', old)]:
            side = pair[label]
            for key in ('reference', 'action_reference'):
                reference = side[key]
                assert reference['source_revision_id'] == comparison[label]['source_revision_id']
                assert getattr(case, reference['field'])[reference['start']:reference['end']] == reference['quote']
    validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': result}]})


@pytest.mark.parametrize('tamper', [
    lambda comparison: comparison['pairs'][0]['current']['reference'].update(start=900),
    lambda comparison: comparison['pairs'][0].update(relation='counter'),
    lambda comparison: comparison['current'].update(source_revision_id=900),
    lambda comparison: comparison['current'].update(case_id=900),
])
def test_frozen_two_sided_evidence_cannot_be_rebound_or_promoted(db, tamper):
    current, _ = prepared(db)
    result = CaseHistoryRetrieval.search(db, source_case_id=current.id)
    forged = deepcopy(result)
    tamper(forged['items'][0]['process_comparison'])
    with pytest.raises(PermissionError, match='evidence_changed'):
        validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': forged}]})
    # Historical results lacking this additive field remain readable as old evidence.
    del result['items'][0]['process_comparison']
    validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': result}]})


def test_source_scope_or_revision_changes_invalidates_both_sides(db):
    current, old = prepared(db)
    result = CaseHistoryRetrieval.search(db, source_case_id=current.id)
    old.operational_area_id = 2
    db.commit()
    with pytest.raises(PermissionError):
        validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': result}]})
    old.operational_area_id = 1
    current.description += '新增原文。'
    CaseSourceService.capture_change(db, current)
    db.commit()
    with pytest.raises(PermissionError):
        validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': result}]})


def test_no_current_process_returns_unknown_without_invented_pairs(db):
    old = recorded(db, 'HISTORY', '抽取原油。')
    current = make_case(db, 'NO-PROCESS')
    CaseSourceService.capture_change(db, current)
    db.commit()
    db.info['authorized_area_ids'] = (1,)
    value = compare_processes(process_comparison_input(db, current), process_comparison_input(db, old))
    assert value['state'] == 'unavailable' and value['pairs'] == []
    assert not value['coverage']['complete']


def test_pair_budget_reports_omissions_without_invented_completeness(db):
    current = recorded(db, 'CURRENT', '抽取原油。' * 6)
    old = recorded(db, 'HISTORY', '抽取原油。' * 6)
    value = compare_processes(process_comparison_input(db, current), process_comparison_input(db, old))
    assert len(value['pairs']) == 24 and value['coverage']['omitted_pairs'] == 12
    assert value['state'] == 'partial' and not value['coverage']['complete']
