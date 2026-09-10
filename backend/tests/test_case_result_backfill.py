from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.case_result import CaseResultSnapshot
from app.services.case_result_backfill import EVENT_TYPE, enqueue_missing_results, process_result_backfill
from app.services.case_result_service import CaseResultService
from test_case_result_access import result_data  # noqa: F401
from test_case_results import db_session, prepare  # noqa: F401


def test_upgrade_reconciliation_queues_once_and_freezes_both_completed_stages(db_session, result_data):
    prepare(db_session)
    assert enqueue_missing_results(db_session) == {"enqueued": 2}
    assert enqueue_missing_results(db_session) == {"enqueued": 0}
    assert process_result_backfill(db_session) == {"selected": 2, "completed": 2, "failed": 0}
    assert db_session.query(CaseResultSnapshot).count() == 2
    assert CaseResultService.latest(db_session, 1)["content"]["versions"]["analysis_run_id"] == "run-1"
    assert enqueue_missing_results(db_session) == {"enqueued": 0}
    assert process_result_backfill(db_session)["selected"] == 0


def test_failed_old_profile_does_not_starve_next_batch(db_session, result_data):
    prepare(db_session)
    profile = result_data[0]
    profile.payload = {"source_hash": "invalid"}
    db_session.add(CaseAnalysisProfile(id="profile-2", case_id=2, profile_version=1,
        source_hash="source-2", schema_version="4.1.0", dictionary_version="rules-1",
        payload={"source_hash": "source-2"}, quality_score=1, analysis_readiness="ready"))
    db_session.commit()
    db_session.info["authorized_area_ids"] = None
    assert enqueue_missing_results(db_session, limit=1)["enqueued"] == 2
    assert process_result_backfill(db_session)["failed"] == 2
    # Failed/pending attempts remain visible in Outbox but do not monopolize selection.
    assert enqueue_missing_results(db_session, limit=1)["enqueued"] == 1
    report = process_result_backfill(db_session)
    assert report["completed"] == 1
    assert db_session.scalar(select(CaseResultSnapshot.case_id)) == 2
    errors = list(db_session.scalars(select(OutboxEvent.error).where(OutboxEvent.error.is_not(None))))
    assert errors == ["case_result_backfill_failed", "case_result_backfill_failed"]


def test_expired_worker_lease_recovers_without_duplicate_results(db_session, result_data):
    prepare(db_session)
    enqueue_missing_results(db_session)
    event = db_session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE).limit(1))
    event.status = "processing"
    event.worker_id = "stopped-worker"
    event.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert process_result_backfill(db_session)["completed"] == 2
    assert db_session.query(CaseResultSnapshot).count() == 2


def test_obsolete_schema_event_is_not_processed_by_new_rule(db_session, result_data):
    prepare(db_session)
    enqueue_missing_results(db_session)
    events = list(db_session.scalars(select(OutboxEvent)))
    for event in events:
        event.payload = {**event.payload, "schema_version": "obsolete"}
    db_session.commit()
    assert process_result_backfill(db_session)["failed"] == 0
    assert db_session.query(CaseResultSnapshot).count() == 0
    assert set(db_session.scalars(select(OutboxEvent.status))) == {"superseded"}


def test_registered_periodic_task_consumes_real_database_events(db_session, result_data, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.tasks import case_result_tasks
    from app.tasks.celery_app import celery_app

    prepare(db_session)
    factory = sessionmaker(bind=db_session.bind, autoflush=False)
    monkeypatch.setattr(case_result_tasks, "SessionLocal", factory)
    schedule = celery_app.conf.beat_schedule["reconcile-case-results"]
    assert schedule["task"] == case_result_tasks.reconcile_case_results.name
    assert "app.tasks.case_result_tasks" in celery_app.conf.include
    report = case_result_tasks.reconcile_case_results.run()
    assert report == {"enqueued": 2, "selected": 2, "completed": 2, "failed": 0}
