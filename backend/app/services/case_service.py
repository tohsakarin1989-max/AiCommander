from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.case import Case, CasePerson, CaseVehicle
from typing import List, Optional
from datetime import datetime, date, time, timezone
from zoneinfo import ZoneInfo
from app.utils.geo import haversine_km, bounding_box
from app.repositories.case_repository import CaseRepository
from app.services.case_quality_service import CaseQualityService
from app.services.case_pipeline_service import CasePipelineService
from app.database import require_area_write_access
from app.utils.datetimes import utc_datetime
from app.services.case_number_service import occupied_numbers, is_number_collision, ensure_number_transaction
from app.services.case_intake_contract import normalize_intake, OIL_UNITS
from app.services.case_source_service import CaseSourceService
from app.models.case_source import CaseLocation, OilMeasurement

class CaseService:
    @staticmethod
    def _refresh_chain_links(db: Session, case_id: int) -> None:
        """旧兼容 hook；扫描已由保存事务中的 Outbox 交给后台。"""

    
    @staticmethod
    def _generate_case_number(db: Session, occurred_time: datetime) -> str:
        """
        根据发生日期自动生成案件编号：
        规则：YYYYMMDD + 当天排序三位，例如 20251201-001
        """
        date_str = occurred_time.strftime("%Y%m%d")
        prefix = f"{date_str}-"
        # 查找当日已有编号
        existing = occupied_numbers(db, prefix)
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
        occurred_time: datetime | None = None,
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
        initial_vehicles: list = None,
        initial_persons: list = None,
        operational_area_id: int = None,
        commit: bool = True,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        time_precision: str | None = None,
        time_expression: str | None = None,
        time_timezone: str = "Asia/Shanghai",
        discovered_at: datetime | None = None,
        oil_volume_unit: str = "unknown",
        initial_locations: list | None = None,
        initial_measurements: list | None = None,
        source_links: list | None = None,
    ) -> Case:
        """创建案件：
        - 如果未提供案件编号，则按日期+当天排序自动生成（YYYYMMDD-001）
        """
        operational_area_id = require_area_write_access(db, operational_area_id)
        intake = dict(occurred_time=occurred_time, occurred_from=occurred_from, occurred_to=occurred_to,
                      time_expression=time_expression, time_timezone=time_timezone, discovered_at=discovered_at,
                      report_time=report_time, latitude=latitude, longitude=longitude, oil_volume=oil_volume,
                      oil_volume_unit=oil_volume_unit, initial_locations=initial_locations,
                      initial_measurements=initial_measurements)
        if time_precision is not None:
            intake["time_precision"] = time_precision
        intake = normalize_intake(intake)
        occurred_time = intake["occurred_time"]
        numbering_zone = ZoneInfo(time_timezone or "Asia/Shanghai")
        numbering_time = (occurred_time or datetime.now(timezone.utc)).astimezone(numbering_zone)
        automatic_number = not case_number or not str(case_number).strip()
        if automatic_number:
            ensure_number_transaction(db)
            case_number = CaseService._generate_case_number(db, numbering_time)

        repo = CaseRepository(db)
        case = Case(
            operational_area_id=operational_area_id,
            case_number=case_number,
            occurred_time=utc_datetime(occurred_time),
            occurred_from=intake["occurred_from"], occurred_to=intake["occurred_to"],
            time_precision=intake["time_precision"], time_expression=time_expression,
            time_timezone=time_timezone, discovered_at=intake["discovered_at"],
            location=location,
            latitude=latitude,
            longitude=longitude,
            case_type=case_type,
            description=description,
            involved_items=involved_items,
            loss_amount=loss_amount,
            oil_type=oil_type,
            oil_volume=oil_volume,
            oil_volume_unit=oil_volume_unit or "unknown",
            oil_value=oil_value,
            facility_type=facility_type,
            facility_owner=facility_owner,
            security_level=security_level,
            modus_operandi=modus_operandi,
            suspect_roles=suspect_roles,
            upstream_source=upstream_source,
            downstream_destination=downstream_destination,
            report_time=intake["report_time"],
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
        if not automatic_number:
            repo.add(case, commit=False)
        else:
            for attempt in range(8):
                # Establish the savepoint before handling insert errors: failures
                # flushing unrelated pending objects must not trigger allocation.
                savepoint = db.begin_nested()
                try:
                    with savepoint:
                        repo.add(case, commit=False)
                    break
                except IntegrityError as exc:
                    if not is_number_collision(exc) or attempt == 7:
                        raise
                    case.case_number = CaseService._generate_case_number(db, numbering_time)
        case._source_legacy_inputs = {key: value for key, value in {
            "vehicle_info": vehicle_info, "involved_persons": involved_persons}.items() if value is not None}
        CaseService._sync_initial_bonus_records(
            db,
            case.id,
            initial_vehicles=initial_vehicles if initial_vehicles is not None else CaseService._legacy_details(vehicle_info, "vehicles"),
            initial_persons=initial_persons if initial_persons is not None else CaseService._legacy_details(involved_persons, "persons"),
            commit=False,
        )
        CaseService._project_incident_location(db, case, intake["initial_locations"],
            explicit_coordinates={"latitude": latitude, "longitude": longitude}
            if latitude is not None or longitude is not None else {})
        CaseService._replace_typed_records(db, case.id, CaseLocation, intake["initial_locations"])
        CaseService._replace_typed_records(db, case.id, OilMeasurement, intake["initial_measurements"])
        CaseSourceService.add_source_links(db, case.id, source_links)
        CaseQualityService.refresh_case_quality(db, case, commit=False)
        CasePipelineService.enqueue_case_change(db, case)
        if not commit:
            return case
        db.commit()
        db.refresh(case)
        CaseService.finish_created_case(db, case)
        return case

    @staticmethod
    def _legacy_details(value, kind):
        """Only explicit object records are parsed; no name-based deduplication."""
        if isinstance(value, dict):
            value = value.get(kind, [value])
        if not isinstance(value, list):
            return []
        model = CaseVehicle if kind == "vehicles" else CasePerson
        allowed = set(model.__table__.columns.keys()) - {"id", "case_id", "created_at", "updated_at"}
        aliases = {"plate": "plate_number", "type": "vehicle_type"} if kind == "vehicles" else {}
        result = []
        for item in value:
            if not isinstance(item, dict):
                continue
            parsed = {aliases.get(key, key): val for key, val in item.items() if aliases.get(key, key) in allowed}
            if parsed:
                result.append(parsed)
        return result

    @staticmethod
    def _replace_typed_records(db, case_id, model, records):
        if records is None:
            return
        allowed = set(model.__table__.columns.keys()) - {"id", "case_id"}
        existing = {row.id: row for row in db.query(model).filter_by(case_id=case_id).all()}
        seen = set()
        # Validate the complete replacement before changing any detail. Missing
        # IDs mean new records, never a guessed match by value or array position.
        for record in records:
            identifier = record.get("id")
            if identifier is None:
                continue
            if type(identifier) is not int or identifier <= 0:
                raise ValueError("invalid_detail_id")
            if identifier in seen:
                raise ValueError("duplicate_detail_id")
            if identifier not in existing:
                raise ValueError("detail_id_not_in_case")
            seen.add(identifier)
        for record in records:
            values = {key: val for key, val in record.items() if key in allowed}
            identifier = record.get("id")
            if identifier is None:
                db.add(model(case_id=case_id, **values))
            else:
                for key, value in values.items():
                    setattr(existing[identifier], key, value)
        for identifier, row in existing.items():
            if identifier not in seen:
                db.delete(row)
        db.flush()

    @staticmethod
    def _project_incident_location(db, case, records, *, explicit_coordinates):
        if records is None:
            if not explicit_coordinates:
                return
            existing = db.query(CaseLocation).filter_by(case_id=case.id, role="incident").all()
            if not existing:
                return
            records = [{"role": row.role, "precision": row.precision, "geometry": row.geometry} for row in existing]
        had_incident = db.query(CaseLocation.id).filter_by(case_id=case.id, role="incident").first() is not None
        incidents = [record for record in records if record.get("role") == "incident"]
        explicit = bool(explicit_coordinates)
        if len(incidents) == 1 and incidents[0].get("precision") == "exact":
            geometry = incidents[0].get("geometry") or {}
            if geometry.get("type") != "Point":
                raise ValueError("精确案发地点必须有点坐标")
            longitude, latitude = geometry["coordinates"]
            if explicit and (explicit_coordinates.get("latitude"), explicit_coordinates.get("longitude")) != (latitude, longitude):
                raise ValueError("主坐标与精确案发地点冲突")
            case.latitude, case.longitude = latitude, longitude
        elif incidents:
            if any(value is not None for value in explicit_coordinates.values()):
                raise ValueError("区域、未知或多个案发地点不能同时作为精确主坐标")
            case.latitude, case.longitude = None, None
        elif had_incident and not explicit:
            # Removing an incident must not leave a ghost route endpoint.
            case.latitude, case.longitude = None, None

    @staticmethod
    def finish_created_case(db: Session, case: Case) -> None:
        """Best-effort derived indexes after the business transaction commits."""
        # Same-transaction Outbox drives profile/history rebuilding in background.
        # No embedding model or secondary vector store is invoked by case save.

    @staticmethod
    def _sync_initial_bonus_records(
        db: Session,
        case_id: int,
        initial_vehicles: list,
        initial_persons: list,
        *,
        replace_vehicles: bool = False,
        replace_persons: bool = False,
        commit: bool = True,
    ) -> None:
        vehicle_fields = {
            "road_vehicle_kind", "height_m", "gross_weight_t",
            "vehicle_type",
            "color",
            "brand",
            "model",
            "plate_number",
            "oil_volume",
            "oil_volume_unit",
            "water_cut",
            "custody_location",
            "current_location",
            "handling_status",
            "transferred_to_police",
            "transfer_time",
            "transfer_document_no",
            "notes",
        }
        person_fields = {
            "name",
            "gender",
            "id_number",
            "home_address",
            "phone",
            "role",
            "handling_status",
            "notes",
        }

        seen_vehicle_ids = set()
        for item in initial_vehicles:
            raw = dict(item or {})
            vehicle_id = raw.get("id")
            payload = {key: value for key, value in raw.items() if key in vehicle_fields}
            if payload.get("oil_volume_unit", "unknown") not in OIL_UNITS:
                raise ValueError("invalid_vehicle_oil_unit")
            has_payload = any(key in vehicle_fields for key in raw)
            if not has_payload:
                if vehicle_id:
                    seen_vehicle_ids.add(vehicle_id)
                continue
            if vehicle_id:
                vehicle = db.query(CaseVehicle).filter(
                    CaseVehicle.id == vehicle_id,
                    CaseVehicle.case_id == case_id,
                ).first()
                if vehicle:
                    seen_vehicle_ids.add(vehicle.id)
                    for key, value in payload.items():
                        setattr(vehicle, key, None if value == "" else value)
                    continue
            clean_payload = {key: value for key, value in payload.items() if value not in (None, "")}
            if clean_payload:
                vehicle = CaseVehicle(case_id=case_id, **clean_payload)
                db.add(vehicle)
                db.flush()
                seen_vehicle_ids.add(vehicle.id)
        if replace_vehicles:
            query = db.query(CaseVehicle).filter(CaseVehicle.case_id == case_id)
            if seen_vehicle_ids:
                query = query.filter(CaseVehicle.id.notin_(seen_vehicle_ids))
            for vehicle in query.all():
                db.delete(vehicle)

        seen_person_ids = set()
        for item in initial_persons:
            raw = dict(item or {})
            person_id = raw.get("id")
            payload = {key: value for key, value in raw.items() if key in person_fields}
            has_payload = any(key in person_fields for key in raw)
            if not has_payload:
                if person_id:
                    seen_person_ids.add(person_id)
                continue
            if person_id:
                person = db.query(CasePerson).filter(
                    CasePerson.id == person_id,
                    CasePerson.case_id == case_id,
                ).first()
                if person:
                    seen_person_ids.add(person.id)
                    for key, value in payload.items():
                        setattr(person, key, None if value == "" else value)
                    continue
            clean_payload = {key: value for key, value in payload.items() if value not in (None, "")}
            if clean_payload:
                person = CasePerson(case_id=case_id, **clean_payload)
                db.add(person)
                db.flush()
                seen_person_ids.add(person.id)
        if replace_persons:
            query = db.query(CasePerson).filter(CasePerson.case_id == case_id)
            if seen_person_ids:
                query = query.filter(CasePerson.id.notin_(seen_person_ids))
            for person in query.all():
                db.delete(person)

        if commit and (initial_vehicles or initial_persons or replace_vehicles or replace_persons):
            db.commit()
    
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
        *,
        initial_vehicles: list | None = None,
        initial_persons: list | None = None,
        replace_vehicles: bool = False,
        replace_persons: bool = False,
        initial_locations: list | None = None,
        initial_measurements: list | None = None,
        source_links: list | None = None,
        commit: bool = True,
        **kwargs
    ) -> Optional[Case]:
        """在一个事务中更新案件标量、人员车辆、质量和派生任务。"""
        repo = CaseRepository(db)
        case = repo.get(case_id)
        if not case:
            return None
        require_area_write_access(db, case.operational_area_id)
        try:
            values = normalize_intake({**kwargs, "initial_locations": initial_locations,
                                       "initial_measurements": initial_measurements}, existing=case)
            initial_locations = values.pop("initial_locations")
            initial_measurements = values.pop("initial_measurements")
            kwargs = values
            legacy = {}
            for key, canonical, kind in (("vehicle_info", initial_vehicles, "vehicles"),
                                          ("involved_persons", initial_persons, "persons")):
                if key in kwargs:
                    legacy[key] = kwargs.pop(key)
                    if canonical is None:
                        parsed = CaseService._legacy_details(legacy[key], kind)
                        if kind == "vehicles":
                            initial_vehicles, replace_vehicles = parsed, True
                        else:
                            initial_persons, replace_persons = parsed, True
                    setattr(case, key, None)
                elif canonical is not None and getattr(case, key) is not None:
                    legacy[key] = getattr(case, key)
                    setattr(case, key, None)
            case._source_legacy_inputs = legacy
            repo.update(case, commit=False, **kwargs)
            CaseService._sync_initial_bonus_records(
                db,
                case.id,
                initial_vehicles=initial_vehicles or [],
                initial_persons=initial_persons or [],
                replace_vehicles=replace_vehicles,
                replace_persons=replace_persons,
                commit=False,
            )
            CaseService._project_incident_location(db, case, initial_locations,
                explicit_coordinates={key: kwargs[key] for key in ("latitude", "longitude") if key in kwargs})
            CaseService._replace_typed_records(db, case.id, CaseLocation, initial_locations)
            CaseService._replace_typed_records(db, case.id, OilMeasurement, initial_measurements)
            CaseSourceService.add_source_links(db, case.id, source_links)
            CaseQualityService.refresh_case_quality(db, case, commit=False)
            changed_fields = set(kwargs)
            if replace_vehicles or initial_vehicles is not None or legacy:
                changed_fields.add("vehicles")
            if replace_persons or initial_persons is not None or legacy:
                changed_fields.add("persons")
            if initial_locations is not None:
                changed_fields.add("locations")
            if initial_measurements is not None:
                changed_fields.add("measurements")
            if source_links is not None:
                changed_fields.add("source_links")
            CasePipelineService.enqueue_case_change(db, case, changed_fields=changed_fields)
            if commit:
                db.commit()
        except Exception:
            db.rollback()
            raise
        if commit:
            db.refresh(case)
        
        # History index updates are delivered by the committed Outbox event.
        return case
    
    @staticmethod
    def delete_case(db: Session, case_id: int) -> bool:
        """删除案件"""
        repo = CaseRepository(db)
        case = repo.get(case_id)
        if not case:
            return False
        require_area_write_access(db, case.operational_area_id)
        
        # Retain only scope metadata before derived rows disappear by FK cascade.
        # The notification and deletion share the repository commit.
        from app.models.case_history_index import CaseHistoryIndex
        from app.services.history_road_refresh import record_change
        index = db.get(CaseHistoryIndex, (case.id, 'case', str(case.id)))
        areas = [case.operational_area_id]
        if index is not None:
            areas.append(index.payload.get('history_area_id')
                         if isinstance(index.payload, dict) else None)
        try:
            record_change(db, case_id=case.id, area_ids=areas)
            repo.delete(case)
        except Exception:
            db.rollback()
            raise
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
                Case.operational_area_id == center.operational_area_id,
            )
            .all()
        )

        result: List[Case] = []
        for c in candidates:
            dist = haversine_km(center.latitude, center.longitude, c.latitude, c.longitude)
            if dist <= radius_km:
                result.append(c)

        return result
