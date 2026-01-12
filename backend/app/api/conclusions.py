from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.conclusion import Conclusion
from app.models.conclusion_review import ConclusionReview
from app.services.conclusion_factory_service import ConclusionFactoryService

router = APIRouter()


@router.post("/generate")
async def generate_conclusion(case_id: int, db: Session = Depends(get_db)):
    try:
        conclusion = await ConclusionFactoryService.generate_conclusion(db, case_id)
        return {
            "id": conclusion.id,
            "case_id": conclusion.case_id,
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


@router.get("/")
def list_conclusions(
    status: Optional[str] = None,
    case_id: Optional[int] = None,
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
    if risk_level:
        query = query.filter(Conclusion.risk_level == risk_level)
    if min_confidence is not None:
        query = query.filter(Conclusion.confidence >= min_confidence)
    if max_confidence is not None:
        query = query.filter(Conclusion.confidence <= max_confidence)
    rows = query.order_by(Conclusion.created_at.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": c.id,
            "case_id": c.case_id,
            "status": c.status,
            "confidence": c.confidence,
            "risk_level": c.risk_level,
            "summary": c.summary,
            "review_reason": "高风险" if c.risk_level == "high" else ("低置信度" if (c.confidence or 0) < 0.7 else None),
            "created_at": str(c.created_at),
        }
        for c in rows
    ]


@router.get("/{conclusion_id}")
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
    return {
        "id": conclusion.id,
        "case_id": conclusion.case_id,
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


@router.post("/{conclusion_id}/review")
def review_conclusion(
    conclusion_id: int,
    action: str,
    note: Optional[str] = None,
    db: Session = Depends(get_db),
):
    conclusion = db.query(Conclusion).filter(Conclusion.id == conclusion_id).first()
    if not conclusion:
        raise HTTPException(status_code=404, detail="结论不存在")

    if action not in {"approve", "reject", "flag"}:
        raise HTTPException(status_code=400, detail="无效的操作类型")

    review = ConclusionReview(
        conclusion_id=conclusion_id,
        action=action,
        note=note,
    )
    db.add(review)

    if action == "approve":
        conclusion.status = "published"
    elif action == "reject":
        conclusion.status = "rejected"
    else:
        conclusion.status = "flagged"

    db.commit()
    db.refresh(conclusion)

    return {
        "id": conclusion.id,
        "status": conclusion.status,
        "review_action": action,
    }
