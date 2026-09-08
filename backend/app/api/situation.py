"""v3.0 双域态势研判只读 API。"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.situation_analysis_service import (
    SituationAnalysisError,
    SituationAnalysisService,
)


router = APIRouter()


@router.get("/overview")
def get_situation_overview(
    window_days: int = Query(default=30, ge=7, le=90),
    as_of: datetime | None = Query(default=None),
    area_keyword: str | None = Query(default=None, max_length=50),
    hotspot_radius_km: float = Query(default=1.5, ge=0.5, le=5),
    well_radius_km: float = Query(default=5, ge=0.5, le=20),
    min_cases: int = Query(default=2, ge=2, le=10),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """比较相邻历史窗口并生成只读态势、井点参考和简报。"""
    try:
        return SituationAnalysisService.build_overview(
            db,
            window_days=window_days,
            as_of=as_of,
            area_keyword=area_keyword,
            hotspot_radius_km=hotspot_radius_km,
            well_radius_km=well_radius_km,
            min_cases=min_cases,
        )
    except SituationAnalysisError as exc:
        raise HTTPException(status_code=422, detail="态势研判范围不合法") from exc
