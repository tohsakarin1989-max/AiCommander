"""涉油案件数智研判服务。

该服务只基于当前项目能够稳定掌握的数据做确定性分析：
案件时间、空间位置、井区/道路/村屯/站库环境、车辆类型、工具痕迹、
现场防护条件、抓获/发现方式和历史相似案件。它不把同人同车多案、
完整团伙结构、完整销赃链条作为核心研判依据。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvidence, CaseVehicle
from app.services.case_quality_service import CaseQualityService
from app.services.case_tag_evidence import TAG_RULE_VERSION, collect_tag_evidence
from app.services.jurisdiction_service import (
    PRODUCTION_TARGET_TYPES,
    ROAD_TYPES,
    TECH_TYPES,
    VILLAGE_TYPES,
    JurisdictionService,
)


Tag = Dict[str, Any]
LEGACY_AREA_BOUNDARY = "旧区域风险评分已停用，不再按邻近案数、资料缺失或未核验状态加分；未计算不表示零风险。"


VEHICLE_KEYWORDS = {
    "pickup": ("皮卡", "皮卡车"),
    "van": ("面包车", "厢货", "厢式", "货车", "箱货"),
    "tanker": ("罐车", "油罐车"),
    "farm": ("农用车", "三轮", "拖拉机"),
    "unknown_plate": ("无牌", "套牌", "遮挡号牌", "假牌"),
}

TOOL_KEYWORDS = {
    "oil_bucket": ("油桶", "桶装", "塑料桶", "铁桶"),
    "hose": ("软管", "胶管", "管线"),
    "pump": ("油泵", "抽油泵", "泵"),
    "tank": ("暗罐", "储油罐", "改装罐", "夹层"),
    "lock_break": ("撬锁", "破锁", "剪锁", "破坏锁具"),
}

WEAKNESS_KEYWORDS = {
    "lighting_gap": ("无照明", "照明不足", "夜间视线差", "灯光不足"),
    "camera_gap": ("监控盲区", "无监控", "摄像头损坏", "视频盲区"),
    "fence_gap": ("无围挡", "围栏破损", "围挡缺失", "围栏缺失"),
    "lock_gap": ("锁具损坏", "锁具薄弱", "未上锁", "锁坏"),
    "hidden_space": ("林带", "沟渠", "废弃院落", "荒地", "隐蔽", "偏僻"),
}

CAPTURE_SOURCE_TAGS = {
    "巡逻发现": ("capture_patrol", "巡查发现"),
    "群众举报": ("capture_public_tip", "群众发现"),
    "技防预警": ("capture_tech", "技防发现"),
    "公安机关线索": ("capture_police_clue", "公安线索"),
    "作业区反馈": ("capture_operation_feedback", "作业区反馈"),
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {_text(val)}" for key, val in value.items())
    return str(value)


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)


def _safe_round(value: Optional[float], ndigits: int = 2) -> Optional[float]:
    return round(value, ndigits) if isinstance(value, (int, float)) else None


class _WorkbenchInputs:
    """Only reuse read-only calculations within one service call and session.

    Nothing is stored on the session or globally. Exact arguments remain part of
    the key: an experience card's 365-day window is not the selected window, and
    a scene's eight examples are not the workbench's display limit.
    """

    _NESTED = {
        "analyze_scene_factors", "build_prevention_suggestions",
        "build_experience_card", "build_report",
    }

    def __init__(self, db: Session):
        self.db = db
        self.values: dict[tuple, dict] = {}

    def call(self, name: str, **parameters) -> dict:
        key = (name, tuple(sorted(parameters.items())))
        if key not in self.values:
            method = getattr(CaseIntelligenceService, name)
            nested = {"_inputs": self} if name in self._NESTED else {}
            self.values[key] = method(self.db, **parameters, **nested)
        return self.values[key]


class CaseIntelligenceService:
    """案件研判工作台：从已破案件中沉淀可解释的防控参考。"""

    @staticmethod
    def build_workbench(
        db: Session,
        case_id: Optional[int] = None,
        days: int = 365,
        limit: int = 8,
        radius_km: float = 1.5,
    ) -> Dict[str, Any]:
        inputs = _WorkbenchInputs(db)
        selected_case = CaseIntelligenceService._get_case(db, case_id) if case_id else None
        quality = (
            selected_case.quality_issues
            or CaseQualityService.evaluate_case(db, selected_case)
            if selected_case
            else None
        )

        tags = (
            CaseIntelligenceService.build_case_tags(db, selected_case)
            if selected_case
            else {"case_id": None, "tags": CaseIntelligenceService._aggregate_tags(db, days)}
        )
        similar_cases = (
            inputs.call("find_similar_cases", case_id=selected_case.id, days=days, limit=limit)
            if selected_case
            else {"case_id": None, "items": []}
        )
        spatiotemporal = inputs.call("analyze_spatiotemporal_patterns", days=days)
        scene = (
            inputs.call("analyze_scene_factors", case_id=selected_case.id, days=days)
            if selected_case
            else CaseIntelligenceService.analyze_global_scene_factors(db, days=days)
        )
        area_profiles = inputs.call(
            "build_area_risk_profiles",
            days=days,
            limit=limit,
            radius_km=radius_km,
        )
        suggestions = inputs.call(
            "build_prevention_suggestions",
            case_id=selected_case.id if selected_case else None,
            days=days,
            limit=limit,
        )
        experience_card = (
            inputs.call("build_experience_card", case_id=selected_case.id, persist=False)
            if selected_case
            else None
        )
        report = inputs.call(
            "build_report",
            case_id=selected_case.id if selected_case else None,
            days=days,
            limit=limit,
        )

        workbench = {
            "scope": {
                "mode": "single_case" if selected_case else "global",
                "days": days,
                "limit": limit,
                "radius_km": radius_km,
            },
            "selected_case": CaseIntelligenceService._case_brief(selected_case) if selected_case else None,
            "quality": quality,
            "readiness": (
                CaseIntelligenceService._practical_readiness(selected_case, quality)
                if selected_case
                else None
            ),
            "feature_tags": tags,
            "similar_cases": similar_cases,
            "spatiotemporal": spatiotemporal,
            "scene_analysis": scene,
            "area_profiles": area_profiles,
            "prevention_suggestions": suggestions,
            "experience_card": experience_card,
            "report": report,
        }
        workbench["context_pack"] = CaseIntelligenceService._build_llm_context_from_workbench(workbench)
        return workbench

    @staticmethod
    def build_llm_context_pack(
        db: Session,
        case_id: Optional[int] = None,
        days: int = 365,
        limit: int = 8,
        radius_km: float = 1.5,
    ) -> Dict[str, Any]:
        """构建供大模型读取的可解释研判上下文包。

        上下文包只整理系统已经掌握的事实、规则研判结果和建议草案，
        不让大模型直接替代评分、相似度或处置决策。
        """
        workbench = CaseIntelligenceService.build_workbench(
            db,
            case_id=case_id,
            days=days,
            limit=limit,
            radius_km=radius_km,
        )
        return workbench["context_pack"]

    @staticmethod
    def build_case_tags(db: Session, case: Case) -> Dict[str, Any]:
        context = CaseIntelligenceService._safe_case_context(db, case)
        tags: List[Tag] = []
        observations: List[Dict[str, Any]] = []
        information_gaps: List[str] = []

        def add(
            key: str,
            label: str,
            category: str,
            confidence: float,
            basis: List[str],
        ) -> None:
            if any(item["key"] == key for item in tags):
                return
            tags.append({
                "key": key,
                "label": label,
                "category": category,
                "confidence": round(confidence, 2),
                "basis": basis,
            })

        if case.occurred_time:
            hour = case.occurred_time.hour
            period = CaseIntelligenceService._time_period(hour)
            add(f"time_{period['key']}", period["label"], "time", 0.95, [f"发生时间 {hour:02d}:00"])
            if case.occurred_time.weekday() >= 5:
                add("time_weekend", "周末发案", "time", 0.9, ["发生时间为周末"])
            if case.occurred_time.month in {11, 12, 1, 2}:
                add("season_winter", "冬季时段", "time", 0.8, [f"发生月份 {case.occurred_time.month} 月"])

        nearest = context.get("nearest", {}) if context else {}
        road = nearest.get("road")
        village = nearest.get("village")
        production = nearest.get("production_target")
        tech = nearest.get("tech")
        if road and road.get("distance_km") is not None and road["distance_km"] <= 0.8:
            add("space_road_access", "邻近已登记道路", "space", 0.88, [f"直线距道路 {road['distance_km']:.2f} 公里，入口及通行条件待核"])
        if village and village.get("distance_km") is not None and village["distance_km"] <= 1.5:
            add("space_near_village", "靠近村屯", "space", 0.82, [f"距村屯 {village['distance_km']:.2f} 公里"])
        if production and production.get("distance_km") is not None and production["distance_km"] <= 0.5:
            add("space_near_production", "贴近生产目标", "space", 0.9, [f"距生产目标 {production['distance_km']:.2f} 公里"])
        if not village:
            information_gaps.append("村屯资料未取得，不能据此认定现场偏远。")
        if not tech:
            information_gaps.append("技防资料未取得，覆盖情况待核，不能认定没有技防。")
        else:
            information_gaps.append("已登记技防点的邻近距离不能证明覆盖或防护不足，需核对有效覆盖资料。")

        terms = {}
        labels = {"weakness_low_security": "安防等级偏低"}
        for category, prefix, dictionary, labeler in (
            ("vehicle", "vehicle", VEHICLE_KEYWORDS, CaseIntelligenceService._vehicle_label),
            ("tool", "tool", TOOL_KEYWORDS, CaseIntelligenceService._tool_label),
            ("defense", "weakness", WEAKNESS_KEYWORDS, CaseIntelligenceService._weakness_label),
        ):
            terms[category] = {}
            for key, words in dictionary.items():
                normalized_key = f"{prefix}_{key}"
                labels[normalized_key] = labeler(key)
                terms[category].update({word: normalized_key for word in words})
        evidence = collect_tag_evidence(case, terms)
        grouped = defaultdict(list)
        for assertion in evidence["assertions"]:
            grouped[(assertion["category"], assertion["value"])].append(assertion)
        if evidence["information_gaps"]:
            information_gaps.append("部分原文或结构化字段未完整提取，自动词项标签暂不作肯定归纳。")
        for (category, key), assertions in grouped.items():
            kinds = {item["kind"] for item in assertions}
            references = [ref for item in assertions
                          for ref in [item["reference"], *item.get("context_references", [])]]
            # Mixed statements require context review, not an affirmative majority vote.
            if kinds == {"stated"} and not evidence["information_gaps"]:
                add(key, labels[key], category, 0.84, [
                    f"原文明确表述：{ref.get('quote', ref.get('value', ''))}" for ref in references
                ])
                tags[-1]["references"] = references
                tags[-1]["kind"] = "stated"
                tags[-1]["is_official_fact"] = False
            else:
                kind = "conflicting" if {"stated", "negated"} <= kinds else (
                    "negated" if kinds == {"negated"} else "uncertain"
                )
                observations.append({
                    "key": key, "label": labels[key], "category": category,
                    "kind": kind, "references": references,
                })
                state = {"negated": "否定表述", "uncertain": "待核表述", "conflicting": "肯否并存待核"}[kind]
                information_gaps.append(f"{labels[key]}：{state}，不作为自动肯定标签。")

        if case.source_type in CAPTURE_SOURCE_TAGS:
            key, label = CAPTURE_SOURCE_TAGS[case.source_type]
            add(key, label, "capture", 0.92, [f"线索来源：{case.source_type}"])

        if case.oil_volume is not None and getattr(case, "oil_volume_unit", None) == "tonne":
            if case.oil_volume >= 2:
                add("oil_large_volume", "涉油数量较大", "oil", 0.82, [f"涉油数量 {case.oil_volume:g}吨"])
            elif case.oil_volume <= 0.5:
                add("oil_small_volume", "涉油数量较少", "oil", 0.72, [f"涉油数量 {case.oil_volume:g}吨，不能据此推定发生转运"])
        elif case.oil_volume is not None:
            information_gaps.append("油量非明确吨单位，未套用吨量大小标签；原始数值与单位分别保留。")

        overrides = CaseIntelligenceService._tag_overrides(case)
        removed = set(overrides.get("removed_keys") or [])
        tags = [tag for tag in tags if tag["key"] not in removed]
        for added in overrides.get("added") or []:
            if isinstance(added, dict) and added.get("key"):
                tags = [tag for tag in tags if tag["key"] != added["key"]]
                tags.append({
                    "key": added["key"],
                    "label": added.get("label") or added["key"],
                    "category": added.get("category") or "manual",
                    "confidence": float(added.get("confidence") or 1.0),
                    "basis": added.get("basis") or ["人工修正"],
                    "manual": True,
                })

        category_counts = Counter(tag["category"] for tag in tags)
        return {
            "case_id": case.id,
            "case_number": case.case_number,
            "tags": sorted(tags, key=lambda item: (item["category"], -item["confidence"], item["label"])),
            "category_counts": dict(category_counts),
            "rule_version": TAG_RULE_VERSION,
            "observations": observations,
            "information_gaps": information_gaps,
            "source_snapshot": evidence["source_snapshot"],
            "structured_sources": evidence["structured_sources"],
            "context": context,
            "principle": "标签基于时间、空间环境、车辆类型、工具痕迹、现场薄弱点和发现方式，不以同人同车多案作为核心依据。",
        }

    @staticmethod
    def update_tag_overrides(
        db: Session,
        case_id: int,
        added: Optional[List[Dict[str, Any]]] = None,
        removed_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        case = CaseIntelligenceService._get_case(db, case_id)
        features = dict(case.features or {})
        intelligence = dict(features.get("intelligence") or {})
        overrides = dict(intelligence.get("tag_overrides") or {})
        current_added = [
            item for item in (overrides.get("added") or [])
            if isinstance(item, dict) and item.get("key")
        ]
        by_key = {item["key"]: item for item in current_added}
        for item in added or []:
            if item.get("key"):
                by_key[item["key"]] = item
        removed = set(overrides.get("removed_keys") or [])
        removed.update(removed_keys or [])
        intelligence["tag_overrides"] = {
            "added": list(by_key.values()),
            "removed_keys": sorted(removed),
            "updated_at": datetime.utcnow().isoformat(),
        }
        features["intelligence"] = intelligence
        case.features = CaseIntelligenceService._json_safe(features)
        db.commit()
        db.refresh(case)
        return CaseIntelligenceService.build_case_tags(db, case)

    @staticmethod
    def find_similar_cases(
        db: Session,
        case_id: int,
        days: int = 365,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Compatibility shape backed by the authorized, versioned history index."""
        from app.services.case_history_compat import build_legacy_similar_cases

        return build_legacy_similar_cases(db, case_id, days=days, limit=limit)

    @staticmethod
    def analyze_spatiotemporal_patterns(db: Session, days: int = 365) -> Dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=days) if days > 0 else None
        query = db.query(Case)
        if cutoff is not None:
            query = query.filter(Case.occurred_time >= cutoff)
        cases = query.order_by(Case.occurred_time.desc()).all()

        hour_counter: Counter[int] = Counter()
        weekday_counter: Counter[str] = Counter()
        month_counter: Counter[str] = Counter()
        period_counter: Counter[str] = Counter()
        type_counter: Counter[str] = Counter()
        facility_counter: Counter[str] = Counter()
        source_counter: Counter[str] = Counter()
        grid_counter: Dict[Tuple[int, int], List[Case]] = defaultdict(list)
        day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        for case in cases:
            if case.occurred_time:
                hour_counter[case.occurred_time.hour] += 1
                weekday_counter[day_names[case.occurred_time.weekday()]] += 1
                month_counter[f"{case.occurred_time.month}月"] += 1
                period_counter[CaseIntelligenceService._time_period(case.occurred_time.hour)["label"]] += 1
            if case.case_type:
                type_counter[case.case_type] += 1
            if case.facility_type:
                facility_counter[case.facility_type] += 1
            if case.source_type:
                source_counter[case.source_type] += 1
            if case.latitude is not None and case.longitude is not None:
                grid_counter[(round(case.latitude, 2), round(case.longitude, 2))].append(case)

        hotspots = []
        for (lat, lon), grid_cases in grid_counter.items():
            if len(grid_cases) < 1:
                continue
            hotspots.append({
                "center": {"latitude": lat, "longitude": lon},
                "case_count": len(grid_cases),
                "case_ids": [case.id for case in grid_cases],
                "case_numbers": [case.case_number for case in grid_cases[:5]],
            })
        hotspots.sort(key=lambda item: item["case_count"], reverse=True)

        insights = []
        if hour_counter:
            top_hour, top_count = hour_counter.most_common(1)[0]
            insights.append(f"高频小时为 {top_hour:02d}:00 左右，关联案件 {top_count} 起。")
        if period_counter:
            top_period, top_count = period_counter.most_common(1)[0]
            insights.append(f"高频时段集中在{top_period}，关联案件 {top_count} 起。")
        if hotspots:
            insights.append(f"空间热点网格 {len(hotspots)} 个，最高网格关联 {hotspots[0]['case_count']} 起案件。")
        if not insights:
            insights.append("历史案件量不足，暂不能形成稳定时空规律。")

        return {
            "days": days,
            "case_count": len(cases),
            "cases_with_geo": sum(1 for case in cases if case.latitude is not None and case.longitude is not None),
            "hour_distribution": CaseIntelligenceService._counter_items(hour_counter, "hour"),
            "period_distribution": CaseIntelligenceService._counter_items(period_counter, "period"),
            "weekday_distribution": CaseIntelligenceService._counter_items(weekday_counter, "weekday"),
            "month_distribution": CaseIntelligenceService._counter_items(month_counter, "month"),
            "case_type_distribution": CaseIntelligenceService._counter_items(type_counter, "case_type"),
            "facility_distribution": CaseIntelligenceService._counter_items(facility_counter, "facility_type"),
            "source_distribution": CaseIntelligenceService._counter_items(source_counter, "source_type"),
            "hotspots": hotspots[:10],
            "insights": insights,
        }

    @staticmethod
    def analyze_scene_factors(
        db: Session, case_id: int, days: int = 365, *, _inputs: Optional[_WorkbenchInputs] = None
    ) -> Dict[str, Any]:
        inputs = _inputs if _inputs is not None else _WorkbenchInputs(db)
        case = CaseIntelligenceService._get_case(db, case_id)
        tags_payload = CaseIntelligenceService.build_case_tags(db, case)
        tags = tags_payload["tags"]
        similar = inputs.call("find_similar_cases", case_id=case_id, days=days, limit=8)
        similar_ids = [item["case"]["id"] for item in similar["items"]]
        related_cases = (
            db.query(Case).filter(Case.id.in_(similar_ids)).all()
            if similar_ids
            else []
        )
        case_group = [case, *related_cases]

        tag_counter = Counter(
            tag["label"]
            for current_case in case_group
            for tag in CaseIntelligenceService.build_case_tags(db, current_case)["tags"]
        )
        vehicle_counter = Counter()
        tool_counter = Counter()
        weakness_counter = Counter()
        capture_counter = Counter()
        for current_case in case_group:
            current_tags = CaseIntelligenceService.build_case_tags(db, current_case)["tags"]
            for tag in current_tags:
                if tag["category"] == "vehicle":
                    vehicle_counter[tag["label"]] += 1
                elif tag["category"] == "tool":
                    tool_counter[tag["label"]] += 1
                elif tag["category"] == "defense":
                    weakness_counter[tag["label"]] += 1
                elif tag["category"] == "capture":
                    capture_counter[tag["label"]] += 1

        context = tags_payload.get("context") or {}
        location_conditions = [
            tag for tag in tags
            if tag["category"] in {"space", "time"}
        ]
        reusable_rules = CaseIntelligenceService._build_reusable_rules(tags, similar["items"])

        return {
            "case_id": case.id,
            "case_number": case.case_number,
            "location_conditions": location_conditions,
            "vehicle_tool_patterns": {
                "vehicles": CaseIntelligenceService._counter_items(vehicle_counter, "label"),
                "tools": CaseIntelligenceService._counter_items(tool_counter, "label"),
                "note": "这里分析车辆类型和工具痕迹，不把同一车牌反复出现作为常态假设。",
            },
            "site_weaknesses": CaseIntelligenceService._counter_items(weakness_counter, "label"),
            "capture_experience": {
                "source_type": case.source_type,
                "distribution_in_similar_cases": CaseIntelligenceService._counter_items(capture_counter, "label"),
                "lesson": CaseIntelligenceService._capture_lesson(case.source_type),
            },
            "condition_frequency": CaseIntelligenceService._counter_items(tag_counter, "label")[:12],
            "reusable_rules": reusable_rules,
            "spatial_context": context,
        }

    @staticmethod
    def analyze_global_scene_factors(db: Session, days: int = 365) -> Dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=days) if days > 0 else None
        query = db.query(Case)
        if cutoff is not None:
            query = query.filter(Case.occurred_time >= cutoff)
        cases = query.order_by(Case.occurred_time.desc()).limit(300).all()
        category_counters: Dict[str, Counter[str]] = defaultdict(Counter)
        for case in cases:
            for tag in CaseIntelligenceService.build_case_tags(db, case)["tags"]:
                category_counters[tag["category"]][tag["label"]] += 1
        return {
            "case_count": len(cases),
            "location_conditions": CaseIntelligenceService._counter_items(category_counters["space"], "label"),
            "vehicle_tool_patterns": {
                "vehicles": CaseIntelligenceService._counter_items(category_counters["vehicle"], "label"),
                "tools": CaseIntelligenceService._counter_items(category_counters["tool"], "label"),
            },
            "site_weaknesses": CaseIntelligenceService._counter_items(category_counters["defense"], "label"),
            "capture_experience": CaseIntelligenceService._counter_items(category_counters["capture"], "label"),
        }

    @staticmethod
    def build_area_risk_profiles(
        db: Session,
        days: int = 365,
        limit: int = 10,
        radius_km: float = 1.5,
    ) -> Dict[str, Any]:
        """Retain the workbench contract without running the retired score."""
        return {
            "state": "retired",
            "code": "legacy_area_scoring_retired",
            "days": days,
            "radius_km": radius_km,
            "profile_count": None,
            "items": [],
            "computed": False,
            "boundary": LEGACY_AREA_BOUNDARY,
            "replacement": {
                "region": "/area-analysis",
                "situation": "/situation",
                "region_api": "/api/facility-analysis/region",
                "situation_api": "/api/situation/briefs/latest",
            },
        }

    @staticmethod
    def build_prevention_suggestions(
        db: Session,
        case_id: Optional[int] = None,
        days: int = 365,
        limit: int = 8,
        *,
        _inputs: Optional[_WorkbenchInputs] = None,
    ) -> Dict[str, Any]:
        inputs = _inputs if _inputs is not None else _WorkbenchInputs(db)
        suggestions: List[Dict[str, Any]] = []
        spatiotemporal = inputs.call("analyze_spatiotemporal_patterns", days=days)
        if case_id is not None:
            case = CaseIntelligenceService._get_case(db, case_id)
            quality = case.quality_issues or CaseQualityService.evaluate_case(db, case)
            tags = CaseIntelligenceService.build_case_tags(db, case)["tags"]
            similar = inputs.call("find_similar_cases", case_id=case_id, days=days, limit=limit)
            scene = inputs.call("analyze_scene_factors", case_id=case_id, days=days)

            if similar["items"]:
                top = similar["items"][0]
                suggestions.append(CaseIntelligenceService._suggestion(
                    "similar_conditions",
                    "相似条件案件复盘",
                    "high",
                    "把本案与相似条件案件放在一起复盘，重点核对共同的时间段、道路通达性、车辆工具和现场薄弱点。",
                    top["reasons"],
                    [top["case"]["case_number"]],
                    0.88,
                ))
            weak_labels = [item["label"] for item in scene.get("site_weaknesses", [])[:4]]
            if weak_labels:
                suggestions.append(CaseIntelligenceService._suggestion(
                    "site_hardening",
                    "现场防护短板补强参考",
                    "high",
                    f"围绕 {CaseIntelligenceService._join_cn(weak_labels)} 做现场核验和补强评估。",
                    ["本案及相似案件中反复出现现场薄弱点。"],
                    weak_labels,
                    0.82,
                ))
            if quality and quality.get("missing_required"):
                missing = []
                for item in quality["missing_required"][:5]:
                    label = item.get("label") if isinstance(item, dict) else str(item).strip()
                    if label:
                        missing.append(label)
                suggestions.append(CaseIntelligenceService._suggestion(
                    "data_completion",
                    "先补齐影响研判的案件字段",
                    "medium",
                    f"优先补齐 {CaseIntelligenceService._join_cn(missing)}，否则历史条件比较会受影响。",
                    ["案件信息质量评分存在缺项。"],
                    missing,
                    0.9,
                ))
            rules = scene.get("reusable_rules") or []
            if rules:
                suggestions.append(CaseIntelligenceService._suggestion(
                    "reusable_rule",
                    "沉淀可复用防控规则",
                    "medium",
                    rules[0],
                    ["由本案标签和相似案件共同生成。"],
                    rules[:3],
                    0.78,
                ))

        peak_periods = spatiotemporal.get("period_distribution") or []
        if peak_periods:
            period = peak_periods[0]
            suggestions.append(CaseIntelligenceService._suggestion(
                "time_attention",
                "高发时段关注参考",
                "medium",
                f"近期已破案件高频时段为{period['period']}，内部分析和现场关注可优先覆盖该时段。",
                spatiotemporal.get("insights", [])[:2],
                [period],
                0.76,
            ))

        deduped = []
        seen = set()
        for item in suggestions:
            if item["id"] not in seen:
                deduped.append(item)
                seen.add(item["id"])

        priority_order = {"high": 0, "medium": 1, "low": 2}
        deduped.sort(key=lambda item: (priority_order.get(item["priority"], 9), -item["confidence"]))
        return {
            "case_id": case_id,
            "suggestion_count": len(deduped),
            "items": deduped[:limit],
            "boundary": "这些是防控参考草案，不自动创建执行任务，也不替代人工研判结论。",
        }

    @staticmethod
    def build_experience_card(
        db: Session, case_id: int, *, persist: bool = True,
        _inputs: Optional[_WorkbenchInputs] = None,
    ) -> Dict[str, Any]:
        inputs = _inputs if _inputs is not None else _WorkbenchInputs(db)
        case = CaseIntelligenceService._get_case(db, case_id)
        existing_features = dict(case.features or {})
        intelligence = dict(existing_features.get("intelligence") or {})
        existing_card = intelligence.get("experience_card") or {}
        if persist and existing_card.get("manual_review_status") in {"confirmed", "archived"}:
            # Legacy batch actions cannot overwrite a human-reviewed historical card.
            # New drafts use the versioned knowledge-asset path instead.
            return deepcopy(existing_card)
        tags_payload = CaseIntelligenceService.build_case_tags(db, case)
        scene = inputs.call("analyze_scene_factors", case_id=case_id, days=365)
        tags = tags_payload["tags"]
        conditions = [tag["label"] for tag in tags if tag["category"] in {"time", "space"}]
        vehicle_tools = [tag["label"] for tag in tags if tag["category"] in {"vehicle", "tool"}]
        weaknesses = [tag["label"] for tag in tags if tag["category"] == "defense"]
        capture_tags = [tag["label"] for tag in tags if tag["category"] == "capture"]
        quality = case.quality_issues or CaseQualityService.evaluate_case(db, case)
        missing_fields = [
            item.get("label")
            for item in quality.get("missing_required", [])
            if isinstance(item, dict) and item.get("label")
        ]

        card = {
            "case_id": case.id,
            "source_case_id": case.id,
            "case_number": case.case_number,
            "generated_at": datetime.utcnow().isoformat(),
            "manual_review_status": "pending",
            "summary": case.description or case.location or case.case_type or "未填写案情摘要",
            "operation_conditions": conditions or ["作案条件信息不足，需补齐时间、地点和现场环境。"],
            "discovery_method": capture_tags or [case.source_type or "发现方式未明确"],
            "protection_shortcomings": weaknesses or ["防护短板未明确，需结合现场照片、监控和防护设施核实。"],
            "evidence_gaps": [*missing_fields, *tags_payload.get("information_gaps", [])]
                or ["暂无明显必填字段缺口，仍需人工核验证据完整性。"],
            "reusable_suggestions": scene.get("reusable_rules", []),
            "referenced_cases": [case.case_number],
            "boundary": "经验卡区分事实、推断和建议；仅沉淀已发生案件经验，不做犯罪预测，不替代人工确认。",
            "what_happened": {
                "time": case.occurred_time.isoformat() if case.occurred_time else None,
                "location": case.location,
                "case_type": case.case_type,
            },
            "why_it_matters": [
                *[f"现场条件：{item}" for item in conditions[:4]],
                *[f"车辆/工具特征：{item}" for item in vehicle_tools[:4]],
                *[f"防护短板：{item}" for item in weaknesses[:4]],
            ] or ["案件信息不足，需先补齐时间、地点、车辆工具和现场环境描述。"],
            "how_it_was_found": capture_tags or [case.source_type or "发现方式未明确"],
            "reusable_lessons": scene.get("reusable_rules", []),
            "next_attention_points": CaseIntelligenceService._next_attention_points(tags),
            "evidence_basis": {
                "tags": tags[:12],
                "observations": tags_payload.get("observations", []),
                "tag_rule_version": tags_payload.get("rule_version"),
                "spatial_context": tags_payload.get("context"),
            },
        }
        if persist:
            intelligence["experience_card"] = card
            existing_features["intelligence"] = intelligence
            case.features = CaseIntelligenceService._json_safe(existing_features)
            db.commit()
            db.refresh(case)
        return card

    @staticmethod
    def build_report(
        db: Session,
        case_id: Optional[int] = None,
        days: int = 365,
        limit: int = 8,
        *,
        _inputs: Optional[_WorkbenchInputs] = None,
    ) -> Dict[str, Any]:
        inputs = _inputs if _inputs is not None else _WorkbenchInputs(db)
        selected_case = CaseIntelligenceService._get_case(db, case_id) if case_id else None
        spatiotemporal = inputs.call("analyze_spatiotemporal_patterns", days=days)
        suggestions = inputs.call("build_prevention_suggestions", case_id=case_id, days=days, limit=limit)
        area_profiles = inputs.call("build_area_risk_profiles", days=days, limit=limit, radius_km=1.5)
        sections = []

        title = (
            f"{selected_case.case_number} 案件研判报告"
            if selected_case
            else f"近 {days} 天涉油案件规律研判报告"
        )
        sections.append({
            "title": "一、研判边界",
            "type": "boundary",
            "items": [
                "本报告基于已破案件信息、辖区空间底座和结构化字段生成。",
                "报告输出防控参考，不做犯罪预测，不自动派发任务。",
                "研判重点为时间、空间、车辆工具、现场防护和抓获经验。",
            ],
        })
        if selected_case:
            experience = inputs.call("build_experience_card", case_id=selected_case.id, persist=False)
            tags_payload = CaseIntelligenceService.build_case_tags(db, selected_case)
            tag_labels = [tag["label"] for tag in tags_payload.get("tags", [])[:8]]
            quality = selected_case.quality_issues or CaseQualityService.evaluate_case(db, selected_case)
            missing_fields = [
                item["label"]
                for item in quality.get("missing_required", [])
                if isinstance(item, dict) and item.get("label")
            ]
            sections.append({
                "title": "二、事实依据",
                "type": "facts",
                "items": [
                    f"案件编号：{selected_case.case_number}",
                    f"案件类型：{selected_case.case_type or '未填写'}",
                    f"发生时间：{selected_case.occurred_time.isoformat() if selected_case.occurred_time else '未填写'}",
                    f"地点：{selected_case.location or '未填写'}",
                    f"发现来源：{selected_case.source_type or '未填写'}",
                    f"结构化标签：{'、'.join(tag_labels) if tag_labels else '暂无'}",
                ],
            })
            sections.append({
                "title": "三、模式发现",
                "type": "patterns",
                "items": [
                    *experience["why_it_matters"][:6],
                    *spatiotemporal.get("insights", [])[:4],
                ],
            })
            sections.append({
                "title": "四、信息缺口",
                "type": "gaps",
                "items": [*missing_fields, *tags_payload.get("information_gaps", [])]
                    or ["暂无明显必填字段缺口。"],
            })
        else:
            sections.append({
                "title": "二、事实依据",
                "type": "facts",
                "items": [
                    f"统计范围：近 {days} 天",
                    f"案件数量：{spatiotemporal.get('case_count', 0)}",
                    "数据来源：已录入案件和辖区空间底座。",
                ],
            })
            sections.append({
                "title": "三、模式发现",
                "type": "patterns",
                # Report-only area notes must not mutate the shared statistics.
                "items": list(spatiotemporal.get("insights", [])),
            })
            sections.append({
                "title": "四、信息缺口",
                "type": "gaps",
                "items": ["未选择具体案件时，仅能输出全局趋势，不能形成单案复盘结论。"],
            })

        pattern_section = next((section for section in sections if section.get("type") == "patterns"), None)
        gap_section = next((section for section in sections if section.get("type") == "gaps"), None)
        if gap_section is not None:
            gap_section["items"].append(area_profiles["boundary"])

        sections.append({
            "title": "五、防控建议草案",
            "type": "prevention_reference",
            "items": [
                f"{item['title']}：{item['action']}"
                for item in suggestions.get("items", [])[:8]
            ] or ["暂无足够依据生成建议。"],
        })

        markdown = [f"# {title}", ""]
        for section in sections:
            markdown.append(f"## {section['title']}")
            for item in section["items"]:
                markdown.append(f"- {item}")
            markdown.append("")

        fact_section = next((section for section in sections if section.get("type") == "facts"), {})
        gap_section = next((section for section in sections if section.get("type") == "gaps"), {})
        inference_items = (pattern_section or {}).get("items", [])
        evidence_refs: List[Dict[str, Any]] = []
        if selected_case:
            evidence_refs.append({
                "id": f"case:{selected_case.case_number}",
                "kind": "case",
                "summary": f"案件 {selected_case.case_number}",
                "basis": [selected_case.location or "地点未填写"],
            })
        report_boundary = [
            "只基于已录入案件、辖区底座和结构化研判结果生成草稿。",
            "必须区分事实依据、模式推断、防控参考和信息缺口。",
            "不得把防控参考写成已执行任务，不自动创建外勤或跨部门处置。",
            "不得编造未掌握的人车链条、销赃链条或未破案件线索。",
        ]
        ai_output = CaseIntelligenceService.build_structured_ai_output(
            title=title,
            output_type="case_intelligence_report",
            facts=fact_section.get("items", []),
            inferences=[
                {
                    "claim": item,
                    "basis": ["规则侧报告章节"],
                    "confidence": "medium",
                }
                for item in inference_items
            ],
            recommendations=[
                {
                    "title": item.get("title"),
                    "action": item.get("action"),
                    "basis": item.get("reason", [])[:4],
                    "evidence": item.get("evidence", [])[:6],
                    "confidence": item.get("confidence"),
                }
                for item in suggestions.get("items", [])[:limit]
            ],
            information_gaps=gap_section.get("items", []),
            evidence_refs=evidence_refs,
            boundary=report_boundary,
        )

        return {
            "title": title,
            "generated_at": datetime.utcnow().isoformat(),
            "case_id": case_id,
            "days": days,
            "sections": sections,
            "markdown": "\n".join(markdown).strip(),
            "ai_output": ai_output,
        }

    @staticmethod
    def build_structured_ai_output(
        *,
        title: str,
        output_type: str,
        facts: List[Any],
        inferences: List[Dict[str, Any]],
        recommendations: List[Dict[str, Any]],
        information_gaps: List[Any],
        evidence_refs: List[Dict[str, Any]],
        boundary: List[str],
        model_status: str = "deterministic_fallback",
    ) -> Dict[str, Any]:
        """统一 AI 草稿输出结构。

        第一版只整合规则侧材料，作为未配置模型或模型失败时的稳定兜底。
        """
        normalized = {
            "title": title,
            "output_type": output_type,
            "draft_status": "draft",
            "review_status": "pending_review",
            "model_status": model_status,
            "generated_at": datetime.utcnow().isoformat(),
            "facts": [CaseIntelligenceService._structured_text(item) for item in facts if item],
            "inferences": [
                CaseIntelligenceService._normalize_structured_inference(item)
                for item in inferences
                if item
            ],
            "recommendations": [
                CaseIntelligenceService._normalize_structured_recommendation(item)
                for item in recommendations
                if item
            ],
            "information_gaps": [
                CaseIntelligenceService._structured_text(item)
                for item in information_gaps
                if item
            ],
            "evidence_refs": [
                CaseIntelligenceService._normalize_structured_evidence_ref(item)
                for item in evidence_refs
                if item
            ],
            "boundary": boundary,
        }
        if not normalized["information_gaps"]:
            normalized["information_gaps"] = ["暂无明显信息缺口，仍需人工复核事实完整性。"]
        normalized["markdown"] = CaseIntelligenceService._render_structured_ai_markdown(normalized)
        return normalized

    @staticmethod
    def _build_llm_context_from_workbench(workbench: Dict[str, Any]) -> Dict[str, Any]:
        selected_case = workbench.get("selected_case")
        scope = workbench.get("scope") or {}
        tags = workbench.get("feature_tags", {}).get("tags", []) or []
        similar_items = workbench.get("similar_cases", {}).get("items", []) or []
        suggestions = workbench.get("prevention_suggestions", {}).get("items", []) or []
        spatiotemporal = workbench.get("spatiotemporal", {}) or {}
        quality = workbench.get("quality") or {}
        readiness = workbench.get("readiness") or {}
        display_limit = int(scope.get("limit") or 8)

        facts: List[str] = []
        if selected_case:
            facts.extend([
                f"案件编号：{selected_case.get('case_number')}",
                f"发生时间：{selected_case.get('occurred_time') or '未填写'}",
                f"地点：{selected_case.get('location') or '未填写'}",
                f"案件类型：{selected_case.get('case_type') or '未填写'}",
                f"线索来源：{selected_case.get('source_type') or '未填写'}",
            ])
            if selected_case.get("facility_type"):
                facts.append(f"目标设施类型：{selected_case.get('facility_type')}")
            if selected_case.get("quality_score") is not None:
                facts.append(f"案件质量评分：{selected_case.get('quality_score')}")
        else:
            facts.extend([
                f"统计范围：近 {scope.get('days') or spatiotemporal.get('days')} 天",
                f"案件数量：{spatiotemporal.get('case_count', 0)}",
                f"带坐标案件：{spatiotemporal.get('cases_with_geo', 0)}",
            ])

        tag_labels = [tag.get("label") for tag in tags[:12] if tag.get("label")]
        if tag_labels:
            facts.append(f"结构化标签：{CaseIntelligenceService._join_cn(tag_labels)}")

        pattern_inferences: List[Dict[str, Any]] = []
        for insight in spatiotemporal.get("insights", [])[:5]:
            pattern_inferences.append({
                "claim": insight,
                "basis": ["案件时空统计"],
                "confidence": "medium" if spatiotemporal.get("case_count", 0) >= 3 else "low",
            })
        for item in similar_items[:5]:
            case_number = item.get("case", {}).get("case_number")
            if case_number:
                pattern_inferences.append({
                    "claim": f"{case_number} 为统一历史检索参考，检索支持度 {item.get('score')}（非概率，不能据此认定实际关联）",
                    "basis": item.get("reasons", [])[:4],
                    "confidence": "未校准",
                })
        prevention_references = [
            {
                "title": item.get("title"),
                "action": item.get("action"),
                "priority": item.get("priority"),
                "basis": item.get("reason", [])[:4],
                "evidence": item.get("evidence", [])[:6],
                "confidence": item.get("confidence"),
            }
            for item in suggestions[:display_limit]
        ]

        information_gaps: List[str] = [LEGACY_AREA_BOUNDARY]
        information_gaps.extend(workbench.get("feature_tags", {}).get("information_gaps", []))
        retrieval = workbench.get("similar_cases") or {}
        if retrieval.get("state") == "unavailable":
            information_gaps.append("统一历史检索暂不可用，不能据此判断没有相关资料。")
        elif retrieval.get("coverage", {}).get("complete") is False:
            information_gaps.append("历史检索未覆盖完整范围，以下为部分结果。")
        for item in (quality.get("missing_required") or [])[:8]:
            if isinstance(item, dict):
                label = item.get("label") or item.get("field")
                reason = item.get("reason")
                if label:
                    information_gaps.append(f"{label}：{reason or '必填字段缺失'}")
        for name, item in readiness.items():
            for blocker in item.get("blockers", []) or []:
                information_gaps.append(f"{name}：{blocker}")
        if not information_gaps:
            information_gaps.append("暂无明显信息缺口，仍需人工复核事实完整性。")

        evidence_index: List[Dict[str, Any]] = []
        for tag in tags[:12]:
            evidence_index.append({
                "id": f"tag:{tag.get('key')}",
                "kind": "tag",
                "summary": f"{tag.get('label')}（{tag.get('category')}）",
                "basis": tag.get("basis", []),
                "references": tag.get("references", []),
            })
        for item in similar_items[:5]:
            case_number = item.get("case", {}).get("case_number")
            evidence_index.append({
                "id": f"similar:{case_number}",
                "kind": "similar_case",
                "summary": f"{case_number}，检索支持度 {item.get('score')}（非概率）",
                "basis": item.get("reasons", []),
                "versions": item.get("versions", {}),
                "evidence_refs": item.get("evidence_refs", []),
            })
        boundary = [
            "只基于已录入案件、辖区底座和结构化研判结果回答。",
            "必须区分事实依据、模式推断、防控参考和信息缺口。",
            "不得把防控参考写成已执行任务，不自动创建外勤或跨部门处置。",
            "不得编造未掌握的人车链条、销赃链条或未破案件线索。",
        ]
        recommended_questions = [
            "本案和哪些已破案件的作案条件相似，依据是什么？",
            "当前结论有哪些事实依据，哪些只是需要复核的推断？",
            "如果要形成复盘材料，还缺哪些字段或证据？",
            "哪些防控参考可以沉淀为后续人工研判清单？",
        ]

        prompt_lines = [
            "你是涉油案件研判辅助大模型。请严格基于以下上下文输出：",
            "1. 事实依据；2. 模式推断；3. 防控参考；4. 信息缺口；5. 证据索引。",
            "边界要求：" + "；".join(boundary),
            "",
            "【事实依据】",
            *[f"- {item}" for item in facts],
            "",
            "【模式推断】",
            *[f"- {item['claim']}；依据：{CaseIntelligenceService._join_cn(item.get('basis') or [])}" for item in pattern_inferences[:8]],
            "",
            "【防控参考】",
            *[f"- {item.get('title')}：{item.get('action')}" for item in prevention_references[:8]],
            "",
            "【信息缺口】",
            *[f"- {item}" for item in information_gaps],
        ]
        structured_output = CaseIntelligenceService.build_structured_ai_output(
            title=(
                f"{selected_case.get('case_number')} AI研判上下文草稿"
                if selected_case
                else "全局 AI研判上下文草稿"
            ),
            output_type="case_intelligence_context_pack",
            facts=facts,
            inferences=pattern_inferences,
            recommendations=prevention_references,
            information_gaps=information_gaps,
            evidence_refs=evidence_index,
            boundary=boundary,
        )

        return {
            "scope": scope,
            "selected_case": selected_case,
            "system_boundary": boundary,
            "facts": facts,
            "pattern_inferences": pattern_inferences,
            "inferences": structured_output["inferences"],
            "prevention_references": prevention_references,
            "recommendations": structured_output["recommendations"],
            "information_gaps": information_gaps,
            "evidence_index": evidence_index,
            "evidence_refs": structured_output["evidence_refs"],
            "boundary": boundary,
            "recommended_questions": recommended_questions,
            "llm_prompt": "\n".join(prompt_lines).strip(),
            "markdown": structured_output["markdown"],
            "ai_output": structured_output,
            "generated_at": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def _safe_case_context(db: Session, case: Case) -> Dict[str, Any]:
        # Read geographic facts directly: the legacy risk-context builder adds
        # uncalibrated proximity/coverage scores and must not be invoked here.
        has_geo = case.latitude is not None and case.longitude is not None
        context = {
            "case_id": case.id,
            "has_geo": has_geo,
            "nearest": {},
            "risk_conditions": [],
            "prevention_opportunities": [],
            "risk_score": None,
            "scoring_state": "retired",
            "state": "missing_coordinates" if not has_geo else "ready",
            "boundary": "仅为已登记要素的直线邻近参考，不代表道路通达、实际关联或技防覆盖；旧风险评分已停用。",
        }
        if not has_geo:
            return context
        try:
            for kind, asset_types in (
                ("road", ROAD_TYPES), ("village", VILLAGE_TYPES),
                ("production_target", PRODUCTION_TARGET_TYPES), ("tech", TECH_TYPES),
            ):
                nearest = JurisdictionService._nearest_asset(
                    db, case.latitude, case.longitude, asset_types,
                )
                context["nearest"][kind] = JurisdictionService._distance_to_dict(nearest)
        except Exception:
            context["state"] = "unavailable"
            context["nearest"] = {}
            context["boundary"] = "地理上下文读取失败，不能解释为没有周边设施或零风险；旧风险评分已停用。"
        return context

    @staticmethod
    def _case_text_pool(case: Case) -> str:
        # 派生特征、历史模型输出和人工标签不反向充当案件原文。
        values = [
            case.case_number,
            case.location,
            case.case_type,
            case.description,
            case.oil_type,
            case.oil_nature,
            case.facility_type,
            case.security_level,
            case.modus_operandi,
            case.source_type,
            case.source_detail,
            case.vehicle_handling,
            case.oil_handling,
        ]
        return " ".join(_text(value) for value in values if value)

    @staticmethod
    def _practical_readiness(case: Case, quality: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        missing = quality.get("missing_required", []) if quality else []
        missing_fields = {item.get("field") for item in missing if isinstance(item, dict)}
        has_geo = case.latitude is not None and case.longitude is not None
        has_scene_text = bool(case.description or case.modus_operandi or case.security_level)
        has_vehicle_or_tool = bool(case.vehicle_info or case.vehicles or _contains_any(CaseIntelligenceService._case_text_pool(case), [kw for values in TOOL_KEYWORDS.values() for kw in values]))

        def status(ok: bool, partial: bool = False) -> str:
            if ok:
                return "ready"
            return "partial" if partial else "blocked"

        return {
            "spatiotemporal": {
                "status": status(bool(case.occurred_time and has_geo), bool(case.occurred_time or case.location)),
                "blockers": [
                    item for item in [
                        "缺少发生时间" if not case.occurred_time else None,
                        "缺少经纬度" if not has_geo else None,
                    ] if item
                ],
            },
            "condition_similarity": {
                "status": status(has_geo and has_scene_text, has_geo or has_scene_text),
                "blockers": [
                    item for item in [
                        "缺少经纬度，无法关联道路/村屯/井口" if not has_geo else None,
                        "缺少现场环境或作案描述" if not has_scene_text else None,
                    ] if item
                ],
            },
            "scene_factors": {
                "status": status(has_scene_text and has_vehicle_or_tool, has_scene_text),
                "blockers": [
                    item for item in [
                        "缺少车辆类型或工具痕迹" if not has_vehicle_or_tool else None,
                        "缺少案情经过/现场描述" if not has_scene_text else None,
                    ] if item
                ],
            },
            "report": {
                "status": status(len(missing_fields) <= 3, bool(case.description)),
                "blockers": [f"缺少 {len(missing_fields)} 个核心字段"] if len(missing_fields) > 3 else [],
            },
        }

    @staticmethod
    def _aggregate_tags(db: Session, days: int) -> List[Tag]:
        cutoff = datetime.utcnow() - timedelta(days=days) if days > 0 else None
        query = db.query(Case)
        if cutoff is not None:
            query = query.filter(Case.occurred_time >= cutoff)
        cases = query.order_by(Case.occurred_time.desc()).limit(200).all()
        counter: Counter[str] = Counter()
        by_label: Dict[str, Tag] = {}
        for case in cases:
            for tag in CaseIntelligenceService.build_case_tags(db, case)["tags"]:
                counter[tag["label"]] += 1
                by_label[tag["label"]] = tag
        return [
            {**by_label[label], "case_count": count}
            for label, count in counter.most_common(20)
        ]

    @staticmethod
    def _build_reusable_rules(tags: List[Tag], similar_items: List[Dict[str, Any]]) -> List[str]:
        labels = {tag["label"] for tag in tags}
        rules = []
        if "夜间时段" in labels or "凌晨时段" in labels:
            rules.append("夜间/凌晨发生的同类案件，应优先核对道路通达性、照明和技防覆盖情况。")
        if "邻近已登记道路" in labels and "贴近生产目标" in labels:
            rules.append("邻近道路及生产目标仅为直线空间条件，需核实入口与路网后再判断是否可达。")
        if labels & {"皮卡类车辆", "厢货/货车类车辆", "罐车/储油车辆"}:
            rules.append("发现同类型车辆在井场、便道或村屯周边异常停留时，应结合历史车辆工具特征复核。")
        if labels & {"油桶装载痕迹", "软管/管线工具", "抽油泵工具", "暗罐/夹层装载"}:
            rules.append("工具和装载痕迹可作为现场检查重点，尤其关注油桶、软管、油泵和改装储油空间。")
        if similar_items:
            rules.append(f"已召回 {len(similar_items)} 起相似条件案件，建议形成同类案件复盘清单。")
        return rules or ["当前案件标签不足，建议先补充现场环境、车辆类型、工具痕迹和抓获方式。"]

    @staticmethod
    def _next_attention_points(tags: List[Tag]) -> List[str]:
        labels = {tag["label"] for tag in tags}
        points = []
        if "邻近已登记道路" in labels:
            points.append("邻近道路是否通过可信入口连接现场，通行条件是否具备。")
        if "靠近村屯" in labels:
            points.append("村屯周边小路、院落、隐蔽停车点是否与案发点条件接近。")
        if labels & {"近距离技防不足", "技防覆盖待核实"}:
            points.append("同类点位的监控、照明、报警覆盖是否真实可用。")
        if labels & {"油桶装载痕迹", "软管/管线工具", "抽油泵工具"}:
            points.append("类似工具痕迹是否在其他已破案件中反复出现。")
        return points or ["补齐案件字段后再生成更具体的关注要点。"]

    @staticmethod
    def _suggestion(
        suggestion_id: str,
        title: str,
        priority: str,
        action: str,
        reason: List[str],
        evidence: List[Any],
        confidence: float,
    ) -> Dict[str, Any]:
        return {
            "id": suggestion_id,
            "title": title,
            "priority": priority,
            "action": action,
            "reason": reason,
            "evidence": evidence,
            "confidence": round(confidence, 2),
            "output_type": "防控参考草案",
        }

    @staticmethod
    def _get_case(db: Session, case_id: Optional[int]) -> Case:
        if case_id is None:
            raise ValueError("case_id_required")
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError("case_not_found")
        return case

    @staticmethod
    def _structured_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, dict):
            label = value.get("summary") or value.get("title") or value.get("claim") or value.get("action")
            return str(label) if label else str(value)
        return str(value)

    @staticmethod
    def _normalize_structured_inference(item: Dict[str, Any]) -> Dict[str, Any]:
        basis = item.get("basis") or item.get("reason") or []
        if isinstance(basis, str):
            basis = [basis]
        return {
            "claim": CaseIntelligenceService._structured_text(item.get("claim") or item.get("title") or item),
            "basis": [CaseIntelligenceService._structured_text(value) for value in basis if value],
            "confidence": item.get("confidence") or "medium",
        }

    @staticmethod
    def _normalize_structured_recommendation(item: Dict[str, Any]) -> Dict[str, Any]:
        basis = item.get("basis") or item.get("reason") or []
        evidence = item.get("evidence") or item.get("evidence_refs") or []
        if isinstance(basis, str):
            basis = [basis]
        if isinstance(evidence, (str, dict)):
            evidence = [evidence]
        return {
            "title": CaseIntelligenceService._structured_text(item.get("title") or "待复核建议"),
            "action": CaseIntelligenceService._structured_text(item.get("action") or item.get("summary") or item),
            "basis": [CaseIntelligenceService._structured_text(value) for value in basis if value],
            "evidence": [value for value in evidence if value],
            "confidence": item.get("confidence"),
            "priority": item.get("priority") or "medium",
        }

    @staticmethod
    def _normalize_structured_evidence_ref(item: Dict[str, Any]) -> Dict[str, Any]:
        basis = item.get("basis") or []
        if isinstance(basis, str):
            basis = [basis]
        return {
            "id": CaseIntelligenceService._structured_text(item.get("id") or item.get("summary") or "evidence"),
            "kind": CaseIntelligenceService._structured_text(item.get("kind") or "evidence"),
            "summary": CaseIntelligenceService._structured_text(item.get("summary") or item),
            "basis": [CaseIntelligenceService._structured_text(value) for value in basis if value],
        }

    @staticmethod
    def _render_structured_ai_markdown(output: Dict[str, Any]) -> str:
        def lines(items: Iterable[Any], empty: str) -> List[str]:
            values = [CaseIntelligenceService._structured_text(item) for item in items if item]
            return [f"- {item}" for item in values] or [f"- {empty}"]

        markdown = [
            f"# {output.get('title')}",
            "",
            f"- 草稿状态：{output.get('draft_status')}",
            f"- 复核状态：{output.get('review_status')}",
            f"- 模型状态：{output.get('model_status')}",
            "",
            "## 事实依据",
            *lines(output.get("facts", []), "暂无事实依据"),
            "",
            "## 模式推断",
        ]
        for item in output.get("inferences", []):
            markdown.append(f"- {item.get('claim')}（置信度：{item.get('confidence')}）")
            if item.get("basis"):
                markdown.append(f"  - 依据：{CaseIntelligenceService._join_cn(item.get('basis') or [])}")
        if not output.get("inferences"):
            markdown.append("- 暂无模式推断")

        markdown.extend(["", "## 建议与补齐事项"])
        for item in output.get("recommendations", []):
            markdown.append(f"- {item.get('title')}：{item.get('action')}")
            if item.get("basis"):
                markdown.append(f"  - 依据：{CaseIntelligenceService._join_cn(item.get('basis') or [])}")
        if not output.get("recommendations"):
            markdown.append("- 暂无建议或补齐事项")

        markdown.extend([
            "",
            "## 信息缺口",
            *lines(output.get("information_gaps", []), "暂无信息缺口"),
            "",
            "## 证据索引",
        ])
        for item in output.get("evidence_refs", []):
            markdown.append(f"- {item.get('id')}｜{item.get('kind')}：{item.get('summary')}")
            if item.get("basis"):
                markdown.append(f"  - 依据：{CaseIntelligenceService._join_cn(item.get('basis') or [])}")
        if not output.get("evidence_refs"):
            markdown.append("- 暂无证据索引")

        markdown.extend([
            "",
            "## 边界说明",
            *lines(output.get("boundary", []), "仅用于研判辅助，不替代人工复核"),
        ])
        return "\n".join(markdown).strip()

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): CaseIntelligenceService._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [CaseIntelligenceService._json_safe(item) for item in value]
        return value

    @staticmethod
    def _case_brief(case: Optional[Case]) -> Optional[Dict[str, Any]]:
        if not case:
            return None
        return {
            "id": case.id,
            "case_number": case.case_number,
            "occurred_time": case.occurred_time.isoformat() if case.occurred_time else None,
            "location": case.location,
            "latitude": case.latitude,
            "longitude": case.longitude,
            "case_type": case.case_type,
            "facility_type": case.facility_type,
            "oil_nature": case.oil_nature,
            "source_type": case.source_type,
            "quality_score": case.quality_score,
        }

    @staticmethod
    def _vehicle_brief(vehicle: CaseVehicle) -> Dict[str, Any]:
        return {
            "vehicle_type": vehicle.vehicle_type,
            "color": vehicle.color,
            "brand": vehicle.brand,
            "model": vehicle.model,
            "plate_number": vehicle.plate_number,
            "notes": vehicle.notes,
        }

    @staticmethod
    def _tag_overrides(case: Case) -> Dict[str, Any]:
        features = case.features if isinstance(case.features, dict) else {}
        intelligence = features.get("intelligence") if isinstance(features.get("intelligence"), dict) else {}
        overrides = intelligence.get("tag_overrides") if isinstance(intelligence.get("tag_overrides"), dict) else {}
        return overrides

    @staticmethod
    def _time_period(hour: int) -> Dict[str, str]:
        if 0 <= hour <= 5:
            return {"key": "early_morning", "label": "凌晨时段"}
        if 6 <= hour <= 11:
            return {"key": "morning", "label": "上午时段"}
        if 12 <= hour <= 17:
            return {"key": "afternoon", "label": "下午时段"}
        if 18 <= hour <= 23:
            return {"key": "night", "label": "夜间时段"}
        return {"key": "unknown", "label": "未知时段"}

    @staticmethod
    def _counter_items(counter: Counter, label_key: str) -> List[Dict[str, Any]]:
        return [
            {label_key: key, "count": count}
            for key, count in counter.most_common()
        ]

    @staticmethod
    def _capture_lesson(source_type: Optional[str]) -> str:
        if source_type == "技防预警":
            return "技防发现有效，但需要结合现场坐标和设备覆盖核验盲区。"
        if source_type == "群众举报":
            return "群众发现能补足盲区，但案件复盘要继续沉淀可识别的异常车辆和时间条件。"
        if source_type == "巡逻发现":
            return "巡查发现说明现场可被主动发现，后续应把有效发现条件转化为关注规则。"
        if source_type == "公安机关线索":
            return "公安线索适合支撑单案突破，系统侧重点仍是沉淀现场条件和防控经验。"
        return "发现方式未结构化，建议补充抓获或发现来源以沉淀经验。"

    @staticmethod
    def _matched_keyword(text: str, keywords: Iterable[str]) -> str:
        for keyword in keywords:
            if keyword in text:
                return keyword
        return ""

    @staticmethod
    def _vehicle_label(key: str) -> str:
        return {
            "pickup": "皮卡类车辆",
            "van": "厢货/货车类车辆",
            "tanker": "罐车/储油车辆",
            "farm": "农用车辆",
            "unknown_plate": "号牌异常车辆",
        }.get(key, key)

    @staticmethod
    def _tool_label(key: str) -> str:
        return {
            "oil_bucket": "油桶装载痕迹",
            "hose": "软管/管线工具",
            "pump": "抽油泵工具",
            "tank": "暗罐/夹层装载",
            "lock_break": "破锁工具",
        }.get(key, key)

    @staticmethod
    def _weakness_label(key: str) -> str:
        return {
            "lighting_gap": "照明不足",
            "camera_gap": "监控盲区",
            "fence_gap": "围挡薄弱",
            "lock_gap": "锁具薄弱",
            "hidden_space": "隐蔽空间",
        }.get(key, key)

    @staticmethod
    def _join_cn(items: Iterable[Any]) -> str:
        values = [str(item) for item in items if item is not None and str(item)]
        return "、".join(values) if values else "相关要素"
