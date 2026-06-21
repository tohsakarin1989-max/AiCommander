from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from app.database import get_db
from app.services.graph_service import GraphService

router = APIRouter()


class SerialGraphRequest(BaseModel):
    case_ids: List[int]
    radius_km: float = 2.0


@router.post("/serial")
def build_serial_graph(
    request: SerialGraphRequest,
    db: Session = Depends(get_db),
):
    if not request.case_ids:
        raise HTTPException(status_code=400, detail="case_ids不能为空")
    graph = GraphService.build_serial_graph(db, request.case_ids, radius_km=request.radius_km)
    return graph
