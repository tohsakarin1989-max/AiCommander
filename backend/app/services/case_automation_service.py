from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvidence, CasePerson, CaseVehicle, OilRecoveryRecord
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.case_quality_service import CaseQualityService, _is_blank


MATERIAL_RULES = {
    "weigh_water_document": {
        "label": "检斤含水单据",
        "category": "oil",
        "evidence_type": "document",
        "keywords": ("检斤", "含水", "过磅", "称重", "计量单", "磅单"),
    },
    "oil_disposition_document": {
        "label": "涉案原油入库/暂存/回收凭证",
        "category": "oil",
        "evidence_type": "document",
        "keywords": ("入库", "暂存", "回收", "处理凭证", "接收单", "收油", "油品处置"),
    },
    "person_disposition_document": {
        "label": "人员处理结果单据",
        "category": "person",
        "evidence_type": "document",
        "keywords": ("人员处理", "处理结果", "移交人员", "嫌疑人", "询问", "处罚", "公安接收人员"),
    },
    "vehicle_transfer_document": {
        "label": "车辆移交单据",
        "category": "vehicle",
        "evidence_type": "document",
        "keywords": ("车辆移交", "移交车辆", "移交清单", "扣押车辆", "车辆接收", "车钥匙", "行驶证"),
    },
    "police_case_document": {
        "label": "报案/立案/公安接收材料",
        "category": "police",
        "evidence_type": "document",
        "keywords": ("报案", "立案", "受案", "公安", "接警", "移交公安", "案件回执"),
    },
}


SQUAD_NAMES = [
    "案件一班",
    "案件二班",
    "案件三班",
    "案件四班",
    "防范一班",
    "防范二班",
    "防范三班",
    "龙虎泡保卫班",
    "葡西保卫班",
    "敖古拉保卫班",
    "新站保卫班",
    "新肇保卫班",
    "敖南保卫班",
    "齐家保卫班",
    "泰来保卫班",
    "龙西保卫班",
    "页岩油保卫班",
]

SQUAD_TARGETS = {
    "案件一班": {"vehicle": 3, "person": 2},
    "案件二班": {"vehicle": 2, "person": 1},
    "案件三班": {"vehicle": 1, "person": 1},
    "案件四班": {"vehicle": 2, "person": 1},
    "龙虎泡保卫班": {"vehicle": 1, "person": 1},
    "葡西保卫班": {"vehicle": 1, "person": 1},
    "敖古拉保卫班": {"vehicle": 1, "person": 1},
    "新站保卫班": {"vehicle": 2, "person": 1},
    "新肇保卫班": {"vehicle": 2, "person": 1},
    "敖南保卫班": {"vehicle": 2, "person": 1},
    "齐家保卫班": {"vehicle": 1, "person": 1},
    "泰来保卫班": {"vehicle": 2, "person": 1},
    "龙西保卫班": {"vehicle": 1, "person": 1},
}

SQUAD_ALIASES = {
    **{name: name for name in SQUAD_NAMES},
    "龙虎泡": "龙虎泡保卫班",
    "葡西": "葡西保卫班",
    "敖古拉": "敖古拉保卫班",
    "新站": "新站保卫班",
    "新肇": "新肇保卫班",
    "敖南": "敖南保卫班",
    "齐家": "齐家保卫班",
    "泰来": "泰来保卫班",
    "龙西": "龙西保卫班",
    "页岩油": "页岩油保卫班",
}

LOW_BONUS_PRICES = {
    "moto": 300,
    "small": 750,
    "big": 1500,
    "heavy": 3000,
    "boat": 3000,
    "non_motor_boat": 1500,
    "other_person": 1500,
    "criminal": 3000,
    "tank_sm": 450,
    "tank_lg": 750,
}

HIGH_BONUS_PRICES = {
    "moto": 450,
    "small": 1200,
    "big": 2250,
    "heavy": 4500,
    "boat": 4500,
    "non_motor_boat": 2250,
    "other_person": 2250,
    "criminal": 4500,
    "tank_sm": 675,
    "tank_lg": 1200,
}

OFFICIAL_BONUS_RULES = {
    "version": "2026_official_workbook",
    "rules_configured": True,
    "vehicle_prices_low": LOW_BONUS_PRICES,
    "vehicle_prices_high": HIGH_BONUS_PRICES,
    "person_prices_low": LOW_BONUS_PRICES,
    "person_prices_high": HIGH_BONUS_PRICES,
    "squad_targets": SQUAD_TARGETS,
    "max_total_amount": None,
}


SOURCE_TYPE_HINTS = {
    "群众举报": ("群众举报", "举报", "群众反映"),
    "巡逻发现": ("巡逻", "巡查", "巡线"),
    "技防预警": ("技防", "预警", "报警", "监控"),
    "公安机关线索": ("公安线索", "公安机关"),
    "作业区反馈": ("作业区", "井区反馈"),
    "领导指派": ("领导指派", "安排核查"),
}


def _text_pool(*values: Any) -> str:
    return " ".join(str(value or "") for value in values)


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _round_amount(value: float) -> float:
    return round(float(value), 2)


class CaseAutomationService:
    """面向案件录入、佐证材料归档和奖金考核测算的轻量自动化服务。"""

    @staticmethod
    def structure_case_text(raw_text: str) -> Dict[str, Any]:
        text = (raw_text or "").strip()
        fields: Dict[str, Any] = {}
        field_sources: Dict[str, str] = {}
        warnings: List[str] = []

        def set_field(field: str, value: Any, source: str) -> None:
            if value is not None and value != "" and field not in fields:
                fields[field] = value
                field_sources[field] = source

        occurred_time = CaseAutomationService._extract_datetime(text)
        if occurred_time:
            set_field("occurred_time", occurred_time.isoformat(), "案情中的日期时间")
        else:
            warnings.append("未识别到明确发生时间，创建案件时仍需人工选择。")

        location = CaseAutomationService._extract_location(text)
        set_field("location", location, "案情中的地点片段")

        case_type = "涉油盗窃" if _contains_any(text, ("盗油", "盗运", "偷油", "涉油盗窃")) else None
        set_field("case_type", case_type, "涉油案件关键词")

        oil_nature = CaseAutomationService._extract_oil_nature(text)
        set_field("oil_nature", oil_nature, "油品性质关键词")
        oil_type = "原油" if _contains_any(text, ("原油", "落地油", "被盗原油", "收缴油")) else None
        set_field("oil_type", oil_type, "油品关键词")

        oil_volume = CaseAutomationService._extract_volume_tons(text)
        set_field("oil_volume", oil_volume, "案情中的数量/检斤描述")

        water_cut = CaseAutomationService._extract_water_cut(text)
        set_field("water_cut", water_cut, "案情中的含水率")

        oil_value = CaseAutomationService._extract_money(text)
        set_field("oil_value", oil_value, "案情中的价值金额")

        for source_type, keywords in SOURCE_TYPE_HINTS.items():
            if _contains_any(text, keywords):
                set_field("source_type", source_type, "线索来源关键词")
                break

        if _contains_any(text, ("报案", "移交公安", "公安接收", "公安处理")):
            set_field("police_reported", True, "公安处置关键词")
        if _contains_any(text, ("立案", "受案")):
            set_field("case_filed", True, "立案/受案关键词")

        if _contains_any(text, ("移交公安", "人员移交", "嫌疑人移交")):
            set_field("person_handling", "移交公安", "人员处置关键词")
        if _contains_any(text, ("车辆移交", "移交车辆", "车移交公安")):
            set_field("vehicle_handling", "移交公安", "车辆处置关键词")
        elif _contains_any(text, ("扣押车辆", "车辆扣押", "查扣车辆")):
            set_field("vehicle_handling", "扣押停放", "车辆处置关键词")
        if _contains_any(text, ("检斤入库", "入库", "回收入库")):
            set_field("oil_handling", "检斤入库", "油品处置关键词")
        elif _contains_any(text, ("暂存", "收缴")):
            set_field("oil_handling", "暂存", "油品处置关键词")

        plate_numbers = CaseAutomationService._extract_plate_numbers(text)
        if plate_numbers:
            set_field(
                "vehicle_info",
                {"plate_number": plate_numbers[0], "raw_plate_numbers": plate_numbers},
                "车牌号识别",
            )

        entities = {
            "plate_numbers": plate_numbers,
            "person_count": CaseAutomationService._extract_person_count(text),
            "material_hints": CaseAutomationService._material_hints_from_text(text),
        }
        suggested_evidence = [
            {"requirement_key": key, "label": rule["label"], "reason": "案情描述触发佐证材料要求"}
            for key, rule in MATERIAL_RULES.items()
            if _contains_any(text, rule["keywords"])
        ]
        if fields.get("oil_volume") is not None or fields.get("water_cut") is not None:
            suggested_evidence.insert(0, {
                "requirement_key": "weigh_water_document",
                "label": MATERIAL_RULES["weigh_water_document"]["label"],
                "reason": "存在涉案油量或含水率字段",
            })

        confidence = min(0.92, 0.35 + len(fields) * 0.06)
        return {
            "case_fields": fields,
            "field_sources": field_sources,
            "entities": entities,
            "suggested_evidence": CaseAutomationService._dedupe_evidence_suggestions(suggested_evidence),
            "warnings": warnings,
            "confidence": round(confidence, 2),
            "boundary": "自动提取结果仅用于辅助录入，提交前需人工核对。",
        }

    @staticmethod
    def classify_evidence_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        title = payload.get("title")
        file_path = payload.get("file_path")
        notes = payload.get("notes")
        evidence_type = payload.get("evidence_type")
        text = _text_pool(title, file_path, notes, Path(str(file_path)).name if file_path else "")
        normalized = text.lower()
        matches: List[Tuple[str, int, List[str]]] = []
        for key, rule in MATERIAL_RULES.items():
            terms = [term for term in rule["keywords"] if term in text or term.lower() in normalized]
            if terms:
                matches.append((key, len(terms), terms))

        if matches:
            matches.sort(key=lambda item: item[1], reverse=True)
            key, score, terms = matches[0]
            rule = MATERIAL_RULES[key]
            confidence = min(0.96, 0.62 + score * 0.1)
            return {
                "requirement_key": key,
                "label": rule["label"],
                "evidence_type": evidence_type or rule["evidence_type"],
                "confidence": round(confidence, 2),
                "matched_terms": terms,
                "source": "keyword_classifier",
            }

        if _contains_any(text, ("照片", "图片", ".jpg", ".jpeg", ".png")):
            return {
                "requirement_key": payload.get("requirement_key"),
                "label": "现场/车辆照片",
                "evidence_type": evidence_type or "photo",
                "confidence": 0.45,
                "matched_terms": [],
                "source": "file_type_hint",
            }

        return {
            "requirement_key": payload.get("requirement_key"),
            "label": "其他材料",
            "evidence_type": evidence_type or "other",
            "confidence": 0.25,
            "matched_terms": [],
            "source": "fallback",
        }

    @staticmethod
    def build_bonus_assessment(
        db: Session,
        case: Case,
        rules: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        related = CaseQualityService.get_related_data(db, case.id)
        material_checks = CaseAutomationService._build_material_checks(case, related)
        normalized_rules = {**OFFICIAL_BONUS_RULES, **(rules or {})}
        rules_configured = bool(normalized_rules.get("rules_configured"))
        gate_ready = all(check["status"] == "satisfied" for check in material_checks if check["required"])
        gate_status = "ready" if gate_ready else "blocked_by_materials"
        if gate_ready and not rules_configured:
            gate_status = "rules_not_configured"

        bonus_context = CaseAutomationService._build_bonus_context(db, case, related)
        calculation_gaps = bonus_context["calculation_gaps"]
        calculation_ready = not calculation_gaps
        bonus_items = CaseAutomationService._calculate_bonus_items(
            case,
            related,
            material_checks,
            normalized_rules,
            bonus_context,
            gate_ready,
            calculation_ready,
        )
        total = sum(item["suggested_amount"] for item in bonus_items if item["status"] == "calculated")
        max_total = normalized_rules.get("max_total_amount")
        if isinstance(max_total, (int, float)) and max_total >= 0:
            total = min(total, float(max_total))
        distribution = CaseAutomationService._build_bonus_distribution(
            total,
            bonus_context["officer_counts"],
        )
        warnings = list(bonus_context["warnings"])
        if not calculation_ready:
            warnings.append("核算指标未齐，整案暂不测算，避免遗漏应计奖金。")
        if gate_status == "blocked_by_materials" and total > 0:
            warnings.append("佐证材料未齐，测算金额仅作预估，暂不能进入复核或发放确认。")
        if total > 0 and not distribution:
            warnings.append("缺少保卫班出警人数，暂不能自动分配到班组。")

        management_context = CaseAutomationService._build_bonus_management_context(
            db,
            case,
            normalized_rules,
            bonus_context,
            total,
        )
        missing_materials = [
            check["label"]
            for check in material_checks
            if check["required"] and check["status"] != "satisfied"
        ]
        return {
            "case_id": case.id,
            "case_number": case.case_number,
            "rules_version": normalized_rules.get("version"),
            "rules_configured": rules_configured,
            "material_gate": {
                "status": gate_status,
                "required_count": sum(1 for check in material_checks if check["required"]),
                "satisfied_count": sum(1 for check in material_checks if check["required"] and check["status"] == "satisfied"),
                "missing_materials": missing_materials,
            },
            "calculation_gate": {
                "status": "ready" if calculation_ready else "blocked_by_data",
                "missing_items": calculation_gaps,
            },
            "material_checks": material_checks,
            "bonus_items": bonus_items,
            "total_suggested_amount": _round_amount(total),
            "primary_squad": bonus_context["primary_squad"],
            "bonus_counts": bonus_context["counts"],
            "squad_performance": bonus_context["squad_performance"],
            "management_context": management_context,
            "distribution": distribution,
            "warnings": warnings,
            "ready_for_review": calculation_ready and gate_status == "ready" and any(item["status"] == "calculated" for item in bonus_items),
            "manual_review_required": True,
            "boundary": "系统只做奖金考核测算和依据链整理，最终发放仍需人工按正式细则复核确认。",
        }

    @staticmethod
    def build_automation_workbench(db: Session, case: Case, include_bonus: bool = True) -> Dict[str, Any]:
        """聚合 4-6 自动化能力：结论分层、经验卡、缺口闭环。"""
        bonus = CaseAutomationService.build_bonus_assessment(db, case) if include_bonus else None
        context = CaseIntelligenceService.build_llm_context_pack(
            db,
            case_id=case.id,
            days=365,
            limit=6,
            radius_km=1.5,
        )
        experience = CaseIntelligenceService.build_experience_card(db, case.id)

        facts = context.get("facts") or []
        inferences = context.get("pattern_inferences") or []
        suggestions = context.get("prevention_references") or []
        info_gaps = CaseAutomationService._filter_real_information_gaps(context.get("information_gaps") or [])
        if bonus:
            material_gaps = bonus.get("material_gate", {}).get("missing_materials") or []
            materials_ready = bonus.get("material_gate", {}).get("status") == "ready"
        else:
            related = CaseQualityService.get_related_data(db, case.id)
            material_checks = CaseAutomationService._build_material_checks(case, related)
            material_gaps = [
                item["label"]
                for item in material_checks
                if item.get("required") and item.get("status") in {"missing", "partial"}
            ]
            materials_ready = not material_gaps
        actions = CaseAutomationService._build_gap_actions(material_gaps, info_gaps)
        ready_for_human_review = (
            materials_ready
            and not actions
            and bool(facts)
        )

        modules = [
            {
                "key": "conclusion_layering",
                "label": "研判结论分层",
                "status": "ready" if facts else "needs_data",
                "metrics": {
                    "facts": len(facts),
                    "inferences": len(inferences),
                    "suggestions": len(suggestions),
                    "gaps": len(info_gaps),
                },
            },
            {
                "key": "experience_card",
                "label": "经验卡沉淀",
                "status": "ready" if experience.get("reusable_lessons") else "needs_data",
                "metrics": {
                    "lessons": len(experience.get("reusable_lessons") or []),
                    "attention_points": len(experience.get("next_attention_points") or []),
                },
            },
            {
                "key": "gap_closure",
                "label": "证据/考核缺口闭环",
                "status": "ready" if not actions else "needs_completion",
                "metrics": {
                    "material_gaps": len(material_gaps),
                    "information_gaps": len(info_gaps),
                    "actions": len(actions),
                },
            },
        ]

        return {
            "case_id": case.id,
            "case_number": case.case_number,
            "version": "automation_456_v1",
            "modules": modules,
            "conclusion_layering": {
                "facts": facts[:10],
                "inferences": inferences[:8],
                "suggestions": suggestions[:8],
                "information_gaps": info_gaps[:10],
                "evidence_index": (context.get("evidence_index") or [])[:12],
                "boundary": context.get("system_boundary") or [],
            },
            "experience_card": experience,
            "gap_closure": {
                "material_gaps": material_gaps,
                "information_gaps": info_gaps,
                "actions": actions,
                "bonus_ready": bool(bonus) and materials_ready,
                "review_ready": materials_ready,
            },
            "bonus_assessment": bonus,
            "ready_for_human_review": ready_for_human_review,
            "boundary": "4-6 自动化只做后台分层、经验沉淀和缺口提醒，不替代人工结论、不自动派发处置任务。",
        }

    @staticmethod
    def _build_material_checks(case: Case, related: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
        vehicles: List[CaseVehicle] = related["vehicles"]
        persons: List[CasePerson] = related["persons"]
        evidence: List[CaseEvidence] = related["evidence"]
        oil_recovery: List[OilRecoveryRecord] = related["oil_recovery"]
        evidence_by_key = {
            e.requirement_key: e
            for e in evidence
            if e.requirement_key
        }
        quality = case.quality_issues or {}
        facts = quality.get("facts") or {}
        text = _text_pool(case.description, case.oil_handling, case.vehicle_handling, case.person_handling)
        has_oil = bool(facts.get("has_oil_signal") or case.oil_volume is not None or case.water_cut is not None or oil_recovery)
        has_person = CaseAutomationService._has_person_bonus_scope(case, persons)
        has_vehicle = bool(facts.get("has_vehicle_signal") or vehicles or not _is_blank(case.vehicle_handling))

        definitions = [
            (
                "weigh_water_document",
                has_oil,
                "案件已记录涉案油量、含水率或涉油处置，需要补齐对应佐证单据",
                bool(case.oil_volume is not None and case.water_cut is not None),
                "已有油量/含水字段，但缺少对应单据附件",
            ),
            (
                "oil_disposition_document",
                has_oil and (_contains_any(text, ("入库", "暂存", "回收", "检斤")) or bool(oil_recovery)),
                "案件已记录涉案原油入库、暂存、回收或处理，需要补齐处置凭证",
                bool(oil_recovery),
                "已有涉案原油处理台账，但缺少处理凭证附件",
            ),
            (
                "person_disposition_document",
                has_person,
                "案件已记录抓获人员或人员处理结果，需要补齐人员处理佐证",
                any(not _is_blank(p.handling_status) for p in persons) or not _is_blank(case.person_handling),
                "已填写人员处理结果，但缺少处理结果单据附件",
            ),
            (
                "vehicle_transfer_document",
                has_vehicle and _contains_any(text, ("移交", "扣押", "查扣", "车辆")),
                "案件已记录查扣车辆或车辆移交处置，需要补齐车辆处置佐证",
                any(not _is_blank(v.transfer_document_no) for v in vehicles) or not _is_blank(case.vehicle_handling),
                "已填写车辆处理信息，但缺少车辆移交/扣押材料附件",
            ),
            (
                "police_case_document",
                bool(case.police_reported or case.case_filed),
                "案件已标记报案或立案，需要补齐公安接收佐证",
                bool(not _is_blank(case.police_officer) or not _is_blank(case.police_phone)),
                "已有公安联系人信息，但缺少报案/立案/接收材料附件",
            ),
        ]

        checks: List[Dict[str, Any]] = []
        for key, required, reason, partial_signal, partial_note in definitions:
            rule = MATERIAL_RULES[key]
            evidence_item = evidence_by_key.get(key)
            if not required:
                status = "not_required"
                note = "当前案件信息未触发该材料要求"
            elif evidence_item:
                status = "satisfied"
                note = f"已归档：{evidence_item.title or evidence_item.file_path or evidence_item.id}"
            elif partial_signal:
                status = "partial"
                note = partial_note
            else:
                status = "missing"
                note = "缺少佐证材料"
            checks.append({
                "requirement_key": key,
                "label": rule["label"],
                "category": rule["category"],
                "required": bool(required),
                "status": status,
                "trigger_reason": reason if required else None,
                "note": note,
                "evidence_id": evidence_item.id if evidence_item else None,
            })
        return checks

    @staticmethod
    def _calculate_bonus_items(
        case: Case,
        related: Dict[str, List[Any]],
        material_checks: List[Dict[str, Any]],
        rules: Dict[str, Any],
        bonus_context: Dict[str, Any],
        gate_ready: bool,
        calculation_ready: bool,
    ) -> List[Dict[str, Any]]:
        status_by_key = {item["requirement_key"]: item["status"] for item in material_checks}
        rules_configured = bool(rules.get("rules_configured"))
        counts = bonus_context["counts"]
        primary_squad = bonus_context["primary_squad"]
        performance = bonus_context["squad_performance"].get(primary_squad or "", {})
        vehicle_high = bool(performance.get("vehicle_high"))
        person_high = bool(performance.get("person_high"))
        vehicle_prices = rules.get("vehicle_prices_high" if vehicle_high else "vehicle_prices_low") or {}
        person_prices = rules.get("person_prices_high" if person_high else "person_prices_low") or {}
        vehicle_basis = "车辆目标已超额" if vehicle_high else "车辆目标未超额"
        person_basis = "人员目标已超额" if person_high else "人员目标未超额"

        vehicle_definitions = [
            ("moto_vehicle_reward", "摩托车（电动车）奖励", "moto", "台"),
            ("small_vehicle_reward", "5吨以下机动车奖励", "small", "台"),
            ("big_vehicle_reward", "5吨以上机动车奖励", "big", "台"),
            ("heavy_vehicle_reward", "重型挂车奖励", "heavy", "台"),
            ("boat_reward", "机动船奖励", "boat", "艘"),
            ("small_tank_reward", "3吨以下炼化油罐奖励", "tank_sm", "个"),
            ("large_tank_reward", "3吨以上炼化油罐奖励", "tank_lg", "个"),
        ]
        items: List[Dict[str, Any]] = []
        for key, label, count_key, unit in vehicle_definitions:
            quantity = counts[count_key]
            unit_price = float(vehicle_prices.get(count_key) or 0)
            items.append(
                CaseAutomationService._bonus_item(
                    key=key,
                    label=label,
                    basis=f"{label.replace('奖励', '')} {quantity} {unit}，{vehicle_basis}",
                    quantity=quantity,
                    unit=unit,
                    required_materials=["vehicle_transfer_document"],
                    material_status=status_by_key,
                    amount=quantity * unit_price,
                    rules_configured=rules_configured,
                    formula=f"{quantity} x {int(unit_price)} 元/{unit}",
                    gate_ready=gate_ready,
                    calculation_ready=calculation_ready,
                )
            )

        other_people = max(0, counts["people"] - counts["criminal"])
        person_definitions = [
            ("criminal_detention_reward", "刑事拘留人员奖励", "criminal", counts["criminal"], "人"),
            ("other_person_reward", "其他处置人员奖励", "other_person", other_people, "人"),
        ]
        for key, label, price_key, quantity, unit in person_definitions:
            unit_price = float(person_prices.get(price_key) or 0)
            items.append(
                CaseAutomationService._bonus_item(
                    key=key,
                    label=label,
                    basis=f"{label.replace('奖励', '')} {quantity} {unit}，{person_basis}",
                    quantity=quantity,
                    unit=unit,
                    required_materials=["person_disposition_document"],
                    material_status=status_by_key,
                    amount=quantity * unit_price,
                    rules_configured=rules_configured,
                    formula=f"{quantity} x {int(unit_price)} 元/{unit}",
                    gate_ready=gate_ready,
                    calculation_ready=calculation_ready,
                )
            )
        return items

    @staticmethod
    def _bonus_item(
        *,
        key: str,
        label: str,
        basis: str,
        quantity: float,
        unit: str,
        required_materials: List[str],
        material_status: Dict[str, str],
        amount: float,
        rules_configured: bool,
        formula: str,
        gate_ready: bool,
        calculation_ready: bool,
    ) -> Dict[str, Any]:
        blocking = [
            key
            for key in required_materials
            if material_status.get(key) not in {"satisfied", "not_required"}
        ]
        if not gate_ready and quantity > 0 and not blocking:
            blocking = [
                key
                for key, status in material_status.items()
                if status not in {"satisfied", "not_required"}
        ]
        if quantity <= 0:
            status = "not_applicable"
        elif not calculation_ready:
            status = "blocked_by_data"
        elif not rules_configured:
            status = "rules_not_configured"
        else:
            status = "calculated"
        return {
            "key": key,
            "label": label,
            "basis": basis,
            "quantity": quantity,
            "unit": unit,
            "formula": formula,
            "required_materials": required_materials,
            "blocked_by": blocking,
            "status": status,
            "suggested_amount": _round_amount(amount if status == "calculated" else 0),
        }

    @staticmethod
    def _build_bonus_context(db: Session, case: Case, related: Dict[str, List[Any]]) -> Dict[str, Any]:
        warnings: List[str] = []
        primary_squad = CaseAutomationService._resolve_primary_squad(case)
        if not primary_squad:
            warnings.append("未识别主控班组，目标档位和金额分配需人工复核。")

        counts, count_warnings, calculation_gaps = CaseAutomationService._extract_case_bonus_counts(case, related)
        warnings.extend(count_warnings)
        officer_counts, officer_warnings = CaseAutomationService._extract_officer_counts(case, primary_squad)
        warnings.extend(officer_warnings)
        quarter_start, quarter_end, _, _ = CaseAutomationService._bonus_period_bounds(case)
        return {
            "primary_squad": primary_squad,
            "counts": counts,
            "squad_performance": CaseAutomationService._build_squad_performance(
                db,
                start_at=quarter_start,
                end_at=quarter_end,
            ),
            "officer_counts": officer_counts,
            "warnings": warnings,
            "calculation_gaps": calculation_gaps,
        }

    @staticmethod
    def _filter_real_information_gaps(items: List[str]) -> List[str]:
        return [
            item
            for item in items
            if item and "暂无明显信息缺口" not in item
        ]

    @staticmethod
    def _build_gap_actions(material_gaps: List[str], information_gaps: List[str]) -> List[Dict[str, Any]]:
        actions: List[Dict[str, Any]] = []
        for label in material_gaps:
            actions.append({
                "source": "material",
                "priority": "high",
                "title": f"补齐{label}",
                "detail": "该材料影响案件复核佐证链，补齐前不进入自动复核。",
            })
        for gap in information_gaps:
            title = gap.split("：", 1)[0]
            actions.append({
                "source": "information",
                "priority": "medium",
                "title": f"核实{title}",
                "detail": gap,
            })
        return actions

    @staticmethod
    def _build_squad_performance(
        db: Session,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
    ) -> Dict[str, Dict[str, Any]]:
        performance = {
            squad: {
                "vehicle_actual": 0,
                "vehicle_target": SQUAD_TARGETS.get(squad, {}).get("vehicle", 0),
                "vehicle_high": False,
                "person_actual": 0,
                "person_target": SQUAD_TARGETS.get(squad, {}).get("person", 0),
                "person_high": False,
            }
            for squad in SQUAD_NAMES
        }
        query = db.query(Case)
        if start_at is not None:
            query = query.filter(Case.occurred_time >= start_at)
        if end_at is not None:
            query = query.filter(Case.occurred_time < end_at)
        for item in query.all():
            squad = CaseAutomationService._resolve_primary_squad(item)
            if not squad or squad not in performance:
                continue
            related = CaseQualityService.get_related_data(db, item.id)
            counts, _, _ = CaseAutomationService._extract_case_bonus_counts(item, related)
            performance[squad]["vehicle_actual"] += (
                counts["moto"] + counts["small"] + counts["big"] + counts["heavy"]
            )
            performance[squad]["person_actual"] += counts["people"]

        for squad, info in performance.items():
            info["vehicle_high"] = bool(info["vehicle_target"] > 0 and info["vehicle_actual"] > info["vehicle_target"])
            info["person_high"] = bool(info["person_target"] > 0 and info["person_actual"] > info["person_target"])
        return performance

    @staticmethod
    def _bonus_period_bounds(case: Case) -> Tuple[datetime, datetime, datetime, datetime]:
        occurred = case.occurred_time or datetime.utcnow()
        quarter = (occurred.month - 1) // 3 + 1
        quarter_start_month = (quarter - 1) * 3 + 1
        tzinfo = occurred.tzinfo
        quarter_start = datetime(occurred.year, quarter_start_month, 1, tzinfo=tzinfo)
        if quarter == 4:
            quarter_end = datetime(occurred.year + 1, 1, 1, tzinfo=tzinfo)
        else:
            quarter_end = datetime(occurred.year, quarter_start_month + 3, 1, tzinfo=tzinfo)
        year_start = datetime(occurred.year, 1, 1, tzinfo=tzinfo)
        year_end = datetime(occurred.year + 1, 1, 1, tzinfo=tzinfo)
        return quarter_start, quarter_end, year_start, year_end

    @staticmethod
    def _build_bonus_management_context(
        db: Session,
        case: Case,
        rules: Dict[str, Any],
        bonus_context: Dict[str, Any],
        selected_total: float,
    ) -> Dict[str, Any]:
        quarter_start, quarter_end, year_start, year_end = CaseAutomationService._bonus_period_bounds(case)
        primary_squad = bonus_context.get("primary_squad")
        target_rules = rules.get("squad_targets") or SQUAD_TARGETS

        quarter_performance = bonus_context.get("squad_performance") or CaseAutomationService._build_squad_performance(
            db,
            start_at=quarter_start,
            end_at=quarter_end,
        )
        annual_performance = CaseAutomationService._build_squad_performance(
            db,
            start_at=year_start,
            end_at=year_end,
        )

        def summarize_period(
            performance: Dict[str, Dict[str, Any]],
            start_at: datetime,
            end_at: datetime,
            target_multiplier: int = 1,
        ) -> Dict[str, Any]:
            if not primary_squad:
                vehicle_target = 0
                person_target = 0
                actual = {}
            else:
                actual = performance.get(primary_squad, {})
                target = target_rules.get(primary_squad, {}) if isinstance(target_rules, dict) else {}
                vehicle_target = int(target.get("vehicle") or actual.get("vehicle_target") or 0) * target_multiplier
                person_target = int(target.get("person") or actual.get("person_target") or 0) * target_multiplier
            vehicle_actual = int(actual.get("vehicle_actual") or 0)
            person_actual = int(actual.get("person_actual") or 0)
            return {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "case_count": CaseAutomationService._count_cases_in_period(db, start_at, end_at, primary_squad),
                "vehicle_actual": vehicle_actual,
                "vehicle_target": vehicle_target,
                "vehicle_remaining": max(0, vehicle_target - vehicle_actual),
                "vehicle_high": bool(vehicle_target > 0 and vehicle_actual > vehicle_target),
                "person_actual": person_actual,
                "person_target": person_target,
                "person_remaining": max(0, person_target - person_actual),
                "person_high": bool(person_target > 0 and person_actual > person_target),
            }

        occurred = case.occurred_time or datetime.utcnow()
        quarter = (occurred.month - 1) // 3 + 1
        return {
            "period_type": "quarter",
            "rules_version": rules.get("version"),
            "pricing_basis": "按案件发生时间所属季度指标判断高低档，单案金额进入该周期人工复核，不代表直接发放。",
            "case_amount_status": "provisional" if selected_total > 0 else "not_calculated",
            "selected_case_amount": _round_amount(selected_total),
            "primary_squad": primary_squad,
            "period": {
                "year": occurred.year,
                "quarter": quarter,
                "quarter_label": f"{occurred.year}年Q{quarter}",
                "annual_label": f"{occurred.year}年度",
            },
            "quarter": summarize_period(quarter_performance, quarter_start, quarter_end, 1),
            "annual": summarize_period(annual_performance, year_start, year_end, 4),
        }

    @staticmethod
    def _count_cases_in_period(
        db: Session,
        start_at: datetime,
        end_at: datetime,
        primary_squad: Optional[str],
    ) -> int:
        query = db.query(Case).filter(Case.occurred_time >= start_at, Case.occurred_time < end_at)
        cases = query.all()
        if not primary_squad:
            return len(cases)
        return sum(1 for item in cases if CaseAutomationService._resolve_primary_squad(item) == primary_squad)

    @staticmethod
    def _resolve_primary_squad(case: Case) -> Optional[str]:
        for value in (case.report_unit, case.operation_role, case.description):
            squad = CaseAutomationService._resolve_squad_from_text(value)
            if squad:
                return squad
        return None

    @staticmethod
    def _resolve_squad_from_text(value: Any) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        for alias, squad in sorted(SQUAD_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if text == alias or alias in text:
                return squad
        return None

    @staticmethod
    def _extract_case_bonus_counts(
        case: Case,
        related: Dict[str, List[Any]],
    ) -> Tuple[Dict[str, int], List[str], List[Dict[str, str]]]:
        counts = {
            "moto": 0,
            "small": 0,
            "big": 0,
            "heavy": 0,
            "boat": 0,
            "tank_sm": 0,
            "tank_lg": 0,
            "people": 0,
            "criminal": 0,
        }
        warnings: List[str] = []
        calculation_gaps: List[Dict[str, str]] = []
        vehicles: List[CaseVehicle] = related["vehicles"]
        persons: List[CasePerson] = related["persons"]

        if vehicles:
            for vehicle in vehicles:
                category = CaseAutomationService._classify_bonus_vehicle(vehicle)
                if category:
                    counts[category] += 1
                else:
                    label = vehicle.plate_number or vehicle.vehicle_type or vehicle.model or "未命名车辆"
                    warnings.append(f"车辆“{label}”未识别到考核类别，未自动计入奖金。")
                    CaseAutomationService._add_calculation_gap(
                        calculation_gaps,
                        "vehicle_category",
                        "车辆考核类别",
                        "已记录涉案车辆，但缺少摩托车、5吨以下、5吨以上等考核类别，需补齐后整案测算。",
                    )
        else:
            vehicle_text = _text_pool(case.description, case.vehicle_info, case.vehicle_handling, case.involved_items)
            text_counts = CaseAutomationService._extract_vehicle_counts_from_text(vehicle_text)
            for key, value in text_counts.items():
                counts[key] += value
            if not any(text_counts.values()) and (case.vehicle_info or not _is_blank(case.vehicle_handling)):
                warnings.append("已填写车辆信息但未识别车辆类别，车辆奖励需补充车辆类型。")
                CaseAutomationService._add_calculation_gap(
                    calculation_gaps,
                    "vehicle_category",
                    "车辆考核类别",
                    "已记录涉案车辆，但缺少摩托车、5吨以下、5吨以上等考核类别，需补齐后整案测算。",
                )

        if persons:
            counts["people"] = len(persons)
            for person in persons:
                person_text = _text_pool(person.handling_status, person.notes)
                if _contains_any(person_text, ("刑事拘留", "刑拘")):
                    counts["criminal"] += 1
                elif _contains_any(person_text, ("行政拘留", "治安拘留", "行政处罚", "治安处罚", "处罚")):
                    continue
                else:
                    CaseAutomationService._add_calculation_gap(
                        calculation_gaps,
                        "person_disposition",
                        "人员处理类型",
                        "已记录抓获人员，但缺少行政拘留、刑事拘留等处理结果，需补齐后整案测算。",
                    )
        elif CaseAutomationService._legacy_person_count(case.involved_persons) > 0:
            person_text = _text_pool(case.involved_persons, case.person_handling)
            counts["people"] = CaseAutomationService._extract_person_count(person_text)
            counts["people"] = max(counts["people"], CaseAutomationService._legacy_person_count(case.involved_persons))
            counts["criminal"] = min(
                counts["people"],
                CaseAutomationService._extract_criminal_detention_count(person_text),
            )
            has_other_disposition = _contains_any(
                person_text,
                ("行政拘留", "治安拘留", "行政处罚", "治安处罚", "处罚"),
            )
            if counts["people"] > 0 and counts["criminal"] < counts["people"] and not has_other_disposition:
                CaseAutomationService._add_calculation_gap(
                    calculation_gaps,
                    "person_disposition",
                    "人员处理类型",
                    "已记录抓获人员，但缺少行政拘留、刑事拘留等处理结果，需补齐后整案测算。",
                )
        return counts, warnings, calculation_gaps

    @staticmethod
    def _has_person_bonus_scope(case: Case, persons: List[CasePerson]) -> bool:
        return bool(persons or CaseAutomationService._legacy_person_count(case.involved_persons) > 0)

    @staticmethod
    def _legacy_person_count(value: Any) -> int:
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            return sum(1 for item in value["items"] if not _is_blank(item))
        if isinstance(value, list):
            return sum(1 for item in value if not _is_blank(item))
        if isinstance(value, dict):
            return 1 if any(not _is_blank(item) for item in value.values()) else 0
        return 0

    @staticmethod
    def _add_calculation_gap(
        gaps: List[Dict[str, str]],
        key: str,
        label: str,
        detail: str,
    ) -> None:
        if any(item["key"] == key for item in gaps):
            return
        gaps.append({"key": key, "label": label, "detail": detail})

    @staticmethod
    def _classify_bonus_vehicle(vehicle: CaseVehicle) -> Optional[str]:
        text = _text_pool(vehicle.vehicle_type, vehicle.brand, vehicle.model, vehicle.notes)
        if _contains_any(text, ("3吨以下罐", "三吨以下罐", "3吨以下炼化油罐", "小罐")):
            return "tank_sm"
        if _contains_any(text, ("3吨以上罐", "三吨以上罐", "5吨以上炼化油罐", "五吨以上炼化油罐", "大罐")):
            return "tank_lg"
        if _contains_any(text, ("摩托", "电动车", "电动摩托", "电瓶车")):
            return "moto"
        if _contains_any(text, ("重型挂车", "半挂", "挂车")):
            return "heavy"
        if _contains_any(text, ("5吨以上", "五吨以上", "大型卡车", "重型卡车")):
            return "big"
        if _contains_any(text, ("船", "机动船")):
            return "boat"
        if _contains_any(text, ("5吨以下", "五吨以下", "小型", "轿车", "面包", "皮卡", "越野", "机动车")):
            return "small"
        return None

    @staticmethod
    def _extract_vehicle_counts_from_text(text: str) -> Dict[str, int]:
        patterns = {
            "tank_sm": (r"(?P<count>[\d一二两三四五六七八九十]+)\s*(?:个|只)?\s*(?:3吨以下罐|三吨以下罐|3吨以下炼化油罐)",),
            "tank_lg": (r"(?P<count>[\d一二两三四五六七八九十]+)\s*(?:个|只)?\s*(?:3吨以上罐|三吨以上罐|5吨以上炼化油罐|五吨以上炼化油罐)",),
            "moto": (r"(?P<count>[\d一二两三四五六七八九十]+)\s*(?:台|辆)\s*(?:摩托车|电动车|电动摩托|电瓶车)",),
            "heavy": (r"(?P<count>[\d一二两三四五六七八九十]+)\s*(?:台|辆)\s*(?:重型挂车|半挂|挂车)",),
            "big": (r"(?P<count>[\d一二两三四五六七八九十]+)\s*(?:台|辆)\s*(?:5吨以上卡车|5吨以上机动车|五吨以上卡车|五吨以上机动车|大型卡车|重型卡车)",),
            "boat": (r"(?P<count>[\d一二两三四五六七八九十]+)\s*(?:艘|条|只)\s*(?:机动船|船只|船)",),
            "small": (r"(?P<count>[\d一二两三四五六七八九十]+)\s*(?:台|辆)\s*(?:5吨以下机动车|五吨以下机动车|小型机动车|轿车|面包车|皮卡|越野车)",),
        }
        counts = {key: 0 for key in ("moto", "small", "big", "heavy", "boat", "tank_sm", "tank_lg")}
        for key, key_patterns in patterns.items():
            for pattern in key_patterns:
                for match in re.finditer(pattern, text):
                    counts[key] += CaseAutomationService._parse_count(match.group("count"))
        return counts

    @staticmethod
    def _extract_officer_counts(case: Case, primary_squad: Optional[str]) -> Tuple[Dict[str, int], List[str]]:
        counts = {squad: 0 for squad in SQUAD_NAMES}
        warnings: List[str] = []

        def add_count(squad: Optional[str], count: int) -> None:
            if squad and squad in counts and count > 0:
                counts[squad] += count

        data = case.security_officers
        if isinstance(data, list):
            for entry in data:
                squad, count = CaseAutomationService._parse_officer_entry(entry, primary_squad)
                add_count(squad, count)
        elif isinstance(data, dict):
            squad, count = CaseAutomationService._parse_officer_entry(data, primary_squad)
            add_count(squad, count)
        elif isinstance(data, str):
            squad, count = CaseAutomationService._parse_officer_entry(data, primary_squad)
            add_count(squad, count)

        if not any(counts.values()):
            for squad, count in CaseAutomationService._parse_officer_counts_from_text(case.description).items():
                add_count(squad, count)

        if not any(counts.values()):
            warnings.append("未填写保卫班出警人员，无法按出警人数自动分配奖金。")
        return {squad: count for squad, count in counts.items() if count > 0}, warnings

    @staticmethod
    def _parse_officer_entry(entry: Any, primary_squad: Optional[str]) -> Tuple[Optional[str], int]:
        if isinstance(entry, dict):
            squad = CaseAutomationService._resolve_squad_from_text(
                entry.get("squad") or entry.get("team") or entry.get("unit") or entry.get("班组")
            ) or primary_squad
            if isinstance(entry.get("count"), int):
                return squad, int(entry["count"])
            names = entry.get("names") or entry.get("officers") or entry.get("人员")
            return squad, CaseAutomationService._count_officer_names(names)

        text = str(entry or "")
        squad = CaseAutomationService._resolve_squad_from_text(text) or primary_squad
        cleaned = text
        for alias in sorted(SQUAD_ALIASES, key=len, reverse=True):
            cleaned = cleaned.replace(alias, "")
        cleaned = re.sub(r"(出警人员?|保卫班|班组|人员|名单|[:：])", " ", cleaned)
        return squad, CaseAutomationService._count_officer_names(cleaned)

    @staticmethod
    def _parse_officer_counts_from_text(text: Any) -> Dict[str, int]:
        raw = str(text or "")
        result: Dict[str, int] = {}
        for alias, squad in sorted(SQUAD_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            pattern = rf"{re.escape(alias)}[^，。；;\n]{{0,8}}出警人员?[:：]?\s*([^，。；;\n]+)"
            match = re.search(pattern, raw)
            if match and squad not in result:
                result[squad] = CaseAutomationService._count_officer_names(match.group(1))
        return result

    @staticmethod
    def _count_officer_names(value: Any) -> int:
        if isinstance(value, list):
            return sum(1 for item in value if str(item or "").strip())
        text = str(value or "").strip()
        if not text:
            return 0
        text = re.sub(r"[()（）\[\]【】]", " ", text)
        parts = [
            part.strip(" :：等")
            for part in re.split(r"[、,，;；/\s]+", text)
            if part.strip(" :：等")
        ]
        return len(parts)

    @staticmethod
    def _build_bonus_distribution(total: float, officer_counts: Dict[str, int]) -> List[Dict[str, Any]]:
        total_amount = int(round(total))
        valid = [(squad, int(officer_counts.get(squad) or 0)) for squad in SQUAD_NAMES if officer_counts.get(squad, 0) > 0]
        if total_amount <= 0 or not valid:
            return []
        total_count = sum(count for _, count in valid)
        exact = [(squad, count, total_amount * count / total_count) for squad, count in valid]
        floors = [int(amount) for _, _, amount in exact]
        remaining = total_amount - sum(floors)
        order = sorted(
            range(len(exact)),
            key=lambda idx: (-(exact[idx][2] - floors[idx]), SQUAD_NAMES.index(exact[idx][0])),
        )
        for idx in order[:remaining]:
            floors[idx] += 1
        return [
            {"squad": squad, "count": count, "amount": floors[index]}
            for index, (squad, count, _) in enumerate(exact)
        ]

    @staticmethod
    def _extract_criminal_detention_count(text: str) -> int:
        patterns = [
            r"刑事拘留\s*(?P<count>[\d一二两三四五六七八九十]+)\s*(?:人|名)",
            r"(?P<count>[\d一二两三四五六七八九十]+)\s*(?:人|名)[^，。；;]{0,8}刑事拘留",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return CaseAutomationService._parse_count(match.group("count"))
        return 0

    @staticmethod
    def _parse_count(value: str) -> int:
        if str(value).isdigit():
            return int(value)
        digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        text = str(value)
        if text == "十":
            return 10
        if "十" in text:
            left, _, right = text.partition("十")
            tens = digits.get(left, 1) if left else 1
            ones = digits.get(right, 0) if right else 0
            return tens * 10 + ones
        return digits.get(text, 0)

    @staticmethod
    def _extract_datetime(text: str) -> Optional[datetime]:
        patterns = [
            r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})[日号]?\s*(\d{1,2})?[时:]?(\d{1,2})?",
            r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2})?[时:]?(\d{1,2})?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            groups = match.groups()
            try:
                if len(groups) == 5:
                    year, month, day, hour, minute = groups
                else:
                    year = datetime.utcnow().year
                    month, day, hour, minute = groups
                return datetime(
                    int(year),
                    int(month),
                    int(day),
                    int(hour or 0),
                    int(minute or 0),
                )
            except ValueError:
                return None
        return None

    @staticmethod
    def _extract_location(text: str) -> Optional[str]:
        patterns = [
            r"(?:在|于)([^，。,；;]{2,40}(?:井场|管线|油井|站|作业区|井区|道路|附近))",
            r"地点[:：]\s*([^，。,；;]{2,60})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_volume_tons(text: str) -> Optional[float]:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(吨|t|T|公斤|千克|kg|KG|升|L|l)", text)
        if not match:
            return None
        value = float(match.group(1))
        unit = match.group(2)
        if unit in {"公斤", "千克", "kg", "KG"}:
            return round(value / 1000, 3)
        if unit in {"升", "L", "l"}:
            return round(value / 1000, 3)
        return value

    @staticmethod
    def _extract_water_cut(text: str) -> Optional[float]:
        patterns = [r"含水率?\s*(\d+(?:\.\d+)?)\s*%", r"含水\s*(\d+(?:\.\d+)?)\s*%"]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        return None

    @staticmethod
    def _extract_money(text: str) -> Optional[int]:
        match = re.search(r"(?:价值|金额|损失)\s*(\d+(?:\.\d+)?)\s*(万元|万|元)", text)
        if not match:
            return None
        value = float(match.group(1))
        return int(value * 10000) if match.group(2) in {"万元", "万"} else int(value)

    @staticmethod
    def _extract_oil_nature(text: str) -> Optional[str]:
        if "落地" in text:
            return "落地原油"
        if "被盗" in text or "盗油" in text or "盗运" in text:
            return "被盗原油"
        if "收缴" in text:
            return "收缴油品"
        if "回收" in text:
            return "回收原油"
        return None

    @staticmethod
    def _extract_plate_numbers(text: str) -> List[str]:
        pattern = r"[\u4e00-\u9fa5][A-Z][A-Z0-9·\-]{4,7}"
        return list(dict.fromkeys(re.findall(pattern, text)))

    @staticmethod
    def _extract_person_count(text: str) -> int:
        match = re.search(r"(抓获|查获|移交)\s*(\d+)\s*(名|人)", text)
        return int(match.group(2)) if match else 0

    @staticmethod
    def _material_hints_from_text(text: str) -> List[str]:
        return [
            rule["label"]
            for rule in MATERIAL_RULES.values()
            if _contains_any(text, rule["keywords"])
        ]

    @staticmethod
    def _dedupe_evidence_suggestions(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen = set()
        result = []
        for item in items:
            key = item["requirement_key"]
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    @staticmethod
    def _oil_tons(case: Case, oil_recovery: List[OilRecoveryRecord]) -> float:
        if case.oil_volume is not None:
            return float(case.oil_volume)
        volumes = [r.volume_tons for r in oil_recovery if r.volume_tons is not None]
        return float(sum(volumes)) if volumes else 0.0

    @staticmethod
    def _net_oil_tons(oil_tons: float, water_cut: Optional[float], oil_recovery: List[OilRecoveryRecord]) -> float:
        water = water_cut
        if water is None:
            water_values = [r.water_cut for r in oil_recovery if r.water_cut is not None]
            water = water_values[0] if water_values else 0
        water = max(0.0, min(float(water or 0), 100.0))
        return round(oil_tons * (1 - water / 100), 3)
