from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict, List
from app.database import get_db
from app.models.report import Report
from app.services.case_intelligence_service import CaseIntelligenceService

router = APIRouter()


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else ([] if value is None else [value])


def _report_ai_output(report: Report) -> Dict[str, Any]:
    content = report.content if isinstance(report.content, dict) else {}
    facts = [
        f"报告编号：{report.id}",
        f"会议编号：{report.meeting_id}",
        f"报告类型：{report.report_type or '未填写'}",
        content.get("summary") or "报告摘要待补齐",
    ]
    inferences = [
        {
            "claim": content.get("conclusions") or content.get("ranking_summary") or "会议报告结论待人工复核",
            "basis": _as_list(report.consensus_points) or ["会议综合报告"],
            "confidence": "medium",
        }
    ]
    recommendations = [
        {
            "title": f"报告建议 {index}",
            "action": item,
            "basis": ["会议报告 recommendations/next_steps 字段"],
            "evidence": [f"report:{report.id}"],
            "priority": "medium",
        }
        for index, item in enumerate(
            _as_list(content.get("recommendations")) + _as_list(content.get("next_steps")),
            start=1,
        )
    ]
    gaps = _as_list(content.get("information_gaps"))
    if not gaps:
        gaps = ["报告草稿仍需人工复核事实依据、结论口径和引用范围。"]

    return CaseIntelligenceService.build_structured_ai_output(
        title=f"会议报告草稿：{report.meeting_id}",
        output_type="meeting_report_draft",
        facts=facts,
        inferences=inferences,
        recommendations=recommendations,
        information_gaps=gaps,
        evidence_refs=[
            {
                "id": f"report:{report.id}",
                "kind": "meeting_report",
                "summary": f"会议 {report.meeting_id} 的 {report.report_type or '综合'} 报告",
                "basis": _as_list(report.consensus_points),
            }
        ],
        boundary=[
            "报告草稿只作为会议材料和领导汇报前的人工复核底稿。",
            "必须区分事实依据、模式推断、防控参考和信息缺口。",
            "不得把建议写成已执行任务，不自动发布正式结论。",
        ],
    )


def _serialize_report(report: Report) -> Dict[str, Any]:
    ai_output = _report_ai_output(report)
    return {
        "id": report.id,
        "meeting_id": report.meeting_id,
        "report_type": report.report_type,
        "content": report.content,
        "consensus_points": report.consensus_points,
        "disagreement_points": report.disagreement_points,
        "model_contributions": report.model_contributions,
        "draft_status": ai_output["draft_status"],
        "review_status": ai_output["review_status"],
        "model_status": ai_output["model_status"],
        "ai_output": ai_output,
        "created_at": str(report.created_at),
    }

@router.get("/", response_model=List[dict])
def get_reports(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """获取报告列表"""
    reports = db.query(Report).offset(skip).limit(limit).all()
    return [_serialize_report(r) for r in reports]

@router.get("/{report_id:int}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    """获取单个报告"""
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    return _serialize_report(report)
