"""
巡逻记录 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.services.patrol_service import PatrolService
from app.services.deployment_service import DeploymentService
from app.services.geo_analysis_service import GeoAnalysisService

router = APIRouter()


# ========== 请求/响应模型 ==========

class PatrolCreate(BaseModel):
    area_name: str
    patrol_type: str = "routine"  # routine/targeted/emergency
    area_coordinates: Optional[List[dict]] = None
    officer_count: int = 1
    officer_names: Optional[str] = None
    related_case_ids: Optional[List[int]] = None
    related_deployment_id: Optional[int] = None
    created_by: Optional[str] = None


class PatrolComplete(BaseModel):
    findings: Optional[str] = None
    issues_found: int = 0
    actions_taken: Optional[str] = None
    patrol_route: Optional[List[dict]] = None
    evidence_photos: Optional[List[str]] = None
    effectiveness_score: Optional[float] = None
    feedback_notes: Optional[str] = None


class PatrolResponse(BaseModel):
    id: int
    patrol_number: str
    patrol_type: str
    area_name: str
    area_coordinates: Optional[List[dict]]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    officer_count: int
    officer_names: Optional[str]
    status: str
    findings: Optional[str]
    issues_found: int
    actions_taken: Optional[str]
    evidence_photos: Optional[List[str]]
    related_case_ids: Optional[List[int]]
    related_deployment_id: Optional[int]
    risk_before: Optional[float]
    risk_after: Optional[float]
    effectiveness_score: Optional[float]
    feedback_notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]

    class Config:
        from_attributes = True


class AreaRiskResponse(BaseModel):
    id: int
    area_name: str
    area_coordinates: Optional[List[dict]]
    risk_score: float
    risk_level: str
    case_count_30d: int
    case_count_7d: int
    patrol_count_30d: int
    last_patrol_date: Optional[datetime]
    days_since_patrol: Optional[int]
    risk_history: Optional[List[dict]]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ========== API 端点 ==========

@router.post("/", response_model=PatrolResponse)
def create_patrol(patrol: PatrolCreate, db: Session = Depends(get_db)):
    """创建巡逻计划"""
    try:
        return PatrolService.create_patrol(
            db=db,
            area_name=patrol.area_name,
            patrol_type=patrol.patrol_type,
            area_coordinates=patrol.area_coordinates,
            officer_count=patrol.officer_count,
            officer_names=patrol.officer_names,
            related_case_ids=patrol.related_case_ids,
            related_deployment_id=patrol.related_deployment_id,
            created_by=patrol.created_by,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=List[PatrolResponse])
def get_patrols(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    area_name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """获取巡逻记录列表"""
    return PatrolService.get_patrols(db, skip, limit, status, area_name)


@router.get("/{patrol_id:int}", response_model=PatrolResponse)
def get_patrol(patrol_id: int, db: Session = Depends(get_db)):
    """获取单个巡逻记录"""
    patrol = PatrolService.get_patrol(db, patrol_id)
    if not patrol:
        raise HTTPException(status_code=404, detail="巡逻记录不存在")
    return patrol


@router.post("/{patrol_id:int}/start", response_model=PatrolResponse)
def start_patrol(patrol_id: int, db: Session = Depends(get_db)):
    """开始巡逻"""
    try:
        return PatrolService.start_patrol(db, patrol_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{patrol_id:int}/complete", response_model=PatrolResponse)
def complete_patrol(
    patrol_id: int,
    data: PatrolComplete,
    db: Session = Depends(get_db),
):
    """完成巡逻并记录结果"""
    try:
        return PatrolService.complete_patrol(
            db=db,
            patrol_id=patrol_id,
            findings=data.findings,
            issues_found=data.issues_found,
            actions_taken=data.actions_taken,
            patrol_route=data.patrol_route,
            evidence_photos=data.evidence_photos,
            effectiveness_score=data.effectiveness_score,
            feedback_notes=data.feedback_notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{patrol_id:int}/cancel", response_model=PatrolResponse)
def cancel_patrol(patrol_id: int, db: Session = Depends(get_db)):
    """取消巡逻"""
    patrol = PatrolService.get_patrol(db, patrol_id)
    if not patrol:
        raise HTTPException(status_code=404, detail="巡逻记录不存在")

    patrol.status = "cancelled"
    db.commit()
    db.refresh(patrol)
    return patrol


# ========== 区域风险 API ==========

@router.get("/areas/risks", response_model=List[AreaRiskResponse])
def get_area_risks(
    skip: int = 0,
    limit: int = 100,
    min_risk: Optional[float] = None,
    db: Session = Depends(get_db),
):
    """获取区域风险评估列表"""
    return PatrolService.get_area_risks(db, skip, limit, min_risk)


@router.get("/areas/{area_name}/risk")
def get_area_risk(area_name: str, db: Session = Depends(get_db)):
    """获取指定区域的风险评分"""
    risk_data = PatrolService.calculate_area_risk_score(db, area_name)
    return {
        "area_name": area_name,
        **risk_data,
    }


@router.post("/areas/refresh-risks")
def refresh_all_area_risks(db: Session = Depends(get_db)):
    """刷新所有区域的风险评分"""
    count = PatrolService.refresh_all_area_risks(db)
    return {"message": f"已刷新 {count} 个区域的风险评分"}


# ========== 智能调度 API ==========

@router.get("/smart-schedule")
def get_smart_schedule(days: int = 90, db: Session = Depends(get_db)):
    """获取智能巡逻时段建议（基于历史案件时间分布动态计算）"""
    return PatrolService.calculate_smart_schedule(db, days=days)


@router.get("/case-driven-plan")
def get_case_driven_patrol_plan(
    days: int = 90,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """按案件信息生成区域化巡逻规划。"""
    if days <= 0:
        raise HTTPException(status_code=400, detail="days 必须大于 0")
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit 必须大于 0")
    return PatrolService.build_case_driven_patrol_plan(db, days=days, limit=limit)


@router.get("/optimized-routes")
def get_optimized_routes(
    radius_km: float = 2.0,
    min_cases: int = 2,
    db: Session = Depends(get_db),
):
    """获取经过 TSP 排序优化的巡逻路线顺序"""
    hotspots = GeoAnalysisService.find_hotspots(db, radius_km=radius_km, min_cases=min_cases)
    ordered = DeploymentService.optimize_route_order(hotspots)
    total_distance = sum(r.get("est_distance_km", 0.0) for r in ordered)
    return {
        "routes": ordered,
        "total_distance_km": round(total_distance, 2),
        "hotspot_count": len(ordered),
    }
