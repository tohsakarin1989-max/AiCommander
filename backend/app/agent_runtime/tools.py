"""Agent 可调用的白名单业务工具。

这些工具只读正式业务表。它们输出候选变更，但不在工具执行阶段落库。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
from itertools import combinations
import json
from typing import Any, Callable, Dict, List

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.services.case_quality_service import CaseQualityService
from app.services.jurisdiction_service import JurisdictionService
from app.utils.geo import haversine_km


class AgentToolNotAllowed(ValueError):
    pass


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _valid_coordinates(latitude: float | None, longitude: float | None) -> bool:
    return (
        latitude is not None
        and longitude is not None
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def _modus_tags(value: str | None) -> list[str]:
    """把可能含自由文本的作案手法压缩成不可逆业务标签。"""
    text = str(value or "")
    mapping = {
        "打孔": "管线打孔",
        "阀": "阀门放油",
        "罐车": "车辆运输",
        "车辆": "车辆运输",
        "内外": "内外勾连待核",
        "夜": "夜间活动",
        "破坏": "设施破坏",
    }
    return list(dict.fromkeys(label for keyword, label in mapping.items() if keyword in text))


@dataclass(frozen=True)
class AgentToolContext:
    case_ids: List[int]
    asset_ids: List[int]
    query: str
    days: int = 365
    radius_km: float = 1.5


def asset_source_signature(asset: JurisdictionAsset) -> str:
    payload = {
        "id": asset.id,
        "name": asset.name,
        "geometry_type": asset.geometry_type,
        "latitude": asset.latitude,
        "longitude": asset.longitude,
        "geometry": asset.geometry,
        "verified": bool(asset.verified),
        "status": asset.status,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


class AgentToolRegistry:
    """显式白名单；不存在动态 SQL、Shell、文件或任意网络工具。"""

    def __init__(self) -> None:
        self._tools: Dict[str, Callable[[Session, AgentToolContext], Dict[str, Any]]] = {
            "case_data_quality": self._case_data_quality,
            "map_data_quality": self._map_data_quality,
            "dual_domain_analysis": self._dual_domain_analysis,
        }

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def execute(
        self,
        tool_name: str,
        db: Session,
        context: AgentToolContext,
    ) -> Dict[str, Any]:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise AgentToolNotAllowed(f"Agent 工具未授权: {tool_name}")
        return tool(db, context)

    @staticmethod
    def _case_data_quality(db: Session, context: AgentToolContext) -> Dict[str, Any]:
        query = db.query(Case)
        if context.case_ids:
            query = query.filter(Case.id.in_(context.case_ids))
        cases = query.order_by(Case.occurred_time.desc()).limit(30).all()

        facts: List[Dict[str, Any]] = []
        findings: List[Dict[str, Any]] = []
        recommendations: List[str] = []
        evidence_refs: List[str] = []
        for case in cases:
            quality = CaseQualityService.evaluate_case(db, case)
            ref = f"case:{case.id}"
            evidence_refs.append(ref)
            facts.append({
                "case_id": case.id,
                "case_number": case.case_number,
                "quality_score": quality["score"],
                "quality_level": quality["level"],
                "missing_count": len(quality["missing_required"]),
                "warning_count": len(quality["warnings"]),
            })
            for item in quality["missing_required"]:
                findings.append({
                    "case_id": case.id,
                    "severity": "missing",
                    "field": item.get("field"),
                    "message": item.get("reason") or "字段缺失，待人工补录",
                    "evidence_ref": ref,
                })
            for item in quality["warnings"]:
                findings.append({
                    "case_id": case.id,
                    "severity": "warning",
                    "field": item.get("field"),
                    "message": item.get("message"),
                    "evidence_ref": ref,
                })
            recommendations.extend(quality["recommendations"])
            if (
                case.latitude is not None
                and case.longitude is not None
                and not _valid_coordinates(case.latitude, case.longitude)
            ):
                findings.append({
                    "case_id": case.id,
                    "severity": "invalid",
                    "field": "latitude/longitude",
                    "message": "案件坐标超出合法范围，必须待人工核验。",
                    "evidence_ref": ref,
                })

        for left, right in combinations(sorted(cases, key=lambda item: item.id), 2):
            left_time = _naive_utc(left.occurred_time)
            right_time = _naive_utc(right.occurred_time)
            same_location = bool(
                (left.location or "").strip()
                and (left.location or "").strip() == (right.location or "").strip()
            )
            same_type = bool(left.case_type and left.case_type == right.case_type)
            near_time = bool(
                left_time
                and right_time
                and abs((left_time - right_time).total_seconds()) <= 6 * 3600
            )
            if same_location and same_type and near_time:
                findings.append({
                    "case_ids": [left.id, right.id],
                    "severity": "duplicate_candidate",
                    "field": "case_record",
                    "message": "两条记录的类型、地点和时间窗口接近，疑似重复，待人工核验。",
                    "evidence_refs": [f"case:{left.id}", f"case:{right.id}"],
                })

        if not cases:
            recommendations.append("当前范围没有可质检案件，请确认筛选条件或先导入脱敏案件。")
        return {
            "tool": "case_data_quality",
            "facts": facts,
            "findings": findings,
            "inferences": [],
            "recommendations": list(dict.fromkeys(recommendations)),
            "information_gaps": [item["message"] for item in findings if item["severity"] == "missing"],
            "candidate_actions": [],
            "evidence_refs": evidence_refs,
            "boundary": [
                "质量结果仅表示录入完整性和一致性，不等同于案件事实认定。",
                "缺失字段只能由人工核实后补录，Agent 不编造内容。",
            ],
        }

    @staticmethod
    def _map_data_quality(db: Session, context: AgentToolContext) -> Dict[str, Any]:
        query = db.query(JurisdictionAsset)
        if context.asset_ids:
            query = query.filter(JurisdictionAsset.id.in_(context.asset_ids))
        assets = query.order_by(JurisdictionAsset.id.asc()).limit(500).all()
        aggregate = JurisdictionService.audit_data_quality(db)

        findings: List[Dict[str, Any]] = []
        candidates: List[Dict[str, Any]] = []
        evidence_refs: List[str] = []
        facts: List[Dict[str, Any]] = []
        for asset in assets:
            ref = f"asset:{asset.id}"
            evidence_refs.append(ref)
            facts.append({
                "asset_id": asset.id,
                "name": asset.name,
                "asset_type": asset.asset_type,
                "source": asset.source,
                "verified": bool(asset.verified),
                "has_coordinates": asset.latitude is not None and asset.longitude is not None,
            })
            reference_time = _naive_utc(asset.last_seen_at or asset.updated_at or asset.created_at)
            if reference_time and reference_time < datetime.utcnow() - timedelta(days=context.days):
                findings.append({
                    "asset_id": asset.id,
                    "severity": "stale",
                    "message": f"地图资源超过 {context.days} 天未更新，待人工核验现状。",
                    "evidence_ref": ref,
                })
            if asset.geometry_type != "point":
                if not asset.geometry:
                    findings.append({
                        "asset_id": asset.id,
                        "severity": "missing",
                        "message": "线面资源缺少几何数据，不能进入空间计算，必须人工核验。",
                        "evidence_ref": ref,
                    })
                continue
            if asset.latitude is None or asset.longitude is None:
                findings.append({
                    "asset_id": asset.id,
                    "severity": "missing",
                    "message": "坐标缺失，不能进入空间计算，必须人工核验。",
                    "evidence_ref": ref,
                })
                continue
            if not _valid_coordinates(asset.latitude, asset.longitude):
                findings.append({
                    "asset_id": asset.id,
                    "severity": "invalid",
                    "message": "坐标超出合法范围，必须人工核验。",
                    "evidence_ref": ref,
                })
                continue
            if not asset.verified:
                findings.append({
                    "asset_id": asset.id,
                    "severity": "unverified",
                    "message": "点位尚未人工核验。",
                    "evidence_ref": ref,
                })
                trimmed_name = (asset.name or "").strip()
                if trimmed_name and trimmed_name != asset.name:
                    candidates.append({
                        "action_type": "asset_patch",
                        "target_type": "jurisdiction_asset",
                        "target_id": asset.id,
                        "patch": {"name": trimmed_name},
                        "reason": "清理名称首尾空格",
                        "source_signature": asset_source_signature(asset),
                        "evidence_refs": [ref],
                    })
                expected_geometry = {
                    "type": "Point",
                    "coordinates": [asset.longitude, asset.latitude],
                }
                if asset.geometry != expected_geometry:
                    candidates.append({
                        "action_type": "asset_patch",
                        "target_type": "jurisdiction_asset",
                        "target_id": asset.id,
                        "patch": {"geometry": expected_geometry},
                        "reason": "使点位几何与已录入经纬度保持一致，不修改经纬度本身",
                        "source_signature": asset_source_signature(asset),
                        "evidence_refs": [ref],
                    })

        for left, right in combinations(sorted(assets, key=lambda item: item.id), 2):
            if left.asset_type != right.asset_type:
                continue
            same_external_id = bool(
                left.external_id
                and right.external_id
                and left.external_id == right.external_id
            )
            same_name = bool(
                (left.name or "").strip()
                and (left.name or "").strip() == (right.name or "").strip()
            )
            same_point = bool(
                _valid_coordinates(left.latitude, left.longitude)
                and _valid_coordinates(right.latitude, right.longitude)
                and haversine_km(
                    left.latitude,
                    left.longitude,
                    right.latitude,
                    right.longitude,
                ) <= 0.05
            )
            if same_external_id or (same_name and same_point):
                findings.append({
                    "asset_ids": [left.id, right.id],
                    "severity": "duplicate_candidate",
                    "message": "两条地图资源标识相同或同名且距离小于 50 米，疑似重复，待人工核验。",
                    "evidence_refs": [f"asset:{left.id}", f"asset:{right.id}"],
                })

        return {
            "tool": "map_data_quality",
            "facts": facts,
            "aggregate": aggregate,
            "findings": findings,
            "inferences": [],
            "recommendations": aggregate.get("recommendations", []),
            "information_gaps": [item["message"] for item in findings],
            "candidate_actions": candidates,
            "evidence_refs": evidence_refs,
            "boundary": [
                "坐标异常只标记为待核验，不作为已确认事实。",
                "候选修正不直接落库，必须经过管理员审批和写入开关校验。",
            ],
        }

    @staticmethod
    def _dual_domain_analysis(db: Session, context: AgentToolContext) -> Dict[str, Any]:
        query = db.query(Case)
        if context.case_ids:
            query = query.filter(Case.id.in_(context.case_ids))
        cases = query.order_by(Case.occurred_time.desc()).limit(10).all()

        facts: List[Dict[str, Any]] = []
        inferences: List[str] = []
        recommendations: List[str] = []
        gaps: List[str] = []
        evidence_refs: List[str] = []
        history_candidates = (
            db.query(Case)
            .filter(Case.latitude.isnot(None), Case.longitude.isnot(None))
            .order_by(Case.occurred_time.desc())
            .limit(500)
            .all()
        )
        for case in cases:
            case_ref = f"case:{case.id}"
            evidence_refs.append(case_ref)
            context_payload = JurisdictionService.build_case_risk_context(db, case.id)
            historical_cases: list[Case] = []
            case_time = _naive_utc(case.occurred_time)
            if _valid_coordinates(case.latitude, case.longitude) and case_time:
                for candidate in history_candidates:
                    if candidate.id == case.id:
                        continue
                    candidate_time = _naive_utc(candidate.occurred_time)
                    if not candidate_time:
                        continue
                    days_apart = abs((case_time - candidate_time).total_seconds()) / 86400
                    if days_apart > context.days:
                        continue
                    if haversine_km(
                        case.latitude,
                        case.longitude,
                        candidate.latitude,
                        candidate.longitude,
                    ) <= context.radius_km:
                        historical_cases.append(candidate)
            modus_tags = _modus_tags(case.modus_operandi or case.description)
            facts.append({
                "case_id": case.id,
                "case_number": case.case_number,
                "case_type": case.case_type,
                "occurred_time": case.occurred_time.isoformat() if case.occurred_time else None,
                "has_geo": context_payload["has_geo"],
                "risk_score": context_payload["risk_score"],
                "nearest": context_payload["nearest"],
                "historical_frequency": {
                    "case_count": len(historical_cases),
                    "days": context.days,
                    "radius_km": context.radius_km,
                },
                "modus_tags": modus_tags,
            })
            # JurisdictionService 的通用上下文会把作案方式、线索来源等原文
            # 拼进描述。Agent 外发摘要只保留确定性的空间条件和不可逆标签，
            # 避免自由文本经由推断列表绕过字段级脱敏。
            inferences.extend(
                item
                for item in context_payload["risk_conditions"]
                if not item.startswith(("已记录作案方式：", "发现来源为"))
            )
            if modus_tags:
                inferences.append(
                    f"案件 {case.id} 已形成作案手法标签：{'、'.join(modus_tags)}，仅用于条件检索。"
                )
            recommendations.extend(context_payload["prevention_opportunities"])
            if not context_payload["has_geo"]:
                gaps.append(f"案件 {case.id} 缺少经纬度，无法形成空间依据。")
            if historical_cases:
                inferences.append(
                    f"案件 {case.id} 周边 {context.radius_km} 公里、前后 {context.days} 天范围内"
                    f"有 {len(historical_cases)} 条历史案件记录，仅作为时空复盘条件。"
                )
                evidence_refs.extend(f"case:{item.id}" for item in historical_cases)
            for nearest in context_payload["nearest"].values():
                if nearest and nearest.get("asset", {}).get("id") is not None:
                    evidence_refs.append(f"asset:{nearest['asset']['id']}")

        if not cases:
            gaps.append("当前范围没有案件，无法开展案件与重点井时空融合研判。")
        return {
            "tool": "dual_domain_analysis",
            "facts": facts,
            "findings": [],
            "inferences": list(dict.fromkeys(inferences)),
            "recommendations": list(dict.fromkeys(recommendations)),
            "information_gaps": gaps,
            "candidate_actions": [],
            "evidence_refs": list(dict.fromkeys(evidence_refs)),
            "boundary": [
                "空间风险条件只用于案后复盘和防控参考，不是犯罪预测。",
                "相邻或相似条件不自动构成串并案结论。",
                "系统不自动派发巡逻或处置任务。",
            ],
        }
