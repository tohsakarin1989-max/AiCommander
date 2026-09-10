"""为案件派生流水线提供带租约的原子 Outbox 领取。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.case_pipeline import OutboxEvent


OUTBOX_LEASE_SECONDS = 300
TERMINAL_STATUSES = {"completed", "superseded", "failed", "cancelled"}


class OutboxClaimLostError(RuntimeError):
    """当前 Worker 的租约已被其他 Worker 接管。"""


class OutboxClaimService:
    @staticmethod
    def claim(
        db: Session,
        event_id: str,
        *,
        expected_type: str,
    ) -> tuple[OutboxEvent, bool]:
        query = db.query(OutboxEvent).filter(OutboxEvent.id == event_id)
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            query = query.with_for_update()
        event = query.first()
        if not event:
            raise ValueError("outbox_event_not_found")
        if event.event_type != expected_type:
            raise ValueError("unsupported_outbox_event")
        if event.status in TERMINAL_STATUSES:
            return event, False

        now = datetime.now(timezone.utc)
        if event.status == "processing" and OutboxClaimService._aware(event.lease_until) > now:
            return event, False
        if event.status not in {"pending", "retry", "processing"}:
            return event, False

        event.status = "processing"
        event.attempts += 1
        event.claimed_at = now
        event.lease_until = now + timedelta(seconds=OUTBOX_LEASE_SECONDS)
        event.worker_id = uuid.uuid4().hex
        db.commit()
        db.refresh(event)
        return event, True

    @staticmethod
    def release(event: OutboxEvent) -> None:
        event.claimed_at = None
        event.lease_until = None
        event.worker_id = None

    @staticmethod
    def finish(
        db: Session,
        *,
        event_id: str,
        worker_id: str,
        status: str,
        error: str | None = None,
        available_at: datetime | None = None,
    ) -> None:
        """以 Worker 令牌作为提交围栏，防止过期 Worker 覆盖新结果。"""
        values = {
            OutboxEvent.status: status,
            OutboxEvent.processed_at: (
                datetime.now(timezone.utc) if status in TERMINAL_STATUSES else None
            ),
            OutboxEvent.error: error,
            OutboxEvent.claimed_at: None,
            OutboxEvent.lease_until: None,
            OutboxEvent.worker_id: None,
        }
        if available_at is not None:
            values[OutboxEvent.available_at] = available_at
        updated = (
            db.query(OutboxEvent)
            .filter(
                OutboxEvent.id == event_id,
                OutboxEvent.status == "processing",
                OutboxEvent.worker_id == worker_id,
            )
            .update(values, synchronize_session=False)
        )
        if updated != 1:
            raise OutboxClaimLostError("outbox_claim_lost")

    @staticmethod
    def _aware(value: datetime | None) -> datetime:
        if value is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
