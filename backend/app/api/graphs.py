from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.services.graph_service import GraphService

router = APIRouter()


@router.post("/serial")
def build_serial_graph(
    case_ids: List[int],
    radius_km: float = 2.0,
    db: Session = Depends(get_db),
):
    if not case_ids:
        raise HTTPException(status_code=400, detail="case_ids不能为空")
    graph = GraphService.build_serial_graph(db, case_ids, radius_km=radius_km)
    return graph
