"""R08: persisted evidence, independent recall, current scope and honest gaps."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from app.models.case import Case
from app.models.case_history_index import CaseHistoryFragment, CaseHistoryIndex, CaseHistoryPosting
from app.models.knowledge_asset import KnowledgeAsset
from app.services.case_history_retrieval import CaseHistoryRetrieval
from app.services.case_source_service import CaseSourceService
from app.services.intelligent_query_history import validate_history_query_evidence
from app.services.intelligent_query_tools import execute_tool
from tests.history_index_helpers import build_history_index
from tests.test_case_history_index import db, make_case  # noqa: F401


def test_missing_index_is_pending_without_corpus_extraction_or_read_writes(db, monkeypatch):
    make_case(db)
    db.info['authorized_area_ids'] = (1,)
    calls, writes = [], []
    from app.services.case_semantic_service import build_semantic_profile
    def extract(values):
        calls.append(values)
        return build_semantic_profile(values)
    monkeypatch.setattr('app.services.case_history_retrieval.build_semantic_profile', extract)
    def capture(_conn, _cursor, sql, *_args):
        if sql.split()[0].lower() in {'insert', 'update', 'delete'}:
            writes.append(sql)
    event.listen(db.bind, 'before_cursor_execute', capture)
    try:
        result = execute_tool(db, 'find_history', {'query': '打孔盗油'})
    finally:
        event.remove(db.bind, 'before_cursor_execute', capture)
    assert result['state'] == 'partial'
    assert result['data']['index_state'] == 'pending'
    assert result['data']['coverage']['missing_index_cases'] == 1
    assert result['data']['items'] == []
    assert calls == [{'description': '打孔盗油'}] and not writes


def test_long_text_tail_is_returned_with_exact_source_reference_and_no_reextract(db, monkeypatch):
    case = make_case(db)
    case.description = ('普通背景资料。' * 80) + '夜间打孔盗油使用软管。'
    revision, _ = CaseSourceService.capture_change(db, case)
    db.commit()
    build_history_index(db)
    db.info['authorized_area_ids'] = (1,)
    result = CaseHistoryRetrieval.search(db, query='打孔盗油软管')
    item = result['items'][0]
    reference = item['fragment']['reference']
    assert reference['start'] > 500 and reference['quote'] == '夜间打孔盗油使用软管。'
    assert case.description[reference['start']:reference['end']] == item['snippet']
    assert item['fragment']['source_revision_id'] == revision.id
    assert item['structural_rank'] == item['lexical_rank'] == 1
    assert result['coverage']['scanned_cases'] == 1
    validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': result}]})
    forged = deepcopy(result)
    forged['items'][0]['fragment']['reference']['start'] -= 1
    with pytest.raises(PermissionError, match='evidence_changed'):
        validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': forged}]})
    case.description += '新增资料。'
    CaseSourceService.capture_change(db, case)
    db.commit()
    changed = CaseHistoryRetrieval.search(db, query='打孔盗油软管')
    assert changed['items'] == [] and changed['index_state'] == 'pending'
    assert changed['coverage']['missing_index_cases'] == 1
    with pytest.raises(PermissionError, match='evidence_changed'):
        validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': result}]})


def test_structural_lexical_and_semantic_branches_recall_independently(db, monkeypatch):
    structure = make_case(db, 'STRUCTURE')
    lexical = make_case(db, 'LEXICAL')
    semantic = make_case(db, 'SEMANTIC')
    structure.description, lexical.description, semantic.description = '夜里。', '专用甲乙丙。', '完全不同的历史用语。'
    for case in (structure, lexical, semantic):
        case.location = None
    db.commit()
    model = SimpleNamespace(state='ready', model_version='synthetic-v63',
        encode=lambda text: [1., 0.] if text == semantic.description else [0., 1.])
    monkeypatch.setattr('app.services.local_embedding_service.get_local_embedder', lambda: model)
    build_history_index(db)
    monkeypatch.setattr('app.services.case_history_retrieval.get_local_embedder',
        lambda: SimpleNamespace(state='ready', model_version='synthetic-v63', encode=lambda _: [1., 0.]))
    db.info['authorized_area_ids'] = (1,)
    result = CaseHistoryRetrieval.search(db, query='专用甲乙丙',
        query_conditions={('time_condition', '夜间', 'stated')}, limit=3)
    items = {item['case_id']: item for item in result['items']}
    assert items[structure.id]['structural_rank'] == 1 and items[structure.id]['lexical_rank'] is None
    assert items[lexical.id]['lexical_rank'] == 1 and items[lexical.id]['structural_rank'] is None
    assert items[semantic.id]['semantic_rank'] == 1 and items[semantic.id]['lexical_rank'] is None
    assert result['coverage']['branch_counts'] == {'structural': 1, 'lexical': 1, 'semantic': 1}


def test_current_authorization_applies_to_fragments_and_postings_even_after_cache(db):
    make_case(db)
    make_case(db, 'HIDDEN', area=2)
    build_history_index(db)
    assert len(list(db.scalars(select(CaseHistoryFragment)))) > 3
    db.info['authorized_area_ids'] = (1,)
    assert {item.case_id for item in db.scalars(select(CaseHistoryFragment))} == {1}
    assert {item.case_id for item in db.scalars(select(CaseHistoryPosting))} == {1}
    result = CaseHistoryRetrieval.search(db, query='胶管')
    assert result['coverage']['authorized_cases'] == 1 and 'HIDDEN' not in str(result)
    db.info['authorized_area_ids'] = ()
    assert CaseHistoryRetrieval.search(db, query='胶管')['items'] == []
    with pytest.raises(PermissionError):
        validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': result}]})


def test_confirmed_experience_fragments_recheck_status_and_evidence(db):
    case = make_case(db)
    asset = KnowledgeAsset(asset_type='experience_card', source_case_id=case.id, version=1,
        title='合成经验', content={'summary': '专用历史经验'}, evidence_refs=[{'id': f'case:{case.id}'}],
        source_signature='a' * 64, source_data_version='b' * 64, status='confirmed')
    db.add(asset)
    db.commit()
    build_history_index(db)
    db.info['authorized_area_ids'] = (1,)
    result = CaseHistoryRetrieval.search(db, query='专用历史经验')
    assert result['items'][0]['fragment']['kind'] == 'confirmed_experience'
    asset.status = 'archived'
    db.commit()
    assert CaseHistoryRetrieval.search(db, query='专用历史经验')['items'] == []
    with pytest.raises(PermissionError):
        validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': result}]})


def test_experience_coverage_counts_latest_confirmed_version_per_case(db):
    case = make_case(db)
    def asset(version, status):
        return KnowledgeAsset(asset_type='experience_card', source_case_id=case.id, version=version,
            title=f'合成经验版本{version}', content={'summary': '专用历史经验'},
            evidence_refs=[{'id': f'case:{case.id}'}], source_signature='a' * 64,
            source_data_version='b' * 64, status=status)
    # Insert order differs from version order; draft/archived revisions are not the selected population.
    selected = asset(3, 'confirmed')
    db.add_all([selected, asset(1, 'confirmed'), asset(4, 'draft'), asset(5, 'archived')])
    db.commit()
    db.info['authorized_area_ids'] = (1,)
    pending = CaseHistoryRetrieval.search(db, query='专用历史经验')
    assert pending['coverage']['missing_experience_indexes'] == 1
    build_history_index(db)
    ready = CaseHistoryRetrieval.search(db, query='专用历史经验')
    assert ready['coverage']['missing_experience_indexes'] == 0
    assert ready['state'] == 'ready' and ready['coverage']['complete'] is True
    assert ready['items'][0]['source_id'] == selected.id
    newest = asset(6, 'confirmed')
    db.add(newest)
    db.commit()
    pending = CaseHistoryRetrieval.search(db, query='专用历史经验')
    assert pending['coverage']['missing_experience_indexes'] == 1 and pending['state'] == 'partial'
    build_history_index(db)
    refreshed = CaseHistoryRetrieval.search(db, query='专用历史经验')
    assert refreshed['coverage']['missing_experience_indexes'] == 0 and refreshed['coverage']['complete'] is True
    assert refreshed['items'][0]['source_id'] == newest.id


def test_cancelled_history_is_partial_and_leaves_no_index_writes(db):
    make_case(db)
    build_history_index(db)
    db.info['authorized_area_ids'] = (1,)
    result = execute_tool(db, 'find_history', {'query': '胶管'}, cancelled=lambda: True)
    assert result['state'] == 'partial'
    assert result['data']['coverage']['cancelled'] is True
    assert result['data']['coverage']['scanned_cases'] == 0


def test_background_rebuild_rolls_back_fragment_replacement(db):
    case = make_case(db)
    build_history_index(db)
    old_ids = set(db.scalars(select(CaseHistoryFragment.id)))
    case.description = '更新后的背景。'
    db.commit()
    from app.services.case_history_index_service import CaseHistoryIndexService
    CaseHistoryIndexService.rebuild_case(db, case)
    db.flush()
    assert set(db.scalars(select(CaseHistoryFragment.id))) != old_ids
    db.rollback()
    assert set(db.scalars(select(CaseHistoryFragment.id))) == old_ids


def test_current_process_clauses_are_indexed_and_invalid_revision_hash_is_rejected(db):
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.services.case_semantic_service import build_semantic_profile, TEXT_FIELDS, SEMANTIC_RULE_VERSION
    from app.services.case_history_retrieval import source_values
    case = make_case(db)
    case.description = '先抽取原油，随后转运。'
    revision, _ = CaseSourceService.capture_change(db, case)
    db.commit()
    build_history_index(db)
    parent = db.scalar(select(CaseHistoryIndex).where(CaseHistoryIndex.case_id == case.id))
    assert parent.payload['fragments']['process_state'] == 'not_ready'
    values = {key: value for key, value in source_values(case).items() if key in TEXT_FIELDS}
    semantics = build_semantic_profile(values, source_revision_id=revision.id,
        source_hash=revision.source_hash, source_payload=revision.payload)
    profile = CaseAnalysisProfile(id='synthetic-fragment-process', case_id=case.id,
        profile_version=1, source_hash=revision.source_hash, source_revision_id=revision.id,
        schema_version='6.3.0', dictionary_version=SEMANTIC_RULE_VERSION,
        payload={'semantics': semantics}, analysis_readiness='partial', is_current=True)
    db.add(profile)
    db.commit()
    build_history_index(db)
    process_rows = list(db.scalars(select(CaseHistoryFragment).where(CaseHistoryFragment.kind == 'process',
        CaseHistoryFragment.field == 'description').order_by(CaseHistoryFragment.start)))
    assert [row.quote for row in process_rows] == ['先抽取原油，', '随后转运。']
    assert ['oil', '原油', 'stated'] not in process_rows[1].conditions
    assert parent.payload['fragments']['process_state'] == 'current'
    altered = deepcopy(profile.payload)
    altered['semantics']['process']['source_hash'] = 'f' * 64
    profile.payload = altered
    db.commit()
    build_history_index(db)
    assert db.scalar(select(CaseHistoryFragment.id).where(CaseHistoryFragment.kind == 'process')) is None
    assert parent.payload['fragments']['process_state'] == 'not_ready'
