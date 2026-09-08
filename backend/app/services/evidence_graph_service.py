"""v2.9 单案证据关系图谱：只读聚合、来源追溯与断链检测。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.agent_run import AgentArtifact, AgentRun
from app.models.case import Case, CaseEvidence, CasePerson, CaseVehicle
from app.models.chain_link import ChainLink
from app.models.jurisdiction import JurisdictionAsset
from app.models.knowledge_asset import KnowledgeAsset
from app.utils.geo import haversine_km


SAFE_REFERENCE = re.compile(r"^[a-z_]+:[A-Za-z0-9._-]+$")
PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ID_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
PLATE_PATTERN = re.compile(r"[\u4e00-\u9fff][A-Z][A-Z0-9]{5,6}")
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class EvidenceGraphError(ValueError):
    pass


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


class EvidenceGraphService:
    """把已有业务对象映射为证据路径，不产生新的业务判断或写操作。"""

    @staticmethod
    def build_case_graph(
        db: Session,
        case_id: int,
        *,
        well_radius_km: float = 5.0,
        max_context_nodes: int = 20,
    ) -> dict[str, Any]:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise EvidenceGraphError("case_not_found")

        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        review_queue: dict[str, dict[str, Any]] = {}

        def add_node(node: dict[str, Any]) -> None:
            nodes.setdefault(node["id"], node)

        def add_edge(edge: dict[str, Any]) -> None:
            edges.setdefault(edge["id"], edge)

        def add_issue(issue: dict[str, Any]) -> None:
            review_queue.setdefault(issue["id"], issue)

        root_id = f"case:{case.id}"
        sensitive_tokens = EvidenceGraphService._case_sensitive_tokens(db, case)
        add_node(
            EvidenceGraphService._node(
                root_id,
                "case",
                "subject",
                case.case_number,
                "当前案件",
                "recorded",
                1.0,
                root_id,
                False,
                {
                    "case_type": case.case_type or "未填写",
                    "status": case.status or "未填写",
                    "quality_score": case.quality_score,
                },
            )
        )

        EvidenceGraphService._add_case_facts(
            case,
            root_id,
            sensitive_tokens=sensitive_tokens,
            add_node=add_node,
            add_edge=add_edge,
            add_issue=add_issue,
        )
        reference_nodes = EvidenceGraphService._add_case_evidence(
            db,
            case,
            root_id,
            add_node=add_node,
            add_edge=add_edge,
        )
        EvidenceGraphService._add_knowledge_assets(
            db,
            case,
            root_id,
            reference_nodes=reference_nodes,
            add_node=add_node,
            add_edge=add_edge,
            add_issue=add_issue,
        )
        EvidenceGraphService._add_chain_context(
            db,
            case,
            add_node=add_node,
            add_edge=add_edge,
            add_issue=add_issue,
            max_context_nodes=max_context_nodes,
        )
        EvidenceGraphService._add_well_context(
            db,
            case,
            root_id,
            add_node=add_node,
            add_edge=add_edge,
            add_issue=add_issue,
            radius_km=well_radius_km,
            max_context_nodes=max_context_nodes,
        )
        EvidenceGraphService._add_agent_artifacts(
            db,
            case,
            root_id,
            reference_nodes=reference_nodes,
            add_node=add_node,
            add_edge=add_edge,
            add_issue=add_issue,
        )

        ordered_nodes = sorted(
            nodes.values(),
            key=lambda item: (
                EvidenceGraphService._layer_rank(item["layer"]),
                item["type"],
                item["id"],
            ),
        )
        ordered_edges = sorted(edges.values(), key=lambda item: item["id"])
        ordered_issues = sorted(
            review_queue.values(),
            key=lambda item: (
                SEVERITY_ORDER.get(item["severity"], 99),
                item["code"],
                item["id"],
            ),
        )
        summary = EvidenceGraphService._summary(
            ordered_nodes,
            ordered_edges,
            ordered_issues,
        )
        canonical = {
            "case_id": case.id,
            "well_radius_km": round(well_radius_km, 3),
            "nodes": ordered_nodes,
            "edges": ordered_edges,
            "review_queue": ordered_issues,
        }
        data_version = sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "case_id": case.id,
            "case_number": case.case_number,
            "generated_at": datetime.utcnow().isoformat(),
            "source_snapshot": {
                "algorithm": "sha256",
                "data_version": data_version,
                "scope": root_id,
            },
            "summary": summary,
            "nodes": ordered_nodes,
            "edges": ordered_edges,
            "review_queue": ordered_issues,
            "boundary": {
                "read_only": True,
                "statements": [
                    "图谱只读取现有案件、材料、井点、链条、Agent 轨迹和知识资产。",
                    "空间接近只表示参考条件，不能证明案件与井点存在事实关联。",
                    "未确认链条、Agent 派生结果和草稿知识资产必须由人工复核。",
                    "图谱不显示材料文件路径、人员身份、电话、证件号或车牌原文。",
                ],
            },
        }

    @staticmethod
    def _node(
        node_id: str,
        node_type: str,
        layer: str,
        label: str,
        subtitle: str,
        status: str,
        confidence: float,
        source_ref: str,
        is_human_confirmed: bool,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": node_id,
            "type": node_type,
            "layer": layer,
            "label": label,
            "subtitle": subtitle,
            "status": status,
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
            "source_ref": source_ref,
            "is_human_confirmed": is_human_confirmed,
            "detail": detail,
        }

    @staticmethod
    def _edge(
        edge_id: str,
        source: str,
        target: str,
        relation: str,
        label: str,
        status: str,
        confidence: float,
        evidence_refs: Iterable[str],
        boundary: str,
    ) -> dict[str, Any]:
        return {
            "id": edge_id,
            "source": source,
            "target": target,
            "relation": relation,
            "label": label,
            "status": status,
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
            "evidence_refs": list(dict.fromkeys(evidence_refs)),
            "boundary": boundary,
        }

    @staticmethod
    def _issue(
        issue_id: str,
        code: str,
        severity: str,
        title: str,
        detail: str,
        related_node_ids: list[str],
        next_action: str,
    ) -> dict[str, Any]:
        return {
            "id": issue_id,
            "code": code,
            "severity": severity,
            "title": title,
            "detail": detail,
            "related_node_ids": related_node_ids,
            "next_action": next_action,
        }

    @staticmethod
    def _add_case_facts(
        case: Case,
        root_id: str,
        *,
        sensitive_tokens: set[str],
        add_node,
        add_edge,
        add_issue,
    ) -> None:
        facts = [
            ("occurred_time", "发生时间", _iso(case.occurred_time), True),
            ("case_type", "案件类型", case.case_type, True),
            ("location", "发生地点", case.location, True),
            ("facility_type", "目标设施", case.facility_type, False),
            ("modus_operandi", "作案手法", case.modus_operandi, False),
        ]
        for key, label, raw_value, required in facts:
            value = EvidenceGraphService._redact_identifiers(
                raw_value,
                sensitive_tokens,
            )
            node_id = f"case_fact:{case.id}:{key}"
            if value:
                add_node(
                    EvidenceGraphService._node(
                        node_id,
                        "case_fact",
                        "source",
                        label,
                        value,
                        "recorded",
                        1.0,
                        f"case:{case.id}:{key}",
                        False,
                        {"field": key, "value": value},
                    )
                )
                add_edge(
                    EvidenceGraphService._edge(
                        f"edge:{root_id}:{node_id}",
                        root_id,
                        node_id,
                        "records",
                        "案件原始字段",
                        "recorded",
                        1.0,
                        [f"case:{case.id}:{key}"],
                        "字段来自当前案件记录，仍以原始业务材料为准。",
                    )
                )
            else:
                gap_id = f"gap:{case.id}:field:{key}"
                add_node(
                    EvidenceGraphService._node(
                        gap_id,
                        "gap",
                        "gap",
                        f"缺少{label}",
                        "待补充并人工核验",
                        "missing",
                        0.0,
                        f"case:{case.id}:{key}",
                        False,
                        {"field": key, "required": required},
                    )
                )
                add_edge(
                    EvidenceGraphService._edge(
                        f"edge:{root_id}:{gap_id}",
                        root_id,
                        gap_id,
                        "requires",
                        "待补证",
                        "inferred",
                        0.0,
                        [root_id],
                        "缺项只表示需要核验，不能据此推导案件事实。",
                    )
                )
                add_issue(
                    EvidenceGraphService._issue(
                        f"issue:{case.id}:field:{key}",
                        "missing_case_field",
                        "high" if required else "medium",
                        f"案件缺少{label}",
                        "证据路径缺少对应的案件原始字段。",
                        [root_id, gap_id],
                        "返回案件页面，根据原始材料补充并人工确认。",
                    )
                )

        coordinate_id = f"case_fact:{case.id}:coordinates"
        if case.latitude is not None and case.longitude is not None:
            add_node(
                EvidenceGraphService._node(
                    coordinate_id,
                    "case_fact",
                    "source",
                    "空间坐标",
                    "坐标已登记，精确值不在图谱摘要展示",
                    "recorded",
                    1.0,
                    f"case:{case.id}:coordinates",
                    False,
                    {"field": "coordinates", "value": "recorded"},
                )
            )
            add_edge(
                EvidenceGraphService._edge(
                    f"edge:{root_id}:{coordinate_id}",
                    root_id,
                    coordinate_id,
                    "records",
                    "案件空间字段",
                    "recorded",
                    1.0,
                    [f"case:{case.id}:coordinates"],
                    "图谱仅展示坐标已登记状态，不输出精确坐标。",
                )
            )
        else:
            gap_id = f"gap:{case.id}:coordinates"
            add_node(
                EvidenceGraphService._node(
                    gap_id,
                    "gap",
                    "gap",
                    "缺少案件坐标",
                    "无法计算案件与井点的空间参考",
                    "missing",
                    0.0,
                    f"case:{case.id}:coordinates",
                    False,
                    {"field": "coordinates", "required": True},
                )
            )
            add_edge(
                EvidenceGraphService._edge(
                    f"edge:{root_id}:{gap_id}",
                    root_id,
                    gap_id,
                    "requires",
                    "待补坐标",
                    "inferred",
                    0.0,
                    [root_id],
                    "没有坐标时不计算任何井点空间关系。",
                )
            )
            add_issue(
                EvidenceGraphService._issue(
                    f"issue:{case.id}:coordinates",
                    "missing_coordinates",
                    "high",
                    "案件坐标缺失",
                    "双域空间参考已停止计算。",
                    [root_id, gap_id],
                    "在案件页面按原始材料补录坐标并人工确认。",
                )
            )

    @staticmethod
    def _add_case_evidence(
        db: Session,
        case: Case,
        root_id: str,
        *,
        add_node,
        add_edge,
    ) -> set[str]:
        reference_nodes = {root_id, f"case:{case.case_number}"}
        evidence_items = (
            db.query(CaseEvidence)
            .filter(CaseEvidence.case_id == case.id)
            .order_by(CaseEvidence.id.asc())
            .limit(30)
            .all()
        )
        for item in evidence_items:
            node_id = f"case_evidence:{item.id}"
            reference_nodes.add(node_id)
            add_node(
                EvidenceGraphService._node(
                    node_id,
                    "case_evidence",
                    "source",
                    f"案件材料 #{item.id}",
                    item.evidence_type or "未分类材料",
                    "recorded",
                    0.9,
                    node_id,
                    False,
                    {
                        "evidence_type": item.evidence_type,
                        "requirement_key": item.requirement_key,
                        "captured_at": _iso(item.captured_at),
                        "sensitive": bool(item.is_sensitive),
                    },
                )
            )
            add_edge(
                EvidenceGraphService._edge(
                    f"edge:{root_id}:{node_id}",
                    root_id,
                    node_id,
                    "has_evidence",
                    "登记材料",
                    "recorded",
                    0.9,
                    [root_id, node_id],
                    "图谱仅展示材料元数据，不读取或返回文件路径和正文。",
                )
            )
        return reference_nodes

    @staticmethod
    def _add_knowledge_assets(
        db: Session,
        case: Case,
        root_id: str,
        *,
        reference_nodes: set[str],
        add_node,
        add_edge,
        add_issue,
    ) -> None:
        asset_versions = (
            db.query(KnowledgeAsset)
            .filter(KnowledgeAsset.source_case_id == case.id)
            .order_by(
                KnowledgeAsset.asset_type.asc(),
                KnowledgeAsset.version.desc(),
                KnowledgeAsset.id.desc(),
            )
            .limit(100)
            .all()
        )
        assets = []
        seen_types: set[str] = set()
        for asset in asset_versions:
            if asset.asset_type in seen_types:
                continue
            seen_types.add(asset.asset_type)
            assets.append(asset)
        for asset in assets:
            node_id = f"knowledge_asset:{asset.id}"
            confirmed = asset.status == "confirmed"
            safe_title = EvidenceGraphService._knowledge_asset_label(asset)
            add_node(
                EvidenceGraphService._node(
                    node_id,
                    "knowledge_asset",
                    "conclusion",
                    safe_title,
                    f"{asset.asset_type} · v{asset.version}",
                    asset.status,
                    0.95 if confirmed else 0.45,
                    node_id,
                    confirmed,
                    {
                        "asset_type": asset.asset_type,
                        "version": asset.version,
                        "status": asset.status,
                        "source_data_version": asset.source_data_version,
                        "reviewed_at": _iso(asset.reviewed_at),
                    },
                )
            )
            refs = EvidenceGraphService._reference_ids(asset.evidence_refs)
            supported = False
            for index, ref in enumerate(refs):
                resolved = EvidenceGraphService._resolve_reference(
                    db,
                    ref,
                    reference_nodes,
                    case,
                    add_node,
                )
                if resolved:
                    supported = True
                    add_edge(
                        EvidenceGraphService._edge(
                            f"edge:support:{resolved}:{node_id}:{index}",
                            resolved,
                            node_id,
                            "supports_knowledge",
                            "支持该知识资产",
                            "confirmed" if confirmed else "inferred",
                            0.95 if confirmed else 0.45,
                            [resolved, node_id],
                            "知识资产状态由人工复核决定，来源引用不等同于结论自动成立。",
                        )
                    )
                else:
                    safe_ref = ref if SAFE_REFERENCE.fullmatch(ref) else "不可识别引用"
                    digest = sha256(ref.encode("utf-8")).hexdigest()[:10]
                    gap_id = f"gap:asset:{asset.id}:ref:{digest}"
                    add_node(
                        EvidenceGraphService._node(
                            gap_id,
                            "gap",
                            "gap",
                            "引用无法解析",
                            safe_ref,
                            "missing",
                            0.0,
                            safe_ref,
                            False,
                            {"reference": safe_ref, "asset_id": asset.id},
                        )
                    )
                    add_edge(
                        EvidenceGraphService._edge(
                            f"edge:{gap_id}:{node_id}",
                            gap_id,
                            node_id,
                            "missing_support",
                            "缺少可解析来源",
                            "inferred",
                            0.0,
                            [safe_ref, node_id],
                            "引用无法解析时，不得把该路径标记为证据完整。",
                        )
                    )
                    add_issue(
                        EvidenceGraphService._issue(
                            f"issue:asset:{asset.id}:ref:{digest}",
                            "unresolved_evidence_ref",
                            "high" if confirmed else "medium",
                            "知识资产存在失效引用",
                            f"{safe_title} 的来源引用无法映射到当前证据节点。",
                            [node_id, gap_id],
                            "核对原始材料和来源编号后重新生成资产版本。",
                        )
                    )
            if not refs:
                add_issue(
                    EvidenceGraphService._issue(
                        f"issue:asset:{asset.id}:empty",
                        "knowledge_asset_without_evidence",
                        "high",
                        "知识资产缺少证据引用",
                        f"{safe_title} 没有可追溯来源。",
                        [node_id],
                        "补充来源并重新生成，不得直接确认当前版本。",
                    )
                )
            if not confirmed and asset.status != "archived":
                add_issue(
                    EvidenceGraphService._issue(
                        f"issue:asset:{asset.id}:draft",
                        "draft_knowledge_asset",
                        "medium",
                        "知识资产尚未人工确认",
                        f"{safe_title} 当前状态为 {asset.status}。",
                        [node_id],
                        "核对事实、推断、适用边界和来源后由人工处理。",
                    )
                )
            if confirmed and not supported:
                add_issue(
                    EvidenceGraphService._issue(
                        f"issue:asset:{asset.id}:broken",
                        "confirmed_asset_without_resolved_source",
                        "high",
                        "已确认资产证据链断开",
                        f"{safe_title} 已确认，但当前没有可解析来源。",
                        [node_id],
                        "暂停作为正式依据，核对来源变化并重新生成版本。",
                    )
                )

    @staticmethod
    def _add_chain_context(
        db: Session,
        case: Case,
        *,
        add_node,
        add_edge,
        add_issue,
        max_context_nodes: int,
    ) -> None:
        links = (
            db.query(ChainLink)
            .filter(
                ChainLink.status != "rejected",
                or_(ChainLink.case_id_a == case.id, ChainLink.case_id_b == case.id),
            )
            .order_by(ChainLink.confidence.desc(), ChainLink.id.asc())
            .limit(max_context_nodes)
            .all()
        )
        related_ids = {
            link.case_id_b if link.case_id_a == case.id else link.case_id_a
            for link in links
        }
        related = {
            item.id: item
            for item in db.query(Case).filter(Case.id.in_(related_ids)).all()
        } if related_ids else {}
        for link in links:
            related_id = link.case_id_b if link.case_id_a == case.id else link.case_id_a
            related_case = related.get(related_id)
            if not related_case:
                continue
            related_node_id = f"case:{related_case.id}"
            add_node(
                EvidenceGraphService._node(
                    related_node_id,
                    "related_case",
                    "context",
                    related_case.case_number,
                    related_case.facility_type or related_case.case_type or "关联案件",
                    "confirmed" if link.status == "confirmed" else "inferred",
                    link.confidence,
                    related_node_id,
                    link.status == "confirmed",
                    {
                        "case_type": related_case.case_type,
                        "facility_type": related_case.facility_type,
                        "occurred_time": _iso(related_case.occurred_time),
                    },
                )
            )
            relation = "chain_relation" if link.status == "confirmed" else "chain_hypothesis"
            boundary = (
                "该链条关系已经人工确认，仍应结合原始案卷使用。"
                if link.status == "confirmed"
                else "该链条仅为时空和环节条件形成的假设，必须人工确认后才能作为正式关系。"
            )
            add_edge(
                EvidenceGraphService._edge(
                    f"edge:chain:{link.id}",
                    f"case:{link.case_id_a}",
                    f"case:{link.case_id_b}",
                    relation,
                    "人工确认链条" if link.status == "confirmed" else "待确认链条假设",
                    "confirmed" if link.status == "confirmed" else "inferred",
                    link.confidence,
                    [
                        f"case:{link.case_id_a}",
                        f"case:{link.case_id_b}",
                        f"chain_link:{link.id}",
                    ],
                    boundary,
                )
            )
            if link.status != "confirmed":
                add_issue(
                    EvidenceGraphService._issue(
                        f"issue:chain:{link.id}",
                        "inferred_chain_link",
                        "medium",
                        "链条关系尚未人工确认",
                        f"{case.case_number} 与 {related_case.case_number} 的关系仍是辅助假设。",
                        [f"case:{case.id}", related_node_id],
                        "回到链条关联面板核对时空条件和案卷材料。",
                    )
                )

    @staticmethod
    def _add_well_context(
        db: Session,
        case: Case,
        root_id: str,
        *,
        add_node,
        add_edge,
        add_issue,
        radius_km: float,
        max_context_nodes: int,
    ) -> None:
        if case.latitude is None or case.longitude is None:
            return
        candidates = (
            db.query(JurisdictionAsset)
            .filter(
                JurisdictionAsset.asset_type == "well",
                JurisdictionAsset.status == "active",
                JurisdictionAsset.latitude.isnot(None),
                JurisdictionAsset.longitude.isnot(None),
            )
            .limit(1000)
            .all()
        )
        nearby: list[tuple[float, JurisdictionAsset]] = []
        for asset in candidates:
            distance = haversine_km(
                case.latitude,
                case.longitude,
                asset.latitude,
                asset.longitude,
            )
            if distance <= radius_km:
                nearby.append((distance, asset))
        nearby.sort(key=lambda item: (item[0], item[1].id))
        production_outputs = [
            output
            for _, item in nearby
            if (output := EvidenceGraphService._production_output(item)) is not None
        ]
        max_output = max(production_outputs, default=None)
        for distance, asset in nearby[:max_context_nodes]:
            node_id = f"well:{asset.id}"
            is_high = EvidenceGraphService._is_high_production(asset, max_output)
            verified = bool(asset.verified)
            attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
            region = (
                attributes.get("作业区")
                or attributes.get("region")
                or attributes.get("area")
                or "未登记作业区"
            )
            add_node(
                EvidenceGraphService._node(
                    node_id,
                    "well",
                    "context",
                    asset.name,
                    "高产井空间参考" if is_high else "井点空间参考",
                    "verified" if verified else "contextual",
                    1.0 if verified else max(0.2, float(asset.confidence_score or 0.5)),
                    node_id,
                    verified,
                    {
                        "asset_type": "well",
                        "distance_km": round(distance, 3),
                        "verified": verified,
                        "is_high_production": is_high,
                        "region": region,
                        "coordinate_value": "withheld",
                    },
                )
            )
            add_edge(
                EvidenceGraphService._edge(
                    f"edge:spatial:{case.id}:{asset.id}",
                    root_id,
                    node_id,
                    "spatial_reference",
                    f"空间参考 {distance:.2f}km",
                    "contextual",
                    max(0.1, 1.0 - distance / max(radius_km, 0.001)),
                    [f"case:{case.id}:coordinates", node_id],
                    "空间接近只能作为核查参考，不能证明案件与该井点存在事实关联。",
                )
            )
            if not verified:
                add_issue(
                    EvidenceGraphService._issue(
                        f"issue:well:{asset.id}",
                        "unverified_well_reference",
                        "medium",
                        "井点坐标尚未人工核验",
                        f"{asset.name} 只能作为低置信空间参考。",
                        [node_id],
                        "由地图数据管家检查坐标来源并完成人工核验。",
                    )
                )

    @staticmethod
    def _add_agent_artifacts(
        db: Session,
        case: Case,
        root_id: str,
        *,
        reference_nodes: set[str],
        add_node,
        add_edge,
        add_issue,
    ) -> None:
        runs = db.query(AgentRun).order_by(AgentRun.created_at.desc()).limit(100).all()
        matched = [
            run
            for run in runs
            if isinstance(run.case_ids, list) and case.id in run.case_ids
        ][:10]
        if not matched:
            return
        run_ids = [run.id for run in matched]
        run_by_id = {run.id: run for run in matched}
        artifacts = (
            db.query(AgentArtifact)
            .filter(AgentArtifact.run_id.in_(run_ids))
            .order_by(AgentArtifact.created_at.desc(), AgentArtifact.id.asc())
            .limit(20)
            .all()
        )
        for artifact in artifacts:
            run = run_by_id[artifact.run_id]
            node_id = f"agent_artifact:{artifact.id}"
            status = "degraded" if run.status == "degraded" else "derived"
            add_node(
                EvidenceGraphService._node(
                    node_id,
                    "agent_artifact",
                    "analysis",
                    artifact.artifact_type,
                    f"Agent 运行 {run.id[:8]} · v{artifact.version}",
                    status,
                    0.5 if status == "derived" else 0.3,
                    node_id,
                    False,
                    {
                        "run_id": run.id,
                        "task_type": run.task_type,
                        "run_status": run.status,
                        "artifact_type": artifact.artifact_type,
                        "version": artifact.version,
                        "source_signature": artifact.source_signature,
                    },
                )
            )
            refs = EvidenceGraphService._reference_ids(artifact.evidence_refs)
            supported = False
            for index, ref in enumerate(refs):
                resolved = EvidenceGraphService._resolve_reference(
                    db,
                    ref,
                    reference_nodes,
                    case,
                    add_node,
                )
                if not resolved:
                    safe_ref = ref if SAFE_REFERENCE.fullmatch(ref) else "不可识别引用"
                    digest = sha256(ref.encode("utf-8")).hexdigest()[:10]
                    gap_id = f"gap:agent:{artifact.id}:ref:{digest}"
                    add_node(
                        EvidenceGraphService._node(
                            gap_id,
                            "gap",
                            "gap",
                            "Agent 引用无法解析",
                            safe_ref,
                            "missing",
                            0.0,
                            safe_ref,
                            False,
                            {"reference": safe_ref, "artifact_id": artifact.id},
                        )
                    )
                    add_edge(
                        EvidenceGraphService._edge(
                            f"edge:{gap_id}:{node_id}",
                            gap_id,
                            node_id,
                            "missing_agent_support",
                            "缺少 Agent 来源",
                            "inferred",
                            0.0,
                            [safe_ref, node_id],
                            "任一 Agent 引用无法解析时，都必须进入人工复核队列。",
                        )
                    )
                    add_issue(
                        EvidenceGraphService._issue(
                            f"issue:agent:{artifact.id}:ref:{digest}",
                            "unresolved_agent_evidence_ref",
                            "high",
                            "Agent 成果存在失效引用",
                            f"{artifact.artifact_type} 的一条来源无法映射到当前证据节点。",
                            [node_id, gap_id],
                            "核对运行轨迹与原始来源后重新生成，不采用失效引用支撑的部分。",
                        )
                    )
                    continue
                supported = True
                add_edge(
                    EvidenceGraphService._edge(
                        f"edge:agent-support:{resolved}:{artifact.id}:{index}",
                        resolved,
                        node_id,
                        "supports_agent_artifact",
                        "Agent 使用该来源",
                        "inferred",
                        0.5,
                        [resolved, node_id],
                        "Agent 成果是派生分析，不能替代来源事实和人工结论。",
                    )
                )
            if not supported:
                add_edge(
                    EvidenceGraphService._edge(
                        f"edge:agent:{case.id}:{artifact.id}",
                        root_id,
                        node_id,
                        "agent_analysis",
                        "派生分析待核验",
                        "inferred",
                        0.3,
                        [root_id],
                        "该 Agent 成果没有可解析证据引用，不得作为完整证据路径。",
                    )
                )
                add_issue(
                    EvidenceGraphService._issue(
                        f"issue:agent:{artifact.id}",
                        "agent_artifact_without_evidence",
                        "high",
                        "Agent 成果缺少证据引用",
                        f"{artifact.artifact_type} 无法回溯到案件字段或材料。",
                        [node_id],
                        "保留运行轨迹，补充来源后重新生成，不采用当前成果。",
                    )
                )

    @staticmethod
    def _reference_ids(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        refs: list[str] = []
        for item in value:
            if isinstance(item, dict):
                ref = item.get("id")
            else:
                ref = item
            if ref is not None and str(ref).strip():
                refs.append(str(ref).strip())
        return list(dict.fromkeys(refs))

    @staticmethod
    def _resolve_reference(
        db: Session,
        ref: str,
        known: set[str],
        case: Case,
        add_node,
    ) -> str | None:
        if ref in known:
            return f"case:{case.id}" if ref == f"case:{case.case_number}" else ref
        matched = re.fullmatch(r"(asset|area|well|map_asset):(\d+)", ref)
        if matched:
            asset = (
                db.query(JurisdictionAsset)
                .filter(JurisdictionAsset.id == int(matched.group(2)))
                .first()
            )
            if not asset:
                return None
            requested_type = matched.group(1)
            if requested_type == "well" and asset.asset_type != "well":
                return None
            if requested_type == "map_asset" and asset.asset_type == "well":
                return None
            verified = bool(asset.verified)
            node_type = "well" if asset.asset_type == "well" else "map_asset"
            canonical_id = f"{node_type}:{asset.id}"
            add_node(
                EvidenceGraphService._node(
                    canonical_id,
                    node_type,
                    "context",
                    asset.name,
                    "已引用地图要素",
                    "verified" if verified else "contextual",
                    1.0 if verified else max(0.2, float(asset.confidence_score or 0.5)),
                    canonical_id,
                    verified,
                    {
                        "asset_type": asset.asset_type,
                        "status": asset.status,
                        "verified": verified,
                        "referenced_as": ref,
                        "coordinate_value": "withheld",
                    },
                )
            )
            known.add(canonical_id)
            return canonical_id
        return None

    @staticmethod
    def _production_output(asset: JurisdictionAsset) -> float | None:
        attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
        for key in ("日产量", "daily_output", "production_output", "产量"):
            try:
                if attributes.get(key) not in (None, ""):
                    return float(attributes[key])
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _case_sensitive_tokens(db: Session, case: Case) -> set[str]:
        """只为遮蔽自由文本读取身份标识，标识本身绝不进入图谱结果。"""
        tokens: set[str] = set()
        people = (
            db.query(CasePerson.name, CasePerson.phone, CasePerson.id_number)
            .filter(CasePerson.case_id == case.id)
            .all()
        )
        vehicles = (
            db.query(CaseVehicle.plate_number)
            .filter(CaseVehicle.case_id == case.id)
            .all()
        )
        for row in [*people, *vehicles]:
            for value in row:
                token = str(value).strip() if value is not None else ""
                if len(token) >= 2:
                    tokens.add(token)

        identity_keys = {
            "name",
            "person_name",
            "phone",
            "mobile",
            "id_number",
            "identity_number",
            "plate_number",
            "license_plate",
            "姓名",
            "电话",
            "手机号",
            "证件号",
            "身份证号",
            "车牌",
            "车牌号",
        }

        def collect_legacy(value: Any, key: str | None = None) -> None:
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    collect_legacy(child_value, str(child_key).strip().lower())
            elif isinstance(value, list):
                for child in value:
                    collect_legacy(child, key)
            elif key in identity_keys and value is not None:
                token = str(value).strip()
                if len(token) >= 2:
                    tokens.add(token)

        collect_legacy(case.involved_persons)
        collect_legacy(case.vehicle_info)
        return tokens

    @staticmethod
    def _redact_identifiers(value: Any, sensitive_tokens: set[str]) -> str:
        text = str(value).strip() if value is not None else ""
        for token in sorted(sensitive_tokens, key=len, reverse=True):
            text = text.replace(token, "[已脱敏]")
        text = PHONE_PATTERN.sub("[手机号已脱敏]", text)
        text = ID_PATTERN.sub("[证件号已脱敏]", text)
        return PLATE_PATTERN.sub("[车牌已脱敏]", text)

    @staticmethod
    def _knowledge_asset_label(asset: KnowledgeAsset) -> str:
        labels = {
            "experience_card": "案件经验卡",
            "case_report": "案件研判报告",
        }
        return f"{labels.get(asset.asset_type, '知识资产')} · v{asset.version}"

    @staticmethod
    def _is_high_production(
        asset: JurisdictionAsset,
        max_output: float | None,
    ) -> bool:
        attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
        tags = set(asset.tags or []) if isinstance(asset.tags, list) else set()
        flag = (
            attributes.get("is_high_production")
            or attributes.get("high_production")
            or attributes.get("高产井")
        )
        if flag is True or str(flag).strip().lower() in {"true", "yes", "1", "是"}:
            return True
        if {"high_production", "高产井", "高产"} & tags:
            return True
        output = EvidenceGraphService._production_output(asset)
        return bool(output is not None and max_output and output >= max_output * 0.8)

    @staticmethod
    def _summary(
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        claim_ids = {
            item["id"]
            for item in nodes
            if item["type"] in {"knowledge_asset", "agent_artifact"}
            and item["status"] != "archived"
        }
        supported_claims = {
            edge["target"]
            for edge in edges
            if edge["target"] in claim_ids
            and edge["relation"] in {"supports_knowledge", "supports_agent_artifact"}
            and edge["source"].startswith(
                ("case:", "case_evidence:", "well:", "map_asset:")
            )
        }
        if claim_ids:
            traceability_rate = round(len(supported_claims) / len(claim_ids) * 100)
        else:
            traceability_rate = 100
        if any(item["severity"] == "high" for item in issues):
            graph_health = "insufficient"
        elif issues:
            graph_health = "review_needed"
        else:
            graph_health = "complete"
        return {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "source_nodes": sum(item["layer"] == "source" for item in nodes),
            "confirmed_nodes": sum(item["status"] == "confirmed" for item in nodes),
            "inferred_nodes": sum(
                item["status"] in {"draft", "inferred", "derived", "degraded"}
                for item in nodes
            ),
            "gap_nodes": sum(item["layer"] == "gap" for item in nodes),
            "traceability_rate": traceability_rate,
            "graph_health": graph_health,
        }

    @staticmethod
    def _layer_rank(layer: str) -> int:
        return {
            "subject": 0,
            "source": 1,
            "context": 2,
            "analysis": 3,
            "conclusion": 4,
            "gap": 5,
        }.get(layer, 99)
