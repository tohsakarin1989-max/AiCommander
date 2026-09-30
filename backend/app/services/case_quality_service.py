from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvidence, CasePerson, CaseVehicle, OilRecoveryRecord
from app.models.case_source import CaseLocation, OilMeasurement
from app.services.case_intake_contract import normalize_intake
from app.services.case_quality_rules import (
    DEFAULT_TIMELINESS_POLICY, TimelinessPolicy, evaluate_timeliness, time_precision, utc_instant,
)
from app.services.case_semantic_mentions import extract_term_assertions

QUALITY_RULE_VERSION = "case-quality-6.1.0-1"
ALLOWED_SOURCE_TYPES = {"巡逻发现", "群众举报", "领导指派", "公安机关线索", "技防预警", "红色网格上报", "作业区反馈", "其他"}
ALLOWED_OIL_NATURES = {"被盗原油", "落地原油", "收缴油品", "回收原油", "其他"}
ALLOWED_OPERATION_ROLES = {"主导", "联合", "配合", "协助"}
ALLOWED_STAGES = {"reported", "filed", "investigating", "transferred", "closed", "archived"}
DISPOSAL_STAGES = {"transferred", "closed", "archived"}
VEHICLE_EVIDENCE_REQUIREMENTS = {
    "vehicle_front": "车辆正面照片", "vehicle_rear": "车辆后面照片",
    "vehicle_left": "车辆左侧照片", "vehicle_right": "车辆右侧照片",
    "vehicle_cabin_front": "驾驶室前排照片", "vehicle_cabin_rear": "驾驶室后排照片",
    "vehicle_trunk": "后备箱照片", "vehicle_dashboard": "仪表台照片",
    "vehicle_engine": "发动机照片", "vehicle_vin": "大架号照片",
    "vehicle_engine_rubbing": "发动机拓印", "vehicle_vin_rubbing": "大架号拓印",
}
SIGNAL_TERMS = {
    "vehicle": {term: term for term in ("车辆", "车牌", "扣押车", "油罐车", "罐车", "皮卡")},
    "person": {term: term for term in ("抓获", "涉案人员", "嫌疑人", "司机")},
    "oil": {term: term for term in ("原油", "落地油", "盗油", "收缴油")},
}


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, dict, tuple, set)) and not value)


def _json_list(value):
    return value if isinstance(value, list) else [value] if isinstance(value, dict) else []


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else None


def _signals(case):
    assertions = extract_term_assertions(
        {field: getattr(case, field, None) for field in ("description", "modus_operandi")}, SIGNAL_TERMS,
    )["assertions"]
    return {item["category"] for item in assertions if item["kind"] == "stated"}


def _valid_geo(case):
    return all(isinstance(case.get(field), (int, float)) and not isinstance(case.get(field), bool)
               and isfinite(case[field]) and -bound <= case[field] <= bound
               for field, bound in (("latitude", 90), ("longitude", 180)))


def _spatial_input(case, locations):
    """An area/mentioned/discovery location must not become a precise incident endpoint."""
    spatial = {"location": case.location, "latitude": case.latitude, "longitude": case.longitude}
    incidents = [row for row in locations if row.role == "incident"]
    if not incidents:
        return spatial
    spatial.update(latitude=None, longitude=None)
    spatial["location"] = spatial["location"] or next((row.description for row in incidents if row.description), None)
    if len(incidents) == 1 and incidents[0].precision == "exact":
        geometry = incidents[0].geometry or {}
        coords = geometry.get("coordinates")
        if geometry.get("type") == "Point" and isinstance(coords, list) and len(coords) == 2:
            spatial.update(longitude=coords[0], latitude=coords[1])
    return spatial


class CaseQualityService:
    """Read-only validity, scenario completeness and input readiness; never case completion."""

    @staticmethod
    def get_related_data(db: Session, case_id: int) -> Dict[str, List[Any]]:
        return {
            "vehicles": db.query(CaseVehicle).filter(CaseVehicle.case_id == case_id).all(),
            "persons": db.query(CasePerson).filter(CasePerson.case_id == case_id).all(),
            "evidence": db.query(CaseEvidence).filter(CaseEvidence.case_id == case_id).all(),
            "oil_recovery": db.query(OilRecoveryRecord).filter(OilRecoveryRecord.case_id == case_id).all(),
            "locations": db.query(CaseLocation).filter(CaseLocation.case_id == case_id).all(),
            "oil_measurements": db.query(OilMeasurement).filter(OilMeasurement.case_id == case_id).all(),
        }

    @staticmethod
    def evaluate_case(db: Session, case: Case, *, related_data=None,
                      timeliness_policy: TimelinessPolicy = DEFAULT_TIMELINESS_POLICY) -> Dict[str, Any]:
        related = related_data if related_data is not None else (
            CaseQualityService.get_related_data(db, case.id) if case.id else {})
        vehicles, persons, evidence, recovery = (related.get(key, []) for key in
                                                ("vehicles", "persons", "evidence", "oil_recovery"))
        measurements = related.get("oil_measurements", [])
        spatial = _spatial_input(case, related.get("locations", []))
        errors, warnings, gaps = [], [], []

        def gap(field, label, reason, capabilities=(), category="context"):
            if not any(item["field"] == field for item in gaps):
                gaps.append({"field": field, "label": label, "reason": reason,
                             "category": category, "affected_capabilities": list(capabilities)})

        def warning(field, message):
            warnings.append({"field": field, "message": message})

        try:
            normalize_intake({
                **{key: getattr(case, key, None) for key in (
                    "occurred_time", "occurred_from", "occurred_to", "report_time", "discovered_at",
                    "time_timezone", "latitude", "longitude", "oil_volume", "oil_volume_unit")},
                "time_precision": time_precision(case),
            })
        except (TypeError, ValueError) as exc:
            errors.append({"field": "input", "label": "录入格式", "message": str(exc)})
        for row, prefix in [(case, "")] + [(vehicle, "vehicle.") for vehicle in vehicles]:
            value = getattr(row, "water_cut", None)
            if value is not None and (not isinstance(value, (float, int)) or isinstance(value, bool)
                                      or not isfinite(value) or not 0 <= value <= 100):
                errors.append({"field": prefix + "water_cut", "label": "含水率", "message": "含水率应为 0–100 之间的有限数值"})

        stage = case.current_stage or "reported"
        signals = _signals(case)
        has_vehicle, has_person = bool(vehicles) or "vehicle" in signals, bool(persons) or "person" in signals
        has_oil = bool(case.oil_type or case.oil_nature or recovery or measurements) or case.oil_volume is not None or "oil" in signals
        for field, label, affected in (
            ("description", "案情描述", ("history_retrieval", "material_export")),
            ("location", "案发地点或区域", ("regional_analysis", "road_comparison")),
            ("case_type", "案件类型", ("history_retrieval",)),
        ):
            if _is_blank(spatial["location"] if field == "location" else getattr(case, field, None)):
                gap(field, label, "缺少该资料会限制对应分析，未知可保留，不阻止保存。", affected)
        precision = time_precision(case)
        if precision == "unknown":
            gap("occurred_time", "发生时间范围待明确", "可记录大致时段或保留未知，不补造精确时刻。", ("regional_analysis",))
        if not _valid_geo(spatial):
            gap("latitude/longitude", "案发位置待定位", "地点描述可先保存；没有可信点坐标时不能进行精确道路比较。", ("regional_analysis", "road_comparison"))
        for field, label in (("report_time", "报送时间"), ("report_unit", "报送/责任单位"), ("source_type", "案件线索来源")):
            if _is_blank(getattr(case, field, None)):
                gap(field, label, "报送资料待补充；与案件结论及分析任务完成状态独立。", (), "reporting")
        if has_vehicle and not vehicles:
            gap("vehicles", "车辆线索明细", "案情明确提及车辆，可记录已知车型等线索；不强求未知车牌或身份。", ("road_comparison",))
        if has_person and not persons:
            gap("persons", "已知人员线索", "仅补充已掌握的角色或描述，不强求身份资料或认定身份。")
        if stage in DISPOSAL_STAGES:
            for present, field, label, records in (
                (has_vehicle, "vehicle_handling", "车辆处理情况", vehicles),
                (has_person, "person_handling", "人员处理情况", persons),
            ):
                if present and _is_blank(getattr(case, field, None)) and not any(row.handling_status for row in records):
                    gap(field, label, "案件已进入移交或结案阶段，仅补充实际适用的处理情况。", (), "stage_material")
        if has_oil:
            if not case.oil_nature and not any(row.oil_nature for row in recovery):
                gap("oil_nature", "油品性质", "油品性质未知时不能推定其来源。", ("history_retrieval",))
            if case.oil_volume is None and not measurements and not any(row.volume_tons is not None for row in recovery):
                gap("oil_volume", "油量或测量记录", "数量未知可保留；案件数量与回收检斤记录分开。", (), "measurement")
            if case.oil_volume is not None and getattr(case, "oil_volume_unit", None) in (None, "unknown"):
                gap("oil_volume_unit", "油量单位待明确", "单位未知的数值不参与同单位汇总，也不自动换算为吨。", ("material_export",), "measurement")
            if any(row.unit in (None, "unknown") for row in measurements):
                gap("oil_measurements.unit", "测量记录单位待明确", "保留该次计量的阶段和原始数值，不并入已知单位汇总。", ("material_export",), "measurement")
            if stage in DISPOSAL_STAGES and not case.oil_handling and not any(row.handling_method for row in recovery):
                gap("oil_handling", "油品处理情况", "仅移交或结案阶段提示已实际发生的油品处置资料。", (), "stage_material")

        # Actual transferred vehicles, not a keyword, activate formal custody requirements.
        applicable_vehicles = [row for row in vehicles if row.transferred_to_police]
        if stage in DISPOSAL_STAGES and applicable_vehicles:
            required_missing = []
            for vehicle in applicable_vehicles:
                keys = {row.requirement_key for row in evidence
                        if (row.meta or {}).get("vehicle_id") == vehicle.id
                        or (len(applicable_vehicles) == 1 and not (row.meta or {}).get("vehicle_id"))}
                missing_keys = [label for key, label in VEHICLE_EVIDENCE_REQUIREMENTS.items() if key not in keys]
                if missing_keys:
                    required_missing.append(f"车辆记录 {vehicle.id}: " + "、".join(missing_keys))
                if not vehicle.transfer_time or not vehicle.transfer_document_no:
                    warning("vehicle.transfer", "已移交车辆缺少移交时间或清单编号，请按实际资料补充。")
            if required_missing:
                gap("case_evidence", "已移交车辆材料待补充", "；".join(required_missing), (), "applicable_material")

        occurred, reported = utc_instant(case.occurred_time), utc_instant(case.report_time)
        if precision == "exact" and occurred and reported and reported < occurred:
            warning("report_time", "报送时间早于已记录的发生时刻，请核对二者含义。")
        if case.case_filed and not case.police_reported:
            warning("case_filed", "已立案但未标记是否报案，请核对。")
        for field, options, label in (
            ("source_type", ALLOWED_SOURCE_TYPES, "线索来源"), ("oil_nature", ALLOWED_OIL_NATURES, "油品性质"),
            ("operation_role", ALLOWED_OPERATION_ROLES, "行动角色"), ("current_stage", ALLOWED_STAGES, "案件阶段"),
        ):
            if getattr(case, field, None) and getattr(case, field) not in options:
                warning(field, f"{label}不在标准枚举内，保留原值待核验。")
        timing = evaluate_timeliness(case, timeliness_policy)
        if timing["reported_in_time"] is False:
            warning("report_time", f"未满足组织规则 {timing['rule_version']} 的 {timing['report_limit_minutes']} 分钟报送时限，请核对资料。")
        if timing["entered_in_time"] is False:
            warning("created_at", f"未满足组织规则 {timing['rule_version']} 的 {timing['entry_limit_hours']} 小时录入时限，请核对资料。")

        case_data = {key: getattr(case, key, None) for key in (
            "description", "location", "latitude", "longitude", "occurred_time", "occurred_from", "occurred_to", "modus_operandi")}
        capabilities = CaseQualityService.build_analysis_readiness({"case": {**case_data, **spatial, "time_precision": precision}})
        priorities = [{"field": item["field"], "label": item["label"], "reason": item["message"],
                       "category": "validation", "affected_capabilities": []} for item in errors]
        priorities = (priorities + gaps)[:3]
        # Compatibility only; never use this score as completion, risk or inference confidence.
        reference_score = round(max(0, 100 - min(len(gaps), 10) * 7 - min(len(errors), 3) * 10), 2)
        return {
            "rule_version": QUALITY_RULE_VERSION,
            "validation": {"status": "invalid" if errors else "valid", "can_save": not errors, "errors": errors, "warnings": warnings},
            "completeness": {"status": "partial" if gaps else "sufficient", "stage": stage, "gaps": gaps, "timeliness": timing},
            "capabilities": capabilities, "priority_gaps": priorities,
            "score": reference_score, "level": "high" if reference_score >= 80 else "medium" if reference_score >= 60 else "low",
            "score_purpose": "legacy_reference_not_case_completion", "category_scores": {"legacy_reference": reference_score},
            "missing_required": [{key: item[key] for key in ("field", "label", "reason")} for item in gaps],
            "warnings": warnings, "recommendations": [item["reason"] for item in priorities],
            "facts": {
                "has_vehicle_signal": has_vehicle, "has_person_signal": has_person, "has_oil_signal": has_oil,
                "reported_within_1h": timing["reported_in_time"] if timeliness_policy.report_limit_minutes == 60 else None,
                "entered_within_48h": timing["entered_in_time"] if timeliness_policy.entry_limit_hours == 48 else None,
                "vehicle_count": len(vehicles), "person_count": len(persons), "evidence_count": len(evidence),
                "oil_recovery_count": len(recovery), "time_precision": precision,
                "oil_measurement_count": len(measurements),
            },
        }

    @staticmethod
    def refresh_case_quality(db: Session, case: Case, *, commit: bool = True) -> Dict[str, Any]:
        result = CaseQualityService.evaluate_case(db, case)
        case.quality_score, case.quality_level = result["score"], result["level"]
        case.quality_issues, case.quality_updated_at = result, datetime.utcnow()
        if commit:
            db.commit()
            db.refresh(case)
        return result

    @staticmethod
    def build_analysis_readiness(profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        case = profile.get("case") or {}
        has_description, has_location = not _is_blank(case.get("description")), not _is_blank(case.get("location"))
        has_geo = _valid_geo(case)
        precision = case.get("time_precision") or ("exact" if case.get("occurred_time") else "unknown")
        has_time = bool((precision == "exact" and case.get("occurred_time")) or
                        (precision == "interval" and case.get("occurred_from") and case.get("occurred_to")))

        def item(label, state, blockers, actions):
            return {"label": label, "status": state, "data_state": state, "runtime_state": "not_checked",
                    "assessment_scope": "input_data_only", "blockers": blockers, "next_actions": actions}

        return {
            "history_retrieval": item("历史条件检索", "ready" if has_description else "partial" if has_location else "missing",
                [] if has_description else ["缺少可检索的案情描述"], ["索引可用性和当前权限由检索服务检查，词项检索不依赖模型。"]),
            "regional_analysis": item("区域与时间分析", "ready" if has_geo and has_time else "partial" if has_location or has_geo else "missing",
                ([] if has_geo else ["缺少可信坐标"]) + ([] if has_time else ["发生时间未知"]),
                ["未知位置或时间不参加精确空间/时间统计，仍保留原始资料。"]),
            "road_comparison": item("道路条件比较", "partial" if has_geo else "missing",
                ([] if has_geo else ["缺少可信道路计算起点"]) + ["设施入口、车型假设与路网许可需由道路任务核验"],
                ["路网版本、通行条件和路由服务未在资料检查中探测，不保证可达。"]),
            "material_export": item("资料与成果导出", "ready" if has_description else "partial",
                [] if has_description else ["原始案情为空，仅可整理已知字段"],
                ["可按需整理已知资料；冻结研判导出另需已形成的有权成果，不要求每案生成报告。"]),
        }

    @staticmethod
    def build_case_feature_profile(db: Session, case: Case) -> Dict[str, Any]:
        related = CaseQualityService.get_related_data(db, case.id)
        quality = CaseQualityService.evaluate_case(db, case, related_data=related)
        return {
            "case": {
                **{key: getattr(case, key, None) for key in (
                    "id", "case_number", "location", "latitude", "longitude", "case_type", "description", "status", "current_stage", "time_expression", "time_timezone")},
                "time_precision": time_precision(case),
                **{key: _iso(getattr(case, key, None)) for key in ("occurred_time", "occurred_from", "occurred_to", "discovered_at")},
            },
            "management": {
                **{key: getattr(case, key, None) for key in (
                    "report_unit", "source_type", "source_detail", "police_reported", "case_filed", "police_officer", "police_phone", "security_officers", "operation_role")},
                "report_time": _iso(case.report_time),
            },
            "oil": {
                **{key: getattr(case, key, None) for key in (
                    "oil_type", "oil_nature", "oil_volume", "oil_volume_unit", "oil_value", "water_cut", "facility_type", "facility_owner", "upstream_source", "downstream_destination", "oil_handling")},
                "recovery_records": [{**{key: getattr(row, key, None) for key in (
                    "id", "oil_nature", "volume_tons", "water_cut", "source", "receiver", "handling_method")},
                    "handled_at": _iso(row.handled_at)} for row in related["oil_recovery"]],
                "measurements": [{**{key: getattr(row, key, None) for key in (
                    "id", "value", "unit", "stage", "method", "water_cut", "water_cut_basis", "source_note")},
                    "measured_at": _iso(row.measured_at)} for row in related["oil_measurements"]],
            },
            "actors": {
                "persons": [{key: getattr(row, key, None) for key in (
                    "id", "name", "gender", "id_number", "home_address", "phone", "role", "handling_status")} for row in related["persons"]],
                "legacy_persons": _json_list(case.involved_persons), "person_handling": case.person_handling,
            },
            "vehicles": [{**{key: getattr(row, key, None) for key in (
                "id", "vehicle_type", "color", "brand", "model", "plate_number", "oil_volume", "oil_volume_unit", "water_cut",
                "custody_location", "current_location", "handling_status", "transferred_to_police", "transfer_document_no")},
                "transfer_time": _iso(row.transfer_time)} for row in related["vehicles"]],
            "legacy_vehicle_info": _json_list(case.vehicle_info),
            "evidence": [{**{key: getattr(row, key, None) for key in (
                "id", "evidence_type", "title", "file_path", "requirement_key", "latitude", "longitude", "is_sensitive", "meta")},
                "captured_at": _iso(row.captured_at)} for row in related["evidence"]],
            "quality": quality, "analysis_readiness": quality["capabilities"],
        }
