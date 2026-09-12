import json
from typing import Dict, Any, Optional, List
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import require_area_write_access
from app.models.conclusion import Conclusion
from app.models.case_result import CaseResultSnapshot
from app.models.ai_model import AIModel
from app.ai.model_factory import ModelFactory
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.case_result_access import CaseResultAccessError
from app.services.case_result_service import CaseResultService
from app.services.vector_db_service import VectorDBService
from app.models.meeting import Meeting, AnalysisResult, Ranking
from app.models.report import Report
from app.models.case import Case
from app.utils.logger import logger
from app.config import settings


class ConclusionResultPendingError(ValueError):
    """不再为缺失或过期成果同步重跑分析。"""

    def __init__(self):
        super().__init__("当前案件成果尚未就绪，请等待后台成果更新后再生成草稿。")


class ConclusionFactoryService:
    @staticmethod
    def _meeting_report_summary(report: Optional[Report]) -> str:
        content = report.content if report else None
        if isinstance(content, dict):
            content = content.get("summary") or json.dumps(content, ensure_ascii=False, default=str)
        if not isinstance(content, str):
            content = ""
        return content[:500] or "基于圆桌会议研判生成的综合结论"

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """将研判证据转成数据库 JSON 字段可存储的结构。"""
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    @staticmethod
    def _get_llm(db: Session):
        model = db.query(AIModel).filter(
            AIModel.role == "moderator",
            AIModel.is_default == True,
            AIModel.is_active == True,
        ).first()
        if not model:
            model = db.query(AIModel).filter(
                AIModel.is_active == True,
            ).first()
        if not model:
            return None
        try:
            return ModelFactory().create_llm(model)
        except Exception as e:
            logger.error(f"创建结论LLM失败: {e}")
            return None

    @staticmethod
    def _build_evidence(db: Session, case_dict: Dict[str, Any]) -> Dict[str, Any]:
        evidence = {
            "case": case_dict,
            "similar_cases": [],
            "related_reports": [],
            "related_meetings": [],
            "case_intelligence": None,
        }
        if settings.ENABLE_VECTOR_DB and case_dict.get("description"):
            try:
                vector_db = VectorDBService()
                if vector_db.is_available(db):
                    results = vector_db.search_similar_cases(
                        case_dict.get("description", ""),
                        top_k=5,
                        min_similarity=0.6,
                        operational_area_ids=[case_dict["operational_area_id"]],
                        db=db,
                    )
                    evidence["similar_cases"] = results
            except Exception as e:
                logger.warning(f"生成相似案件证据失败: {e}")

        case_id = case_dict.get("case_id")
        if case_id is not None:
            try:
                evidence["case_intelligence"] = {
                    "experience_card": CaseIntelligenceService.build_experience_card(db, case_id),
                    "similar_cases": CaseIntelligenceService.find_similar_cases(db, case_id, days=365, limit=5),
                    "prevention_suggestions": CaseIntelligenceService.build_prevention_suggestions(
                        db,
                        case_id=case_id,
                        days=365,
                        limit=5,
                    ),
                    "report": CaseIntelligenceService.build_report(db, case_id=case_id, days=365, limit=5),
                }
            except Exception as e:
                logger.warning(f"生成案件研判证据失败: {e}")
            try:
                meetings = db.query(Meeting).all()
                for meeting in meetings:
                    case_ids = meeting.case_ids if isinstance(meeting.case_ids, list) else []
                    if case_id in case_ids:
                        evidence["related_meetings"].append({
                            "meeting_id": meeting.meeting_id,
                            "status": meeting.status,
                            "created_at": str(meeting.created_at) if meeting.created_at else None,
                        })
                        report = (
                            db.query(Report)
                            .filter(Report.meeting_id == meeting.meeting_id)
                            .first()
                        )
                        if report:
                            evidence["related_reports"].append({
                                "report_id": report.id,
                                "meeting_id": report.meeting_id,
                                "report_type": report.report_type,
                                "created_at": str(report.created_at) if report.created_at else None,
                            })
            except Exception as e:
                logger.warning(f"生成相关会议/报告证据失败: {e}")
        return evidence

    @staticmethod
    def _fallback_summary(case_dict: Dict[str, Any]) -> Dict[str, Any]:
        desc = case_dict.get("description") or ""
        summary = desc[:300] if desc else "暂无案件描述，建议补充案情信息。"
        confidence = 0.4 if desc else 0.2
        risk_level = "medium" if case_dict.get("loss_amount") else "unknown"
        return {
            "summary": summary,
            "confidence": confidence,
            "risk_level": risk_level,
            "key_evidence": ["案件基础信息", "结构化字段缺失提示"],
        }

    @staticmethod
    def _build_conclusion_ai_output(
        *,
        title: str,
        output_type: str,
        facts: List[Any],
        payload: Dict[str, Any],
        information_gaps: List[Any],
        evidence_refs: List[Dict[str, Any]],
        model_status: str,
    ) -> Dict[str, Any]:
        inference_notes = payload.get("inference_notes") or []
        if isinstance(inference_notes, str):
            inference_notes = [inference_notes]
        inferences = [
            {
                "claim": item,
                "basis": payload.get("key_evidence") or ["结论草稿摘要"],
                "confidence": payload.get("confidence", "low"),
            }
            for item in (inference_notes or [payload.get("summary") or "结论草稿待人工复核"])
        ]
        recommendations = [
            {
                "title": f"复核建议 {index}",
                "action": item,
                "basis": payload.get("key_evidence") or ["结论草稿"],
                "evidence": [ref.get("id") for ref in evidence_refs if ref.get("id")],
                "priority": "medium",
            }
            for index, item in enumerate(payload.get("recommendations") or ["人工复核事实依据后再确认结论。"], start=1)
        ]
        return CaseIntelligenceService.build_structured_ai_output(
            title=title,
            output_type=output_type,
            facts=facts,
            inferences=inferences,
            recommendations=recommendations,
            information_gaps=information_gaps or ["结论草稿仍需人工复核事实依据、推断边界和引用范围。"],
            evidence_refs=evidence_refs,
            boundary=[
                "结论草稿只用于人工复核前的研判表达。",
                "不替代人工审核，不替代规则评分、事实确认和处置决策。",
                "不得编造未掌握的人车链条、销赃链条或未破案件线索。",
                "低置信度或高风险内容必须保持待人工复核，不自动发布。",
            ],
            model_status=model_status,
        )

    @staticmethod
    def require_conclusion_result_access(db: Session, conclusion: Conclusion) -> None:
        """新结论的每次交付/复核都验证冻结来源；旧会议结论保持既有契约。"""
        evidence = conclusion.evidence if isinstance(conclusion.evidence, dict) else {}
        if "source_result" not in evidence:
            return
        source = evidence["source_result"]
        if not isinstance(source, dict) or not isinstance(source.get("result_id"), str):
            raise CaseResultAccessError()
        result = CaseResultService.read(db, source["result_id"])
        if (result["content"]["case_id"] != conclusion.case_id
                or result["content_sha256"] != source.get("content_sha256")
                or result["content"]["schema_version"] != source.get("schema_version")
                or result["content"]["versions"] != source.get("versions")):
            raise CaseResultAccessError()

    @staticmethod
    def _result_text(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("label") or value.get("message") or value.get("summary")
                       or value.get("claim") or json.dumps(value, ensure_ascii=False, sort_keys=True))
        return str(value)

    @staticmethod
    def _result_draft(result: dict) -> dict:
        """只重新排版冻结内容，不抽取原文、不检索、不推理或生成新建议。"""
        content = result["content"]
        labels = {
            "occurred_time": "发生时间", "location": "地点", "case_type": "案件类型",
            "oil_type": "油品类型", "oil_nature": "油品性质", "facility_type": "设施类型",
            "modus_operandi": "作案手法", "report_unit": "报告单位", "source_type": "线索来源",
        }
        facts = [content["facts_summary"]["label"]]
        for key, value in content["facts_summary"]["recorded_fields"].items():
            if value is not None and value != "":
                facts.append(f"{labels.get(key, key)}：{ConclusionFactoryService._result_text(value)}")
        candidates = content["candidates"]
        gaps = [ConclusionFactoryService._result_text(item)
                for items in content["information_gaps"].values() for item in items]
        evidence_ids = list(content["facts_summary"]["evidence_refs"])
        for candidate in candidates:
            evidence_ids.extend(candidate["evidence_refs"])
            gaps.extend(f"{candidate['title']}：{ConclusionFactoryService._result_text(item)}"
                        for item in candidate["information_gaps"])
            gaps.extend(f"{candidate['title']}（反向依据）：{ConclusionFactoryService._result_text(item)}"
                        for item in candidate["counter_evidence"])
        evidence_refs = [{"id": ref, "kind": ref.split(":", 1)[0], "summary": ref, "basis": []}
                         for ref in dict.fromkeys(evidence_ids)]
        source = {
            "result_id": result["id"], "content_sha256": result["content_sha256"],
            "schema_version": content["schema_version"], "versions": content["versions"],
        }
        ai_output = CaseIntelligenceService.build_structured_ai_output(
            title=f"案件 #{content['case_id']} 既有成果结论草稿",
            output_type="conclusion_draft",
            facts=facts,
            inferences=[{"claim": item["claim"], "basis": item["supporting_evidence"],
                         "confidence": "未校准（规则支持度不是概率）"} for item in candidates],
            recommendations=[],
            information_gaps=list(dict.fromkeys(gaps)),
            evidence_refs=evidence_refs,
            boundary=[*content["boundary"], "仅复用既有成果形成草稿，不替代人工审核，不自动发布。"],
            model_status="reused_case_result",
        )
        # 兼容旧展示结构，同时完整保留每项候选的反向证据与版本，不把规则分数变成概率。
        for inference, candidate in zip(ai_output["inferences"], candidates):
            inference.update({key: candidate[key] for key in (
                "id", "evidence_refs", "counter_evidence", "information_gaps", "boundary",
                "score", "score_kind", "is_official_fact",
            )})
        ai_output["source_result"] = source
        ai_output["confidence_available"] = False
        summary = "\n".join([
            "复用已冻结的案件成果，以下内容为待人工判断草稿。",
            *facts,
            *[f"候选（非正式事实）：{item['claim']}" for item in candidates],
            *([] if candidates else ["当前成果未提供候选，不补造推断。"]),
            *[f"信息缺口：{item}" for item in dict.fromkeys(gaps)],
        ])
        return {
            "summary": summary,
            "evidence": ConclusionFactoryService._json_safe({
                "source_result": source, "key_evidence": facts,
                "inference_notes": [item["claim"] for item in candidates],
                "recommendations": [], "information_gaps": list(dict.fromkeys(gaps)),
                "confidence_available": False, "ai_output": ai_output,
                "raw": {"case_result": content},
            }),
        }

    @staticmethod
    async def generate_conclusion(db: Session, case_id: int) -> Conclusion:
        # PostgreSQL按案件串行化同成果请求；只取行锁，不更新任何案件字段。
        case = db.scalar(select(Case).where(Case.id == case_id).with_for_update()
                         .execution_options(populate_existing=True))
        if case is None:
            raise ValueError("案件不存在")
        if "authorized_area_ids" not in db.info:
            raise CaseResultAccessError()
        require_area_write_access(db, case.operational_area_id)
        if db.scalar(select(CaseResultSnapshot.id).where(CaseResultSnapshot.case_id == case_id)
                     .limit(1)) is None:
            raise ConclusionResultPendingError()
        result = CaseResultService.latest(db, case_id)
        if result.get("freshness") != "current":
            raise ConclusionResultPendingError()

        existing = db.scalar(select(Conclusion).where(
            Conclusion.case_id == case_id,
            Conclusion.evidence["source_result"]["result_id"].as_string() == result["id"],
        ).order_by(Conclusion.id.desc()).limit(1).execution_options(populate_existing=True))
        if existing is not None:
            ConclusionFactoryService.require_conclusion_result_access(db, existing)
            # 包括已发布/驳回/标记记录：重复生成不能抹掉或绕过人工判断。
            return existing

        draft = ConclusionFactoryService._result_draft(result)
        conclusion = Conclusion(
            case_id=case_id,
            status="needs_review",
            confidence=0.0,  # 旧数值字段兼容占位；confidence_available=false，非概率或评分。
            risk_level="unknown",
            summary=draft["summary"],
            evidence=draft["evidence"],
        )
        db.add(conclusion)
        db.commit()
        db.refresh(conclusion)
        return conclusion

    @staticmethod
    async def generate_from_meeting(db: Session, meeting_id: str) -> Conclusion:
        """从会议报告一键生成结论"""
        # 获取会议
        meeting = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
        if not meeting:
            raise ValueError("会议不存在")
        if meeting.status != "completed":
            raise ValueError("会议尚未完成，无法生成结论")

        # 获取会议报告
        report = db.query(Report).filter(Report.meeting_id == meeting_id).first()

        # 获取关联案件
        case_ids = meeting.case_ids if isinstance(meeting.case_ids, list) else []
        if not case_ids:
            raise ValueError("会议无关联案件")

        # 获取案件信息
        cases = db.query(Case).filter(Case.id.in_(case_ids)).all()
        cases_data = [
            {
                "case_id": c.id,
                "case_number": c.case_number,
                "case_type": c.case_type,
                "location": c.location,
                "description": c.description,
                "loss_amount": c.loss_amount,
            }
            for c in cases
        ]

        # 获取分析结果
        analysis_results = (
            db.query(AnalysisResult)
            .filter(AnalysisResult.meeting_id == meeting_id)
            .order_by(AnalysisResult.round_number.desc())
            .all()
        )

        # 获取排名数据
        rankings = (
            db.query(Ranking)
            .filter(Ranking.meeting_id == meeting_id)
            .all()
        )

        # 构建证据链
        evidence = {
            "meeting": {
                "meeting_id": meeting_id,
                "status": meeting.status,
                "case_ids": case_ids,
            },
            "report": {
                "content": report.content if report else None,
                "report_type": report.report_type if report else None,
            } if report else None,
            "cases": cases_data,
            "analysis_results": [
                {
                    "analyst_model_id": ar.analyst_model_id,
                    "round": ar.round_number,
                    "content": ar.result_content,
                }
                for ar in analysis_results[:5]  # 最多取5个
            ],
            "rankings": [
                {
                    "stage": r.stage,
                    "data": r.ranking_data,
                }
                for r in rankings
            ],
        }

        # 使用 LLM 生成结论
        llm = ConclusionFactoryService._get_llm(db)
        payload: Dict[str, Any]

        if llm:
            model_status = "llm_success"
            prompt = f"""你是资深案件分析助手，请基于圆桌会议的研判结果生成最终结论。

会议信息：
- 会议ID: {meeting_id}
- 关联案件数: {len(case_ids)}

案件信息：
{json.dumps(cases_data, ensure_ascii=False, indent=2)}

会议报告：
{report.content if report else '暂无报告内容'}

分析结果摘要：
{json.dumps([ar.result_content for ar in analysis_results[:3]], ensure_ascii=False, indent=2) if analysis_results else '暂无分析结果'}

请输出JSON格式结论，包含以下字段：
- summary: 综合研判结论（300字以内）
- confidence: 置信度（0-1之间的浮点数）
- risk_level: 风险等级（low/medium/high）
- key_evidence: 关键证据列表（字符串数组）
- recommendations: 处置建议列表（字符串数组）
"""
            try:
                response = await llm.ainvoke(prompt)
                content = response.content if hasattr(response, "content") else str(response)
                # 尝试提取 JSON
                try:
                    payload = json.loads(content)
                except json.JSONDecodeError:
                    # 尝试从 markdown 代码块中提取
                    import re
                    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                    if json_match:
                        payload = json.loads(json_match.group(1))
                    else:
                        raise
            except Exception as e:
                logger.warning(f"从会议生成结论解析失败，使用降级方案: {e}")
                payload = {
                    "summary": ConclusionFactoryService._meeting_report_summary(report),
                    "confidence": 0.6,
                    "risk_level": "medium",
                    "key_evidence": ["圆桌会议研判结果", f"关联案件 {len(case_ids)} 起"],
                    "recommendations": ["建议进一步核实关键信息"],
                }
                model_status = "llm_failed"
        else:
            payload = {
                "summary": ConclusionFactoryService._meeting_report_summary(report),
                "confidence": 0.5,
                "risk_level": "medium",
                "key_evidence": ["圆桌会议研判结果"],
                "recommendations": [],
            }
            model_status = "deterministic_fallback"

        confidence = float(payload.get("confidence", 0.0))
        risk_level = payload.get("risk_level", "unknown")
        status = "needs_review"

        # 使用第一个案件ID作为主案件
        primary_case_id = case_ids[0] if case_ids else None
        safe_evidence = ConclusionFactoryService._json_safe(evidence)
        ai_output = ConclusionFactoryService._build_conclusion_ai_output(
            title=f"会议 {meeting_id} 情报结论草稿",
            output_type="conclusion_draft",
            facts=[
                f"会议编号：{meeting_id}",
                f"关联案件数：{len(case_ids)}",
                f"会议状态：{meeting.status}",
            ],
            payload=payload,
            information_gaps=["会议结论发布前需人工复核案件事实、报告引用和建议边界。"],
            evidence_refs=[
                {
                    "id": f"meeting:{meeting_id}",
                    "kind": "meeting",
                    "summary": f"圆桌会议 {meeting_id}",
                    "basis": payload.get("key_evidence") or [],
                },
                *([
                    {
                        "id": f"report:{report.id}",
                        "kind": "meeting_report",
                        "summary": f"会议报告 {report.report_type or '综合'}",
                        "basis": [],
                    }
                ] if report else []),
            ],
            model_status=model_status,
        )

        conclusion = Conclusion(
            case_id=primary_case_id,
            meeting_id=meeting_id,
            status=status,
            confidence=confidence,
            risk_level=risk_level,
            summary=payload.get("summary"),
            evidence={
                "key_evidence": payload.get("key_evidence", []),
                "recommendations": payload.get("recommendations", []),
                "ai_output": ai_output,
                "raw": safe_evidence,
            },
        )
        db.add(conclusion)
        db.commit()
        db.refresh(conclusion)
        return conclusion
