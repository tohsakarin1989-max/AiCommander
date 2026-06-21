from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from app.database import get_db
from app.services.map_mcp_service import MapMCPService
from app.models.case import Case
from app.services.case_service import CaseService

router = APIRouter()

class LocationQuery(BaseModel):
    latitude: float
    longitude: float

class POISearchQuery(BaseModel):
    latitude: float
    longitude: float
    keywords: Optional[str] = "加油站|油库|管线|设施"
    radius: Optional[int] = 1000

@router.post("/location-info")
async def get_location_info(query: LocationQuery):
    """获取位置信息（逆地理编码）"""
    try:
        result = await MapMCPService.get_location_info(
            query.latitude,
            query.longitude
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取位置信息失败: {str(e)}")

@router.post("/nearby-pois")
async def search_nearby_pois(query: POISearchQuery):
    """搜索周边POI"""
    try:
        result = await MapMCPService.search_nearby_pois(
            query.latitude,
            query.longitude,
            query.keywords,
            query.radius
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索周边POI失败: {str(e)}")

@router.get("/weather/{city}")
async def get_weather(city: str):
    """获取天气信息"""
    try:
        result = await MapMCPService.get_weather_info(city)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取天气信息失败: {str(e)}")

@router.post("/comprehensive-analysis/{case_id}")
async def get_comprehensive_analysis(
    case_id: int,
    db: Session = Depends(get_db)
):
    """
    获取全面的位置分析（包括村屯、加油站、炼化点、路口等）
    
    针对偏远地区优化：
    - 使用自适应半径搜索，根据实际找到的村屯数量动态调整范围
    - 偏远地区人烟稀少，自动扩大搜索范围（最大100-150公里）
    """
    try:
        case = CaseService.get_case(db, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="案件不存在")
        
        if not case.latitude or not case.longitude:
            raise HTTPException(status_code=400, detail="案件缺少经纬度信息")
        
        result = await MapMCPService.get_comprehensive_location_analysis(
            case.latitude, case.longitude
        )
        
        # 判断是否为偏远地区
        is_remote = result.get("search_stats", {}).get("is_remote_area", False)
        
        # 添加来路分析（传入偏远地区标识）
        approach_analysis = await MapMCPService.analyze_approach_routes(
            case.latitude, case.longitude, case.description or "", is_remote
        )
        result["approach_analysis"] = approach_analysis
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

@router.post("/analyze-case-location/{case_id}")
async def analyze_case_location(
    case_id: int,
    db: Session = Depends(get_db)
):
    """
    结合AI和地图MCP数据，智能分析案件位置
    需要配置AI模型
    """
    try:
        case = CaseService.get_case(db, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="案件不存在")
        
        if not case.latitude or not case.longitude:
            raise HTTPException(status_code=400, detail="案件缺少经纬度信息")
        
        # 获取默认主持人模型用于AI分析
        from app.models.ai_model import AIModel
        from app.ai.model_factory import ModelFactory
        
        # 先尝试获取默认的主持人模型
        moderator_model = db.query(AIModel).filter(
            AIModel.role == "moderator",
            AIModel.is_default == True,
            AIModel.is_active == True
        ).first()
        
        # 如果没有默认的，尝试获取任意一个活跃的主持人模型
        if not moderator_model:
            moderator_model = db.query(AIModel).filter(
                AIModel.role == "moderator",
                AIModel.is_active == True
            ).first()
        
        # 如果还是没有，尝试获取任意一个活跃的模型（不限制角色）
        if not moderator_model:
            moderator_model = db.query(AIModel).filter(
                AIModel.is_active == True
            ).first()
        
        if not moderator_model:
            raise HTTPException(
                status_code=400, 
                detail="未配置AI模型，无法进行智能分析。请在系统设置中配置至少一个AI模型。"
            )
        
        factory = ModelFactory()
        llm = factory.create_llm(moderator_model)
        
        result = await MapMCPService.analyze_case_location_with_ai(
            case.latitude,
            case.longitude,
            case.description or "",
            llm
        )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

