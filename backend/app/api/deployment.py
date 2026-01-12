from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.services.deployment_service import DeploymentService

router = APIRouter()

@router.get("/report")
def get_deployment_report(
    days: int = 90,
    db: Session = Depends(get_db)
):
    """
    获取完整的工作部署建议报告
    基于已破获案件数据，生成预防性的工作部署建议
    """
    try:
        report = DeploymentService.generate_deployment_report(db, days)
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成部署报告失败: {str(e)}")

@router.get("/temporal-patterns")
def get_temporal_patterns(
    days: int = 90,
    db: Session = Depends(get_db)
):
    """获取时间模式分析"""
    return DeploymentService.analyze_temporal_patterns(db, days)

@router.get("/target-patterns")
def get_target_patterns(db: Session = Depends(get_db)):
    """获取目标模式分析"""
    return DeploymentService.analyze_target_patterns(db)

@router.get("/patrol-routes")
def get_patrol_routes(
    radius_km: float = 2.0,
    db: Session = Depends(get_db)
):
    """获取巡逻路线建议"""
    return DeploymentService.generate_patrol_routes(db, radius_km)

@router.get("/resource-allocation")
def get_resource_allocation(db: Session = Depends(get_db)):
    """获取资源配置建议"""
    return DeploymentService.generate_resource_allocation(db)

@router.get("/prevention-measures")
def get_prevention_measures(db: Session = Depends(get_db)):
    """获取预防措施建议"""
    return DeploymentService.generate_prevention_measures(db)

