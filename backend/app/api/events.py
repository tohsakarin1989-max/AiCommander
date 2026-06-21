"""
事件和区域研判 API
用于管理事件录入、区域分析和研判会话
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from app.database import get_db
from app.models.event import Event, AreaProfile, EventRelation, AnalysisSession, EVENT_TYPES, RELATION_TYPES
from app.services.case_service import CaseService
from app.services.relation_analysis_service import RelationAnalysisService
from app.services.area_analysis_service import AreaAnalysisService

router = APIRouter()


def _event_value(event: Any, field_name: str, default: Any = None) -> Any:
    """兼容 SQLAlchemy model 和 dict 两种事件结构。"""
    if isinstance(event, dict):
        return event.get(field_name, default)
    return getattr(event, field_name, default)


def _event_days_since(event_time: Optional[datetime], now: datetime) -> Optional[int]:
    if not event_time:
        return None
    if event_time.tzinfo is not None:
        event_time = event_time.replace(tzinfo=None)
    return (now - event_time).days


def _serialize_event(event: Any) -> Dict[str, Any]:
    if isinstance(event, dict):
        return dict(event)

    return {
        "id": event.id,
        "event_number": event.event_number,
        "event_type": event.event_type,
        "event_type_name": EVENT_TYPES.get(event.event_type, event.event_type),
        "occurred_time": event.occurred_time,
        "location": event.location,
        "latitude": event.latitude,
        "longitude": event.longitude,
        "village_name": event.village_name,
        "village_distance_km": event.village_distance_km,
        "township": event.township,
        "title": event.title,
        "description": event.description,
        "vehicles": event.vehicles,
        "oil_volume_liters": event.oil_volume_liters,
        "oil_type": event.oil_type,
        "equipment": event.equipment,
        "suspects_count": event.suspects_count,
        "discovery_method": event.discovery_method,
        "handling_result": event.handling_result,
        "risk_level": event.risk_level,
        "related_case_id": event.related_case_id,
        "created_at": event.created_at,
    }


def _serialize_area_analysis(result: Dict[str, Any]) -> Dict[str, Any]:
    serialized = dict(result)
    serialized["events"] = [
        _serialize_event(event) for event in result.get("events", [])
    ]
    serialized.setdefault("timeline", [])
    serialized.setdefault("relations", [])
    serialized.setdefault("risk_assessment", {})
    serialized.setdefault("suggestions", [])
    serialized.setdefault("patrol_suggestions", [])
    return serialized


def _next_event_number(db: Session, generated_at: datetime) -> str:
    prefix = f"EVT{generated_at.strftime('%Y%m%d')}"
    existing_numbers = db.query(Event.event_number).filter(
        Event.event_number.like(f"{prefix}%")
    ).all()

    max_sequence = 0
    for event_number, in existing_numbers:
        suffix = event_number.replace(prefix, "", 1)
        if suffix.isdigit():
            max_sequence = max(max_sequence, int(suffix))

    return f"{prefix}{max_sequence + 1:03d}"


def _build_event_model(event: "EventCreate", event_number: str) -> Event:
    return Event(
        event_number=event_number,
        event_type=event.event_type,
        occurred_time=event.occurred_time,
        location=event.location,
        latitude=event.latitude,
        longitude=event.longitude,
        village_name=event.village_name,
        village_distance_km=event.village_distance_km,
        township=event.township,
        title=event.title,
        description=event.description,
        vehicles=event.vehicles,
        oil_volume_liters=event.oil_volume_liters,
        oil_type=event.oil_type,
        equipment=event.equipment,
        suspects_count=event.suspects_count,
        suspects_description=event.suspects_description,
        discovery_method=event.discovery_method,
        handling_result=event.handling_result,
        related_case_id=event.related_case_id,
    )


def _normalize_relation(source_event: Event, relation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    target_event = relation.get("event")
    target_id = relation.get("event_id") or relation.get("event_b_id")
    if target_id is None and target_event is not None:
        target_id = _event_value(target_event, "id")

    if target_id is None or target_id == source_event.id:
        return None

    relation_type = relation.get("relation_type")
    if not relation_type:
        relation_types = relation.get("relation_types") or []
        relation_type = relation_types[0] if relation_types else "unknown"

    normalized = {
        key: value
        for key, value in relation.items()
        if key != "event"
    }
    normalized["event_id"] = target_id
    normalized["event_a_id"] = source_event.id
    normalized["event_b_id"] = target_id
    normalized["relation_type"] = relation_type

    if target_event is not None:
        normalized["related_event"] = _serialize_event(target_event)

    return normalized


# ==================== Pydantic 模型 ====================

class EventCreate(BaseModel):
    """创建事件"""
    event_type: str = Field(..., description="事件类型")
    occurred_time: datetime = Field(..., description="发生时间")
    location: Optional[str] = Field(None, description="地点描述")
    latitude: Optional[float] = Field(None, description="纬度")
    longitude: Optional[float] = Field(None, description="经度")
    village_name: Optional[str] = Field(None, description="关联村屯")
    village_distance_km: Optional[float] = Field(None, description="距村屯距离(km)")
    township: Optional[str] = Field(None, description="所属乡镇")
    title: Optional[str] = Field(None, description="事件标题")
    description: Optional[str] = Field(None, description="详细描述")
    vehicles: Optional[List[Dict]] = Field(None, description="涉及车辆")
    oil_volume_liters: Optional[float] = Field(None, description="涉及油量(升)")
    oil_type: Optional[str] = Field(None, description="油品类型")
    equipment: Optional[List[str]] = Field(None, description="涉及设备/工具")
    suspects_count: Optional[int] = Field(None, description="涉及人数")
    suspects_description: Optional[str] = Field(None, description="人员特征描述")
    discovery_method: Optional[str] = Field(None, description="发现方式")
    handling_result: Optional[str] = Field(None, description="处置结果")
    related_case_id: Optional[int] = Field(None, description="关联案件ID")


class EventUpdate(BaseModel):
    """更新事件"""
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    village_name: Optional[str] = None
    village_distance_km: Optional[float] = None
    township: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    vehicles: Optional[List[Dict]] = None
    oil_volume_liters: Optional[float] = None
    oil_type: Optional[str] = None
    equipment: Optional[List[str]] = None
    suspects_count: Optional[int] = None
    suspects_description: Optional[str] = None
    discovery_method: Optional[str] = None
    handling_result: Optional[str] = None
    risk_level: Optional[str] = None
    analysis_notes: Optional[str] = None
    suggested_actions: Optional[List[str]] = None


class EventResponse(BaseModel):
    """事件响应"""
    id: int
    event_number: str
    event_type: str
    occurred_time: datetime
    location: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    village_name: Optional[str]
    village_distance_km: Optional[float]
    township: Optional[str]
    title: Optional[str]
    description: Optional[str]
    vehicles: Optional[List[Dict]]
    oil_volume_liters: Optional[float]
    oil_type: Optional[str]
    equipment: Optional[List[str]]
    suspects_count: Optional[int]
    discovery_method: Optional[str]
    handling_result: Optional[str]
    is_analyzed: bool
    risk_level: Optional[str]
    analysis_notes: Optional[str]
    suggested_actions: Optional[List[str]]
    related_case_id: Optional[int]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class AreaAnalysisRequest(BaseModel):
    """区域分析请求"""
    area_name: str = Field(..., description="区域名称")
    radius_km: float = Field(5.0, description="分析半径(km)")
    days_back: int = Field(365, description="回溯天数")


class AreaAnalysisResponse(BaseModel):
    """区域分析响应"""
    area_name: str
    events: List[Dict[str, Any]]
    timeline: Any
    relations: List[Dict[str, Any]]
    risk_assessment: Dict[str, Any]
    suggestions: List[Dict[str, Any]]
    patrol_suggestions: Any


class AreaRiskRankingItem(BaseModel):
    """区域风险排名项"""
    area_name: str
    event_count: int
    last_event: Optional[datetime]
    type_counts: Dict[str, int]
    risk_score: float
    risk_level: str
    days_since_last: Optional[int]


class AreaHotspotResponse(BaseModel):
    """事件热点区域"""
    area_name: str
    event_count: int
    last_event: Optional[datetime]
    center_latitude: Optional[float]
    center_longitude: Optional[float]
    type_counts: Dict[str, int]
    risk_score: float
    risk_level: str
    days_since_last: Optional[int]


class RefreshAreaProfileResponse(BaseModel):
    """刷新区域档案响应"""
    message: str
    profile_id: int
    area_name: str
    risk_level: str
    risk_score: float
    total_events: int


class CorrelationAnalysisRequest(BaseModel):
    """关联分析请求"""
    event_ids: List[int] = Field(..., description="要分析的事件ID列表")


class CorrelationRelationResponse(BaseModel):
    """关联分析结果项"""
    event_id: int
    event_a_id: int
    event_b_id: int
    relation_type: str
    distance_km: Optional[float] = None
    time_gap_days: Optional[int] = None
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    chain_role: Optional[str] = None
    common_plates: Optional[List[str]] = None
    related_event: Optional[Dict[str, Any]] = None


class CorrelationAnalysisResponse(BaseModel):
    """关联分析响应"""
    event_count: int
    relations: List[CorrelationRelationResponse]
    relation_count: int


class AreaProfileResponse(BaseModel):
    """区域档案响应"""
    id: int
    area_name: str
    area_type: str
    center_latitude: Optional[float]
    center_longitude: Optional[float]
    radius_km: float
    township: Optional[str]
    county: Optional[str]
    total_events: int
    events_last_30_days: int
    events_last_90_days: int
    first_event_time: Optional[datetime]
    last_event_time: Optional[datetime]
    event_types_count: Optional[Dict]
    risk_level: str
    risk_score: float
    risk_factors: Optional[List]
    assessment: Optional[str]
    suggested_actions: Optional[List]
    patrol_suggestions: Optional[List]
    is_active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# ==================== 事件类型常量 ====================

@router.get("/types")
async def get_event_types():
    """获取所有事件类型"""
    return {
        "event_types": EVENT_TYPES,
        "relation_types": RELATION_TYPES
    }


# ==================== 事件 CRUD ====================

@router.post("/", response_model=EventResponse)
async def create_event(event: EventCreate, db: Session = Depends(get_db)):
    """创建新事件"""
    for _ in range(5):
        db_event = _build_event_model(
            event=event,
            event_number=_next_event_number(db, datetime.now()),
        )
        db.add(db_event)
        try:
            db.commit()
            db.refresh(db_event)
            return db_event
        except IntegrityError:
            db.rollback()

    raise HTTPException(status_code=409, detail="事件编号生成冲突，请重试")


@router.get("/", response_model=List[EventResponse])
async def list_events(
    skip: int = 0,
    limit: int = 100,
    event_type: Optional[str] = None,
    village_name: Optional[str] = None,
    days_back: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """获取事件列表"""
    query = db.query(Event)

    if event_type:
        query = query.filter(Event.event_type == event_type)
    if village_name:
        query = query.filter(Event.village_name.ilike(f"%{village_name}%"))
    if days_back:
        cutoff = datetime.now() - timedelta(days=days_back)
        query = query.filter(Event.occurred_time >= cutoff)

    events = query.order_by(Event.occurred_time.desc()).offset(skip).limit(limit).all()
    return events


@router.get("/{event_id:int}", response_model=EventResponse)
async def get_event(event_id: int, db: Session = Depends(get_db)):
    """获取单个事件详情"""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")
    return event


@router.post("/{event_id:int}/convert-to-case")
async def convert_event_to_case(event_id: int, db: Session = Depends(get_db)):
    """将事件转为案件，并回写事件关联案件 ID"""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")
    if event.related_case_id:
        return {
            "case_id": event.related_case_id,
            "event_id": event.id,
            "message": "事件已关联案件",
        }

    description_parts = [
        event.title or EVENT_TYPES.get(event.event_type, event.event_type),
        event.description,
        f"发现方式：{event.discovery_method}" if event.discovery_method else None,
        f"处置结果：{event.handling_result}" if event.handling_result else None,
        f"涉及车辆：{event.vehicles}" if event.vehicles else None,
        f"涉及设备：{', '.join(event.equipment)}" if event.equipment else None,
    ]
    case = CaseService.create_case(
        db=db,
        case_number=None,
        occurred_time=event.occurred_time,
        location=event.location,
        latitude=event.latitude,
        longitude=event.longitude,
        case_type=EVENT_TYPES.get(event.event_type, event.event_type),
        description="\n".join(part for part in description_parts if part),
        oil_type=event.oil_type,
        oil_volume=event.oil_volume_liters,
        vehicle_info={"vehicles": event.vehicles} if event.vehicles else None,
    )

    event.related_case_id = case.id
    event.handling_result = event.handling_result or "已转案件"
    db.commit()
    db.refresh(event)

    return {
        "case_id": case.id,
        "event_id": event.id,
        "message": "事件已转为案件",
    }


@router.put("/{event_id:int}", response_model=EventResponse)
async def update_event(
    event_id: int,
    event_update: EventUpdate,
    db: Session = Depends(get_db)
):
    """更新事件"""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")

    update_data = event_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(event, key, value)

    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id:int}")
async def delete_event(event_id: int, db: Session = Depends(get_db)):
    """删除事件"""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")

    db.delete(event)
    db.commit()
    return {"message": "事件已删除"}


# ==================== 区域分析 ====================

@router.post("/area/analyze", response_model=AreaAnalysisResponse)
async def analyze_area(
    request: AreaAnalysisRequest,
    db: Session = Depends(get_db)
):
    """
    分析指定区域的事件聚集情况

    这是核心分析功能，实现用户描述的研判逻辑：
    - 分析某村屯周边的事件分布
    - 识别事件之间的关联
    - 评估区域风险
    - 给出巡逻建议
    """
    result = AreaAnalysisService.analyze_area(
        db=db,
        area_name=request.area_name,
        radius_km=request.radius_km,
        time_range_days=request.days_back
    )

    return _serialize_area_analysis(result)


@router.get("/area/risk-ranking", response_model=List[AreaRiskRankingItem])
async def get_area_risk_ranking(
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """获取区域风险排名"""
    result = AreaAnalysisService.get_area_risk_ranking(db, limit=limit)
    return result


@router.get("/area/hotspots", response_model=List[AreaHotspotResponse])
async def get_hotspots(
    days_back: int = 90,
    min_events: int = 2,
    db: Session = Depends(get_db)
):
    """获取事件热点区域"""
    result = AreaAnalysisService.identify_hotspots(
        db=db,
        days_back=days_back,
        min_events=min_events
    )
    return result


# ==================== 区域档案 ====================

@router.get("/areas", response_model=List[AreaProfileResponse])
async def list_area_profiles(
    skip: int = 0,
    limit: int = 50,
    risk_level: Optional[str] = None,
    is_active: bool = True,
    db: Session = Depends(get_db)
):
    """获取区域档案列表"""
    query = db.query(AreaProfile)

    if risk_level:
        query = query.filter(AreaProfile.risk_level == risk_level)
    if is_active is not None:
        query = query.filter(AreaProfile.is_active == is_active)

    profiles = query.order_by(AreaProfile.risk_score.desc()).offset(skip).limit(limit).all()
    return profiles


@router.get("/areas/{area_id:int}", response_model=AreaProfileResponse)
async def get_area_profile(area_id: int, db: Session = Depends(get_db)):
    """获取区域档案详情"""
    profile = db.query(AreaProfile).filter(AreaProfile.id == area_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="区域档案不存在")
    return profile


@router.post("/areas/{area_name}/refresh", response_model=RefreshAreaProfileResponse)
async def refresh_area_profile(
    area_name: str,
    radius_km: float = 5.0,
    db: Session = Depends(get_db)
):
    """
    刷新区域档案

    重新计算该区域的统计数据和风险评估
    """
    # 先进行区域分析
    analysis = AreaAnalysisService.analyze_area(
        db=db,
        area_name=area_name,
        radius_km=radius_km
    )

    # 查找或创建区域档案
    profile = db.query(AreaProfile).filter(AreaProfile.area_name == area_name).first()

    if not profile:
        profile = AreaProfile(area_name=area_name)
        db.add(profile)

    # 更新统计数据
    profile.radius_km = radius_km
    profile.total_events = len(analysis.get("events", []))

    events = analysis.get("events", [])
    now = datetime.now()
    profile.events_last_30_days = sum(
        1 for e in events
        if (days_since := _event_days_since(_event_value(e, "occurred_time"), now)) is not None
        and days_since <= 30
    )
    profile.events_last_90_days = sum(
        1 for e in events
        if (days_since := _event_days_since(_event_value(e, "occurred_time"), now)) is not None
        and days_since <= 90
    )

    # 更新风险评估
    risk = analysis.get("risk_assessment", {})
    profile.risk_level = risk.get("level", "low")
    profile.risk_score = risk.get("score", 0)
    profile.risk_factors = risk.get("factors", [])
    profile.risk_updated_at = datetime.now()

    # 更新建议
    profile.suggested_actions = analysis.get("suggestions", [])
    profile.patrol_suggestions = analysis.get("patrol_suggestions", [])

    # 计算中心点
    if events:
        lats = [
            _event_value(e, "latitude")
            for e in events
            if _event_value(e, "latitude") is not None
        ]
        lngs = [
            _event_value(e, "longitude")
            for e in events
            if _event_value(e, "longitude") is not None
        ]
        if lats and lngs:
            profile.center_latitude = sum(lats) / len(lats)
            profile.center_longitude = sum(lngs) / len(lngs)

    # 事件类型统计
    type_counts = {}
    for e in events:
        t = _event_value(e, "event_type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    profile.event_types_count = type_counts

    times = [
        _event_value(e, "occurred_time")
        for e in events
        if _event_value(e, "occurred_time")
    ]
    if times:
        profile.first_event_time = min(times)
        profile.last_event_time = max(times)

    db.commit()
    db.refresh(profile)

    return {
        "message": "区域档案已更新",
        "profile_id": profile.id,
        "area_name": area_name,
        "risk_level": profile.risk_level,
        "risk_score": profile.risk_score,
        "total_events": profile.total_events
    }


# ==================== 关联分析 ====================

@router.post("/correlations/analyze", response_model=CorrelationAnalysisResponse)
async def analyze_correlations(
    request: CorrelationAnalysisRequest,
    db: Session = Depends(get_db)
):
    """
    分析指定事件之间的关联

    识别：
    - 空间聚集
    - 上下游关联
    - 车辆关联
    - 手法相似
    """
    # 获取事件
    events = db.query(Event).filter(Event.id.in_(request.event_ids)).all()

    if len(events) < 2:
        raise HTTPException(status_code=400, detail="至少需要2个事件进行关联分析")

    all_relations = []

    for event in events:
        # 空间关联
        spatial = RelationAnalysisService.find_spatial_relations(db, event)
        all_relations.extend(
            relation for relation in (
                _normalize_relation(event, item) for item in spatial
            )
            if relation is not None
        )

        # 上下游关联
        supply_chain = RelationAnalysisService.find_supply_chain_relations(db, event)
        all_relations.extend(
            relation for relation in (
                _normalize_relation(event, item) for item in supply_chain
            )
            if relation is not None
        )

        # 车辆关联
        vehicle = RelationAnalysisService.find_vehicle_relations(db, event)
        all_relations.extend(
            relation for relation in (
                _normalize_relation(event, item) for item in vehicle
            )
            if relation is not None
        )

    # 去重
    unique_relations = []
    seen = set()
    for r in all_relations:
        event_pair = tuple(sorted((r["event_a_id"], r["event_b_id"])))
        key = (*event_pair, r["relation_type"])
        if key not in seen:
            seen.add(key)
            unique_relations.append(r)

    return {
        "event_count": len(events),
        "relations": unique_relations,
        "relation_count": len(unique_relations)
    }


@router.get("/correlations")
async def list_correlations(
    relation_type: Optional[str] = None,
    is_confirmed: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """获取已识别的关联关系"""
    query = db.query(EventRelation)

    if relation_type:
        query = query.filter(EventRelation.relation_type == relation_type)
    if is_confirmed is not None:
        query = query.filter(EventRelation.is_confirmed == is_confirmed)

    relations = query.order_by(EventRelation.created_at.desc()).offset(skip).limit(limit).all()

    return [{
        "id": r.id,
        "event_a_id": r.event_a_id,
        "event_b_id": r.event_b_id,
        "relation_type": r.relation_type,
        "confidence": r.confidence,
        "distance_km": r.distance_km,
        "time_gap_days": r.time_gap_days,
        "evidence": r.evidence,
        "reasoning": r.reasoning,
        "is_confirmed": r.is_confirmed,
        "created_at": r.created_at
    } for r in relations]


@router.post("/correlations/{relation_id:int}/confirm")
async def confirm_correlation(
    relation_id: int,
    confirmed: bool = True,
    confirmed_by: str = "system",
    db: Session = Depends(get_db)
):
    """确认或否定关联关系"""
    relation = db.query(EventRelation).filter(EventRelation.id == relation_id).first()
    if not relation:
        raise HTTPException(status_code=404, detail="关联关系不存在")

    if confirmed:
        relation.is_confirmed = True
        relation.is_rejected = False
    else:
        relation.is_confirmed = False
        relation.is_rejected = True

    relation.confirmed_by = confirmed_by
    relation.confirmed_at = datetime.now()

    db.commit()

    return {"message": "关联状态已更新", "is_confirmed": relation.is_confirmed}


# ==================== 统计和概览 ====================

@router.get("/statistics")
async def get_event_statistics(
    days_back: int = 30,
    db: Session = Depends(get_db)
):
    """获取事件统计数据"""
    cutoff = datetime.now() - timedelta(days=days_back)

    # 总事件数
    total = db.query(func.count(Event.id)).scalar()
    recent = db.query(func.count(Event.id)).filter(Event.occurred_time >= cutoff).scalar()

    # 按类型统计
    type_stats = db.query(
        Event.event_type,
        func.count(Event.id)
    ).filter(
        Event.occurred_time >= cutoff
    ).group_by(Event.event_type).all()

    # 按村屯统计
    village_stats = db.query(
        Event.village_name,
        func.count(Event.id)
    ).filter(
        Event.occurred_time >= cutoff,
        Event.village_name.isnot(None)
    ).group_by(Event.village_name).order_by(func.count(Event.id).desc()).limit(10).all()

    # 高风险区域
    high_risk_areas = db.query(AreaProfile).filter(
        AreaProfile.risk_level.in_(["high", "critical"])
    ).order_by(AreaProfile.risk_score.desc()).limit(5).all()

    return {
        "total_events": total,
        "recent_events": recent,
        "days_back": days_back,
        "by_type": {t: c for t, c in type_stats},
        "by_village": {v: c for v, c in village_stats if v},
        "high_risk_areas": [{
            "area_name": a.area_name,
            "risk_level": a.risk_level,
            "risk_score": a.risk_score,
            "event_count": a.total_events
        } for a in high_risk_areas]
    }


@router.get("/map-data")
async def get_map_data(
    days_back: int = 90,
    event_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取地图展示数据"""
    cutoff = datetime.now() - timedelta(days=days_back)

    query = db.query(Event).filter(
        Event.occurred_time >= cutoff,
        Event.latitude.isnot(None),
        Event.longitude.isnot(None)
    )

    if event_type:
        query = query.filter(Event.event_type == event_type)

    events = query.all()

    return {
        "events": [{
            "id": e.id,
            "event_number": e.event_number,
            "event_type": e.event_type,
            "title": e.title or EVENT_TYPES.get(e.event_type, e.event_type),
            "latitude": e.latitude,
            "longitude": e.longitude,
            "occurred_time": e.occurred_time.isoformat() if e.occurred_time else None,
            "village_name": e.village_name,
            "risk_level": e.risk_level
        } for e in events],
        "event_types": EVENT_TYPES
    }
