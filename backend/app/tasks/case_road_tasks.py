"""Consume durable road jobs on a dedicated queue, separate from case saving."""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import and_, or_, select

from app.config import settings
from app.database import SessionLocal
from app.models.case_pipeline import OutboxEvent
from app.services.case_road_jobs import EVENT_TYPE, process_comparison
from app.services.case_road_triggers import REQUEST_TYPE, process_request
from app.tasks.celery_app import celery_app


@celery_app.task(name='aicommander.case_roads.process_next', queue='road_analysis')
def process_next_comparison():
    # One job per task keeps long calculations from multiplying inside a batch.
    # Road worker concurrency is a deployment limit, not global HTTP admission.
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        selected = db.execute(select(OutboxEvent.id, OutboxEvent.event_type).where(
            OutboxEvent.event_type.in_((EVENT_TYPE, REQUEST_TYPE)),
            or_(and_(OutboxEvent.status.in_(('pending', 'retry')), OutboxEvent.available_at <= now),
                and_(OutboxEvent.event_type == REQUEST_TYPE, OutboxEvent.status == 'waiting_dependency',
                     OutboxEvent.available_at <= now),
                and_(OutboxEvent.status == 'processing', or_(OutboxEvent.lease_until.is_(None),
                                                            OutboxEvent.lease_until <= now))))
            .order_by(OutboxEvent.available_at, OutboxEvent.id).limit(1)).first()
        if selected is None:
            return {'selected': 0}
        identifier, kind = selected
        if kind == REQUEST_TYPE:
            return {'selected': 1, **process_request(db, identifier)}
        return {'selected': 1, **process_comparison(db, identifier,
            artifact_root=Path(settings.MAP_PACKAGE_ROOT) / 'road-graphs')}
