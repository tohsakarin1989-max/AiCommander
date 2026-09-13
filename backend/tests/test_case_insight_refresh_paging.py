"""Map/profile compensation reaches the tail and retains rollback activation."""
import pytest

from app.models.case_history_index import CaseHistoryIndexCursor
from app.models.case_pipeline import OutboxEvent
from app.services.case_insight_service import CaseInsightService
from test_case_insights import db_session, _case, _current_map  # noqa: F401


def requests(db):
    return db.query(OutboxEvent).filter_by(event_type='case.insights.requested')


def test_repeated_small_pages_reach_all_cases_without_duplicate_requests(db_session):
    db = db_session
    area, _ = _current_map(db)
    cases = [_case(db, f'PAGE-{index}') for index in range(3)]
    for case in cases:
        case.operational_area_id = area.id
    requests(db).delete(synchronize_session=False)
    db.commit()
    for index in range(3):
        outcome = CaseInsightService.reconcile_current_pairs(db, limit=1)
        assert outcome['scanned'] == 1
        assert requests(db).count() == index + 1
    assert outcome['after_case_id'] == 0 and outcome['completed_passes'] == 1
    assert {int(row.aggregate_id) for row in requests(db)} == {case.id for case in cases}
    for _ in range(3):
        CaseInsightService.reconcile_current_pairs(db, limit=1)
    assert requests(db).count() == 3


def test_interrupted_enqueue_does_not_advance_cursor(db_session, monkeypatch):
    db = db_session
    area, _ = _current_map(db)
    for index in range(2):
        case = _case(db, f'RETRY-{index}')
        case.operational_area_id = area.id
    requests(db).delete(synchronize_session=False)
    db.commit()
    first = CaseInsightService.reconcile_current_pairs(db, limit=1)
    original = CaseInsightService.enqueue_analysis
    def fail(*args):
        original(*args)
        raise RuntimeError('interrupted before commit')
    monkeypatch.setattr(CaseInsightService, 'enqueue_analysis', fail)
    with pytest.raises(RuntimeError, match='before commit'):
        CaseInsightService.reconcile_current_pairs(db, limit=1)
    db.rollback()
    cursor = db.get(CaseHistoryIndexCursor, 'case-insight-pairs')
    assert cursor.after_case_id == first['after_case_id'] and requests(db).count() == 1
    monkeypatch.setattr(CaseInsightService, 'enqueue_analysis', original)
    assert CaseInsightService.reconcile_current_pairs(db, limit=1)['after_case_id'] == 0
    assert requests(db).count() == 2


def test_scoped_session_cannot_advance_global_cursor(db_session):
    db_session.info['authorized_area_ids'] = (1,)
    with pytest.raises(PermissionError, match='background_session_required'):
        CaseInsightService.reconcile_current_pairs(db_session)
    assert db_session.get(CaseHistoryIndexCursor, 'case-insight-pairs') is None
