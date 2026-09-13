from datetime import datetime, timedelta, timezone

from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.models.case_result import CaseResultSnapshot
from app.services.dashboard_summary_service import DashboardSummaryService
from app.services.case_result_snapshot import assemble_case_result
from test_case_search_page import search_db, add_case, client_for  # noqa: F401
from test_case_result_access import result_data  # noqa: F401

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def test_activity_limits_scope_order_and_read_only(search_db):
    for index in range(110):
        add_case(search_db, f"VISIBLE-{index}", created_at=NOW-timedelta(minutes=index+1),
                 updated_at=NOW-timedelta(seconds=index+1))
    add_case(search_db, "PRIVATE", operational_area_id=2, created_at=NOW-timedelta(seconds=1))
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    first = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW)
    repeat = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW)
    assert first['activities'] == repeat['activities']
    assert len(first['activities']) == 20
    assert len({item['id'] for item in first['activities']}) == 20
    assert all(item['case_number'].startswith('VISIBLE') for item in first['activities'])
    assert first['activities'] == sorted(first['activities'], key=lambda item: (item['recorded_at'], item['id']), reverse=True)
    more = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW, activity_limit=100)
    assert len(more['activities']) == 100
    assert more['metrics'] == first['metrics']
    assert search_db.query(Case).count() == 110
    assert search_db.query(OutboxEvent).count() == 0
    assert client_for(search_db).get('/api/cases/dashboard-summary?activity_limit=101').status_code == 422


def test_current_task_state_is_not_an_invented_transition(search_db):
    visible = add_case(search_db, 'TASK', created_at=NOW-timedelta(days=30))
    hidden = add_case(search_db, 'HIDDEN', operational_area_id=2)
    search_db.flush()
    for index, status in enumerate(('pending', 'processing', 'retry', 'failed')):
        for case in (visible, hidden):
            search_db.add(OutboxEvent(id=f'{case.id}-{status}', aggregate_type='case', aggregate_id=str(case.id),
                event_type='case.insights.requested', payload={'private': 'not public'},
                idempotency_key=f'{case.id}-{status}', status=status, attempts=index,
                error='do not disclose', created_at=NOW-timedelta(hours=1)))
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    data = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW)
    assert data['processing'] == dict(pending=1, processing=1, retry=1, failed=1)
    tasks = [item for item in data['activities'] if item['kind'] == 'task']
    assert len(tasks) == 4
    assert all(item['recorded_at'] == NOW-timedelta(hours=1) for item in tasks)
    assert 'do not disclose' not in str(data)
    assert 'not public' not in str(data)
    assert data['completion'] == dict(completed=0, degraded=0)


def test_old_case_new_snapshot_rechecks_all_evidence(db_session, result_data):
    profile, run, candidate = result_data
    candidate.evidence_refs = ['case:2']
    snapshot = assemble_case_result(profile, run, [candidate])
    db_session.add(CaseResultSnapshot(id='saved-ui', case_id=1, case_profile_id=profile.id,
        content=snapshot['content'], content_sha256=snapshot['content_sha256'], created_at=NOW-timedelta(hours=1)))
    db_session.commit()
    db_session.info['authorized_area_ids'] = (1, 2)
    data = DashboardSummaryService.build(db_session, operational_area_id=1, days=7, as_of=NOW)
    assert data['metrics']['cases'] == 0
    assert data['recent_results'][0]['result_id'] == 'saved-ui'
    assert any(item['kind'] == 'result' for item in data['activities'])
    db_session.info['authorized_area_ids'] = (1,)
    denied = DashboardSummaryService.build(db_session, operational_area_id=1, days=7, as_of=NOW)
    assert denied['recent_results'] == []
    assert all(item['kind'] != 'result' for item in denied['activities'])
    assert db_session.query(CaseResultSnapshot).count() == 1
