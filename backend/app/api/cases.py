from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from app.database import get_db
from app.services.case_service import CaseService
from app.models.case import Case
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
    suspect_roles: Optional[dict] = None
    vehicle_info: Optional[dict] = None
    upstream_source: Optional[str] = None
    downstream_destination: Optional[str] = None
    involved_persons: Optional[dict] = None
    involved_items: Optional[dict] = None
    loss_amount: Optional[int] = None

class CaseUpdate(BaseModel):
    location: Optional[str] = None
    case_type: Optional[str] = None
    description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    involved_persons: Optional[dict] = None
    involved_items: Optional[dict] = None
    loss_amount: Optional[int] = None
    # 涉油案件特征
    oil_type: Optional[str] = None
    oil_volume: Optional[float] = None
    oil_value: Optional[int] = None
    facility_type: Optional[str] = None
    facility_owner: Optional[str] = None
    security_level: Optional[str] = None
    modus_operandi: Optional[str] = None
    suspect_roles: Optional[dict] = None
    vehicle_info: Optional[dict] = None
    upstream_source: Optional[str] = None
    downstream_destination: Optional[str] = None
    status: Optional[str] = None

class CaseResponse(BaseModel):
    id: int
    case_number: str
    occurred_time: datetime
    location: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    case_type: Optional[str]
    description: Optional[str]
    involved_persons: Optional[dict]
    involved_items: Optional[dict]
    loss_amount: Optional[int]
    # 涉油案件特征
    oil_type: Optional[str]
    oil_volume: Optional[float]
    oil_value: Optional[int]
    facility_type: Optional[str]
    facility_owner: Optional[str]
    security_level: Optional[str]
    modus_operandi: Optional[str]
    suspect_roles: Optional[dict]
    vehicle_info: Optional[dict]
    upstream_source: Optional[str]
    downstream_destination: Optional[str]
    # 结构化预处理结果（如有）
    features: Optional[dict] = None
    status: str
    
    class Config:
        from_attributes = True

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
    )

@router.get("/", response_model=List[CaseResponse])
def get_cases(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """获取案件列表"""
    return CaseService.get_cases(db, skip=skip, limit=limit)

@router.get("/{case_id}", response_model=CaseResponse)
def get_case(case_id: int, db: Session = Depends(get_db)):
    """获取单个案件"""
    case = CaseService.get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="案件不存在")
    return case

@router.put("/{case_id}", response_model=CaseResponse)
def update_case(
    case_id: int,
    case_update: CaseUpdate,
    db: Session = Depends(get_db)
):
    """更新案件"""
    update_data = case_update.dict(exclude_unset=True)
    case = CaseService.update_case(db, case_id, **update_data)
    if not case:
        raise HTTPException(status_code=404, detail="案件不存在")
    return case

@router.delete("/{case_id}")
def delete_case(case_id: int, db: Session = Depends(get_db)):
    """删除案件"""
    success = CaseService.delete_case(db, case_id)
    if not success:
        raise HTTPException(status_code=404, detail="案件不存在")
    return {"message": "删除成功"}


@router.get("/{case_id}/nearby", response_model=List[CaseResponse])
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


@router.post("/{case_id}/preprocess")
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


@router.post("/import")
async def import_cases(
    file: UploadFile = File(...),
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
    errors: List[str] = []

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
                errors.append(f"第{idx}行缺少发生时间或描述，已跳过")
                continue
            occurred_time = parse_time(str(ot_raw))
            location = row.get("location") or None
            lat = row.get("latitude")
            lng = row.get("longitude")
            try:
                latitude = float(lat) if lat not in (None, "", "None") else None
            except ValueError:
                latitude = None
            try:
                longitude = float(lng) if lng not in (None, "", "None") else None
            except ValueError:
                longitude = None

            CaseService.create_case(
                db=db,
                case_number=None,
                occurred_time=occurred_time,
                location=location,
                latitude=latitude,
                longitude=longitude,
                case_type=None,
                description=str(desc),
            )
            created_count += 1
        except Exception as e:
            errors.append(f"第{idx}行导入失败: {e}")

    return {
        "created": created_count,
        "errors": errors,
        "total": len(rows),
    }


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
