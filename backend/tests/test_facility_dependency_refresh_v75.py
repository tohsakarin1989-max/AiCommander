from copy import deepcopy
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.case_pipeline import OutboxEvent
from app.models.jurisdiction import JurisdictionAsset
from app.models.road_network import RoadNetworkVersion
from app.services import road_refresh_jobs as refresh
from app.services.case_road_jobs import EVENT_TYPE as COMPARE_TYPE
from app.services.case_road_triggers import REQUEST_TYPE
from test_road_refresh_jobs import delegated  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401
from test_road_network_service import ready  # noqa: F401


def new_pass(db):
    # Advancing the poll pass is test bookkeeping only, not a dependency input.
    db.query(OutboxEvent).filter_by(event_type=refresh.DEPENDENCY_EVENT_TYPE).update(
        {'idempotency_key': OutboxEvent.id})
    db.commit()
    identifier = refresh.enqueue_dependency_check(db)
    db.commit()
    return identifier


def test_dependency_pass_is_paged_single_active_and_unchanged_input_stays_deduplicated(delegated, monkeypatch):
    db, _ = delegated
    request = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == REQUEST_TYPE))
    db.add(OutboxEvent(id='v75-second-request', event_type=REQUEST_TYPE, aggregate_type=request.aggregate_type,
        aggregate_id=request.aggregate_id, payload=deepcopy(request.payload),
        idempotency_key='v75-second-request', status='completed'))
    db.commit()
    monkeypatch.setattr(refresh, 'PAGE_SIZE', 1)
    identifier = new_pass(db)
    assert refresh.enqueue_dependency_check(db) is None
    first = refresh.process(db, identifier)
    assert first['status'] == 'pending' and first['scanned'] == 1
    assert refresh.enqueue_dependency_check(db) is None
    assert refresh.process(db, identifier)['status'] == 'completed'
    assert db.query(OutboxEvent).filter_by(event_type=COMPARE_TYPE).count() == 1
    again = new_pass(db)
    refresh.process(db, again)
    refresh.process(db, again)
    assert db.query(OutboxEvent).filter_by(event_type=COMPARE_TYPE).count() == 1
    db.add(JurisdictionAsset(id=888, operational_area_id=1, name='新增设施，不引用旧候选', asset_type='well'))
    db.commit()
    changed = new_pass(db)
    refresh.process(db, changed)
    refresh.process(db, changed)
    jobs = db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == COMPARE_TYPE)).all()
    assert len(jobs) == 2
    assert jobs[0].payload['dependency_sha256'] != jobs[1].payload['dependency_sha256']


def test_new_compatible_graph_refresh_does_not_depend_on_old_paths(delegated):
    db, _ = delegated
    first = new_pass(db)
    assert refresh.process(db, first)['created'] == 1
    old = db.get(RoadNetworkVersion, 'graph-1')
    values = {column.key: deepcopy(getattr(old, column.key)) for column in RoadNetworkVersion.__table__.columns}
    values.update(id='new-shortcut-graph', graph_sha256='d' * 64, input_sha256='e' * 64,
                  valid_from=datetime.now(timezone.utc) - timedelta(seconds=1))
    db.add(RoadNetworkVersion(**values))
    db.commit()
    changed = new_pass(db)
    assert refresh.process(db, changed)['created'] == 1
    jobs = db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == COMPARE_TYPE)).all()
    assert {job.payload['network_id'] for job in jobs} == {'graph-1', 'new-shortcut-graph'}
    assert all(job.payload['dependencies']['policy'] == 'whole_authorized_scope_conservative' for job in jobs)
