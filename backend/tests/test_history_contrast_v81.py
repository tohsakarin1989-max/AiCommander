"""Independent, evidence-grounded contrast recall, never absence-as-negation."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event

from app.api import knowledge
from app.database import get_db
from app.models.case import Case
from app.models.case_source import CaseRevision
from app.services.case_history_retrieval import CaseHistoryRetrieval, HistoryUnavailable
from app.services.case_source_service import CaseSourceService
from app.services.intelligent_query_history import validate_history_query_evidence
from tests.history_index_helpers import build_history_index
from tests.test_case_history_retrieval import db_session as db  # noqa: F401


QUERY = '夜间。使用软管。'


def add(db, number, text, *, area=1, year=2000):
    row = Case(case_number=number, description=text, operational_area_id=area,
               occurred_time=datetime(year, 1, 1))
    db.add(row)
    db.flush()
    CaseSourceService.capture_change(db, row)
    db.commit()
    return row


def ready(db):
    build_history_index(db)
    db.info['authorized_area_ids'] = (1,)


def query(db, **values):
    return CaseHistoryRetrieval.search(db, query=QUERY, purpose='contrast', **values)


def validate(db, data):
    validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': data}]})


def test_opposition_is_recalled_independently_with_shared_evidence_in_another_fragment(db):
    opposite = add(db, 'OPPOSITE', '夜里。未使用胶管。')
    for index in range(110):
        add(db, f'POSITIVE-{index}', QUERY, year=2026)
    ready(db)
    positive = CaseHistoryRetrieval.search(db, query=QUERY, limit=1)
    assert positive['items'][0]['case_id'] != opposite.id
    result = query(db, limit=1)
    assert result['purpose'] == result['query_context']['purpose'] == 'contrast'
    assert result['items'][0]['case_id'] == opposite.id
    assert result['items'][0]['snippet'] == '未使用胶管。'
    item = result['items'][0]
    assert ['time_condition', '夜间', 'stated'] in item['shared_conditions']
    assert ['tool', '软管', 'negated'] in item['different_conditions']
    assert item['contrast_evidence']['shared_conditions'][0]['historical_reference']['quote'] == '夜里。'
    assert item['fragment']['source_revision_id'] == db.query(CaseRevision).filter_by(case_id=opposite.id).one().id
    assert result['coverage']['recency_limit'] is None
    assert result['coverage']['authorized_cases'] == 111
    assert result['coverage']['eligible_fragments'] == 1
    validate(db, result)


@pytest.mark.parametrize('text', [
    '夜间。未提及工具。',
    '夜间。可能未使用胶管。',
    '夜间。是否使用胶管待核。',
    '夜间。使用胶管。',
    '未使用胶管。',
    '夜间。使用胶管。未使用胶管。',
])
def test_missing_uncertain_positive_pure_opposite_and_conflicting_are_not_contrast(db, text):
    add(db, 'NOT-A-CONTRAST', text)
    ready(db)
    assert query(db)['items'] == []


def test_uncertain_query_condition_is_not_an_explicit_opposition(db):
    add(db, 'NEGATIVE', '夜间。未使用胶管。')
    ready(db)
    result = CaseHistoryRetrieval.search(db, query='夜间。可能使用软管。', purpose='contrast')
    assert result['items'] == []


def test_default_similar_polarity_guard_remains_unchanged(db):
    add(db, 'NEGATIVE', '未使用胶管。')
    ready(db)
    default = CaseHistoryRetrieval.search(db, query='使用软管。')
    explicit = CaseHistoryRetrieval.search(db, query='使用软管。', purpose='similar')
    assert default['items'] == explicit['items'] == []


def test_source_case_query_binds_both_revisions_and_current_permissions(db):
    from app.models.map_foundation import OperationalArea

    db.add(OperationalArea(id=2, code='HIDDEN', name='其他区'))
    db.commit()
    source = add(db, 'CURRENT', QUERY)
    historic = add(db, 'HISTORY', '夜间。未使用胶管。')
    add(db, 'SECRET', '夜间。未使用胶管。', area=2)
    ready(db)
    result = CaseHistoryRetrieval.search(db, source_case_id=source.id, purpose='contrast')
    assert [item['case_id'] for item in result['items']] == [historic.id]
    assert 'SECRET' not in str(result)
    validate(db, result)
    db.info['authorized_area_ids'] = ()
    with pytest.raises(PermissionError):
        validate(db, result)
    with pytest.raises(HistoryUnavailable):
        CaseHistoryRetrieval.search(db, source_case_id=source.id, purpose='contrast')
    assert query(db)['items'] == []


def test_edit_and_delete_invalidate_contrasts_without_reusing_stale_sources(db):
    historic = add(db, 'HISTORY', '夜间。未使用胶管。')
    ready(db)
    previous = query(db)
    assert previous['items']
    historic.description = '夜间。使用胶管。'
    CaseSourceService.capture_change(db, historic)
    db.commit()
    stale = query(db)
    assert stale['items'] == [] and stale['coverage']['missing_index_cases'] == 1
    with pytest.raises(PermissionError):
        validate(db, previous)
    ready(db)
    assert query(db)['items'] == []
    db.delete(historic)
    db.commit()
    assert query(db)['coverage']['authorized_cases'] == 0


def test_tampered_shared_reference_or_polarity_cannot_be_reused(db):
    add(db, 'HISTORY', '夜间。未使用胶管。')
    ready(db)
    result = query(db)
    changed = deepcopy(result)
    changed['items'][0]['contrast_evidence']['shared_conditions'][0]['historical_reference']['quote'] = '白天。'
    with pytest.raises(PermissionError):
        validate(db, changed)
    changed = deepcopy(result)
    changed['items'][0]['contrast_evidence']['different_conditions'][0]['current_condition'][2] = 'uncertain'
    with pytest.raises(PermissionError):
        validate(db, changed)


def test_read_is_no_write_and_does_not_reencode_corpus(db, monkeypatch):
    add(db, 'HISTORY', '夜间。未使用胶管。')
    ready(db)
    calls, writes = [], []
    encoder = SimpleNamespace(state='ready', model_version='synthetic-contrast-query',
                              encode=lambda text: calls.append(text) or [1., 0.])
    monkeypatch.setattr('app.services.case_history_retrieval.get_local_embedder', lambda: encoder)

    def capture(_conn, _cursor, sql, *_):
        if sql.lstrip().split()[0].lower() in {'insert', 'update', 'delete'}:
            writes.append(sql)

    event.listen(db.bind, 'before_cursor_execute', capture)
    try:
        result = query(db)
    finally:
        event.remove(db.bind, 'before_cursor_execute', capture)
    assert result['items'] and result['degraded'] is True
    assert calls == [QUERY] and writes == []


def test_api_accepts_contrast_and_rejects_unknown_purpose(db):
    add(db, 'HISTORY', '夜间。未使用胶管。')
    ready(db)
    app = FastAPI()
    app.include_router(knowledge.router, prefix='/api/knowledge')
    app.dependency_overrides[get_db] = lambda: db

    @app.middleware('http')
    async def identity(request: Request, call_next):
        request.state.principal = SimpleNamespace(id=1)
        return await call_next(request)

    with TestClient(app) as client:
        result = client.get('/api/knowledge/history', params={'q': QUERY, 'purpose': 'contrast'})
        assert result.status_code == 200 and result.json()['purpose'] == 'contrast'
        assert result.json()['items'][0]['contrast_evidence']['different_conditions']
        assert result.headers['Cache-Control'] == 'no-store'
        assert client.get('/api/knowledge/history', params={'q': QUERY, 'purpose': 'invent'}).status_code == 422


def test_daily_references_mix_two_similar_and_one_independent_contrast(db):
    source = add(db, 'CURRENT', QUERY)
    add(db, 'SIMILAR-ONE', '夜里。使用胶管。')
    add(db, 'SIMILAR-TWO', '夜间。使用软管。')
    opposite = add(db, 'CONTRAST', '夜里。未使用胶管。')
    ready(db)
    result = CaseHistoryRetrieval.case_references(db, source_case_id=source.id)
    assert result['purpose'] == result['query_context']['purpose'] == 'mixed'
    assert [row['purpose'] for row in result['items']] == ['similar', 'similar', 'contrast']
    assert result['items'][-1]['case_id'] == opposite.id
    assert len({row['case_id'] for row in result['items']}) == 3
    assert result['coverage']['scanned_cases'] == 3  # Union, not sum of two recalls.
    assert set(result['coverage']['recall_purposes']) == {'similar', 'contrast'}
    validate(db, result)


def test_daily_references_does_not_fill_missing_contrast_with_another_similar_case(db):
    source = add(db, 'CURRENT', QUERY)
    for index in range(3):
        add(db, f'SIMILAR-{index}', QUERY)
    ready(db)
    result = CaseHistoryRetrieval.case_references(db, source_case_id=source.id)
    assert len(result['items']) == 2
    assert result['reference_mix']['contrast'] == 0


def test_daily_mix_only_encodes_the_query_once(db, monkeypatch):
    source = add(db, 'CURRENT', QUERY)
    add(db, 'HISTORY', '夜間。夜里。未使用胶管。')
    ready(db)
    calls = []
    encoder = SimpleNamespace(state='ready', model_version='synthetic-query-only',
                              encode=lambda text: calls.append(text) or [1., 0.])
    monkeypatch.setattr('app.services.case_history_retrieval.get_local_embedder', lambda: encoder)
    result = CaseHistoryRetrieval.case_references(db, source_case_id=source.id)
    assert result['reference_mix']['contrast'] == 1 and len(calls) == 1


def test_daily_api_uses_single_read_and_rejects_ambiguous_mix_request(db):
    source = add(db, 'CURRENT', QUERY)
    add(db, 'HISTORY', '夜间。未使用胶管。')
    ready(db)
    app = FastAPI()
    app.include_router(knowledge.router, prefix='/api/knowledge')
    app.dependency_overrides[get_db] = lambda: db

    @app.middleware('http')
    async def identity(request: Request, call_next):
        request.state.principal = SimpleNamespace(id=1)
        return await call_next(request)

    with TestClient(app) as client:
        response = client.get('/api/knowledge/history', params={'source_case_id': source.id, 'include_contrast': True})
        assert response.status_code == 200 and response.json()['purpose'] == 'mixed'
        assert response.json()['items'][0]['purpose'] == 'contrast'
        assert client.get('/api/knowledge/history', params={'q': QUERY, 'include_contrast': True}).status_code == 422


def test_missing_index_and_cancelled_contrast_are_partial_not_completed_no_match(db):
    add(db, 'HISTORY', '夜间。未使用胶管。')
    db.info['authorized_area_ids'] = (1,)
    pending = query(db)
    assert pending['items'] == [] and pending['index_state'] == 'pending'
    assert pending['coverage']['complete'] is False and pending['degraded'] is True
    ready(db)
    cancelled = query(db, cancelled=lambda: True)
    assert cancelled['items'] == [] and cancelled['coverage']['cancelled'] is True
    assert cancelled['state'] == 'partial'


def test_daily_mix_rejects_source_change_between_independent_recalls(db, monkeypatch):
    source = add(db, 'CURRENT', QUERY)
    add(db, 'HISTORY', '夜间。未使用胶管。')
    ready(db)
    original_search = CaseHistoryRetrieval._search

    def changed_before_contrast(db, **kwargs):
        if kwargs['purpose'] == 'contrast':
            source.description = '白天。使用软管。'
            CaseSourceService.capture_change(db, source)
            db.commit()
        return original_search(db, **kwargs)

    monkeypatch.setattr(CaseHistoryRetrieval, '_search', changed_before_contrast)
    with pytest.raises(HistoryUnavailable, match='source_changed'):
        CaseHistoryRetrieval.case_references(db, source_case_id=source.id)
