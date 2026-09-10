"""案件画像与统一地图的确定性融合研判。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis, HypothesisFeedback
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature
from app.repositories.spatial_repository import SpatialRepository
from app.services.outbox_claim_service import OutboxClaimLostError, OutboxClaimService


CASE_INSIGHT_ALGORITHM_VERSION = "dual-domain-3.4.0"
SOURCE_TYPES = {"well", "pipeline_node", "station", "valve", "production_target"}
STORAGE_TYPES = {"storage", "oil_depot", "village", "residential", "settlement"}
ROAD_TYPES = {"road", "path", "access_road", "internal_route", "temporary_route"}


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
            )
            .order_by(Case.id)
            .limit(max(1, min(limit, 5000)))
            .all()
        )
        paired = 0
        missing = 0
        for profile, case in rows:
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
        db.commit()
        return {"scanned": len(rows), "paired": paired, "missing_pairs": missing}

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

    @staticmethod
    def _build_candidates(
        db: Session,
        case: Case,
        profile: CaseAnalysisProfile,
        snapshot: MapSnapshot,
    ) -> list[dict[str, Any]]:
        candidates = []
        candidates.extend(CaseInsightService._source_candidates(db, case, profile, snapshot))
        candidates.extend(CaseInsightService._storage_candidates(db, case, profile, snapshot))
        activity = CaseInsightService._activity_candidate(db, case, profile, snapshot)
        if activity:
            candidates.append(activity)
        candidates.extend(CaseInsightService._route_candidates(db, case, profile, snapshot))
        candidates.sort(key=lambda item: (-item["score"], item["hypothesis_type"], item["title"]))
        return candidates[:3]

    @staticmethod
    def _source_candidates(db: Session, case: Case, profile: CaseAnalysisProfile, snapshot: MapSnapshot) -> list[dict[str, Any]]:
        nearby = SpatialRepository.nearby_assets(
            db,
            latitude=case.latitude,
            longitude=case.longitude,
            asset_types=SOURCE_TYPES,
            radius_km=20,
            operational_area_id=case.operational_area_id or snapshot.operational_area_id,
            snapshot_id=snapshot.id,
            limit=10,
        )
        if not nearby:
            return []
        scored_assets = []
        for candidate_asset, candidate_distance in nearby:
            attributes = candidate_asset.attributes or {}
            distance_score = max(0.0, 80.0 - candidate_distance * 8)
            oil_match = (
                10.0
                if case.oil_type and attributes.get("oil_type") == case.oil_type
                else 0.0
            )
            try:
                production_output = float(attributes.get("production_output") or 0)
            except (TypeError, ValueError):
                production_output = 0.0
            production = 10.0 if production_output >= 80 else 0.0
            score = round(min(100.0, distance_score + oil_match + production), 2)
            scored_assets.append(
                (
                    -score,
                    candidate_distance,
                    CaseInsightService._source_asset_id(candidate_asset),
                    candidate_asset,
                    distance_score,
                    oil_match,
                    production,
                )
            )
        (
            negative_score,
            distance,
            _,
            asset,
            distance_score,
            oil_match,
            production,
        ) = min(scored_assets)
        score = -negative_score
        counter = ["空间接近不等同于已确认盗取来源"]
        if not asset.verified:
            counter.append("该设施尚未通过内部来源核验")
        gaps = [] if case.oil_type else ["案件未记录油品类型，无法核验油品匹配"]
        return [{
            "hypothesis_type": "possible_source",
            "title": f"可能盗取来源候选：{asset.name}",
            "claim": f"该生产设施距案发点约 {distance:.2f} 公里，建议作为来源核查候选。",
            "score": score,
            "confidence": CaseInsightService._confidence(score),
            "region": CaseInsightService._point_region(asset.latitude, asset.longitude, 500),
            "evidence_refs": [f"case_profile:{profile.id}", f"map_asset:{CaseInsightService._source_asset_id(asset)}@snapshot:{snapshot.id}"],
            "supporting_evidence": [f"设施与案发点距离约 {distance:.2f} 公里", f"设施类型为 {asset.asset_type}"],
            "counter_evidence": counter,
            "information_gaps": gaps,
            "score_components": {"distance": round(distance_score, 2), "oil_match": oil_match, "production": production},
        }]

    @staticmethod
    def _storage_candidates(db: Session, case: Case, profile: CaseAnalysisProfile, snapshot: MapSnapshot) -> list[dict[str, Any]]:
        nearby = SpatialRepository.nearby_assets(
            db,
            latitude=case.latitude,
            longitude=case.longitude,
            asset_types=STORAGE_TYPES,
            radius_km=15,
            operational_area_id=case.operational_area_id or snapshot.operational_area_id,
            snapshot_id=snapshot.id,
            limit=10,
        )
        if not nearby:
            return []
        asset, distance = nearby[0]
        score = round(max(20.0, 72.0 - distance * 5 + (8 if asset.verified else 0)), 2)
        return [{
            "hypothesis_type": "storage_area",
            "title": f"囤储核查候选区：{asset.name}",
            "claim": f"该区域距案发点约 {distance:.2f} 公里，具备进一步核查的空间条件。",
            "score": score,
            "confidence": CaseInsightService._confidence(score),
            "region": CaseInsightService._point_region(asset.latitude, asset.longitude, 800),
            "evidence_refs": [f"case_profile:{profile.id}", f"map_asset:{CaseInsightService._source_asset_id(asset)}@snapshot:{snapshot.id}"],
            "supporting_evidence": [f"距案发点约 {distance:.2f} 公里", f"地图类型为 {asset.asset_type}"],
            "counter_evidence": ["地图用途或聚落属性不能证明存在非法囤储行为"],
            "information_gaps": ["缺少现场核查、车辆停留或技防事件佐证"],
            "score_components": {"distance": round(max(0.0, 72.0 - distance * 5), 2), "verified": 8 if asset.verified else 0},
        }]

    @staticmethod
    def _activity_candidate(db: Session, case: Case, profile: CaseAnalysisProfile, snapshot: MapSnapshot) -> dict[str, Any] | None:
        historical = [
            (item, distance)
            for item, distance in SpatialRepository.nearby_cases(db, case=case, radius_km=30, limit=50)
            if item.case_type == case.case_type or (item.modus_operandi and item.modus_operandi == case.modus_operandi)
        ]
        if len(historical) < 2:
            return None
        selected = historical[:10]
        center_lat = sum(item.latitude for item, _ in selected) / len(selected)
        center_lon = sum(item.longitude for item, _ in selected) / len(selected)
        score = min(85.0, 45.0 + len(selected) * 8)
        return {
            "hypothesis_type": "activity_area",
            "title": "可能活动或落脚候选区",
            "claim": f"{len(selected)} 起同类或同手法历史案件在该区域形成空间聚集，建议按网格核查。",
            "score": score,
            "confidence": CaseInsightService._confidence(score),
            "region": CaseInsightService._point_region(center_lat, center_lon, 1500),
            "evidence_refs": [f"case_profile:{profile.id}", *[f"case:{item.id}" for item, _ in selected]],
            "supporting_evidence": [f"同类或同手法历史案件 {len(selected)} 起", "仅输出区域网格，不输出具体住址"],
            "counter_evidence": ["历史案件聚集可能由报案密度或生产设施分布造成"],
            "information_gaps": ["缺少人员活动、车辆停留或技防聚合数据"],
            "score_components": {"historical_case_count": len(selected), "cluster_score": score},
        }

    @staticmethod
    def _route_candidates(db: Session, case: Case, profile: CaseAnalysisProfile, snapshot: MapSnapshot) -> list[dict[str, Any]]:
        roads = SpatialRepository.nearby_assets(
            db,
            latitude=case.latitude,
            longitude=case.longitude,
            asset_types=ROAD_TYPES,
            radius_km=5,
            operational_area_id=case.operational_area_id or snapshot.operational_area_id,
            snapshot_id=snapshot.id,
            limit=10,
        )
        if not roads:
            return []
        asset, distance = roads[0]
        score = round(max(20.0, 68.0 - distance * 8), 2)
        return [{
            "hypothesis_type": "transfer_route",
            "title": f"可能转运方向候选：{asset.name}",
            "claim": f"该道路距案发点约 {distance:.2f} 公里，可作为转运方向核查线索。",
            "score": score,
            "confidence": CaseInsightService._confidence(score),
            "region": CaseInsightService._point_region(asset.latitude, asset.longitude, 500),
            "evidence_refs": [f"case_profile:{profile.id}", f"map_asset:{CaseInsightService._source_asset_id(asset)}@snapshot:{snapshot.id}"],
            "supporting_evidence": [f"道路与案发点距离约 {distance:.2f} 公里"],
            "counter_evidence": ["道路接近只说明通行条件，不能证明实际经过"],
            "information_gaps": ["缺少卡口、车辆或时段通行事件佐证"],
            "score_components": {"distance": score},
        }]

    @staticmethod
    def _confidence(score: float) -> float:
        return round(max(0.2, min(0.9, score / 100)), 2)

    @staticmethod
    def _source_asset_id(asset: JurisdictionAsset | MapSnapshotFeature) -> int:
        """返回原始地图要素编号，避免证据引用快照内部行号。"""
        return asset.asset_id if isinstance(asset, MapSnapshotFeature) else asset.id

    @staticmethod
    def _point_region(latitude: float, longitude: float, radius_m: int) -> dict[str, Any]:
        return {
            "type": "circle",
            "center": [round(longitude, 6), round(latitude, 6)],
            "radius_m": radius_m,
            "precision": "area_only",
        }

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
