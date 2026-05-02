from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models.report import Report

router = APIRouter()

@router.get("/", response_model=List[dict])
def get_reports(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """获取报告列表"""
    reports = db.query(Report).offset(skip).limit(limit).all()
    return [
        {
            "id": r.id,
            "meeting_id": r.meeting_id,
            "report_type": r.report_type,
            "content": r.content,
            "consensus_points": r.consensus_points,
            "disagreement_points": r.disagreement_points,
            "model_contributions": r.model_contributions,
            "created_at": str(r.created_at)
        }
        for r in reports
    ]

@router.get("/{report_id:int}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    """获取单个报告"""
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    return {
        "id": report.id,
        "meeting_id": report.meeting_id,
        "report_type": report.report_type,
        "content": report.content,
        "consensus_points": report.consensus_points,
        "disagreement_points": report.disagreement_points,
        "model_contributions": report.model_contributions,
        "created_at": str(report.created_at)
    }
