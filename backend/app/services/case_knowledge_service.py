from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case import CaseEvidence
from app.models.conclusion import Conclusion
from app.models.knowledge_asset import KnowledgeAsset
from app.models.report import Report
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.case_profile_service import CaseProfileService


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else ([] if value is None else [value])


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {_text(val)}" for key, val in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text(item) for item in value)
    return str(value)


def _tokens(query: str) -> List[str]:
    cleaned = query.replace("，", " ").replace(",", " ").strip().lower()
    parts = [token.strip() for token in cleaned.split() if token.strip()]
    if len(parts) == 1 and re.fullmatch(r'[\u3400-\u9fff]{4,}', parts[0]):
        token = parts[0]
        return [token, *[token[index : index + 2] for index in range(0, len(token) - 1)]]
    return parts


def _score(query: str, haystack: str) -> float:
    normalized = haystack.lower()
    tokens = _tokens(query)
    if not tokens:
        return 0.1 if normalized else 0.0
    hits = sum(1 for token in tokens if token in normalized)
    return round(hits / len(tokens), 3)


def _now() -> str:
    return datetime.utcnow().isoformat()


class CaseKnowledgeService:
    """案件知识资产、证据型问答和材料辅助的确定性底座。"""

    @staticmethod
    def update_experience_card_status(
        db: Session,
        case_id: int,
        *,
        status: str,
        reviewer: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        if status not in {"draft", "confirmed", "archived"}:
            raise ValueError("invalid_experience_status")
        case = CaseProfileService.get_case(db, case_id)
        features = dict(case.features or {})
        intelligence = dict(features.get("intelligence") or {})
        card = dict(intelligence.get("experience_card") or {})
        if not card:
            raise ValueError("experience_card_not_found")
        card["manual_review_status"] = status
        card["reviewed_at"] = _now()
        if reviewer:
            card["reviewer"] = reviewer
        if note:
            card["review_note"] = note
        if status == "confirmed":
            card["asset_status"] = "active"
        elif status == "archived":
            card["asset_status"] = "archived"
        else:
            card["asset_status"] = "draft"
        intelligence["experience_card"] = card
        features["intelligence"] = intelligence
        case.features = features
        db.commit()
        db.refresh(case)
        return card

    @staticmethod
    def list_experience_cards(db: Session, status: str = "confirmed", limit: int = 50) -> Dict[str, Any]:
        items = CaseKnowledgeService._experience_items(db, "", status=status, limit=limit, require_match=False)
        return {"items": items, "total": len(items), "status": status, "generated_at": _now()}

    @staticmethod
    def search_experience_cards(db: Session, query: str, status: str = "confirmed", limit: int = 20) -> Dict[str, Any]:
        items = CaseKnowledgeService._experience_items(db, query, status=status, limit=limit, require_match=bool(query.strip()))
        return {"items": items, "total": len(items), "query": query, "generated_at": _now()}

    @staticmethod
    def search(db: Session, query: str, case_id: Optional[int] = None, limit: int = 20) -> Dict[str, Any]:
        from app.services.legacy_history_search import history_candidates, merge_source_ranks
        if not 1 <= limit <= 20 or not query.strip() or len(query) > 2000:
            raise ValueError('invalid_knowledge_query')
        history, history_state = history_candidates(db, query, case_id, limit)
        candidates: List[Dict[str, Any]] = []

        for conclusion in CaseKnowledgeService._conclusion_query(db, case_id):
            text = _text([conclusion.summary, conclusion.evidence])
            score = _score(query, text)
            if score > 0:
                candidates.append({
                    "source_type": "conclusion",
                    "source_id": conclusion.id,
                    "title": f"结论 #{conclusion.id}",
                    "snippet": conclusion.summary or "结论摘要待补齐",
                    "score": score,
                    "route": f"/conclusions?conclusionId={conclusion.id}",
                    "evidence_refs": [
                        {"id": f"conclusion:{conclusion.id}", "kind": "conclusion", "summary": conclusion.summary or "结论"},
                        {"id": f"case:{conclusion.case_id}", "kind": "case", "summary": f"案件 #{conclusion.case_id}"},
                    ],
                })

        for report in CaseKnowledgeService._report_query(db, case_id):
            text = _text([report.content, report.consensus_points, report.disagreement_points, report.model_contributions])
            score = _score(query, text)
            if score > 0:
                content = _as_dict(report.content)
                candidates.append({
                    "source_type": "report",
                    "source_id": report.id,
                    "title": f"分析报告 #{report.id}",
                    "snippet": content.get("summary") or content.get("conclusions") or f"会议 {report.meeting_id} 报告",
                    "score": score,
                    "route": f"/reports?meetingId={report.meeting_id}" if report.meeting_id else f"/reports?reportId={report.id}",
                    "evidence_refs": [
                        {
                            "id": f"report:{report.id}",
                            "kind": "report",
                            "summary": content.get("summary") or f"报告 #{report.id}",
                        }
                    ],
                })

        items = merge_source_ranks(history, candidates, limit)
        return {
            "query": query,
            "items": items,
            "total": len(items),
            "insufficient_evidence": not items,
            "history": history_state,
            "state": history_state['state'],
            "boundary": "案件与已确认经验复用全库授权检索；报告、结论为兼容补充（各检查最近100条），不代表这些材料的全库检索。历史相似不是当前事实，不补造事实。",
        }

    @staticmethod
    def evidence_qa(db: Session, query: str, case_id: Optional[int] = None) -> Dict[str, Any]:
        search = CaseKnowledgeService.search(db, query, case_id=case_id, limit=5)
        results = search.get("items", [])
        if not results:
            return {
                "answer": ("检索尚未完成：当前只有部分结果，不能判断没有相关资料。" if search['state'] == 'partial'
                           else "本次条件下未找到可引用来源；历史报告和结论仅在兼容范围内检索。"),
                "facts": [],
                "inferences": [],
                "citations": [],
                "insufficient_evidence": True,
                "state": search['state'], "history": search['history'],
                "boundary": search['boundary'],
            }
        facts = [item["snippet"] for item in results[:3] if item.get("snippet")]
        citations = [
            ref
            for item in results
            for ref in item.get("evidence_refs", [])[:3]
        ][:8]
        return {
            "answer": "；".join(facts) or "已找到相关案件依据，需人工复核后形成正式表述。",
            "facts": facts,
            "inferences": [
                {
                    "claim": "可作为研判参考，但不能替代人工确认。",
                    "basis": [item.get("title") for item in results[:3]],
                    "confidence": "medium",
                }
            ],
            "citations": citations,
            "insufficient_evidence": False,
            "state": search['state'], "history": search['history'],
            "boundary": search['boundary'] + "回答只基于返回引用，不直接生成处置任务。",
        }

    @staticmethod
    def citation_assist(db: Session, query: str, case_id: Optional[int] = None) -> Dict[str, Any]:
        search = CaseKnowledgeService.search(db, query, case_id=case_id, limit=8)
        results = search.get("items", [])
        citations = [
            {
                "title": item["title"],
                "snippet": item["snippet"],
                "source_type": item["source_type"],
                "source_id": item["source_id"],
                "route": item["route"],
                "evidence_refs": item.get("evidence_refs", []),
            }
            for item in results
        ]
        return {
            "query": query,
            "citations": citations,
            "draft_lines": [f"{item['snippet']}（来源：{item['title']}）" for item in citations[:5]],
            "insufficient_evidence": not citations,
            "state": search['state'], "history": search['history'],
            "boundary": search['boundary'] + "引用助手只提供可回溯素材，报告正文仍需人工复核。",
        }

    @staticmethod
    def review_report(db: Session, report_id: int) -> Dict[str, Any]:
        report = db.query(Report).filter(Report.id == report_id).first()
        if not report:
            raise ValueError("report_not_found")
        content = _as_dict(report.content)
        findings: List[Dict[str, Any]] = []
        if not _as_list(report.consensus_points):
            findings.append({"type": "missing_basis", "severity": "high", "message": "报告缺少共识依据或事实引用。"})
        if not content.get("summary"):
            findings.append({"type": "missing_summary", "severity": "medium", "message": "报告摘要为空。"})
        if not _as_list(content.get("information_gaps")):
            findings.append({"type": "missing_gap_section", "severity": "medium", "message": "报告未列明资料缺口。"})
        if not findings:
            findings.append({"type": "manual_review", "severity": "low", "message": "报告仍需人工复核事实、推论和建议边界。"})
        return {
            "report_id": report.id,
            "findings": findings,
            "suggested_fixes": [item["message"] for item in findings],
            "manual_review_required": True,
            "boundary": "审稿结果不自动改写报告，不发布正式结论。",
        }

    @staticmethod
    def draft_conclusion(db: Session, case_id: int) -> Dict[str, Any]:
        profile = CaseProfileService.build_case_profile(db, case_id)
        facts = [
            f"案件编号：{profile['case']['case_number']}",
            f"发生地点：{profile['case'].get('location') or '未填写'}",
            f"案件类型：{profile['case'].get('case_type') or '未填写'}",
        ]
        quality_gaps = [
            item.get("label") or item.get("field") or str(item)
            for item in profile.get("quality_gaps", [])
            if isinstance(item, dict)
        ]
        experience = profile.get("experience_card") or {}
        inferences = [
            {
                "claim": experience.get("summary") or "案件具备研判价值，但需继续补齐依据。",
                "basis": [f"case:{case_id}", "case_profile"],
                "confidence": "medium" if experience else "low",
            }
        ]
        evidence_refs = CaseKnowledgeService._case_evidence_refs(profile)
        draft = CaseIntelligenceService.build_structured_ai_output(
            title=f"结论草稿：{profile['case']['case_number']}",
            output_type="case_conclusion_draft",
            facts=facts,
            inferences=inferences,
            recommendations=[
                {
                    "title": "补齐资料后复核",
                    "action": "围绕案件画像中的质量缺口和证据引用补齐材料，再提交人工审核。",
                    "basis": quality_gaps or ["案件画像"],
                    "priority": "medium",
                }
            ],
            information_gaps=quality_gaps or ["仍需人工复核事实引用和建议边界。"],
            evidence_refs=evidence_refs,
            boundary=[
                "结论草稿不自动发布。",
                "必须由人工确认事实、推论和建议后才能进入正式结论。",
            ],
        )
        return {
            "case_id": case_id,
            "status": "draft",
            "not_published": True,
            "facts": draft["facts"],
            "inferences": draft["inferences"],
            "recommendations": draft["recommendations"],
            "information_gaps": draft["information_gaps"],
            "evidence_refs": evidence_refs,
            "ai_output": draft,
            "manual_review_required": True,
        }

    @staticmethod
    def build_case_diagram(db: Session, case_id: int) -> Dict[str, Any]:
        profile = CaseProfileService.build_case_profile(db, case_id)
        case = profile["case"]
        nodes: List[Dict[str, Any]] = [
            {"id": f"case:{case_id}", "type": "case", "label": case["case_number"], "detail": case.get("description")},
            {"id": f"time:{case_id}", "type": "time", "label": case.get("occurred_time") or "发生时间未填"},
            {"id": f"location:{case_id}", "type": "location", "label": case.get("location") or "地点未填"},
        ]
        edges = [
            {"from": f"case:{case_id}", "to": f"time:{case_id}", "label": "发生时间"},
            {"from": f"case:{case_id}", "to": f"location:{case_id}", "label": "发生地点"},
        ]
        for collection, node_type, label_field in [
            ("vehicles", "vehicle", "plate_number"),
            ("persons", "person", "name"),
            ("evidence", "evidence", "title"),
        ]:
            for item in profile["related"].get(collection, [])[:8]:
                node_id = f"{node_type}:{item.get('id')}"
                nodes.append({"id": node_id, "type": node_type, "label": item.get(label_field) or item.get("vehicle_type") or node_type})
                edges.append({"from": f"case:{case_id}", "to": node_id, "label": node_type})
        experience = profile.get("experience_card") or {}
        if experience:
            nodes.append({"id": f"experience:{case_id}", "type": "experience", "label": "经验卡", "detail": experience.get("summary")})
            edges.append({"from": f"case:{case_id}", "to": f"experience:{case_id}", "label": "复盘沉淀"})
        return {"case_id": case_id, "nodes": nodes, "edges": edges, "boundary": "一案一图只展示已录入事实和已生成的候选资产。"}

    @staticmethod
    def curate_tags(db: Session, case_id: int, confirm: bool = False) -> Dict[str, Any]:
        case = CaseProfileService.get_case(db, case_id)
        tags = CaseIntelligenceService.build_case_tags(db, case).get("tags", [])
        recommended = [
            {
                "key": item.get("key"),
                "label": item.get("label"),
                "category": item.get("category"),
                "confidence": item.get("confidence"),
                "basis": item.get("basis") or [],
                "status": "candidate",
            }
            for item in tags
            if item.get("confidence", 0) >= 0.75
        ][:12]
        if confirm and recommended:
            CaseIntelligenceService.update_tag_overrides(db, case_id, added=recommended, removed_keys=[])
            applied = True
        else:
            applied = False
        return {
            "case_id": case_id,
            "recommended_tags": recommended,
            "merge_suggestions": CaseKnowledgeService._tag_merges(recommended),
            "low_confidence_tags": [item for item in tags if item.get("confidence", 1) < 0.75],
            "human_confirmation_required": True,
            "applied": applied,
            "boundary": "标签策展只给候选项，确认后才写入人工标签覆盖。",
        }

    @staticmethod
    def _experience_items(db: Session, query: str, *, status: str, limit: int, require_match: bool) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        dedicated_case_ids = {
            source_case_id
            for (source_case_id,) in db.query(KnowledgeAsset.source_case_id)
            .filter(KnowledgeAsset.asset_type == "experience_card")
            .distinct()
            .all()
        }
        assets = (
            db.query(KnowledgeAsset)
            .filter(
                KnowledgeAsset.asset_type == "experience_card",
                KnowledgeAsset.status == status,
            )
            .order_by(KnowledgeAsset.created_at.desc(), KnowledgeAsset.id.desc())
            .limit(500)
            .all()
        )
        for asset in assets:
            case = db.query(Case).filter(Case.id == asset.source_case_id).first()
            if not case:
                continue
            score = _score(query, _text(asset.content))
            if require_match and score <= 0:
                continue
            items.append(
                CaseKnowledgeService._experience_asset_result(case, asset, score)
            )

        for case in db.query(Case).order_by(Case.occurred_time.desc()).limit(500).all():
            if case.id in dedicated_case_ids:
                continue
            card = _as_dict(_as_dict(_as_dict(case.features).get("intelligence")).get("experience_card"))
            if card.get("manual_review_status") != status:
                continue
            score = _score(query, _text(card))
            if require_match and score <= 0:
                continue
            items.append(CaseKnowledgeService._experience_result(case, card, score))
        items.sort(key=lambda item: item.get("score", 0), reverse=True)
        return items[:limit]

    @staticmethod
    def _experience_asset_result(
        case: Case,
        asset: KnowledgeAsset,
        score: float,
    ) -> Dict[str, Any]:
        card = _as_dict(asset.content)
        return {
            "source_type": "experience_card",
            "source_id": asset.id,
            "asset_id": asset.id,
            "asset_version": asset.version,
            "case_id": case.id,
            "case_number": case.case_number,
            "title": asset.title,
            "summary": card.get("summary") or case.description or "经验卡摘要待补齐",
            "snippet": card.get("summary") or case.description or "经验卡摘要待补齐",
            "score": score,
            "manual_review_status": asset.status,
            "applicability_reason": "命中已确认经验卡，可作为同类已发生案件复盘参考。",
            "tags": _as_list(_as_dict(card.get("evidence_basis")).get("tags")),
            "route": f"/case-intelligence?caseId={case.id}",
            "evidence_refs": asset.evidence_refs or [],
            "boundary": card.get("boundary") or "经验卡只作为复盘参考。",
        }

    @staticmethod
    def _experience_result(case: Case, card: Dict[str, Any], score: float) -> Dict[str, Any]:
        return {
            "source_type": "experience_card",
            "source_id": case.id,
            "case_id": case.id,
            "case_number": case.case_number,
            "title": f"经验卡 {case.case_number}",
            "summary": card.get("summary") or case.description or "经验卡摘要待补齐",
            "snippet": card.get("summary") or case.description or "经验卡摘要待补齐",
            "score": score,
            "manual_review_status": card.get("manual_review_status"),
            "applicability_reason": "命中已确认经验卡，可作为同类已发生案件复盘参考。",
            "tags": _as_list(_as_dict(card.get("evidence_basis")).get("tags")),
            "route": f"/case-intelligence?caseId={case.id}",
            "evidence_refs": [
                {"id": f"case:{case.id}", "kind": "case", "summary": f"案件 {case.case_number}"},
                {"id": f"experience_card:{case.id}", "kind": "experience_card", "summary": card.get("summary") or "经验卡"},
            ],
            "boundary": card.get("boundary") or "经验卡只作为复盘参考。",
        }

    @staticmethod
    def _latest_experience_asset(
        db: Session,
        case_id: int,
        *,
        status: str,
    ) -> Optional[KnowledgeAsset]:
        return (
            db.query(KnowledgeAsset)
            .filter(
                KnowledgeAsset.asset_type == "experience_card",
                KnowledgeAsset.source_case_id == case_id,
                KnowledgeAsset.status == status,
            )
            .order_by(KnowledgeAsset.version.desc())
            .first()
        )

    @staticmethod
    def _has_experience_asset(db: Session, case_id: int) -> bool:
        return (
            db.query(KnowledgeAsset.id)
            .filter(
                KnowledgeAsset.asset_type == "experience_card",
                KnowledgeAsset.source_case_id == case_id,
            )
            .first()
            is not None
        )

    @staticmethod
    def _case_evidence_refs(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        refs = [
            {
                "id": f"case:{profile['case']['id']}",
                "kind": "case",
                "summary": f"案件 {profile['case']['case_number']}",
                "route": f"/cases?caseId={profile['case']['id']}",
            }
        ]
        refs.extend(
            {
                "id": f"case_evidence:{item.get('id')}",
                "kind": "case_evidence",
                "summary": item.get("title") or item.get("requirement_key") or "案件证据",
                "route": f"/cases?caseId={profile['case']['id']}",
            }
            for item in profile.get("related", {}).get("evidence", [])
            if item.get("id")
        )
        return refs

    @staticmethod
    def _case_evidence_refs_from_case(db: Session, case: Case) -> List[Dict[str, Any]]:
        refs = [
            {
                "id": f"case:{case.id}",
                "kind": "case",
                "summary": f"案件 {case.case_number}",
                "route": f"/cases?caseId={case.id}",
            }
        ]
        refs.extend(
            {
                "id": f"case_evidence:{item.id}",
                "kind": "case_evidence",
                "summary": item.title or item.requirement_key or "案件证据",
                "route": f"/cases?caseId={case.id}",
            }
            for item in db.query(CaseEvidence).filter(CaseEvidence.case_id == case.id).limit(8).all()
        )
        return refs

    @staticmethod
    def _conclusion_query(db: Session, case_id: Optional[int]) -> Iterable[Conclusion]:
        from app.services.case_result_access import CaseResultAccessError
        from app.services.conclusion_factory_service import ConclusionFactoryService

        query = db.query(Conclusion)
        if case_id is not None:
            query = query.filter(Conclusion.case_id == case_id)
        accessible = []
        for conclusion in query.order_by(Conclusion.id.desc()).limit(100):
            try:
                ConclusionFactoryService.require_conclusion_result_access(db, conclusion)
            except CaseResultAccessError:
                continue
            accessible.append(conclusion)
        return accessible

    @staticmethod
    def _report_query(db: Session, case_id: Optional[int] = None) -> Iterable[Report]:
        if case_id is None:
            return db.query(Report).order_by(Report.id.desc()).limit(100).all()
        from app.models.meeting import Meeting
        # Retain the documented legacy 100-report supplement, but never mix an
        # unrelated meeting into a case-filtered query. No text-similarity dedup.
        rows = (db.query(Report, Meeting.case_ids).join(Meeting, Report.meeting_id == Meeting.meeting_id)
                .order_by(Report.id.desc()).limit(100).all())
        return [report for report, identifiers in rows
                if isinstance(identifiers, list) and case_id in identifiers]

    @staticmethod
    def _tag_merges(tags: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: Dict[str, str] = {}
        merges: List[Dict[str, Any]] = []
        for tag in tags:
            label = str(tag.get("label") or "")
            normalized = label.replace("时段", "").replace("发案", "")
            if normalized in seen and seen[normalized] != label:
                merges.append({"from": label, "to": seen[normalized], "reason": "标签语义接近，建议人工确认是否合并。"})
            else:
                seen[normalized] = label
        return merges
