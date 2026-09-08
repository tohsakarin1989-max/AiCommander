from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.evidence_graph_service import EvidenceGraphError, EvidenceGraphService
from app.services.graph_service import GraphService

router = APIRouter()


class SerialGraphRequest(BaseModel):
    case_ids: List[int]
    radius_km: float = 2.0


@router.get("/evidence/{case_id:int}")
def build_evidence_graph(
    case_id: int,
    well_radius_km: float = Query(default=5.0, ge=0.5, le=20.0),
    max_context_nodes: int = Query(default=20, ge=5, le=50),
    db: Session = Depends(get_db),
):
    """构建只读证据走廊；不修改案件、井点、链条或知识资产。"""
    try:
        return EvidenceGraphService.build_case_graph(
            db,
            case_id,
            well_radius_km=well_radius_km,
            max_context_nodes=max_context_nodes,
        )
    except EvidenceGraphError as exc:
        if str(exc) == "case_not_found":
            raise HTTPException(status_code=404, detail="案件不存在")
        raise HTTPException(status_code=422, detail="证据图谱范围不合法")


@router.post("/serial")
def build_serial_graph(
    request: SerialGraphRequest,
    db: Session = Depends(get_db),
):
    if not request.case_ids:
        raise HTTPException(status_code=400, detail="case_ids不能为空")
    graph = GraphService.build_serial_graph(db, request.case_ids, radius_km=request.radius_km)
    return graph
