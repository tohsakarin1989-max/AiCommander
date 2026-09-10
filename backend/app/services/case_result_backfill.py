"""升级后分批补齐已有画像/融合成果，复用Outbox记录失败和重试。"""
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.case_insight import CaseAnalysisRun
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.case_result import CaseResultSnapshot
from app.models.map_foundation import MapSnapshot
from app.services.case_result_service import CaseResultService
from app.services.case_result_snapshot import RESULT_SCHEMA_VERSION
from app.services.outbox_claim_service import OutboxClaimService

EVENT_TYPE = "case.results.freeze"


def enqueue_missing_results(db: Session, limit: int = 50) -> dict:
    """每次至多两批，只排未尝试版本；失败项保留状态，不饿死后续案件。"""
    size = max(1, min(limit, 200))
    queued = 0
    for with_run in (False, True):
        target = (CaseAnalysisProfile.id + ":" + CaseAnalysisRun.id if with_run
                  else CaseAnalysisProfile.id + ":base")
        columns = [CaseAnalysisProfile.id]
        if with_run:
            columns.append(CaseAnalysisRun.id)
        query = select(*columns).where(CaseAnalysisProfile.is_current.is_(True))
        if with_run:
            query = query.join(CaseAnalysisRun, CaseAnalysisRun.case_profile_id == CaseAnalysisProfile.id).join(
                MapSnapshot, MapSnapshot.id == CaseAnalysisRun.map_snapshot_id,
            ).where(CaseAnalysisRun.status.in_(("completed", "degraded")), MapSnapshot.status == "current")
        result_run = CaseResultSnapshot.content["versions"]["analysis_run_id"].as_string()
        result_exists = exists(select(CaseResultSnapshot.id).where(
            CaseResultSnapshot.case_profile_id == CaseAnalysisProfile.id,
            CaseResultSnapshot.content["schema_version"].as_string() == RESULT_SCHEMA_VERSION,
            result_run == CaseAnalysisRun.id if with_run else result_run.is_(None),
        ))
        event_exists = exists(select(OutboxEvent.id).where(
            OutboxEvent.event_type == EVENT_TYPE, OutboxEvent.aggregate_id == target,
            OutboxEvent.payload["schema_version"].as_string() == RESULT_SCHEMA_VERSION,
        ))
        rows = db.execute(query.where(~result_exists, ~event_exists).order_by(CaseAnalysisProfile.id).limit(size)).all()
        for row in rows:
            profile_id, run_id = row[0], row[1] if with_run else None
            aggregate_id = f"{profile_id}:{run_id or 'base'}"
            dialect = db.get_bind().dialect.name
            if dialect not in {"sqlite", "postgresql"}:
                raise ValueError("unsupported_case_result_database")
            insert = sqlite_insert if dialect == "sqlite" else postgres_insert
            event_id = db.scalar(insert(OutboxEvent).values(
                id=str(uuid4()), event_type=EVENT_TYPE, aggregate_type="case_result", aggregate_id=aggregate_id,
                payload={"profile_id": profile_id, "run_id": run_id, "schema_version": RESULT_SCHEMA_VERSION},
                idempotency_key=hashlib.sha256(f"{EVENT_TYPE}:{RESULT_SCHEMA_VERSION}:{aggregate_id}".encode()).hexdigest(),
                status="pending", attempts=0,
            ).on_conflict_do_nothing(index_elements=["idempotency_key"]).returning(OutboxEvent.id))
            queued += int(event_id is not None)
    db.commit()
    return {"enqueued": queued}


def process_result_backfill(db: Session, limit: int = 50) -> dict:
    now = datetime.now(timezone.utc)
    event_ids = list(db.scalars(select(OutboxEvent.id).where(
        OutboxEvent.event_type == EVENT_TYPE,
        or_(and_(OutboxEvent.status.in_(("pending", "retry")), OutboxEvent.available_at <= now),
            and_(OutboxEvent.status == "processing", or_(OutboxEvent.lease_until.is_(None), OutboxEvent.lease_until <= now))),
    ).order_by(OutboxEvent.created_at, OutboxEvent.id).limit(max(1, min(limit, 200)))))
    completed = failed = 0
    for event_id in event_ids:
        worker_id = None
        try:
            event, claimed = OutboxClaimService.claim(db, event_id, expected_type=EVENT_TYPE)
            if not claimed:
                continue
            worker_id = event.worker_id
            if event.payload.get("schema_version") != RESULT_SCHEMA_VERSION:
                OutboxClaimService.finish(db, event_id=event_id, worker_id=worker_id, status="superseded")
            else:
                profile = db.scalar(select(CaseAnalysisProfile).where(CaseAnalysisProfile.id == event.payload["profile_id"]))
                run_id = event.payload.get("run_id")
                run = db.scalar(select(CaseAnalysisRun).where(CaseAnalysisRun.id == run_id)) if run_id else None
                if profile is None or (run_id and run is None):
                    raise ValueError("case_result_source_unavailable")
                CaseResultService.freeze_completed_inputs(db, profile, run)
                OutboxClaimService.finish(db, event_id=event_id, worker_id=worker_id, status="completed")
            db.commit()
            completed += 1
        except Exception:
            db.rollback()
            failed += 1
            event = db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id).execution_options(populate_existing=True))
            if event is not None and worker_id and event.worker_id == worker_id:
                OutboxClaimService.finish(db, event_id=event_id, worker_id=worker_id,
                    status="retry" if event.attempts < 3 else "failed", error="case_result_backfill_failed",
                    available_at=datetime.now(timezone.utc) + timedelta(seconds=min(60, 2 ** event.attempts)))
                db.commit()
    return {"selected": len(event_ids), "completed": completed, "failed": failed}
