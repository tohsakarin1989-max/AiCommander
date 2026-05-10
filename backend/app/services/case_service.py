from sqlalchemy.orm import Session
from app.models.case import Case
from typing import List, Optional
from datetime import datetime, date, time
from app.utils.geo import haversine_km, bounding_box
from app.repositories.case_repository import CaseRepository
from app.config import settings
from app.services.case_quality_service import CaseQualityService

class CaseService:
    @staticmethod
    def _refresh_chain_links(db: Session, case_id: int) -> None:
        try:
            from app.services.chain_analysis_service import ChainAnalysisService

            ChainAnalysisService.scan_chain_links(case_id, db)
        except Exception as e:
            from app.utils.logger import logger

            logger.warning(f"链条关联扫描失败: {e}")

    
    @staticmethod
    def _generate_case_number(db: Session, occurred_time: datetime) -> str:
        """
        根据发生日期自动生成案件编号：
        规则：YYYYMMDD + 当天排序三位，例如 20251201-001
        """
        date_str = occurred_time.strftime("%Y%m%d")
        prefix = f"{date_str}-"
        # 查找当日已有编号
        repo = CaseRepository(db)
        existing = repo.get_case_numbers_by_prefix(prefix)
        used = set()
        for num in existing:
            parts = str(num).split("-")
            if len(parts) != 2:
                continue
            try:
                used.add(int(parts[1]))
            except ValueError:
                continue
        seq = 1
        while seq in used:
            seq += 1
        return f"{prefix}{seq:03d}"

    @staticmethod
    def create_case(
        db: Session,
        case_number: Optional[str],
        occurred_time: datetime,
        location: str = None,
        latitude: float = None,
        longitude: float = None,
        case_type: str = None,
        description: str = None,
        involved_persons: dict = None,
        involved_items: dict = None,
        loss_amount: int = None,
        # 涉油案件特征
        oil_type: str = None,
        oil_volume: float = None,
        oil_value: int = None,
        facility_type: str = None,
        facility_owner: str = None,
        security_level: str = None,
        modus_operandi: str = None,
        suspect_roles: dict = None,
        vehicle_info: dict = None,
        upstream_source: str = None,
        downstream_destination: str = None,
        report_time: datetime = None,
        report_unit: str = None,
        source_type: str = None,
        source_detail: str = None,
        police_reported: bool = None,
        case_filed: bool = None,
        police_officer: str = None,
        police_phone: str = None,
        security_officers: list = None,
        oil_nature: str = None,
        water_cut: float = None,
        vehicle_handling: str = None,
        person_handling: str = None,
        oil_handling: str = None,
        operation_role: str = None,
        current_stage: str = None,
    ) -> Case:
        """创建案件：
        - 如果未提供案件编号，则按日期+当天排序自动生成（YYYYMMDD-001）
        """
        if not case_number or not str(case_number).strip():
            case_number = CaseService._generate_case_number(db, occurred_time)

        repo = CaseRepository(db)
        case = Case(
            case_number=case_number,
            occurred_time=occurred_time,
            location=location,
            latitude=latitude,
            longitude=longitude,
            case_type=case_type,
            description=description,
            involved_persons=involved_persons,
            involved_items=involved_items,
            loss_amount=loss_amount,
            oil_type=oil_type,
            oil_volume=oil_volume,
            oil_value=oil_value,
            facility_type=facility_type,
            facility_owner=facility_owner,
            security_level=security_level,
            modus_operandi=modus_operandi,
            suspect_roles=suspect_roles,
            vehicle_info=vehicle_info,
            upstream_source=upstream_source,
            downstream_destination=downstream_destination,
            report_time=report_time,
            report_unit=report_unit,
            source_type=source_type,
            source_detail=source_detail,
            police_reported=police_reported,
            case_filed=case_filed,
            police_officer=police_officer,
            police_phone=police_phone,
            security_officers=security_officers,
            oil_nature=oil_nature,
            water_cut=water_cut,
            vehicle_handling=vehicle_handling,
            person_handling=person_handling,
            oil_handling=oil_handling,
            operation_role=operation_role,
            current_stage=current_stage or "reported",
        )
        repo.add(case)
        CaseQualityService.refresh_case_quality(db, case)
        
        # 自动索引到向量数据库（异步，不阻塞）
        if settings.ENABLE_VECTOR_DB:
            try:
                from app.services.vector_db_service import VectorDBService
                vector_db = VectorDBService()
                if vector_db.is_available():
                    case_dict = {
                        "case_number": case.case_number,
                        "description": case.description,
                        "modus_operandi": case.modus_operandi,
                        "case_type": case.case_type,
                        "facility_type": case.facility_type,
                        "oil_type": case.oil_type,
                        "vehicle_info": case.vehicle_info,
                        "location": case.location,
                        "occurred_time": case.occurred_time,
                        "source_type": case.source_type,
                        "oil_nature": case.oil_nature,
                        "report_unit": case.report_unit,
                        "quality_score": case.quality_score,
                    }
                    vector_db.add_case(case.id, case_dict)
            except Exception as e:
                from app.utils.logger import logger
                logger.warning(f"自动索引案件到向量数据库失败: {e}")
        
        # 预处理改为由用户手动触发，不再自动执行
        CaseService._refresh_chain_links(db, case.id)
        return case
    
    @staticmethod
    def get_cases(
        db: Session,
        skip: int = 0,
        limit: int = 100
    ) -> List[Case]:
        """获取案件列表"""
        repo = CaseRepository(db)
        return repo.list(skip=skip, limit=limit)
    
    @staticmethod
    def get_case(db: Session, case_id: int) -> Optional[Case]:
        """获取单个案件"""
        repo = CaseRepository(db)
        return repo.get(case_id)
    
    @staticmethod
    def get_cases_by_ids(db: Session, case_ids: List[int]) -> List[Case]:
        """根据ID列表获取案件"""
        repo = CaseRepository(db)
        return repo.get_by_ids(case_ids)
    
    @staticmethod
    def update_case(
        db: Session,
        case_id: int,
        **kwargs
    ) -> Optional[Case]:
        """更新案件"""
        repo = CaseRepository(db)
        case = repo.get(case_id)
        if not case:
            return None
        repo.update(case, **kwargs)
        CaseQualityService.refresh_case_quality(db, case)
        
        # 更新向量数据库索引
        if settings.ENABLE_VECTOR_DB:
            try:
                from app.services.vector_db_service import VectorDBService
                vector_db = VectorDBService()
                if vector_db.is_available():
                    case_dict = {
                        "case_number": case.case_number,
                        "description": case.description,
                        "modus_operandi": case.modus_operandi,
                        "case_type": case.case_type,
                        "facility_type": case.facility_type,
                        "oil_type": case.oil_type,
                        "vehicle_info": case.vehicle_info,
                        "location": case.location,
                        "occurred_time": case.occurred_time,
                        "source_type": case.source_type,
                        "oil_nature": case.oil_nature,
                        "report_unit": case.report_unit,
                        "quality_score": case.quality_score,
                    }
                    vector_db.update_case(case.id, case_dict)
            except Exception as e:
                from app.utils.logger import logger
                logger.warning(f"更新向量数据库索引失败: {e}")
        CaseService._refresh_chain_links(db, case.id)
        return case
    
    @staticmethod
    def delete_case(db: Session, case_id: int) -> bool:
        """删除案件"""
        repo = CaseRepository(db)
        case = repo.get(case_id)
        if not case:
            return False
        
        # 从向量数据库删除
        if settings.ENABLE_VECTOR_DB:
            try:
                from app.services.vector_db_service import VectorDBService
                vector_db = VectorDBService()
                if vector_db.is_available():
                    vector_db.delete_case(case_id)
            except Exception as e:
                from app.utils.logger import logger
                logger.warning(f"从向量数据库删除案件失败: {e}")
        
        repo.delete(case)
        return True

    @staticmethod
    def get_nearby_cases(
        db: Session,
        center_case_id: int,
        radius_km: float = 1.0,
    ) -> List[Case]:
        """
        查询指定案件在给定半径（公里）内的其他案件
        用于空间串并案分析和地图聚合
        """
        center = db.query(Case).filter(Case.id == center_case_id).first()
        if not center or center.latitude is None or center.longitude is None:
            return []

        min_lat, max_lat, min_lon, max_lon = bounding_box(
            center.latitude, center.longitude, radius_km
        )

        # 先用粗略经纬度边界框过滤，再用精确距离筛选
        candidates = (
            db.query(Case)
            .filter(
                Case.id != center_case_id,
                Case.latitude.isnot(None),
                Case.longitude.isnot(None),
                Case.latitude >= min_lat,
                Case.latitude <= max_lat,
                Case.longitude >= min_lon,
                Case.longitude <= max_lon,
            )
            .all()
        )

        result: List[Case] = []
        for c in candidates:
            dist = haversine_km(center.latitude, center.longitude, c.latitude, c.longitude)
            if dist <= radius_km:
                result.append(c)

        return result
