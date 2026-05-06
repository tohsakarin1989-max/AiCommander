from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.database import get_db
from app.services.case_service import CaseService
from app.services.case_automation_service import CaseAutomationService
from app.services.case_quality_service import CaseQualityService
from app.models.case import Case, CaseEvidence, CasePerson, CaseTip, CaseVehicle, OilRecoveryRecord
from app.models.preprocess_job import PreprocessJob
from app.tasks.preprocess_tasks import preprocess_case_task
import csv
import io
import openpyxl

router = APIRouter()
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".xltx", ".xltm"}

class CaseCreate(BaseModel):
    case_number: Optional[str] = None
    occurred_time: datetime
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    case_type: Optional[str] = None
    description: Optional[str] = None
    # 涉油案件特征
    oil_type: Optional[str] = None
    oil_volume: Optional[float] = None
    oil_value: Optional[int] = None
    facility_type: Optional[str] = None
    facility_owner: Optional[str] = None
    security_level: Optional[str] = None
    modus_operandi: Optional[str] = None
    suspect_roles: Optional[Any] = None
    vehicle_info: Optional[Any] = None
    upstream_source: Optional[str] = None
    downstream_destination: Optional[str] = None
    involved_persons: Optional[Any] = None
    involved_items: Optional[Any] = None
    loss_amount: Optional[int] = None
    # 业务管理细则字段
    report_time: Optional[datetime] = None
    report_unit: Optional[str] = None
    source_type: Optional[str] = None
    source_detail: Optional[str] = None
    police_reported: Optional[bool] = None
    case_filed: Optional[bool] = None
    police_officer: Optional[str] = None
    police_phone: Optional[str] = None
    security_officers: Optional[List[str]] = None
    oil_nature: Optional[str] = None
    water_cut: Optional[float] = None
    vehicle_handling: Optional[str] = None
    person_handling: Optional[str] = None
    oil_handling: Optional[str] = None
    operation_role: Optional[str] = None
    current_stage: Optional[str] = None

class CaseUpdate(BaseModel):
    case_number: Optional[str] = None
    occurred_time: Optional[datetime] = None
    location: Optional[str] = None
    case_type: Optional[str] = None
    description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    involved_persons: Optional[Any] = None
    involved_items: Optional[Any] = None
    loss_amount: Optional[int] = None
    # 涉油案件特征
    oil_type: Optional[str] = None
    oil_volume: Optional[float] = None
    oil_value: Optional[int] = None
    facility_type: Optional[str] = None
    facility_owner: Optional[str] = None
    security_level: Optional[str] = None
    modus_operandi: Optional[str] = None
    suspect_roles: Optional[Any] = None
    vehicle_info: Optional[Any] = None
    upstream_source: Optional[str] = None
    downstream_destination: Optional[str] = None
    status: Optional[str] = None
    report_time: Optional[datetime] = None
    report_unit: Optional[str] = None
    source_type: Optional[str] = None
    source_detail: Optional[str] = None
    police_reported: Optional[bool] = None
    case_filed: Optional[bool] = None
    police_officer: Optional[str] = None
    police_phone: Optional[str] = None
    security_officers: Optional[List[str]] = None
    oil_nature: Optional[str] = None
    water_cut: Optional[float] = None
    vehicle_handling: Optional[str] = None
    person_handling: Optional[str] = None
    oil_handling: Optional[str] = None
    operation_role: Optional[str] = None
    current_stage: Optional[str] = None

class CaseResponse(BaseModel):
    id: int
    case_number: str
    occurred_time: datetime
    location: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    case_type: Optional[str]
    description: Optional[str]
    involved_persons: Optional[Any]
    involved_items: Optional[Any]
    loss_amount: Optional[int]
    # 涉油案件特征
    oil_type: Optional[str]
    oil_volume: Optional[float]
    oil_value: Optional[int]
    facility_type: Optional[str]
    facility_owner: Optional[str]
    security_level: Optional[str]
    modus_operandi: Optional[str]
    suspect_roles: Optional[Any]
    vehicle_info: Optional[Any]
    upstream_source: Optional[str]
    downstream_destination: Optional[str]
    report_time: Optional[datetime] = None
    report_unit: Optional[str] = None
    source_type: Optional[str] = None
    source_detail: Optional[str] = None
    police_reported: Optional[bool] = None
    case_filed: Optional[bool] = None
    police_officer: Optional[str] = None
    police_phone: Optional[str] = None
    security_officers: Optional[List[str]] = None
    oil_nature: Optional[str] = None
    water_cut: Optional[float] = None
    vehicle_handling: Optional[str] = None
    person_handling: Optional[str] = None
    oil_handling: Optional[str] = None
    operation_role: Optional[str] = None
    current_stage: Optional[str] = None
    quality_score: Optional[float] = None
    quality_level: Optional[str] = None
    quality_issues: Optional[dict] = None
    quality_updated_at: Optional[datetime] = None
    # 结构化预处理结果（如有）
    features: Optional[dict] = None
    status: str
    
    class Config:
        from_attributes = True


class CaseQualityResponse(BaseModel):
    score: float
    level: str
    category_scores: Dict[str, float]
    missing_required: List[Dict[str, str]]
    warnings: List[Dict[str, str]]
    recommendations: List[str]
    facts: Dict[str, Any]


class CaseStructureRequest(BaseModel):
    text: str


class EvidenceClassifyRequest(BaseModel):
    title: Optional[str] = None
    file_path: Optional[str] = None
    evidence_type: Optional[str] = None
    requirement_key: Optional[str] = None
    notes: Optional[str] = None


class BonusCalculationRequest(BaseModel):
    rules: Optional[Dict[str, Any]] = None


class CaseVehicleCreate(BaseModel):
    vehicle_type: Optional[str] = None
    color: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    plate_number: Optional[str] = None
    oil_volume: Optional[float] = None
    water_cut: Optional[float] = None
    custody_location: Optional[str] = None
    current_location: Optional[str] = None
    handling_status: Optional[str] = None
    transferred_to_police: Optional[bool] = None
    transfer_time: Optional[datetime] = None
    transfer_document_no: Optional[str] = None
    notes: Optional[str] = None


class CaseVehicleResponse(CaseVehicleCreate):
    id: int
    case_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CasePersonCreate(BaseModel):
    name: Optional[str] = None
    gender: Optional[str] = None
    id_number: Optional[str] = None
    home_address: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    handling_status: Optional[str] = None
    notes: Optional[str] = None


class CasePersonResponse(CasePersonCreate):
    id: int
    case_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CaseEvidenceCreate(BaseModel):
    evidence_type: Optional[str] = None
    title: Optional[str] = None
    file_path: Optional[str] = None
    requirement_key: Optional[str] = None
    captured_at: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_sensitive: Optional[bool] = None
    meta: Optional[dict] = None
    notes: Optional[str] = None


class CaseEvidenceResponse(CaseEvidenceCreate):
    id: int
    case_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OilRecoveryCreate(BaseModel):
    oil_nature: Optional[str] = None
    volume_tons: Optional[float] = None
    water_cut: Optional[float] = None
    source: Optional[str] = None
    receiver: Optional[str] = None
    handled_at: Optional[datetime] = None
    handling_method: Optional[str] = None
    notes: Optional[str] = None


class OilRecoveryResponse(OilRecoveryCreate):
    id: int
    case_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CaseTipCreate(BaseModel):
    case_id: Optional[int] = None
    reporter_name: Optional[str] = None
    reporter_contact: Optional[str] = None
    reported_at: Optional[datetime] = None
    location: Optional[str] = None
    content: Optional[str] = None
    source_type: Optional[str] = None
    verification_status: Optional[str] = None
    resolution: Optional[str] = None
    prevention_actions: Optional[List[dict]] = None


class CaseTipResponse(CaseTipCreate):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


def _get_case_or_404(db: Session, case_id: int) -> Case:
    case = CaseService.get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="案件不存在")
    return case


class CaseStatistics(BaseModel):
    """案件统计数据"""
    total_cases: int
    today_cases: int
    pending_cases: int
    processing_cases: int
    resolved_cases: int
    this_week_cases: int
    this_month_cases: int
    cases_with_geo: int
    case_type_distribution: dict
    daily_trend: List[dict]


@router.get("/statistics", response_model=CaseStatistics)
def get_case_statistics(db: Session = Depends(get_db)):
    """
    获取案件统计数据
    用于智慧大屏和仪表板展示
    """
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = today_start.replace(day=1)

    # 总数统计
    total_cases = db.query(func.count(Case.id)).scalar() or 0

    # 今日案件
    today_cases = db.query(func.count(Case.id)).filter(
        Case.occurred_time >= today_start
    ).scalar() or 0

    # 状态统计
    pending_cases = db.query(func.count(Case.id)).filter(
        Case.status == 'pending'
    ).scalar() or 0

    processing_cases = db.query(func.count(Case.id)).filter(
        Case.status == 'processing'
    ).scalar() or 0

    resolved_cases = db.query(func.count(Case.id)).filter(
        Case.status == 'resolved'
    ).scalar() or 0

    # 本周案件
    this_week_cases = db.query(func.count(Case.id)).filter(
        Case.occurred_time >= week_start
    ).scalar() or 0

    # 本月案件
    this_month_cases = db.query(func.count(Case.id)).filter(
        Case.occurred_time >= month_start
    ).scalar() or 0

    # 带地理坐标的案件
    cases_with_geo = db.query(func.count(Case.id)).filter(
        Case.latitude.isnot(None),
        Case.longitude.isnot(None)
    ).scalar() or 0

    # 案件类型分布
    type_counts = db.query(
        Case.case_type,
        func.count(Case.id)
    ).group_by(Case.case_type).all()

    case_type_distribution = {
        (t or '未分类'): c for t, c in type_counts
    }

    # 最近7天趋势
    daily_trend = []
    for i in range(6, -1, -1):
        day = today_start - timedelta(days=i)
        day_end = day + timedelta(days=1)
        count = db.query(func.count(Case.id)).filter(
            Case.occurred_time >= day,
            Case.occurred_time < day_end
        ).scalar() or 0
        daily_trend.append({
            'date': day.strftime('%Y-%m-%d'),
            'label': day.strftime('%m/%d'),
            'count': count
        })

    return CaseStatistics(
        total_cases=total_cases,
        today_cases=today_cases,
        pending_cases=pending_cases,
        processing_cases=processing_cases,
        resolved_cases=resolved_cases,
        this_week_cases=this_week_cases,
        this_month_cases=this_month_cases,
        cases_with_geo=cases_with_geo,
        case_type_distribution=case_type_distribution,
        daily_trend=daily_trend
    )


@router.post("/structure-preview")
def structure_case_text(payload: CaseStructureRequest):
    """从案情文本中自动提取案件录入字段，供人工确认后写入。"""
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="案情文本不能为空")
    return CaseAutomationService.structure_case_text(payload.text)


@router.post("/evidence/classify")
def classify_case_evidence(payload: EvidenceClassifyRequest):
    """识别佐证材料类型，返回可写入 CaseEvidence.requirement_key 的归档建议。"""
    return CaseAutomationService.classify_evidence_payload(payload.model_dump(exclude_unset=True))


@router.post("/", response_model=CaseResponse)
def create_case(case: CaseCreate, db: Session = Depends(get_db)):
    """创建案件"""
    return CaseService.create_case(
        db=db,
        case_number=case.case_number,
        occurred_time=case.occurred_time,
        location=case.location,
        latitude=case.latitude,
        longitude=case.longitude,
        case_type=case.case_type,
        description=case.description,
        involved_persons=case.involved_persons,
        involved_items=case.involved_items,
        loss_amount=case.loss_amount,
        oil_type=case.oil_type,
        oil_volume=case.oil_volume,
        oil_value=case.oil_value,
        facility_type=case.facility_type,
        facility_owner=case.facility_owner,
        security_level=case.security_level,
        modus_operandi=case.modus_operandi,
        suspect_roles=case.suspect_roles,
        vehicle_info=case.vehicle_info,
        upstream_source=case.upstream_source,
        downstream_destination=case.downstream_destination,
        report_time=case.report_time,
        report_unit=case.report_unit,
        source_type=case.source_type,
        source_detail=case.source_detail,
        police_reported=case.police_reported,
        case_filed=case.case_filed,
        police_officer=case.police_officer,
        police_phone=case.police_phone,
        security_officers=case.security_officers,
        oil_nature=case.oil_nature,
        water_cut=case.water_cut,
        vehicle_handling=case.vehicle_handling,
        person_handling=case.person_handling,
        oil_handling=case.oil_handling,
        operation_role=case.operation_role,
        current_stage=case.current_stage,
    )

@router.get("/", response_model=List[CaseResponse])
def get_cases(
    skip: int = 0,
    limit: int = 100,
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    case_type: Optional[str] = None,
    oil_type: Optional[str] = None,
    source_type: Optional[str] = None,
    report_unit: Optional[str] = None,
    current_stage: Optional[str] = None,
    quality_level: Optional[str] = None,
    min_quality_score: Optional[float] = None,
    max_quality_score: Optional[float] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    has_geo: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    获取案件列表（支持筛选）

    Args:
        keyword: 关键词搜索（搜索案件编号、地点、描述）
        status: 状态筛选
        case_type: 案件类型筛选
        oil_type: 油品类型筛选
        source_type: 线索来源筛选
        report_unit: 报送/责任单位筛选
        current_stage: 当前办理阶段筛选
        quality_level: 信息质量等级筛选
        min_quality_score/max_quality_score: 信息质量评分范围
        start_date: 开始日期
        end_date: 结束日期
        has_geo: 是否有地理坐标
    """
    query = db.query(Case)

    # 关键词搜索
    if keyword:
        keyword_pattern = f"%{keyword}%"
        query = query.filter(
            (Case.case_number.ilike(keyword_pattern)) |
            (Case.location.ilike(keyword_pattern)) |
            (Case.description.ilike(keyword_pattern))
        )

    # 状态筛选
    if status:
        query = query.filter(Case.status == status)

    # 案件类型筛选
    if case_type:
        query = query.filter(Case.case_type == case_type)

    # 油品类型筛选
    if oil_type:
        query = query.filter(Case.oil_type == oil_type)

    if source_type:
        query = query.filter(Case.source_type == source_type)

    if report_unit:
        query = query.filter(Case.report_unit == report_unit)

    if current_stage:
        query = query.filter(Case.current_stage == current_stage)

    if quality_level:
        query = query.filter(Case.quality_level == quality_level)

    if min_quality_score is not None:
        query = query.filter(Case.quality_score >= min_quality_score)
    if max_quality_score is not None:
        query = query.filter(Case.quality_score <= max_quality_score)

    # 日期范围筛选
    if start_date:
        query = query.filter(Case.occurred_time >= start_date)
    if end_date:
        query = query.filter(Case.occurred_time <= end_date)

    # 地理坐标筛选
    if has_geo is True:
        query = query.filter(Case.latitude.isnot(None), Case.longitude.isnot(None))
    elif has_geo is False:
        query = query.filter((Case.latitude.is_(None)) | (Case.longitude.is_(None)))

    # 排序和分页
    query = query.order_by(Case.occurred_time.desc())
    return query.offset(skip).limit(limit).all()

@router.get("/{case_id:int}", response_model=CaseResponse)
def get_case(case_id: int, db: Session = Depends(get_db)):
    """获取单个案件"""
    case = CaseService.get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="案件不存在")
    return case

@router.put("/{case_id:int}", response_model=CaseResponse)
def update_case(
    case_id: int,
    case_update: CaseUpdate,
    db: Session = Depends(get_db)
):
    """更新案件"""
    update_data = case_update.model_dump(exclude_unset=True)
    case = CaseService.update_case(db, case_id, **update_data)
    if not case:
        raise HTTPException(status_code=404, detail="案件不存在")
    return case

@router.delete("/{case_id:int}")
def delete_case(case_id: int, db: Session = Depends(get_db)):
    """删除案件"""
    success = CaseService.delete_case(db, case_id)
    if not success:
        raise HTTPException(status_code=404, detail="案件不存在")
    return {"message": "删除成功"}


@router.get("/{case_id:int}/nearby", response_model=List[CaseResponse])
def get_nearby_cases(
    case_id: int,
    radius_km: float = 1.0,
    db: Session = Depends(get_db),
):
    """
    获取指定案件附近一定半径（公里）内的其他案件
    用于空间串并案和地图聚类分析
    """
    if radius_km <= 0:
        raise HTTPException(status_code=400, detail="radius_km 必须大于 0")
    nearby = CaseService.get_nearby_cases(db, center_case_id=case_id, radius_km=radius_km)
    return nearby


@router.get("/{case_id:int}/quality", response_model=CaseQualityResponse)
def get_case_quality(case_id: int, db: Session = Depends(get_db)):
    """获取案件信息质量评分，评分规则来自业务管理细则。"""
    case = _get_case_or_404(db, case_id)
    if not case.quality_issues:
        return CaseQualityService.refresh_case_quality(db, case)
    return case.quality_issues


@router.post("/{case_id:int}/quality/recalculate", response_model=CaseQualityResponse)
def recalculate_case_quality(case_id: int, db: Session = Depends(get_db)):
    """重新计算案件信息质量评分。"""
    case = _get_case_or_404(db, case_id)
    return CaseQualityService.refresh_case_quality(db, case)


@router.get("/{case_id:int}/bonus-assessment")
def get_bonus_assessment(case_id: int, db: Session = Depends(get_db)):
    """获取案件奖金考核材料门禁和默认规则测算结果。"""
    case = _get_case_or_404(db, case_id)
    return CaseAutomationService.build_bonus_assessment(db, case)


@router.get("/{case_id:int}/automation-workbench")
def get_case_automation_workbench(case_id: int, db: Session = Depends(get_db)):
    """获取案件自动化工作台：结论分层、经验卡和缺口闭环。"""
    case = _get_case_or_404(db, case_id)
    return CaseAutomationService.build_automation_workbench(db, case)


@router.post("/{case_id:int}/bonus-assessment/calculate")
def calculate_bonus_assessment(
    case_id: int,
    payload: BonusCalculationRequest,
    db: Session = Depends(get_db),
):
    """按传入的奖金考核细则参数重新测算案件奖金。"""
    case = _get_case_or_404(db, case_id)
    return CaseAutomationService.build_bonus_assessment(db, case, rules=payload.rules)


@router.get("/{case_id:int}/feature-profile")
def get_case_feature_profile(case_id: int, db: Session = Depends(get_db)):
    """获取统一案件画像，供预处理、研判、巡逻、圆桌会议等模块复用。"""
    case = _get_case_or_404(db, case_id)
    return CaseQualityService.build_case_feature_profile(db, case)


@router.get("/{case_id:int}/vehicles", response_model=List[CaseVehicleResponse])
def list_case_vehicles(case_id: int, db: Session = Depends(get_db)):
    """获取案件涉案车辆台账。"""
    _get_case_or_404(db, case_id)
    return (
        db.query(CaseVehicle)
        .filter(CaseVehicle.case_id == case_id)
        .order_by(CaseVehicle.created_at.desc())
        .all()
    )


@router.post("/{case_id:int}/vehicles", response_model=CaseVehicleResponse)
def create_case_vehicle(case_id: int, payload: CaseVehicleCreate, db: Session = Depends(get_db)):
    """新增案件涉案车辆台账，并同步刷新信息质量评分。"""
    case = _get_case_or_404(db, case_id)
    vehicle = CaseVehicle(case_id=case_id, **payload.model_dump(exclude_unset=True))
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    CaseQualityService.refresh_case_quality(db, case)
    return vehicle


@router.get("/{case_id:int}/persons", response_model=List[CasePersonResponse])
def list_case_persons(case_id: int, db: Session = Depends(get_db)):
    """获取案件抓获/涉案人员台账。"""
    _get_case_or_404(db, case_id)
    return (
        db.query(CasePerson)
        .filter(CasePerson.case_id == case_id)
        .order_by(CasePerson.created_at.desc())
        .all()
    )


@router.post("/{case_id:int}/persons", response_model=CasePersonResponse)
def create_case_person(case_id: int, payload: CasePersonCreate, db: Session = Depends(get_db)):
    """新增抓获/涉案人员信息，并同步刷新信息质量评分。"""
    case = _get_case_or_404(db, case_id)
    person = CasePerson(case_id=case_id, **payload.model_dump(exclude_unset=True))
    db.add(person)
    db.commit()
    db.refresh(person)
    CaseQualityService.refresh_case_quality(db, case)
    return person


@router.get("/{case_id:int}/evidence", response_model=List[CaseEvidenceResponse])
def list_case_evidence(case_id: int, db: Session = Depends(get_db)):
    """获取案件证据材料目录。"""
    _get_case_or_404(db, case_id)
    return (
        db.query(CaseEvidence)
        .filter(CaseEvidence.case_id == case_id)
        .order_by(CaseEvidence.created_at.desc())
        .all()
    )


@router.post("/{case_id:int}/evidence", response_model=CaseEvidenceResponse)
def create_case_evidence(case_id: int, payload: CaseEvidenceCreate, db: Session = Depends(get_db)):
    """新增证据材料目录项，并同步刷新信息质量评分。"""
    case = _get_case_or_404(db, case_id)
    evidence_data = payload.model_dump(exclude_unset=True)
    classification = CaseAutomationService.classify_evidence_payload(evidence_data)
    if not evidence_data.get("requirement_key") and classification.get("requirement_key"):
        evidence_data["requirement_key"] = classification["requirement_key"]
    if not evidence_data.get("evidence_type") and classification.get("evidence_type"):
        evidence_data["evidence_type"] = classification["evidence_type"]
    meta = evidence_data.get("meta") or {}
    meta["auto_classification"] = classification
    evidence_data["meta"] = meta
    evidence = CaseEvidence(case_id=case_id, **evidence_data)
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    CaseQualityService.refresh_case_quality(db, case)
    return evidence


@router.get("/{case_id:int}/oil-recovery", response_model=List[OilRecoveryResponse])
def list_oil_recovery(case_id: int, db: Session = Depends(get_db)):
    """获取案件涉案原油回收/处理记录。"""
    _get_case_or_404(db, case_id)
    return (
        db.query(OilRecoveryRecord)
        .filter(OilRecoveryRecord.case_id == case_id)
        .order_by(OilRecoveryRecord.created_at.desc())
        .all()
    )


@router.post("/{case_id:int}/oil-recovery", response_model=OilRecoveryResponse)
def create_oil_recovery(case_id: int, payload: OilRecoveryCreate, db: Session = Depends(get_db)):
    """新增涉案原油回收/处理记录，并同步刷新信息质量评分。"""
    case = _get_case_or_404(db, case_id)
    record = OilRecoveryRecord(case_id=case_id, **payload.model_dump(exclude_unset=True))
    db.add(record)
    db.commit()
    db.refresh(record)
    CaseQualityService.refresh_case_quality(db, case)
    return record


@router.post("/{case_id:int}/preprocess")
def preprocess_case(case_id: int, db: Session = Depends(get_db)):
    """
    手动触发指定案件的预处理任务：
    - 使用与主持人相同的大模型对案情做摘要和结构化分析
    - 结果写入 Case.features 字段
    """
    case = CaseService.get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="案件不存在")

    try:
        task = preprocess_case_task.delay(case_id)
        return {"message": "预处理任务已提交", "task_id": str(task.id)}
    except Exception:
        # 如果 Celery 不可用，则尝试同步执行一次，避免完全失败
        from app.services.preprocess_service import CasePreprocessService

        result = CasePreprocessService.preprocess_case(db, case_id)
        if result is None:
            raise HTTPException(status_code=500, detail="预处理失败，请检查模型配置")
        return {"message": "预处理已同步完成", "result": result}


@router.get("/tips", response_model=List[CaseTipResponse])
def list_case_tips(
    case_id: Optional[int] = None,
    verification_status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """获取举报/线索台账，可按案件或核实状态筛选。"""
    query = db.query(CaseTip)
    if case_id is not None:
        query = query.filter(CaseTip.case_id == case_id)
    if verification_status:
        query = query.filter(CaseTip.verification_status == verification_status)
    return query.order_by(CaseTip.reported_at.desc(), CaseTip.created_at.desc()).all()


@router.post("/tips", response_model=CaseTipResponse)
def create_case_tip(payload: CaseTipCreate, db: Session = Depends(get_db)):
    """新增举报/线索台账。"""
    if payload.case_id is not None:
        _get_case_or_404(db, payload.case_id)
    tip = CaseTip(**payload.model_dump(exclude_unset=True))
    db.add(tip)
    db.commit()
    db.refresh(tip)
    if tip.case_id is not None:
        case = _get_case_or_404(db, tip.case_id)
        CaseQualityService.refresh_case_quality(db, case)
    return tip


@router.post("/import")
async def import_cases(
    file: UploadFile = File(...),
    dry_run: bool = False,
    db: Session = Depends(get_db),
):
    """
    导入历史案件（CSV/Excel）：
    - 只要求包含列：occurred_time, description
    - 可选：location, latitude, longitude

    occurred_time 建议为 ISO 时间或 "YYYY-MM-DD HH:MM" 格式。
    """
    filename = file.filename or ""
    lowered = filename.lower()
    if not any(lowered.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="仅支持 CSV 或 Excel (xlsx) 文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，限制为 10MB")

    created_count = 0
    valid_count = 0
    preview_rows: List[dict] = []
    errors: List[dict] = []

    def parse_time(value: str) -> datetime:
        value = value.strip()
        # 尝试多种常见时间格式
        fmts = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d",
        ]
        for fmt in fmts:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        # 如果都失败，直接抛错
        raise ValueError(f"无法解析时间格式: {value}")

    def parse_optional_time(value) -> Optional[datetime]:
        if value in (None, "", "None"):
            return None
        return parse_time(str(value))

    def parse_optional_float(value) -> Optional[float]:
        if value in (None, "", "None"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def parse_optional_bool(value) -> Optional[bool]:
        if value in (None, "", "None"):
            return None
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "是", "已", "已报", "已立案"}:
            return True
        if text in {"0", "false", "no", "n", "否", "未", "未报", "未立案"}:
            return False
        return None

    rows: List[dict] = []

    try:
        if lowered.endswith(".csv"):
            text = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        elif lowered.endswith((".xlsx", ".xlsm", ".xltx", ".xltm")):
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
            ws = wb.active
            headers = [str(c.value).strip() if c.value is not None else "" for c in next(ws.rows)]
            for r in ws.iter_rows(min_row=2, values_only=True):
                row = {headers[i]: (r[i] if i < len(r) else None) for i in range(len(headers))}
                rows.append(row)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析文件失败: {e}")

    required_cols = {"occurred_time", "description"}
    if not rows:
        raise HTTPException(status_code=400, detail="文件中没有数据")

    missing = required_cols - set(rows[0].keys())
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"缺少必需列: {', '.join(missing)}。至少需要: occurred_time, description",
        )

    for idx, row in enumerate(rows, start=2):  # 行号从2开始（跳过表头）
        try:
            ot_raw = row.get("occurred_time")
            desc = row.get("description")
            if not ot_raw or not desc:
                errors.append({"row": idx, "error": "缺少发生时间或描述"})
                continue
            occurred_time = parse_time(str(ot_raw))
            location = row.get("location") or None
            latitude = parse_optional_float(row.get("latitude"))
            longitude = parse_optional_float(row.get("longitude"))
            report_time = parse_optional_time(row.get("report_time"))
            report_unit = row.get("report_unit") or row.get("security_team") or None
            source_type = row.get("source_type") or None
            oil_nature = row.get("oil_nature") or None
            water_cut = parse_optional_float(row.get("water_cut"))

            valid_count += 1
            preview_rows.append({
                "row": idx,
                "occurred_time": occurred_time.isoformat(),
                "location": location,
                "latitude": latitude,
                "longitude": longitude,
                "report_time": report_time.isoformat() if report_time else None,
                "report_unit": report_unit,
                "source_type": source_type,
                "description": str(desc)[:120],
            })

            if not dry_run:
                CaseService.create_case(
                    db=db,
                    case_number=None,
                    occurred_time=occurred_time,
                    location=location,
                    latitude=latitude,
                    longitude=longitude,
                    case_type=row.get("case_type") or None,
                    description=str(desc),
                    report_time=report_time,
                    report_unit=report_unit,
                    source_type=source_type,
                    source_detail=row.get("source_detail") or None,
                    police_reported=parse_optional_bool(row.get("police_reported")),
                    case_filed=parse_optional_bool(row.get("case_filed")),
                    police_officer=row.get("police_officer") or None,
                    police_phone=row.get("police_phone") or None,
                    oil_type=row.get("oil_type") or None,
                    oil_volume=parse_optional_float(row.get("oil_volume")),
                    oil_nature=oil_nature,
                    water_cut=water_cut,
                    facility_type=row.get("facility_type") or None,
                    facility_owner=row.get("facility_owner") or None,
                    modus_operandi=row.get("modus_operandi") or None,
                    vehicle_handling=row.get("vehicle_handling") or None,
                    person_handling=row.get("person_handling") or None,
                    oil_handling=row.get("oil_handling") or None,
                    operation_role=row.get("operation_role") or None,
                    current_stage=row.get("current_stage") or None,
                )
                created_count += 1
        except Exception as e:
            errors.append({"row": idx, "error": str(e)})

    return {
        "created": created_count,
        "updated": 0,
        "valid": valid_count,
        "errors": errors,
        "total": len(rows),
        "dry_run": dry_run,
        "preview": preview_rows[:20],
    }


@router.get("/hotspot-evolution")
def get_hotspot_evolution(
    months: int = 6,
    radius_km: float = 1.0,
    min_cases: int = 2,
    db: Session = Depends(get_db)
):
    """获取热点时间演化数据（按月分段）"""
    from app.services.geo_analysis_service import GeoAnalysisService
    try:
        return GeoAnalysisService.find_hotspots_by_period(
            db=db, months=months, radius_km=radius_km, min_cases=min_cases
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/geo/analysis")
def get_geographic_analysis(
    case_ids: Optional[List[int]] = None,
    db: Session = Depends(get_db)
):
    """
    获取地理线索分析报告
    包括：热点区域、串案分析、地理模式等
    """
    from app.services.geo_analysis_service import GeoAnalysisService
    
    clues = GeoAnalysisService.generate_geographic_clues(db, case_ids)
    return clues

@router.get("/geo/hotspots")
def get_hotspots(
    radius_km: float = 0.5,
    min_cases: int = 3,
    db: Session = Depends(get_db)
):
    """获取案件热点区域"""
    from app.services.geo_analysis_service import GeoAnalysisService
    
    hotspots = GeoAnalysisService.find_hotspots(db, radius_km, min_cases)
    return {"hotspots": hotspots}

@router.get("/geo/serial-cases")
def get_serial_cases(
    case_ids: Optional[List[int]] = None,
    max_distance_km: float = 2.0,
    time_window_days: int = 30,
    use_semantic: bool = True,
    use_geo: bool = True,
    min_semantic_similarity: float = 0.6,
    db: Session = Depends(get_db)
):
    """
    获取串案分析（支持语义和地理混合分析）
    
    Args:
        use_semantic: 是否使用语义分析
        use_geo: 是否使用地理分析
        min_semantic_similarity: 最小语义相似度阈值（0-1）
    """
    if use_semantic:
        from app.services.semantic_analysis_service import SemanticAnalysisService
        service = SemanticAnalysisService()
        serial_cases = service.analyze_hybrid_serial_cases(
            db, case_ids, max_distance_km, time_window_days,
            min_semantic_similarity, use_semantic, use_geo
        )
    else:
        from app.services.geo_analysis_service import GeoAnalysisService
        serial_cases = GeoAnalysisService.analyze_serial_cases(
            db, case_ids, max_distance_km, time_window_days
        )
    return {"serial_cases": serial_cases}

@router.get("/semantic/search")
def semantic_search(
    query: str,
    top_k: int = 10,
    min_similarity: float = 0.5,
    db: Session = Depends(get_db)
):
    """基于语义相似度搜索案件"""
    from app.services.semantic_analysis_service import SemanticAnalysisService
    service = SemanticAnalysisService()
    results = service.search_by_semantic_similarity(
        db, query, top_k, min_similarity
    )
    return {"query": query, "results": results}

@router.get("/trajectory/{case_ids}")
def get_trajectory(
    case_ids: str,  # 逗号分隔的案件ID
    db: Session = Depends(get_db)
):
    """获取案件轨迹"""
    from app.services.trajectory_service import TrajectoryService
    case_id_list = [int(id.strip()) for id in case_ids.split(",") if id.strip().isdigit()]
    trajectory = TrajectoryService.extract_trajectory(db, case_id_list)
    return {"trajectory": trajectory}

@router.get("/trajectory/{case_ids}/analysis")
def analyze_trajectory(
    case_ids: str,
    db: Session = Depends(get_db)
):
    """分析轨迹模式"""
    from app.services.trajectory_service import TrajectoryService
    case_id_list = [int(id.strip()) for id in case_ids.split(",") if id.strip().isdigit()]
    trajectory = TrajectoryService.extract_trajectory(db, case_id_list)
    analysis = TrajectoryService.analyze_trajectory_pattern(trajectory)
    return analysis

@router.get("/trajectory/{case_ids}/predict")
def predict_next_location(
    case_ids: str,
    use_ai: bool = True,
    db: Session = Depends(get_db)
):
    """预测下一个可能的位置"""
    from app.services.trajectory_service import TrajectoryService
    case_id_list = [int(id.strip()) for id in case_ids.split(",") if id.strip().isdigit()]
    prediction = TrajectoryService.predict_next_location(db, case_id_list, use_ai)
    return prediction

@router.get("/trajectory/{case_ids}/replay")
def get_trajectory_replay(
    case_ids: str,
    interval_seconds: int = 60,
    db: Session = Depends(get_db)
):
    """获取轨迹回放数据"""
    from app.services.trajectory_service import TrajectoryService
    case_id_list = [int(id.strip()) for id in case_ids.split(",") if id.strip().isdigit()]
    replay_data = TrajectoryService.get_trajectory_replay_data(db, case_id_list, interval_seconds)
    return replay_data

@router.get("/preprocess/status")
def get_preprocess_status(db: Session = Depends(get_db)):
    """
    获取预处理队列状态：
    - pending: 等待中的任务数
    - processing: 进行中的任务数
    - success: 最近成功任务数
    - avg_duration_seconds: 成功任务的平均耗时（秒）
    """
    pending = (
        db.query(PreprocessJob)
        .filter(PreprocessJob.status == "queued")
        .count()
    )
    processing = (
        db.query(PreprocessJob)
        .filter(PreprocessJob.status == "processing")
        .count()
    )
    successes = (
        db.query(PreprocessJob)
        .filter(PreprocessJob.status == "success", PreprocessJob.finished_at.isnot(None))
        .order_by(PreprocessJob.finished_at.desc())
        .limit(100)
        .all()
    )
    durations = []
    for j in successes:
        if j.started_at and j.finished_at:
            delta = (j.finished_at - j.started_at).total_seconds()
            if delta >= 0:
                durations.append(delta)
    avg_duration = sum(durations) / len(durations) if durations else None

    return {
        "pending": pending,
        "processing": processing,
        "success": len(successes),
        "avg_duration_seconds": avg_duration,
    }
