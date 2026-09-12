"""案件画像与统一地图的确定性融合研判。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_history_index import CaseHistoryIndexCursor
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis, HypothesisFeedback
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature
from app.repositories.spatial_repository import SpatialRepository
from app.services.outbox_claim_service import OutboxClaimLostError, OutboxClaimService
from app.services.scorers.dual_domain_v34 import (
    DualDomainV34, VERSION as SCORER_VERSION, SOURCE_TYPES, STORAGE_TYPES, ROAD_TYPES,
)


CASE_INSIGHT_ALGORITHM_VERSION = SCORER_VERSION


class CaseInsightService:
    """评分与证据由确定性工具生成；不调用大模型创造事实。"""

    @staticmethod
    def enqueue_analysis(
        db: Session,
        profile: CaseAnalysisProfile,
        snapshot: MapSnapshot,
    ) -> OutboxEvent:
        key = hashlib.sha256(
            f"insight:{profile.id}:{snapshot.id}:{CASE_INSIGHT_ALGORITHM_VERSION}".encode()
        ).hexdigest()
        existing = db.query(OutboxEvent).filter(OutboxEvent.idempotency_key == key).first()
        if existing:
            run = (
                db.query(CaseAnalysisRun)
                .filter(
                    CaseAnalysisRun.case_profile_id == profile.id,
                    CaseAnalysisRun.map_snapshot_id == snapshot.id,
                    CaseAnalysisRun.algorithm_version == CASE_INSIGHT_ALGORITHM_VERSION,
                )
                .first()
            )
            if run and profile.is_current and snapshot.status == "current":
                CaseInsightService._activate_run_hypotheses(db, run)
            return existing
        event = OutboxEvent(
            id=str(uuid.uuid4()),
            event_type="case.insights.requested",
            aggregate_type="case",
            aggregate_id=str(profile.case_id),
            payload={
                "case_id": profile.case_id,
                "case_profile_id": profile.id,
                "map_snapshot_id": snapshot.id,
                "algorithm_version": CASE_INSIGHT_ALGORITHM_VERSION,
            },
            idempotency_key=key,
            status="pending",
        )
        db.add(event)
        db.flush()
        return event

    @staticmethod
    def process_event(db: Session, event_id: str) -> dict[str, Any]:
        event, claimed = OutboxClaimService.claim(
            db,
            event_id,
            expected_type="case.insights.requested",
        )
        if not claimed and event.status == "completed":
            run = (
                db.query(CaseAnalysisRun)
                .filter(
                    CaseAnalysisRun.case_profile_id == event.payload.get("case_profile_id"),
                    CaseAnalysisRun.map_snapshot_id == event.payload.get("map_snapshot_id"),
                )
                .first()
            )
            return {
                "event_id": event.id,
                "status": run.status if run else "completed",
                "run_id": run.id if run else None,
                "idempotent_replay": True,
            }
        if not claimed:
            return {
                "event_id": event.id,
                "status": event.status,
                "idempotent_replay": event.status == "superseded",
            }
        worker_id = str(event.worker_id)
        try:
            case_query = db.query(Case).filter(Case.id == int(event.aggregate_id))
            profile_query = db.query(CaseAnalysisProfile).filter(
                CaseAnalysisProfile.id == event.payload["case_profile_id"]
            )
            snapshot_query = db.query(MapSnapshot).filter(
                MapSnapshot.id == event.payload["map_snapshot_id"]
            )
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                # 与案件治理流水线一致：case -> profile。地图只读并在提交前复核 current，
                # 避免和地图发布事务形成反向锁顺序。
                case_query = case_query.with_for_update()
                profile_query = profile_query.with_for_update()
            case = case_query.first()
            profile = profile_query.first()
            snapshot = snapshot_query.first()
            if not profile or not snapshot or not case:
                raise ValueError("analysis_input_not_found")
            if not profile.is_current or snapshot.status != "current":
                OutboxClaimService.finish(
                    db,
                    event_id=event.id,
                    worker_id=worker_id,
                    status="superseded",
                )
                db.commit()
                return {
                    "event_id": event.id,
                    "status": "superseded",
                    "idempotent_replay": False,
                }
            existing = (
                db.query(CaseAnalysisRun)
                .filter(
                    CaseAnalysisRun.case_profile_id == profile.id,
                    CaseAnalysisRun.map_snapshot_id == snapshot.id,
                    CaseAnalysisRun.algorithm_version == CASE_INSIGHT_ALGORITHM_VERSION,
                )
                .first()
            )
            if existing:
                CaseInsightService._activate_run_hypotheses(db, existing)
                from app.services.case_result_service import CaseResultService

                CaseResultService.freeze_completed_inputs(db, profile, existing)
                OutboxClaimService.finish(
                    db,
                    event_id=event.id,
                    worker_id=worker_id,
                    status="completed",
                )
                db.commit()
                return {
                    "event_id": event.id,
                    "run_id": existing.id,
                    "status": existing.status,
                    "idempotent_replay": True,
                }

            run = CaseAnalysisRun(
                id=str(uuid.uuid4()),
                case_id=case.id,
                case_profile_id=profile.id,
                map_snapshot_id=snapshot.id,
                algorithm_version=CASE_INSIGHT_ALGORITHM_VERSION,
                status="running",
                information_gaps=[],
            )
            db.add(run)
            db.flush()
            CaseInsightService._activate_run_hypotheses(db, run)

            if case.latitude is None or case.longitude is None:
                run.status = "degraded"
                run.summary = "证据不足，未生成空间候选。"
                run.information_gaps = ["案件缺少经纬度，无法执行案件—地图空间融合"]
                hypotheses: list[dict[str, Any]] = []
            else:
                hypotheses = CaseInsightService._build_candidates(db, case, profile, snapshot)
                run.status = "completed" if hypotheses else "degraded"
                run.summary = (
                    f"基于案件画像、地图版本和算法版本生成 {len(hypotheses)} 项待核验候选。"
                    if hypotheses
                    else "当前证据不足，未生成候选。"
                )
                run.information_gaps = [] if hypotheses else ["当前范围内缺少可支撑推断的生产设施、道路或历史案件"]

            db.refresh(profile)
            db.refresh(snapshot)
            from app.services.case_pipeline_service import CasePipelineService

            if (
                not profile.is_current
                or snapshot.status != "current"
                or CasePipelineService.source_hash(db, case) != profile.source_hash
            ):
                db.rollback()
                current_event = db.query(OutboxEvent).filter(
                    OutboxEvent.id == event_id,
                    OutboxEvent.worker_id == worker_id,
                ).first()
                if current_event:
                    OutboxClaimService.finish(
                        db,
                        event_id=event_id,
                        worker_id=worker_id,
                        status="superseded",
                    )
                    db.commit()
                return {
                    "event_id": event_id,
                    "status": "superseded",
                    "idempotent_replay": False,
                }

            for rank, candidate in enumerate(hypotheses[:3], start=1):
                db.add(
                    CaseHypothesis(
                        id=str(uuid.uuid4()),
                        analysis_run_id=run.id,
                        case_id=case.id,
                        rank=rank,
                        status="candidate",
                        boundary="仅为区域级候选，必须由人工结合现场证据判断，不进入正式案件事实。",
                        **candidate,
                    )
                )
            run.completed_at = datetime.now(timezone.utc)
            from app.services.case_result_service import CaseResultService

            CaseResultService.freeze_completed_inputs(db, profile, run)
            OutboxClaimService.finish(
                db,
                event_id=event.id,
                worker_id=worker_id,
                status="completed",
            )
            db.commit()
            return {
                "event_id": event.id,
                "run_id": run.id,
                "status": run.status,
                "candidate_count": len(hypotheses[:3]),
                "idempotent_replay": False,
            }
        except Exception as exc:
            db.rollback()
            failed = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
            if failed and failed.worker_id == worker_id:
                OutboxClaimService.finish(
                    db,
                    event_id=event_id,
                    worker_id=worker_id,
                    status="retry" if failed.attempts < 3 else "failed",
                    error=str(exc)[:2000],
                    available_at=datetime.now(timezone.utc)
                    + timedelta(seconds=min(60, 2 ** failed.attempts)),
                )
                db.commit()
            if isinstance(exc, OutboxClaimLostError):
                return {"event_id": event_id, "status": "lease_lost"}
            raise

    @staticmethod
    def _activate_run_hypotheses(db: Session, run: CaseAnalysisRun) -> None:
        (
            db.query(CaseHypothesis)
            .filter(
                CaseHypothesis.case_id == run.case_id,
                CaseHypothesis.analysis_run_id != run.id,
                CaseHypothesis.status == "candidate",
            )
            .update({CaseHypothesis.status: "superseded"}, synchronize_session=False)
        )
        (
            db.query(CaseHypothesis)
            .filter(CaseHypothesis.analysis_run_id == run.id)
            .update({CaseHypothesis.status: "candidate"}, synchronize_session=False)
        )

    @staticmethod
    def process_pending(db: Session, limit: int = 30) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        events = (
            db.query(OutboxEvent)
            .filter(
                OutboxEvent.event_type == "case.insights.requested",
                or_(
                    and_(
                        OutboxEvent.status.in_(("pending", "retry")),
                        OutboxEvent.available_at <= now,
                    ),
                    and_(
                        OutboxEvent.status == "processing",
                        or_(
                            OutboxEvent.lease_until.is_(None),
                            OutboxEvent.lease_until <= now,
                        ),
                    ),
                ),
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(max(1, min(limit, 100)))
            .all()
        )
        completed = 0
        failed = 0
        for event in events:
            try:
                CaseInsightService.process_event(db, event.id)
                completed += 1
            except Exception:
                failed += 1
        return {"selected": len(events), "completed": completed, "failed": failed}

    @staticmethod
    def reconcile_current_pairs(db: Session, limit: int = 500) -> dict[str, int]:
        """补偿画像发布与地图发布交错时遗漏的当前版本组合。"""
        if db.info.get('authorized_area_ids') is not None:
            raise PermissionError('case_insight_reconcile_background_session_required')
        # Reuse the durable background cursor table with an independent key.
        # Cursor advancement and enqueues commit together; unchanged early cases
        # must not starve later cases after a new map is published.
        dialect = db.get_bind().dialect.name
        if dialect == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        elif dialect == 'sqlite':
            from sqlalchemy.dialects.sqlite import insert
        else:
            raise ValueError('unsupported_case_insight_database')
        cursor_name = 'case-insight-pairs'
        db.execute(insert(CaseHistoryIndexCursor).values(
            name=cursor_name, after_case_id=0, completed_passes=0).on_conflict_do_nothing())
        db.execute(update(CaseHistoryIndexCursor).where(CaseHistoryIndexCursor.name == cursor_name)
                   .values(updated_at=datetime.now(timezone.utc)))
        cursor = db.scalar(select(CaseHistoryIndexCursor).where(
            CaseHistoryIndexCursor.name == cursor_name).execution_options(populate_existing=True))
        size = max(1, min(limit, 5000))
        snapshots = {
            item.operational_area_id: item
            for item in db.query(MapSnapshot)
            .filter(MapSnapshot.status == "current")
            .order_by(MapSnapshot.operational_area_id, MapSnapshot.published_at.desc())
            .all()
        }
        rows = (
            db.query(CaseAnalysisProfile, Case)
            .join(Case, Case.id == CaseAnalysisProfile.case_id)
            .filter(
                CaseAnalysisProfile.is_current.is_(True),
                Case.operational_area_id.isnot(None),
                Case.id > cursor.after_case_id,
            )
            .order_by(Case.id)
            .limit(size + 1)
            .all()
        )
        paired = 0
        missing = 0
        for profile, case in rows[:size]:
            snapshot = snapshots.get(case.operational_area_id)
            if snapshot is None:
                continue
            paired += 1
            existing = (
                db.query(CaseAnalysisRun.id)
                .filter(
                    CaseAnalysisRun.case_profile_id == profile.id,
                    CaseAnalysisRun.map_snapshot_id == snapshot.id,
                    CaseAnalysisRun.algorithm_version == CASE_INSIGHT_ALGORITHM_VERSION,
                )
                .first()
            )
            if existing is None:
                missing += 1
            CaseInsightService.enqueue_analysis(db, profile, snapshot)
        if len(rows) > size:
            cursor.after_case_id = rows[size - 1][1].id
        else:
            cursor.after_case_id = 0
            cursor.completed_passes += 1
        after_case_id, completed_passes = cursor.after_case_id, cursor.completed_passes
        db.commit()
        return {"scanned": min(len(rows), size), "paired": paired, "missing_pairs": missing,
                "after_case_id": after_case_id, "completed_passes": completed_passes}

    @staticmethod
    def record_feedback(
        db: Session,
        *,
        hypothesis_id: str,
        decision: str,
        note: str | None,
        created_by: int | None,
    ) -> HypothesisFeedback:
        hypothesis = db.query(CaseHypothesis).filter(CaseHypothesis.id == hypothesis_id).first()
        if not hypothesis:
            raise ValueError("hypothesis_not_found")
        if decision not in {"useful", "not_useful", "insufficient_information"}:
            raise ValueError("invalid_feedback")
        feedback = HypothesisFeedback(
            hypothesis_id=hypothesis.id,
            decision=decision,
            note=(note or "").strip()[:2000] or None,
            created_by=created_by,
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)
        return feedback

    _build_candidates = staticmethod(DualDomainV34._build_candidates)
    _source_candidates = staticmethod(DualDomainV34._source_candidates)
    _storage_candidates = staticmethod(DualDomainV34._storage_candidates)
    _activity_candidate = staticmethod(DualDomainV34._activity_candidate)
    _route_candidates = staticmethod(DualDomainV34._route_candidates)
    _confidence = staticmethod(DualDomainV34._confidence)
    _source_asset_id = staticmethod(DualDomainV34._source_asset_id)
    _point_region = staticmethod(DualDomainV34._point_region)

    @staticmethod
    def run_to_dict(db: Session, run: CaseAnalysisRun) -> dict[str, Any]:
        hypotheses = (
            db.query(CaseHypothesis)
            .filter(CaseHypothesis.analysis_run_id == run.id)
            .order_by(CaseHypothesis.rank)
            .all()
        )
        return {
            "id": run.id,
            "case_id": run.case_id,
            "case_profile_id": run.case_profile_id,
            "map_snapshot_id": run.map_snapshot_id,
            "algorithm_version": run.algorithm_version,
            "status": run.status,
            "summary": run.summary,
            "information_gaps": run.information_gaps,
            "completed_at": run.completed_at,
            "hypotheses": [CaseInsightService.hypothesis_to_dict(item) for item in hypotheses],
        }

    @staticmethod
    def hypothesis_to_dict(item: CaseHypothesis) -> dict[str, Any]:
        return {
            "id": item.id,
            "analysis_run_id": item.analysis_run_id,
            "case_id": item.case_id,
            "hypothesis_type": item.hypothesis_type,
            "rank": item.rank,
            "title": item.title,
            "claim": item.claim,
            "score": item.score,
            "confidence": item.confidence,
            "region": item.region,
            "evidence_refs": item.evidence_refs,
            "supporting_evidence": item.supporting_evidence,
            "counter_evidence": item.counter_evidence,
            "information_gaps": item.information_gaps,
            "score_components": item.score_components,
            "status": item.status,
            "boundary": item.boundary,
            "created_at": item.created_at,
        }
