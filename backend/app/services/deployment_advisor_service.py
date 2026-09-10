"""全域态势摘要与最多三项可解释部署参考。"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.deployment_advisor import (
    DeploymentRecommendation,
    RecommendationFeedback,
    SituationBrief,
    TechDefenseEventAggregate,
    TechDefenseSource,
)
from app.models.map_foundation import MapSnapshot, OperationalArea
from app.services.case_insight_service import CASE_INSIGHT_ALGORITHM_VERSION


class DeploymentAdvisorService:
    """只产生部署参考，不创建巡逻、调查、抓捕或处置任务。"""

    @staticmethod
    def import_tech_summary(
        db: Session,
        *,
        source_key: str,
        source_name: str,
        operational_area_id: int,
        period_start: datetime,
        period_end: datetime,
        device_type: str,
        online_count: int,
        offline_count: int,
        alert_count: int,
        redacted_vehicle_event_count: int,
        disposition_summary: str | None,
    ) -> tuple[TechDefenseEventAggregate, bool]:
        area = db.query(OperationalArea).filter(OperationalArea.id == operational_area_id).first()
        if not area or area.status != "active":
            raise ValueError("operational_area_not_found")
        if period_end <= period_start:
            raise ValueError("invalid_period")
        source = (
            db.query(TechDefenseSource)
            .filter(
                TechDefenseSource.source_key == source_key.strip(),
                TechDefenseSource.operational_area_id == area.id,
            )
            .first()
        )
        if source is None:
            source = TechDefenseSource(
                source_key=source_key.strip(),
                name=source_name.strip(),
                operational_area_id=area.id,
                status="active",
            )
            db.add(source)
            db.flush()
        existing = (
            db.query(TechDefenseEventAggregate)
            .filter(
                TechDefenseEventAggregate.source_id == source.id,
                TechDefenseEventAggregate.period_start == period_start,
                TechDefenseEventAggregate.period_end == period_end,
                TechDefenseEventAggregate.device_type == device_type,
            )
            .first()
        )
        if existing:
            return existing, True
        aggregate = TechDefenseEventAggregate(
            source_id=source.id,
            operational_area_id=area.id,
            period_start=period_start,
            period_end=period_end,
            device_type=device_type,
            online_count=online_count,
            offline_count=offline_count,
            alert_count=alert_count,
            redacted_vehicle_event_count=redacted_vehicle_event_count,
            disposition_summary=(disposition_summary or "").strip()[:1000] or None,
        )
        db.add(aggregate)
        db.commit()
        db.refresh(aggregate)
        return aggregate, False

    @staticmethod
    def generate_brief(
        db: Session,
        *,
        operational_area_id: int,
        period_type: str,
        as_of: datetime,
    ) -> tuple[SituationBrief, bool]:
        if period_type not in {"daily", "weekly"}:
            raise ValueError("invalid_period_type")
        area = db.query(OperationalArea).filter(OperationalArea.id == operational_area_id).first()
        if not area or area.status != "active":
            raise ValueError("operational_area_not_found")
        end = DeploymentAdvisorService._aware(as_of)
        if period_type == "daily":
            start = end.replace(hour=0, minute=0, second=0, microsecond=0)
            valid_until = end + timedelta(days=1)
        else:
            day_start = end.replace(hour=0, minute=0, second=0, microsecond=0)
            start = day_start - timedelta(days=day_start.weekday())
            valid_until = end + timedelta(days=7)

        hypothesis_rows = (
            db.query(CaseHypothesis, CaseAnalysisRun)
            .join(CaseAnalysisRun, CaseAnalysisRun.id == CaseHypothesis.analysis_run_id)
            .join(
                CaseAnalysisProfile,
                CaseAnalysisProfile.id == CaseAnalysisRun.case_profile_id,
            )
            .join(MapSnapshot, MapSnapshot.id == CaseAnalysisRun.map_snapshot_id)
            .join(Case, Case.id == CaseHypothesis.case_id)
            .filter(
                Case.operational_area_id == area.id,
                CaseAnalysisRun.completed_at >= start,
                CaseAnalysisRun.completed_at <= end,
                CaseAnalysisRun.algorithm_version == CASE_INSIGHT_ALGORITHM_VERSION,
                CaseAnalysisRun.status == "completed",
                CaseAnalysisProfile.is_current.is_(True),
                MapSnapshot.status == "current",
                MapSnapshot.operational_area_id == area.id,
                CaseHypothesis.status == "candidate",
            )
            .order_by(CaseHypothesis.score.desc(), CaseHypothesis.id)
            .all()
        )
        tech_items = (
            db.query(TechDefenseEventAggregate)
            .filter(
                TechDefenseEventAggregate.operational_area_id == area.id,
                TechDefenseEventAggregate.period_end >= start,
                TechDefenseEventAggregate.period_end <= end,
            )
            .order_by(TechDefenseEventAggregate.period_end, TechDefenseEventAggregate.id)
            .all()
        )
        map_snapshot = (
            db.query(MapSnapshot)
            .filter(
                MapSnapshot.operational_area_id == area.id,
                MapSnapshot.status == "current",
            )
            .order_by(MapSnapshot.published_at.desc())
            .first()
        )
        fingerprint_payload = {
            "area": area.id,
            "period_type": period_type,
            "period_start": start.isoformat(),
            "hypotheses": [item.id for item, _ in hypothesis_rows],
            "tech": [item.id for item in tech_items],
            "map_snapshot": map_snapshot.id if map_snapshot else None,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = (
            db.query(SituationBrief)
            .filter(
                SituationBrief.operational_area_id == area.id,
                SituationBrief.period_type == period_type,
                SituationBrief.input_fingerprint == fingerprint,
            )
            .first()
        )
        if existing:
            return existing, True

        recommendations = DeploymentAdvisorService._recommendations(
            hypothesis_rows,
            tech_items,
            valid_until,
        )
        evidence_refs = [f"case_hypothesis:{item.id}" for item, _ in hypothesis_rows]
        evidence_refs.extend(f"tech_aggregate:{item.id}" for item in tech_items)
        if map_snapshot:
            evidence_refs.append(f"map_snapshot:{map_snapshot.id}")
        gaps = []
        if not tech_items:
            gaps.append("本周期无技防聚合数据，建议仅基于案件和地图候选判断")
        if not map_snapshot:
            gaps.append("厂区离线地图尚未发布")
        brief = SituationBrief(
            id=str(uuid.uuid4()),
            operational_area_id=area.id,
            period_type=period_type,
            period_start=start,
            period_end=end,
            input_fingerprint=fingerprint,
            status="completed" if recommendations else "no_change",
            algorithm_version="deployment-advisor-3.5.0",
            scope_policy_version="area-scope-3.6.0",
            summary=(
                f"本周期识别到 {len(hypothesis_rows)} 项案件候选和 {len(tech_items)} 组技防摘要，形成 {len(recommendations)} 项部署参考。"
                if recommendations
                else "本周期未发现足以形成新增部署建议的明显变化。"
            ),
            evidence_refs=evidence_refs,
            information_gaps=gaps,
        )
        db.add(brief)
        db.flush()
        for rank, item in enumerate(recommendations[:3], start=1):
            db.add(
                DeploymentRecommendation(
                    id=str(uuid.uuid4()),
                    brief_id=brief.id,
                    rank=rank,
                    valid_until=valid_until,
                    status="candidate",
                    auto_execution_allowed=False,
                    boundary="仅供人工部署参考，不自动创建巡逻、调查、抓捕或处置任务。",
                    **item,
                )
            )
        db.commit()
        db.refresh(brief)
        return brief, False

    @staticmethod
    def _recommendations(
        hypothesis_rows: list[tuple[CaseHypothesis, CaseAnalysisRun]],
        tech_items: list[TechDefenseEventAggregate],
        valid_until: datetime,
    ) -> list[dict[str, Any]]:
        del valid_until
        items: list[dict[str, Any]] = []
        seen_types = set()
        for hypothesis, _ in hypothesis_rows:
            if hypothesis.hypothesis_type in seen_types:
                continue
            seen_types.add(hypothesis.hypothesis_type)
            center = (hypothesis.region or {}).get("center") or []
            target = hypothesis.title
            if len(center) == 2:
                target = f"{center[1]:.2f}:{center[0]:.2f} 网格"
            items.append({
                "title": f"围绕{hypothesis.title}开展限时人工核查",
                "target_area": target,
                "time_window": "本建议有效期内，具体时段由值班人员结合现场安排",
                "suggested_action": "核对现有台账、现场条件和可用技防摘要，确认或排除该候选。",
                "resource_assumption": "不新增固定任务，使用现有核查力量，由人工决定是否采用。",
                "expected_effect": "优先核实高分候选，同时避免把空间接近误写为案件事实。",
                "evidence_refs": [f"case_hypothesis:{hypothesis.id}", *hypothesis.evidence_refs],
                "supporting_evidence": hypothesis.supporting_evidence,
                "information_gaps": hypothesis.information_gaps,
                "confidence": hypothesis.confidence,
            })
            if len(items) >= 2:
                break

        offline_total = sum(item.offline_count for item in tech_items)
        online_total = sum(item.online_count for item in tech_items)
        if offline_total > 0 and offline_total / max(1, offline_total + online_total) >= 0.2:
            relevant = [item for item in tech_items if item.offline_count > 0]
            items.append({
                "title": "优先核验技防覆盖缺口",
                "target_area": "当前厂区技防覆盖范围",
                "time_window": "下一次部署研判前",
                "suggested_action": "核验离线设备影响范围，并把无法提供佐证的区域标记为信息缺口。",
                "resource_assumption": "由设备维护或值班人员确认，不自动派发维修任务。",
                "expected_effect": "降低候选研判因技防中断造成的证据盲区。",
                "evidence_refs": [f"tech_aggregate:{item.id}" for item in relevant],
                "supporting_evidence": [f"在线 {online_total} 台、离线 {offline_total} 台"],
                "information_gaps": ["缺少设备级覆盖范围时只能判断总体缺口"],
                "confidence": round(min(0.9, 0.5 + offline_total / max(1, online_total + offline_total)), 2),
            })
        return items[:3]

    @staticmethod
    def record_feedback(
        db: Session,
        *,
        recommendation_id: str,
        decision: str,
        usefulness_score: int | None,
        note: str | None,
        created_by: int | None,
    ) -> RecommendationFeedback:
        recommendation = (
            db.query(DeploymentRecommendation)
            .join(
                SituationBrief,
                SituationBrief.id == DeploymentRecommendation.brief_id,
            )
            .filter(DeploymentRecommendation.id == recommendation_id)
            .first()
        )
        if not recommendation:
            raise ValueError("recommendation_not_found")
        if decision not in {"adopt_reference", "not_adopted", "insufficient_information"}:
            raise ValueError("invalid_feedback")
        if usefulness_score is not None and not 1 <= usefulness_score <= 5:
            raise ValueError("invalid_score")
        feedback = RecommendationFeedback(
            recommendation_id=recommendation.id,
            decision=decision,
            usefulness_score=usefulness_score,
            note=(note or "").strip()[:2000] or None,
            created_by=created_by,
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)
        return feedback

    @staticmethod
    def brief_to_dict(db: Session, brief: SituationBrief) -> dict[str, Any]:
        recommendations = (
            db.query(DeploymentRecommendation)
            .filter(DeploymentRecommendation.brief_id == brief.id)
            .order_by(DeploymentRecommendation.rank)
            .all()
        )
        return {
            "id": brief.id,
            "operational_area_id": brief.operational_area_id,
            "period_type": brief.period_type,
            "period_start": brief.period_start,
            "period_end": brief.period_end,
            "status": brief.status,
            "algorithm_version": brief.algorithm_version,
            "scope_policy_version": brief.scope_policy_version,
            "summary": brief.summary,
            "evidence_refs": brief.evidence_refs,
            "information_gaps": brief.information_gaps,
            "generated_at": brief.generated_at,
            "recommendations": [DeploymentAdvisorService.recommendation_to_dict(item) for item in recommendations],
        }

    @staticmethod
    def recommendation_to_dict(item: DeploymentRecommendation) -> dict[str, Any]:
        return {
            "id": item.id,
            "brief_id": item.brief_id,
            "rank": item.rank,
            "title": item.title,
            "target_area": item.target_area,
            "time_window": item.time_window,
            "suggested_action": item.suggested_action,
            "resource_assumption": item.resource_assumption,
            "expected_effect": item.expected_effect,
            "evidence_refs": item.evidence_refs,
            "supporting_evidence": item.supporting_evidence,
            "information_gaps": item.information_gaps,
            "confidence": item.confidence,
            "valid_until": item.valid_until,
            "status": item.status,
            "auto_execution_allowed": item.auto_execution_allowed,
            "boundary": item.boundary,
        }

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
