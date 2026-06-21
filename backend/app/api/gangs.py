"""
相似条件组分析 API。

保留 /gangs 路径以兼容前端历史命名，实际语义为已侦破案件的
作案条件聚类和防控参考画像。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.database import get_db
from app.services.gang_analysis_service import GangAnalysisService

router = APIRouter()


class GangProfile(BaseModel):
    case_ids: List[int]
    case_count: int
    active_hours: List[int]
    active_days: List[int]
    preferred_locations: List[str]
    modus_operandi: List[str]
    target_facilities: List[str]
    known_persons: List[str]
    known_vehicles: List[str]
    source_types: List[str] = []
    oil_natures: List[str] = []
    report_units: List[str] = []
    quality: dict = {}
    oil_types: List[str]
    geographic_center: Optional[dict]
    time_span_days: int
    risk_score: float


class GangAnalysisRequest(BaseModel):
    case_ids: Optional[List[int]] = None
    min_similarity: float = 0.5
    min_cases: int = 2
    time_window_days: int = 90


class TimelineEntry(BaseModel):
    case_id: int
    case_number: str
    occurred_time: Optional[str]
    location: Optional[str]
    case_type: Optional[str]
    modus_operandi: Optional[str]


@router.post("/identify", response_model=List[GangProfile])
def identify_gangs(request: GangAnalysisRequest, db: Session = Depends(get_db)):
    """
    识别相似条件组

    基于案件时间、地点、作案手法、现场条件和管理画像聚类。
    同人同车不作为跨案规律，仅用于重复录入或同案拆分核验。
    """
    try:
        gangs = GangAnalysisService.identify_gangs(
            db=db,
            case_ids=request.case_ids,
            min_similarity=request.min_similarity,
            min_cases=request.min_cases,
            time_window_days=request.time_window_days,
        )
        return gangs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quick-identify")
def quick_identify_gangs(
    min_similarity: float = 0.5,
    min_cases: int = 2,
    time_window_days: int = 90,
    db: Session = Depends(get_db)
):
    """快速识别相似条件组（GET 方法）"""
    try:
        gangs = GangAnalysisService.identify_gangs(
            db=db,
            min_similarity=min_similarity,
            min_cases=min_cases,
            time_window_days=time_window_days,
        )
        return {
            "total_gangs": len(gangs),
            "gangs": gangs,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{gang_index}/relations")
def get_gang_relations(
    gang_index: int,
    min_similarity: float = 0.5,
    min_cases: int = 2,
    time_window_days: int = 90,
    db: Session = Depends(get_db)
):
    """获取条件组关系图数据"""
    try:
        gangs = GangAnalysisService.identify_gangs(
            db=db,
            min_similarity=min_similarity,
            min_cases=min_cases,
            time_window_days=time_window_days,
        )

        if gang_index < 0 or gang_index >= len(gangs):
            raise HTTPException(status_code=404, detail="条件组索引无效")

        gang = gangs[gang_index]
        relations = GangAnalysisService.get_gang_relations(gang)
        return {
            "gang_profile": gang,
            "relations": relations,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/timeline", response_model=List[TimelineEntry])
def get_gang_timeline(case_ids: List[int], db: Session = Depends(get_db)):
    """获取条件组案件时间线"""
    try:
        timeline = GangAnalysisService.analyze_gang_timeline(db, case_ids)
        return timeline
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics")
def get_gang_statistics(
    time_window_days: int = 90,
    db: Session = Depends(get_db)
):
    """获取条件组分析统计数据"""
    try:
        gangs = GangAnalysisService.identify_gangs(
            db=db,
            min_similarity=0.5,
            min_cases=2,
            time_window_days=time_window_days,
        )

        total_cases_in_gangs = sum(g["case_count"] for g in gangs)
        high_risk_gangs = [g for g in gangs if g["risk_score"] >= 60]

        return {
            "total_gangs": len(gangs),
            "total_cases_in_gangs": total_cases_in_gangs,
            "high_risk_gangs": len(high_risk_gangs),
            "average_gang_size": total_cases_in_gangs / len(gangs) if gangs else 0,
            "top_gangs": gangs[:5],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{gang_index}/activity-heatmap")
def get_gang_activity_heatmap(
    gang_index: int,
    request: GangAnalysisRequest,
    db: Session = Depends(get_db),
):
    """
    获取指定条件组的案件时间热力图（7天×24小时矩阵）

    先识别条件组，取 gang_index 对应条件组的 case_ids，调用 get_activity_heatmap
    """
    try:
        gangs = GangAnalysisService.identify_gangs(
            db=db,
            case_ids=request.case_ids,
            min_similarity=request.min_similarity,
            min_cases=request.min_cases,
            time_window_days=request.time_window_days,
        )

        if gang_index < 0 or gang_index >= len(gangs):
            raise HTTPException(status_code=404, detail="条件组索引无效")

        case_ids = gangs[gang_index]["case_ids"]
        heatmap = GangAnalysisService.get_activity_heatmap(case_ids, db)
        return heatmap
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cross-gang-persons")
def get_cross_gang_persons(
    request: GangAnalysisRequest,
    db: Session = Depends(get_db),
):
    """
    兼容旧接口：不再检测跨组共现人员

    已侦破案件中的同人同车只用于重复录入或同案拆分核验。
    """
    try:
        gangs = GangAnalysisService.identify_gangs(
            db=db,
            case_ids=request.case_ids,
            min_similarity=request.min_similarity,
            min_cases=request.min_cases,
            time_window_days=request.time_window_days,
        )
        cross_persons = GangAnalysisService.find_cross_gang_persons(gangs)
        return cross_persons
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
