from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.case_knowledge_service import CaseKnowledgeService


router = APIRouter()


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


@router.get("/search")
def search_knowledge(
    q: str,
    case_id: Optional[int] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return CaseKnowledgeService.search(db, q, case_id=case_id, limit=limit)
