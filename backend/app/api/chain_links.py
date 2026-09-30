from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.chain_analysis_service import ChainAnalysisService

router = APIRouter()


class ChainConfirmRequest(BaseModel):
    operator: Optional[str] = None


@router.get("/")
def list_chain_links(
    case_id: Optional[int] = None,
    include_rejected: bool = False,
    include_stale: bool = False,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    links = ChainAnalysisService.list_links(db, case_id=case_id, include_rejected=include_rejected,
                                            include_stale=include_stale)
    return [ChainAnalysisService.link_to_dict(link) for link in links]


@router.post("/{link_id:int}/confirm")
def confirm_chain_link(link_id: int, payload: ChainConfirmRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        link = ChainAnalysisService.confirm_link(link_id, payload.operator or "人工确认", db)
    except ValueError as exc:
        if str(exc) != "chain_source_changed":
            raise
        raise HTTPException(status_code=409, detail="关联依据已变化，请等待后台重新分析；旧人工记录仍保留") from exc
    if not link:
        raise HTTPException(status_code=404, detail="链条关联不存在")
    return ChainAnalysisService.link_to_dict(link)


@router.post("/{link_id:int}/reject")
def reject_chain_link(link_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    link = ChainAnalysisService.reject_link(link_id, db)
    if not link:
        raise HTTPException(status_code=404, detail="链条关联不存在")
    return ChainAnalysisService.link_to_dict(link)


@router.get("/map-data")
def get_chain_map_data(
    case_id: Optional[int] = None,
    min_confidence: Optional[float] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    links = ChainAnalysisService.list_links(db, case_id=case_id, include_rejected=False)
    threshold = (
        min_confidence
        if min_confidence is not None
        else ChainAnalysisService._float_config(db, "chain_min_confidence", ChainAnalysisService.DEFAULT_MIN_CONFIDENCE)
    )
    visible = [
        ChainAnalysisService.link_to_dict(link)
        for link in links
        if ChainAnalysisService.freshness(link, db) == "current"
        and (link.status == "confirmed" or link.confidence >= threshold)
    ]
    return {
        "chain_links": visible,
        "total": len(visible),
        "boundary": "地图连线仅表示系统推断或人工确认的上下游关联，未确认连线不得直接作为定案依据。",
    }


@router.get("/context")
def get_chain_context(case_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return ChainAnalysisService.get_chain_context(case_id, db)


@router.post("/scan")
def scan_case_chain_links(case_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    links = ChainAnalysisService.scan_chain_links(case_id, db)
    return {
        "created_or_existing": [ChainAnalysisService.link_to_dict(link) for link in links],
        "total": len(links),
    }
