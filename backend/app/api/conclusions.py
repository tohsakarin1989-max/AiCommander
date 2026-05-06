from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.database import get_db
from app.models.conclusion import Conclusion
from app.models.conclusion_review import ConclusionReview
from app.models.meeting import Meeting
from app.models.report import Report
from app.services.conclusion_factory_service import ConclusionFactoryService

router = APIRouter()


class GenerateConclusionRequest(BaseModel):
    case_id: int


class ReviewConclusionRequest(BaseModel):
    action: Optional[str] = None
    feedback: Optional[str] = None
    note: Optional[str] = None
    approved: Optional[bool] = None


@router.post("/generate")
async def generate_conclusion(
    payload: Optional[GenerateConclusionRequest] = Body(None),
    case_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    resolved_case_id = payload.case_id if payload else case_id
    if resolved_case_id is None:
        raise HTTPException(status_code=422, detail="缺少 case_id")

    try:
        conclusion = await ConclusionFactoryService.generate_conclusion(db, resolved_case_id)
        return {
            "id": conclusion.id,
            "case_id": conclusion.case_id,
            "meeting_id": conclusion.meeting_id,
            "status": conclusion.status,
            "confidence": conclusion.confidence,
            "risk_level": conclusion.risk_level,
            "summary": conclusion.summary,
            "evidence": conclusion.evidence,
            "created_at": str(conclusion.created_at),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成结论失败: {e}")


@router.post("/from-meeting/{meeting_id}")
async def generate_from_meeting(meeting_id: str, db: Session = Depends(get_db)):
    """从会议报告一键生成结论"""
    try:
        conclusion = await ConclusionFactoryService.generate_from_meeting(db, meeting_id)
        return {
            "id": conclusion.id,
            "case_id": conclusion.case_id,
            "meeting_id": conclusion.meeting_id,
            "status": conclusion.status,
            "confidence": conclusion.confidence,
            "risk_level": conclusion.risk_level,
            "summary": conclusion.summary,
            "evidence": conclusion.evidence,
            "created_at": str(conclusion.created_at),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"从会议生成结论失败: {e}")


@router.post("/{conclusion_id:int}/link-meeting")
def link_to_meeting(
    conclusion_id: int,
    meeting_id: str,
    db: Session = Depends(get_db),
):
    """将结论关联到指定会议"""
    conclusion = db.query(Conclusion).filter(Conclusion.id == conclusion_id).first()
    if not conclusion:
        raise HTTPException(status_code=404, detail="结论不存在")

    meeting = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="会议不存在")

    conclusion.meeting_id = meeting_id
    db.commit()
    db.refresh(conclusion)

    return {
        "id": conclusion.id,
        "meeting_id": conclusion.meeting_id,
        "message": "关联成功",
    }


@router.get("/")
def list_conclusions(
    status: Optional[str] = None,
    case_id: Optional[int] = None,
    meeting_id: Optional[str] = None,
    risk_level: Optional[str] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(Conclusion)
    if status:
        query = query.filter(Conclusion.status == status)
    if case_id is not None:
        query = query.filter(Conclusion.case_id == case_id)
    if meeting_id:
        query = query.filter(Conclusion.meeting_id == meeting_id)
    if risk_level:
        query = query.filter(Conclusion.risk_level == risk_level)
    if min_confidence is not None:
        query = query.filter(Conclusion.confidence >= min_confidence)
    if max_confidence is not None:
        query = query.filter(Conclusion.confidence <= max_confidence)
    rows = query.order_by(Conclusion.created_at.desc()).offset(skip).limit(limit).all()

    # 获取关联会议信息
    meeting_ids = [c.meeting_id for c in rows if c.meeting_id]
    meeting_map = {}
    if meeting_ids:
        meetings = db.query(Meeting).filter(Meeting.meeting_id.in_(meeting_ids)).all()
        meeting_map = {m.meeting_id: {"status": m.status, "created_at": str(m.created_at)} for m in meetings}

    return [
        {
            "id": c.id,
            "case_id": c.case_id,
            "meeting_id": c.meeting_id,
            "meeting_info": meeting_map.get(c.meeting_id) if c.meeting_id else None,
            "status": c.status,
            "confidence": c.confidence,
            "risk_level": c.risk_level,
            "summary": c.summary,
            "review_reason": "高风险" if c.risk_level == "high" else ("低置信度" if (c.confidence or 0) < 0.7 else None),
            "created_at": str(c.created_at),
        }
        for c in rows
    ]


@router.get("/{conclusion_id:int}")
def get_conclusion(conclusion_id: int, db: Session = Depends(get_db)):
    conclusion = db.query(Conclusion).filter(Conclusion.id == conclusion_id).first()
    if not conclusion:
        raise HTTPException(status_code=404, detail="结论不存在")
    reviews = (
        db.query(ConclusionReview)
        .filter(ConclusionReview.conclusion_id == conclusion_id)
        .order_by(ConclusionReview.created_at.desc())
        .all()
    )

    # 获取关联会议信息
    meeting_info = None
    if conclusion.meeting_id:
        meeting = db.query(Meeting).filter(Meeting.meeting_id == conclusion.meeting_id).first()
        if meeting:
            meeting_info = {
                "meeting_id": meeting.meeting_id,
                "status": meeting.status,
                "case_ids": meeting.case_ids,
                "created_at": str(meeting.created_at),
            }

    return {
        "id": conclusion.id,
        "case_id": conclusion.case_id,
        "meeting_id": conclusion.meeting_id,
        "meeting_info": meeting_info,
        "status": conclusion.status,
        "confidence": conclusion.confidence,
        "risk_level": conclusion.risk_level,
        "summary": conclusion.summary,
        "evidence": conclusion.evidence,
        "created_at": str(conclusion.created_at),
        "reviews": [
            {
                "id": r.id,
                "action": r.action,
                "note": r.note,
                "created_at": str(r.created_at),
            }
            for r in reviews
        ],
    }


@router.post("/{conclusion_id:int}/review")
def review_conclusion(
    conclusion_id: int,
    payload: Optional[ReviewConclusionRequest] = Body(None),
    action: Optional[str] = None,
    note: Optional[str] = None,
    db: Session = Depends(get_db),
):
    conclusion = db.query(Conclusion).filter(Conclusion.id == conclusion_id).first()
    if not conclusion:
        raise HTTPException(status_code=404, detail="结论不存在")

    resolved_action = action
    resolved_note = note

    if payload is not None:
        resolved_action = payload.action or payload.feedback or resolved_action
        resolved_note = payload.note if payload.note is not None else resolved_note
        if resolved_action is None and payload.approved is not None:
            resolved_action = "approve" if payload.approved else "reject"

    if resolved_action not in {"approve", "reject", "flag"}:
        raise HTTPException(status_code=400, detail="无效的操作类型")

    review = ConclusionReview(
        conclusion_id=conclusion_id,
        action=resolved_action,
        note=resolved_note,
    )
    db.add(review)

    if resolved_action == "approve":
        conclusion.status = "published"
    elif resolved_action == "reject":
        conclusion.status = "rejected"
    else:
        conclusion.status = "flagged"

    db.commit()
    db.refresh(conclusion)

    return {
        "id": conclusion.id,
        "status": conclusion.status,
        "review_action": resolved_action,
    }
