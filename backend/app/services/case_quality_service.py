from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvidence, CasePerson, CaseVehicle, OilRecoveryRecord


ALLOWED_SOURCE_TYPES = {
    "巡逻发现",
    "群众举报",
    "领导指派",
    "公安机关线索",
    "技防预警",
    "红色网格上报",
    "作业区反馈",
    "其他",
}

ALLOWED_OIL_NATURES = {"被盗原油", "落地原油", "收缴油品", "回收原油", "其他"}
ALLOWED_OPERATION_ROLES = {"主导", "联合", "配合", "协助"}
ALLOWED_STAGES = {"reported", "filed", "investigating", "transferred", "closed", "archived"}

VEHICLE_EVIDENCE_REQUIREMENTS = {
    "vehicle_front": "车辆正面照片",
    "vehicle_rear": "车辆后面照片",
    "vehicle_left": "车辆左侧照片",
    "vehicle_right": "车辆右侧照片",
    "vehicle_cabin_front": "驾驶室前排照片",
    "vehicle_cabin_rear": "驾驶室后排照片",
    "vehicle_trunk": "后备箱照片",
    "vehicle_dashboard": "仪表台照片",
    "vehicle_engine": "发动机照片",
    "vehicle_vin": "大架号照片",
    "vehicle_engine_rubbing": "发动机拓印",
    "vehicle_vin_rubbing": "大架号拓印",
}


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _strip_tz(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _text_contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


class CaseQualityService:
    """按业务细则对案件信息做确定性评分，并输出可供研判模块复用的案件画像。"""

    @staticmethod
    def get_related_data(db: Session, case_id: int) -> Dict[str, List[Any]]:
        return {
            "vehicles": db.query(CaseVehicle).filter(CaseVehicle.case_id == case_id).all(),
            "persons": db.query(CasePerson).filter(CasePerson.case_id == case_id).all(),
            "evidence": db.query(CaseEvidence).filter(CaseEvidence.case_id == case_id).all(),
            "oil_recovery": db.query(OilRecoveryRecord).filter(OilRecoveryRecord.case_id == case_id).all(),
        }

    @staticmethod
    def evaluate_case(db: Session, case: Case) -> Dict[str, Any]:
        related = CaseQualityService.get_related_data(db, case.id) if case.id else {
            "vehicles": [],
            "persons": [],
            "evidence": [],
            "oil_recovery": [],
        }
        vehicles: List[CaseVehicle] = related["vehicles"]
        persons: List[CasePerson] = related["persons"]
        evidence: List[CaseEvidence] = related["evidence"]
        oil_recovery: List[OilRecoveryRecord] = related["oil_recovery"]

        score = 0.0
        category_scores: Dict[str, float] = {}
        missing_required: List[Dict[str, str]] = []
        warnings: List[Dict[str, str]] = []
        recommendations: List[str] = []

        def add_missing(field: str, label: str, reason: str = "业务细则要求完整报送") -> None:
            missing_required.append({"field": field, "label": label, "reason": reason})

        def add_warning(field: str, message: str) -> None:
            warnings.append({"field": field, "message": message})

        # 1. 基础完整性 30 分
        basic_fields = [
            ("occurred_time", "发生时间"),
            ("location", "案发地点"),
            ("case_type", "案件类型"),
            ("description", "案情描述"),
            ("report_time", "报送时间"),
            ("report_unit", "报送/责任单位"),
            ("source_type", "案件线索来源"),
        ]
        present_basic = 0
        for field, label in basic_fields:
            if _is_blank(getattr(case, field, None)):
                add_missing(field, label)
            else:
                present_basic += 1
        basic_score = present_basic / len(basic_fields) * 30
        category_scores["completeness"] = round(basic_score, 2)
        score += basic_score

        # 2. 类型适配 20 分：案件涉及车辆/人员/原油时，要求明细和处置同步完善。
        text_pool = " ".join(
            str(v or "")
            for v in (
                case.case_type,
                case.description,
                case.modus_operandi,
                case.vehicle_handling,
                case.person_handling,
                case.oil_handling,
            )
        )
        legacy_vehicle_info = _json_list(case.vehicle_info)
        legacy_persons = _json_list(case.involved_persons)
        has_vehicle_signal = bool(vehicles or legacy_vehicle_info or _text_contains_any(text_pool, ("车辆", "车牌", "扣押车", "油罐车", "罐车")))
        has_person_signal = bool(persons or legacy_persons or _text_contains_any(text_pool, ("抓获", "人员", "嫌疑人", "司机")))
        has_oil_signal = bool(
            case.oil_type
            or case.oil_volume is not None
            or case.oil_nature
            or oil_recovery
            or _text_contains_any(text_pool, ("原油", "落地油", "盗油", "收缴油"))
        )

        type_checks: List[bool] = []
        if has_vehicle_signal:
            type_checks.extend([
                bool(vehicles or legacy_vehicle_info),
                not _is_blank(case.vehicle_handling) or any(not _is_blank(v.handling_status) for v in vehicles),
                any(not _is_blank(v.plate_number) for v in vehicles) or any(isinstance(v, dict) and not _is_blank(v.get("plate_number") or v.get("plate")) for v in legacy_vehicle_info),
            ])
            if not (vehicles or legacy_vehicle_info):
                add_missing("vehicles", "涉案车辆明细")
            if _is_blank(case.vehicle_handling) and not any(not _is_blank(v.handling_status) for v in vehicles):
                add_missing("vehicle_handling", "车辆处理方式")
        if has_person_signal:
            type_checks.extend([
                bool(persons or legacy_persons),
                not _is_blank(case.person_handling) or any(not _is_blank(p.handling_status) for p in persons),
            ])
            if not (persons or legacy_persons):
                add_missing("persons", "抓获人员明细")
            if _is_blank(case.person_handling) and not any(not _is_blank(p.handling_status) for p in persons):
                add_missing("person_handling", "人员处理方式")
        if has_oil_signal:
            type_checks.extend([
                not _is_blank(case.oil_nature) or any(not _is_blank(r.oil_nature) for r in oil_recovery),
                case.oil_volume is not None or any(r.volume_tons is not None for r in oil_recovery),
                not _is_blank(case.oil_handling) or any(not _is_blank(r.handling_method) for r in oil_recovery),
            ])
            if _is_blank(case.oil_nature) and not any(not _is_blank(r.oil_nature) for r in oil_recovery):
                add_missing("oil_nature", "原油性质")
            if case.oil_volume is None and not any(r.volume_tons is not None for r in oil_recovery):
                add_missing("oil_volume", "涉案原油数量/检斤数量")
            if _is_blank(case.oil_handling) and not any(not _is_blank(r.handling_method) for r in oil_recovery):
                add_missing("oil_handling", "原油处理方式")
        if case.police_reported or case.case_filed:
            type_checks.extend([not _is_blank(case.police_officer), not _is_blank(case.police_phone)])
            if _is_blank(case.police_officer):
                add_missing("police_officer", "公安出警人")
            if _is_blank(case.police_phone):
                add_missing("police_phone", "公安联系电话")
        type_score = (sum(1 for ok in type_checks if ok) / len(type_checks) * 20) if type_checks else 14
        category_scores["type_fit"] = round(type_score, 2)
        score += type_score

        # 3. 一致性 15 分
        consistency_penalties = 0
        occurred_time = _strip_tz(case.occurred_time)
        report_time = _strip_tz(case.report_time)
        created_at = _strip_tz(case.created_at)
        if report_time and occurred_time and report_time < occurred_time:
            consistency_penalties += 4
            add_warning("report_time", "报送时间早于案发时间")
        if case.case_filed and not case.police_reported:
            consistency_penalties += 3
            add_warning("case_filed", "已立案但未标记是否报案")
        if (case.latitude is None) ^ (case.longitude is None):
            consistency_penalties += 2
            add_warning("latitude/longitude", "经纬度只填写了一项")
        if case.water_cut is not None and not 0 <= case.water_cut <= 100:
            consistency_penalties += 3
            add_warning("water_cut", "含水率应在 0-100 之间")
        for vehicle in vehicles:
            if vehicle.water_cut is not None and not 0 <= vehicle.water_cut <= 100:
                consistency_penalties += 2
                add_warning("vehicle.water_cut", f"车辆 {vehicle.plate_number or vehicle.id} 含水率应在 0-100 之间")
            if vehicle.transferred_to_police and (_is_blank(vehicle.transfer_time) or _is_blank(vehicle.transfer_document_no)):
                consistency_penalties += 3
                add_warning("vehicle.transfer", f"车辆 {vehicle.plate_number or vehicle.id} 已移交公安但缺少移交时间或清单编号")
        consistency_score = max(0, 15 - consistency_penalties)
        category_scores["consistency"] = round(consistency_score, 2)
        score += consistency_score

        # 4. 证据材料 15 分
        evidence_keys = {e.requirement_key for e in evidence if e.requirement_key}
        if has_vehicle_signal:
            missing_vehicle_keys = [
                {"key": key, "label": label}
                for key, label in VEHICLE_EVIDENCE_REQUIREMENTS.items()
                if key not in evidence_keys
            ]
            vehicle_evidence_score = (len(VEHICLE_EVIDENCE_REQUIREMENTS) - len(missing_vehicle_keys)) / len(VEHICLE_EVIDENCE_REQUIREMENTS) * 10
            evidence_score = vehicle_evidence_score + min(len(evidence) * 1.25, 5)
            if missing_vehicle_keys:
                add_warning("case_evidence", "涉案车辆证据照片/拓印不完整")
                recommendations.append(
                    "补齐车辆正面、后面、左右侧、驾驶室、后备箱、仪表台、发动机、大架号及拓印材料。"
                )
        else:
            evidence_score = min(len(evidence) * 3, 12)
            if case.latitude is not None and case.longitude is not None and evidence:
                evidence_score += 3
        evidence_score = min(evidence_score, 15)
        category_scores["evidence"] = round(evidence_score, 2)
        score += evidence_score

        # 5. 研判可用性 10 分
        analyzability_checks = [
            case.latitude is not None and case.longitude is not None,
            not _is_blank(case.modus_operandi),
            bool(vehicles or legacy_vehicle_info),
            not _is_blank(case.upstream_source) or not _is_blank(case.downstream_destination),
            not _is_blank(case.source_type),
        ]
        analyzability_score = sum(1 for ok in analyzability_checks if ok) / len(analyzability_checks) * 10
        category_scores["analyzability"] = round(analyzability_score, 2)
        score += analyzability_score

        # 6. 时效性 5 分
        timeliness_score = 0.0
        reported_within_1h = None
        entered_within_48h = None
        if occurred_time and report_time:
            reported_within_1h = 0 <= (report_time - occurred_time).total_seconds() <= 3600
            timeliness_score += 3 if reported_within_1h else 0
            if not reported_within_1h:
                add_warning("report_time", "业务细则要求案件发生后 1 小时内报送")
        if occurred_time and created_at:
            entered_within_48h = 0 <= (created_at - occurred_time).total_seconds() <= 48 * 3600
            timeliness_score += 2 if entered_within_48h else 0
            if not entered_within_48h:
                add_warning("created_at", "业务细则要求案件发生后 48 小时内录入系统")
        category_scores["timeliness"] = round(timeliness_score, 2)
        score += timeliness_score

        # 7. 标准化 5 分
        standard_checks = [
            _is_blank(case.source_type) or case.source_type in ALLOWED_SOURCE_TYPES,
            _is_blank(case.oil_nature) or case.oil_nature in ALLOWED_OIL_NATURES,
            _is_blank(case.operation_role) or case.operation_role in ALLOWED_OPERATION_ROLES,
            _is_blank(case.current_stage) or case.current_stage in ALLOWED_STAGES,
        ]
        if case.source_type and case.source_type not in ALLOWED_SOURCE_TYPES:
            add_warning("source_type", "线索来源不在标准枚举内")
        if case.oil_nature and case.oil_nature not in ALLOWED_OIL_NATURES:
            add_warning("oil_nature", "原油性质不在标准枚举内")
        if case.operation_role and case.operation_role not in ALLOWED_OPERATION_ROLES:
            add_warning("operation_role", "联合行动角色不在标准枚举内")
        standard_score = sum(1 for ok in standard_checks if ok) / len(standard_checks) * 5
        category_scores["standardization"] = round(standard_score, 2)
        score += standard_score

        final_score = round(min(max(score, 0), 100), 2)
        if final_score >= 80:
            level = "high"
        elif final_score >= 60:
            level = "medium"
        else:
            level = "low"

        if missing_required:
            recommendations.append("优先补齐缺项字段；信息不准确或缺项会影响后续研判、报送和统计口径。")
        if case.latitude is None or case.longitude is None:
            recommendations.append("补充经纬度，空间研判、热点演化和巡逻规划才可准确使用该案件。")
        if has_person_signal and not persons and not legacy_persons:
            recommendations.append("补充抓获人员姓名、身份证号、住址及处理方式，支撑同伙识别。")

        return {
            "score": final_score,
            "level": level,
            "category_scores": category_scores,
            "missing_required": missing_required,
            "warnings": warnings,
            "recommendations": recommendations,
            "facts": {
                "has_vehicle_signal": has_vehicle_signal,
                "has_person_signal": has_person_signal,
                "has_oil_signal": has_oil_signal,
                "reported_within_1h": reported_within_1h,
                "entered_within_48h": entered_within_48h,
                "vehicle_count": len(vehicles) + len(legacy_vehicle_info),
                "person_count": len(persons) + len(legacy_persons),
                "evidence_count": len(evidence),
                "oil_recovery_count": len(oil_recovery),
            },
        }

    @staticmethod
    def refresh_case_quality(db: Session, case: Case, *, commit: bool = True) -> Dict[str, Any]:
        result = CaseQualityService.evaluate_case(db, case)
        case.quality_score = result["score"]
        case.quality_level = result["level"]
        case.quality_issues = result
        case.quality_updated_at = datetime.utcnow()
        if commit:
            db.commit()
            db.refresh(case)
        return result

    @staticmethod
    def build_analysis_readiness(profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        case = profile.get("case", {})
        quality = profile.get("quality", {})
        facts = quality.get("facts", {}) if isinstance(quality, dict) else {}
        missing = {
            item.get("field")
            for item in quality.get("missing_required", [])
            if isinstance(item, dict)
        }
        has_geo = case.get("latitude") is not None and case.get("longitude") is not None
        has_time = not _is_blank(case.get("occurred_time"))
        has_location = not _is_blank(case.get("location"))
        has_description = not _is_blank(case.get("description"))
        has_actor_or_vehicle = bool(
            profile.get("vehicles")
            or profile.get("legacy_vehicle_info")
            or profile.get("actors", {}).get("persons")
            or profile.get("actors", {}).get("legacy_persons")
        )
        has_flow = bool(
            profile.get("oil", {}).get("upstream_source")
            or profile.get("oil", {}).get("downstream_destination")
        )

        def item(status: str, blockers: List[str], actions: List[str]) -> Dict[str, Any]:
            return {
                "status": status,
                "blockers": blockers,
                "next_actions": actions,
            }

        spacetime_blockers: List[str] = []
        spacetime_actions: List[str] = []
        if not has_time:
            spacetime_blockers.append("缺少发生时间")
            spacetime_actions.append("补充发生时间，支撑时序聚类和热点演化。")
        if not has_geo:
            spacetime_blockers.append("缺少经纬度")
            spacetime_actions.append("补充经纬度，支撑地图落点、热点演化和轨迹研判。")
        if has_geo and has_time:
            spacetime_status = "ready"
        elif has_location and has_time:
            spacetime_status = "partial"
        else:
            spacetime_status = "missing_geo"

        gang_blockers: List[str] = []
        gang_actions: List[str] = []
        if not has_actor_or_vehicle:
            gang_blockers.append("缺少人员或车辆锚点")
            gang_actions.append("补充抓获人员、车牌、车辆品牌型号、处理状态，支撑同伙识别。")
        if not has_flow:
            gang_actions.append("补充上游来源或疑似销赃去向，提升团伙分工画像质量。")
        if has_actor_or_vehicle and has_time:
            gang_status = "ready"
        elif facts.get("has_person_signal") or facts.get("has_vehicle_signal"):
            gang_status = "partial"
        else:
            gang_status = "missing_actor_vehicle"

        patrol_blockers: List[str] = []
        patrol_actions: List[str] = []
        if not has_location:
            patrol_blockers.append("缺少巡逻区域")
            patrol_actions.append("补充案发地点或责任区域，才能生成巡逻区域建议。")
        if not has_geo:
            patrol_actions.append("补充经纬度后可生成更准确路线顺序。")
        if has_geo and has_location:
            patrol_status = "ready"
        elif has_location:
            patrol_status = "partial"
        else:
            patrol_status = "missing_location"

        roundtable_blockers: List[str] = []
        roundtable_actions: List[str] = []
        if not has_description:
            roundtable_blockers.append("缺少案情描述")
            roundtable_actions.append("补充标准化案情描述，圆桌会议才能形成有效上下文。")
        if missing:
            roundtable_actions.append("先补齐质量评分提示的核心缺项，减少圆桌研判偏差。")
        score = quality.get("score")
        if has_description and isinstance(score, (int, float)) and score >= 70:
            roundtable_status = "ready"
        elif has_description:
            roundtable_status = "partial"
        else:
            roundtable_status = "missing_core"

        return {
            "spacetime": item(spacetime_status, spacetime_blockers, spacetime_actions),
            "gang": item(gang_status, gang_blockers, gang_actions),
            "patrol": item(patrol_status, patrol_blockers, patrol_actions),
            "roundtable": item(roundtable_status, roundtable_blockers, roundtable_actions),
        }

    @staticmethod
    def build_case_feature_profile(db: Session, case: Case) -> Dict[str, Any]:
        related = CaseQualityService.get_related_data(db, case.id)
        quality = case.quality_issues or CaseQualityService.refresh_case_quality(db, case)
        profile = {
            "case": {
                "id": case.id,
                "case_number": case.case_number,
                "occurred_time": case.occurred_time.isoformat() if case.occurred_time else None,
                "location": case.location,
                "latitude": case.latitude,
                "longitude": case.longitude,
                "case_type": case.case_type,
                "description": case.description,
                "status": case.status,
                "current_stage": case.current_stage,
            },
            "management": {
                "report_time": case.report_time.isoformat() if case.report_time else None,
                "report_unit": case.report_unit,
                "source_type": case.source_type,
                "source_detail": case.source_detail,
                "police_reported": case.police_reported,
                "case_filed": case.case_filed,
                "police_officer": case.police_officer,
                "police_phone": case.police_phone,
                "security_officers": case.security_officers or [],
                "operation_role": case.operation_role,
            },
            "oil": {
                "oil_type": case.oil_type,
                "oil_nature": case.oil_nature,
                "oil_volume": case.oil_volume,
                "oil_value": case.oil_value,
                "water_cut": case.water_cut,
                "facility_type": case.facility_type,
                "facility_owner": case.facility_owner,
                "upstream_source": case.upstream_source,
                "downstream_destination": case.downstream_destination,
                "oil_handling": case.oil_handling,
                "recovery_records": [
                    {
                        "id": r.id,
                        "oil_nature": r.oil_nature,
                        "volume_tons": r.volume_tons,
                        "water_cut": r.water_cut,
                        "source": r.source,
                        "receiver": r.receiver,
                        "handled_at": r.handled_at.isoformat() if r.handled_at else None,
                        "handling_method": r.handling_method,
                    }
                    for r in related["oil_recovery"]
                ],
            },
            "actors": {
                "persons": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "gender": p.gender,
                        "id_number": p.id_number,
                        "home_address": p.home_address,
                        "phone": p.phone,
                        "role": p.role,
                        "handling_status": p.handling_status,
                    }
                    for p in related["persons"]
                ],
                "legacy_persons": _json_list(case.involved_persons),
                "person_handling": case.person_handling,
            },
            "vehicles": [
                {
                    "id": v.id,
                    "vehicle_type": v.vehicle_type,
                    "color": v.color,
                    "brand": v.brand,
                    "model": v.model,
                    "plate_number": v.plate_number,
                    "oil_volume": v.oil_volume,
                    "water_cut": v.water_cut,
                    "custody_location": v.custody_location,
                    "current_location": v.current_location,
                    "handling_status": v.handling_status,
                    "transferred_to_police": v.transferred_to_police,
                    "transfer_time": v.transfer_time.isoformat() if v.transfer_time else None,
                    "transfer_document_no": v.transfer_document_no,
                }
                for v in related["vehicles"]
            ],
            "legacy_vehicle_info": _json_list(case.vehicle_info),
            "evidence": [
                {
                    "id": e.id,
                    "evidence_type": e.evidence_type,
                    "title": e.title,
                    "file_path": e.file_path,
                    "requirement_key": e.requirement_key,
                    "captured_at": e.captured_at.isoformat() if e.captured_at else None,
                    "latitude": e.latitude,
                    "longitude": e.longitude,
                    "is_sensitive": e.is_sensitive,
                    "meta": e.meta,
                }
                for e in related["evidence"]
            ],
            "quality": quality,
        }
        profile["analysis_readiness"] = CaseQualityService.build_analysis_readiness(profile)
        return profile
