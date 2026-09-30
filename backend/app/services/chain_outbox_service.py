"""Durable, identity-bound refresh of the legacy chain projection.

Case saves record intent only. No model, routing or nearby-case scan runs in the
business transaction. Both source hashes remain independently checked on reads.
"""
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

from sqlalchemy import and_, or_

from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.services.case_road_triggers import capture_road_authority
from app.services.outbox_claim_service import OutboxClaimService


EVENT_TYPE = "case.chain.requested"


def enqueue_chain_change(db, case, *, source_hash, source_event_id):
    authority = capture_road_authority(db)
    if authority is None:
        return None  # A system event does not imply authority over all cases.
    key = hashlib.sha256(f"{EVENT_TYPE}:{source_event_id}".encode()).hexdigest()
    existing = db.query(OutboxEvent).filter_by(idempotency_key=key).first()
    if existing:
        return existing
    event = OutboxEvent(
        id=str(uuid4()), event_type=EVENT_TYPE, aggregate_type="case", aggregate_id=str(case.id),
        payload={"case_id": case.id, "source_hash": source_hash, "authority": authority},
        idempotency_key=key, status="pending",
    )
    db.add(event)
    db.flush()
    return event


def process_request(db, event_id):
    from app.services.case_pipeline_service import CasePipelineService
    from app.services.case_road_jobs import _identity
    from app.services.chain_analysis_service import ChainAnalysisService

    if db.new or db.dirty or db.deleted:
        raise ValueError("chain_worker_requires_clean_session")
    previous = dict(db.info)
    token = None
    attempts = 0
    try:
        scheduled = db.query(OutboxEvent).filter_by(id=event_id).first()
        if scheduled and scheduled.status in {"pending", "retry"}:
            if OutboxClaimService._aware(scheduled.available_at) > datetime.now(timezone.utc):
                return {"event_id": event_id, "status": scheduled.status, "claimed": False}
        event, claimed = OutboxClaimService.claim(db, event_id, expected_type=EVENT_TYPE)
        if not claimed:
            return {"event_id": event_id, "status": event.status, "claimed": False}
        token, attempts = str(event.worker_id), event.attempts
        payload = dict(event.payload)
        authority = payload["authority"]
        _identity(db, authority["user_id"], authority["scope"])
        # Serialize chain refreshes, not case saves, using one advisory lock.
        # Deterministic pair inserts remain protected by the existing unique key.
        if db.get_bind().dialect.name == "postgresql":
            from sqlalchemy import text
            db.execute(text("SELECT pg_advisory_xact_lock(600001)"))
        case_query = db.query(Case).filter(Case.id == payload["case_id"])
        if db.get_bind().dialect.name == "postgresql":
            case_query = case_query.with_for_update()
        case = case_query.first()
        if case is None:
            raise PermissionError("chain_source_unavailable")
        if CasePipelineService.source_hash(db, case) != payload["source_hash"]:
            status, links = "superseded", []
        else:
            status = "completed"
            links = ChainAnalysisService.scan_chain_links(case.id, db, commit=False)
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status=status)
        db.commit()
        return {"event_id": event_id, "status": status, "link_count": len(links)}
    except Exception as exc:
        db.rollback()
        if token is None:
            raise
        current = db.query(OutboxEvent).filter_by(id=event_id).first()
        if current is None or current.worker_id != token:
            return {"event_id": event_id, "status": "lease_lost"}
        status = "failed" if isinstance(exc, PermissionError) or attempts >= 3 else "retry"
        OutboxClaimService.finish(
            db, event_id=event_id, worker_id=token, status=status,
            error="chain_authority_unavailable" if isinstance(exc, PermissionError) else "chain_refresh_unavailable",
            available_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        db.commit()
        return {"event_id": event_id, "status": status}
    finally:
        db.info.clear()
        db.info.update(previous)


def process_pending(db, limit=50):
    now = datetime.now(timezone.utc)
    event_ids = [row[0] for row in db.query(OutboxEvent.id).filter(
        OutboxEvent.event_type == EVENT_TYPE,
        or_(and_(OutboxEvent.status.in_(("pending", "retry")), OutboxEvent.available_at <= now),
            and_(OutboxEvent.status == "processing",
                 or_(OutboxEvent.lease_until.is_(None), OutboxEvent.lease_until <= now))),
    ).order_by(OutboxEvent.created_at, OutboxEvent.id).limit(max(1, min(limit, 200))).all()]
    outcomes = [process_request(db, event_id) for event_id in event_ids]
    return {"selected": len(outcomes),
            "completed": sum(row["status"] in {"completed", "superseded"} for row in outcomes),
            "failed": sum(row["status"] in {"retry", "failed", "lease_lost"} for row in outcomes)}
