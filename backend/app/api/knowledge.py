from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.case_knowledge_service import CaseKnowledgeService


router = APIRouter()


class ExperienceCardStatusRequest(BaseModel):
    status: str
    reviewer: Optional[str] = None
    note: Optional[str] = None


@router.get("/experience-cards")
def list_experience_cards(
    status: str = "confirmed",
    limit: int = 50,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return CaseKnowledgeService.list_experience_cards(db, status=status, limit=limit)


@router.get("/experience-cards/search")
def search_experience_cards(
    q: str,
    status: str = "confirmed",
    limit: int = 20,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return CaseKnowledgeService.search_experience_cards(db, q, status=status, limit=limit)


@router.post("/experience-cards/{case_id:int}/status")
def update_experience_card_status(
    case_id: int,
    payload: ExperienceCardStatusRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return CaseKnowledgeService.update_experience_card_status(
            db,
            case_id,
            status=payload.status,
            reviewer=payload.reviewer,
            note=payload.note,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "case_not_found":
            raise HTTPException(status_code=404, detail="案件不存在")
        if message == "experience_card_not_found":
            raise HTTPException(status_code=404, detail="经验卡不存在")
        if message == "invalid_experience_status":
            raise HTTPException(status_code=422, detail="经验卡状态必须为 draft/confirmed/archived")
        raise HTTPException(status_code=400, detail=message)


@router.get("/search")
def search_knowledge(
    q: str,
    case_id: Optional[int] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return CaseKnowledgeService.search(db, q, case_id=case_id, limit=limit)
