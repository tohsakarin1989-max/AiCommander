"""涉油案件数智研判服务。

该服务只基于当前项目能够稳定掌握的数据做确定性分析：
案件时间、空间位置、井区/道路/村屯/站库环境、车辆类型、工具痕迹、
现场防护条件、抓获/发现方式和历史相似案件。它不把同人同车多案、
完整团伙结构、完整销赃链条作为核心研判依据。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvidence, CaseVehicle
from app.models.jurisdiction import JurisdictionAsset
from app.services.case_quality_service import CaseQualityService
from app.services.jurisdiction_service import (
    PRODUCTION_TARGET_TYPES,
    ROAD_TYPES,
    TECH_TYPES,
    VILLAGE_TYPES,
    JurisdictionService,
)
from app.utils.geo import haversine_km


Tag = Dict[str, Any]


VEHICLE_KEYWORDS = {
    "pickup": ("皮卡", "皮卡车"),
    "van": ("面包车", "厢货", "厢式", "货车", "箱货"),
    "tanker": ("罐车", "油罐", "储油罐"),
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
        selected_case = CaseIntelligenceService._get_case(db, case_id) if case_id else None
        quality = (
            selected_case.quality_issues
            or CaseQualityService.refresh_case_quality(db, selected_case)
            if selected_case
            else None
        )

        tags = (
            CaseIntelligenceService.build_case_tags(db, selected_case)
            if selected_case
            else {"case_id": None, "tags": CaseIntelligenceService._aggregate_tags(db, days)}
        )
        similar_cases = (
            CaseIntelligenceService.find_similar_cases(db, selected_case.id, days=days, limit=limit)
            if selected_case
            else {"case_id": None, "items": []}
        )
        spatiotemporal = CaseIntelligenceService.analyze_spatiotemporal_patterns(db, days=days)
        scene = (
            CaseIntelligenceService.analyze_scene_factors(db, selected_case.id, days=days)
            if selected_case
            else CaseIntelligenceService.analyze_global_scene_factors(db, days=days)
        )
        area_profiles = CaseIntelligenceService.build_area_risk_profiles(
            db,
            days=days,
            limit=limit,
            radius_km=radius_km,
        )
        suggestions = CaseIntelligenceService.build_prevention_suggestions(
            db,
            case_id=selected_case.id if selected_case else None,
            days=days,
            limit=limit,
        )
        experience_card = (
            CaseIntelligenceService.build_experience_card(db, selected_case.id)
            if selected_case
            else None
        )
        report = CaseIntelligenceService.build_report(
            db,
            case_id=selected_case.id if selected_case else None,
            days=days,
            limit=limit,
        )

        return {
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
        return CaseIntelligenceService._build_llm_context_from_workbench(workbench)

    @staticmethod
    def build_case_tags(db: Session, case: Case) -> Dict[str, Any]:
        context = CaseIntelligenceService._safe_case_context(db, case)
        text_pool = CaseIntelligenceService._case_text_pool(case)
        tags: List[Tag] = []

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
            add("space_road_access", "道路通达", "space", 0.88, [f"距道路 {road['distance_km']:.2f} 公里"])
        if village and village.get("distance_km") is not None and village["distance_km"] <= 1.5:
            add("space_near_village", "靠近村屯", "space", 0.82, [f"距村屯 {village['distance_km']:.2f} 公里"])
        if production and production.get("distance_km") is not None and production["distance_km"] <= 0.5:
            add("space_near_production", "贴近生产目标", "space", 0.9, [f"距生产目标 {production['distance_km']:.2f} 公里"])
        if not village or (village.get("distance_km") is not None and village["distance_km"] > 2.0):
            if _contains_any(text_pool, ("井场", "井口", "井区", "偏远", "荒地")) or case.facility_type:
                add("space_remote_site", "偏远井场", "space", 0.72, ["案情或设施类型显示井场/井口，且近距离村屯信息不足"])
        if not tech:
            add("defense_unknown_tech", "技防覆盖待核实", "defense", 0.55, ["辖区底座未找到近距离技防要素"])
        elif tech.get("distance_km") is not None and tech["distance_km"] > 0.8:
            add("defense_tech_gap", "近距离技防不足", "defense", 0.76, [f"距最近技防点 {tech['distance_km']:.2f} 公里"])

        vehicle_text = " ".join(
            [
                text_pool,
                _text(case.vehicle_info),
                _text([CaseIntelligenceService._vehicle_brief(v) for v in (case.vehicles or [])]),
            ]
        )
        for key, keywords in VEHICLE_KEYWORDS.items():
            if _contains_any(vehicle_text, keywords):
                add(f"vehicle_{key}", CaseIntelligenceService._vehicle_label(key), "vehicle", 0.86, [f"命中车辆描述：{CaseIntelligenceService._matched_keyword(vehicle_text, keywords)}"])

        for key, keywords in TOOL_KEYWORDS.items():
            if _contains_any(text_pool, keywords):
                add(f"tool_{key}", CaseIntelligenceService._tool_label(key), "tool", 0.86, [f"命中工具/装载描述：{CaseIntelligenceService._matched_keyword(text_pool, keywords)}"])

        for key, keywords in WEAKNESS_KEYWORDS.items():
            if _contains_any(text_pool, keywords):
                add(f"weakness_{key}", CaseIntelligenceService._weakness_label(key), "defense", 0.84, [f"命中现场薄弱描述：{CaseIntelligenceService._matched_keyword(text_pool, keywords)}"])
        if case.security_level and any(word in case.security_level for word in ("低", "薄弱", "差")):
            add("weakness_low_security", "安防等级偏低", "defense", 0.82, [f"安防等级：{case.security_level}"])

        if case.source_type in CAPTURE_SOURCE_TAGS:
            key, label = CAPTURE_SOURCE_TAGS[case.source_type]
            add(key, label, "capture", 0.92, [f"线索来源：{case.source_type}"])

        if case.oil_volume is not None:
            if case.oil_volume >= 2:
                add("oil_large_volume", "涉油数量较大", "oil", 0.82, [f"涉油数量 {case.oil_volume:g}"])
            elif case.oil_volume <= 0.5:
                add("oil_small_volume", "小批量转运", "oil", 0.72, [f"涉油数量 {case.oil_volume:g}"])

        overrides = CaseIntelligenceService._tag_overrides(case)
        removed = set(overrides.get("removed_keys") or [])
        tags = [tag for tag in tags if tag["key"] not in removed]
        for added in overrides.get("added") or []:
            if isinstance(added, dict) and added.get("key") and not any(tag["key"] == added["key"] for tag in tags):
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
        case.features = features
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
        base_case = CaseIntelligenceService._get_case(db, case_id)
        base_tags = CaseIntelligenceService.build_case_tags(db, base_case)["tags"]
        cutoff = datetime.utcnow() - timedelta(days=days) if days > 0 else None
        query = db.query(Case).filter(Case.id != base_case.id)
        if cutoff is not None:
            query = query.filter(Case.occurred_time >= cutoff)
        candidates = query.order_by(Case.occurred_time.desc()).limit(500).all()

        items = []
        for other in candidates:
            scored = CaseIntelligenceService._score_case_similarity(db, base_case, base_tags, other)
            if scored["similarity_score"] >= 25:
                items.append(scored)
        items.sort(key=lambda item: item["similarity_score"], reverse=True)

        return {
            "case_id": base_case.id,
            "case_number": base_case.case_number,
            "principle": "相似度按作案条件计算：时间、空间环境、车辆类型、工具痕迹、现场薄弱点和抓获方式；不把同人同车重复出现作为核心依据。",
            "items": items[:limit],
        }

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
    def analyze_scene_factors(db: Session, case_id: int, days: int = 365) -> Dict[str, Any]:
        case = CaseIntelligenceService._get_case(db, case_id)
        tags_payload = CaseIntelligenceService.build_case_tags(db, case)
        tags = tags_payload["tags"]
        similar = CaseIntelligenceService.find_similar_cases(db, case_id, days=days, limit=8)
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
        cutoff = datetime.utcnow() - timedelta(days=days) if days > 0 else None
        case_query = db.query(Case).filter(Case.latitude.isnot(None), Case.longitude.isnot(None))
        if cutoff is not None:
            case_query = case_query.filter(Case.occurred_time >= cutoff)
        cases = case_query.all()
        assets = db.query(JurisdictionAsset).filter(
            JurisdictionAsset.status == "active",
            JurisdictionAsset.latitude.isnot(None),
            JurisdictionAsset.longitude.isnot(None),
        ).all()

        profiles = []
        for asset in assets:
            nearby = []
            for case in cases:
                distance = haversine_km(asset.latitude, asset.longitude, case.latitude, case.longitude)
                if distance <= radius_km:
                    nearby.append((case, distance))
            if not nearby and asset.asset_type not in PRODUCTION_TARGET_TYPES:
                continue
            tag_counter: Counter[str] = Counter()
            hour_counter: Counter[int] = Counter()
            for case, _ in nearby:
                if case.occurred_time:
                    hour_counter[case.occurred_time.hour] += 1
                for tag in CaseIntelligenceService.build_case_tags(db, case)["tags"]:
                    tag_counter[tag["label"]] += 1
            score = min(100, (asset.risk_level or 1) * 10 + len(nearby) * 24)
            reasons = []
            if nearby:
                reasons.append(f"{radius_km:g} 公里范围内关联已破案件 {len(nearby)} 起。")
            if asset.asset_type in PRODUCTION_TARGET_TYPES:
                reasons.append("该要素属于生产目标，适合作为风险画像对象。")
            if not asset.verified:
                score = min(100, score + 6)
                reasons.append("底座要素尚未核验，研判使用前需确认名称和坐标。")
            if not reasons:
                reasons.append("暂无历史案件关联，维持基础关注并补充周边条件。")

            profiles.append({
                "asset": CaseIntelligenceService._asset_brief(asset),
                "risk_score": round(score, 1),
                "risk_level": CaseIntelligenceService._risk_level(score),
                "case_count": len(nearby),
                "related_cases": [
                    {
                        **CaseIntelligenceService._case_brief(case),
                        "distance_km": round(distance, 3),
                    }
                    for case, distance in sorted(nearby, key=lambda item: item[1])[:8]
                ],
                "common_tags": CaseIntelligenceService._counter_items(tag_counter, "label")[:8],
                "top_hours": CaseIntelligenceService._counter_items(hour_counter, "hour")[:5],
                "risk_reasons": reasons,
            })

        if not profiles and cases:
            profiles = CaseIntelligenceService._fallback_case_grid_profiles(cases)

        profiles.sort(key=lambda item: (item["risk_score"], item["case_count"]), reverse=True)
        return {
            "days": days,
            "radius_km": radius_km,
            "profile_count": len(profiles),
            "items": profiles[:limit],
        }

    @staticmethod
    def build_prevention_suggestions(
        db: Session,
        case_id: Optional[int] = None,
        days: int = 365,
        limit: int = 8,
    ) -> Dict[str, Any]:
        suggestions: List[Dict[str, Any]] = []
        spatiotemporal = CaseIntelligenceService.analyze_spatiotemporal_patterns(db, days=days)
        area_profiles = CaseIntelligenceService.build_area_risk_profiles(db, days=days, limit=limit)

        if case_id is not None:
            case = CaseIntelligenceService._get_case(db, case_id)
            quality = case.quality_issues or CaseQualityService.refresh_case_quality(db, case)
            tags = CaseIntelligenceService.build_case_tags(db, case)["tags"]
            similar = CaseIntelligenceService.find_similar_cases(db, case_id, days=days, limit=limit)
            scene = CaseIntelligenceService.analyze_scene_factors(db, case_id, days=days)

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
                missing = [item.get("label") for item in quality["missing_required"][:5] if item.get("label")]
                suggestions.append(CaseIntelligenceService._suggestion(
                    "data_completion",
                    "先补齐影响研判的案件字段",
                    "medium",
                    f"优先补齐 {CaseIntelligenceService._join_cn(missing)}，否则相似条件和风险画像会失真。",
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

        for profile in area_profiles.get("items", [])[:3]:
            suggestions.append(CaseIntelligenceService._suggestion(
                f"area_{profile['asset']['id']}",
                f"关注区域：{profile['asset']['name']}",
                "high" if profile["risk_score"] >= 70 else "medium",
                "该区域具备历史案件或相似现场条件，建议纳入人工研判关注清单。",
                profile["risk_reasons"],
                [case["case_number"] for case in profile.get("related_cases", [])[:5]],
                min(0.9, 0.55 + profile["risk_score"] / 200),
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
            "boundary": "这些是防控参考草案，不自动派发巡逻任务，也不替代人工研判结论。",
        }

    @staticmethod
    def build_experience_card(db: Session, case_id: int) -> Dict[str, Any]:
        case = CaseIntelligenceService._get_case(db, case_id)
        tags_payload = CaseIntelligenceService.build_case_tags(db, case)
        scene = CaseIntelligenceService.analyze_scene_factors(db, case_id)
        tags = tags_payload["tags"]
        conditions = [tag["label"] for tag in tags if tag["category"] in {"time", "space"}]
        vehicle_tools = [tag["label"] for tag in tags if tag["category"] in {"vehicle", "tool"}]
        weaknesses = [tag["label"] for tag in tags if tag["category"] == "defense"]
        capture_tags = [tag["label"] for tag in tags if tag["category"] == "capture"]

        return {
            "case_id": case.id,
            "case_number": case.case_number,
            "summary": case.description or case.location or case.case_type or "未填写案情摘要",
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
                "spatial_context": tags_payload.get("context"),
            },
        }

    @staticmethod
    def build_report(
        db: Session,
        case_id: Optional[int] = None,
        days: int = 365,
        limit: int = 8,
    ) -> Dict[str, Any]:
        selected_case = CaseIntelligenceService._get_case(db, case_id) if case_id else None
        spatiotemporal = CaseIntelligenceService.analyze_spatiotemporal_patterns(db, days=days)
        suggestions = CaseIntelligenceService.build_prevention_suggestions(db, case_id=case_id, days=days, limit=limit)
        area_profiles = CaseIntelligenceService.build_area_risk_profiles(db, days=days, limit=limit)
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
            experience = CaseIntelligenceService.build_experience_card(db, selected_case.id)
            tags_payload = CaseIntelligenceService.build_case_tags(db, selected_case)
            tag_labels = [tag["label"] for tag in tags_payload.get("tags", [])[:8]]
            quality = selected_case.quality_issues or CaseQualityService.refresh_case_quality(db, selected_case)
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
                "items": missing_fields or ["暂无明显必填字段缺口。"],
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
                "items": spatiotemporal.get("insights", []),
            })
            sections.append({
                "title": "四、信息缺口",
                "type": "gaps",
                "items": ["未选择具体案件时，仅能输出全局趋势，不能形成单案复盘结论。"],
            })

        area_items = [
            f"{profile['asset']['name']}：{'; '.join(profile['risk_reasons'][:2])}"
            for profile in area_profiles.get("items", [])[:5]
        ]
        pattern_section = next((section for section in sections if section.get("type") == "patterns"), None)
        if pattern_section is not None:
            pattern_section["items"].extend(
                [f"重点关注区域：{item}" for item in area_items]
                or ["辖区底座或案件坐标不足，暂不能形成区域画像。"]
            )
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

        return {
            "title": title,
            "generated_at": datetime.utcnow().isoformat(),
            "case_id": case_id,
            "days": days,
            "sections": sections,
            "markdown": "\n".join(markdown).strip(),
        }

    @staticmethod
    def _build_llm_context_from_workbench(workbench: Dict[str, Any]) -> Dict[str, Any]:
        selected_case = workbench.get("selected_case")
        scope = workbench.get("scope") or {}
        tags = workbench.get("feature_tags", {}).get("tags", []) or []
        similar_items = workbench.get("similar_cases", {}).get("items", []) or []
        suggestions = workbench.get("prevention_suggestions", {}).get("items", []) or []
        area_profiles = workbench.get("area_profiles", {}).get("items", []) or []
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
                    "claim": f"{case_number} 与当前案件具备相似作案条件，分值 {item.get('similarity_score')}",
                    "basis": item.get("reasons", [])[:4],
                    "confidence": "high" if item.get("similarity_score", 0) >= 70 else "medium",
                })
        for profile in area_profiles[:4]:
            asset = profile.get("asset", {})
            pattern_inferences.append({
                "claim": f"{asset.get('name', '未命名区域')} 可作为区域画像关注对象",
                "basis": profile.get("risk_reasons", [])[:4],
                "confidence": "high" if profile.get("risk_score", 0) >= 70 else "medium",
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

        information_gaps: List[str] = []
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
            })
        for item in similar_items[:5]:
            case_number = item.get("case", {}).get("case_number")
            evidence_index.append({
                "id": f"similar:{case_number}",
                "kind": "similar_case",
                "summary": f"{case_number}，相似度 {item.get('similarity_score')}",
                "basis": item.get("reasons", []),
            })
        for profile in area_profiles[:5]:
            asset = profile.get("asset", {})
            evidence_index.append({
                "id": f"area:{asset.get('id')}",
                "kind": "area_profile",
                "summary": f"{asset.get('name')}，风险画像分 {profile.get('risk_score')}",
                "basis": profile.get("risk_reasons", []),
            })

        boundary = [
            "只基于已录入案件、辖区底座和结构化研判结果回答。",
            "必须区分事实依据、模式推断、防控参考和信息缺口。",
            "不得把防控参考写成已执行任务，不自动派发巡逻或跨部门处置。",
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

        return {
            "scope": scope,
            "selected_case": selected_case,
            "system_boundary": boundary,
            "facts": facts,
            "pattern_inferences": pattern_inferences,
            "prevention_references": prevention_references,
            "information_gaps": information_gaps,
            "evidence_index": evidence_index,
            "recommended_questions": recommended_questions,
            "llm_prompt": "\n".join(prompt_lines).strip(),
            "generated_at": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def _score_case_similarity(
        db: Session,
        base_case: Case,
        base_tags: List[Tag],
        other: Case,
    ) -> Dict[str, Any]:
        other_tags = CaseIntelligenceService.build_case_tags(db, other)["tags"]
        base_by_category = CaseIntelligenceService._tag_sets_by_category(base_tags)
        other_by_category = CaseIntelligenceService._tag_sets_by_category(other_tags)
        score = 0.0
        reasons: List[str] = []
        components: Dict[str, float] = {}

        time_score = CaseIntelligenceService._tag_overlap_score(base_by_category, other_by_category, {"time"})
        if time_score:
            components["time"] = round(time_score * 18, 2)
            score += components["time"]
            reasons.append("发案时间或时段标签相似")
        if base_case.occurred_time and other.occurred_time:
            hour_diff = abs(base_case.occurred_time.hour - other.occurred_time.hour)
            hour_diff = min(hour_diff, 24 - hour_diff)
            if hour_diff <= 2:
                score += 8
                components["hour_near"] = 8
                reasons.append(f"发生小时接近，相差 {hour_diff} 小时")

        space_score = CaseIntelligenceService._tag_overlap_score(base_by_category, other_by_category, {"space", "defense"})
        if space_score:
            components["space_condition"] = round(space_score * 30, 2)
            score += components["space_condition"]
            reasons.append("空间环境或现场薄弱点相似")
        if (
            base_case.latitude is not None and base_case.longitude is not None
            and other.latitude is not None and other.longitude is not None
        ):
            distance = haversine_km(base_case.latitude, base_case.longitude, other.latitude, other.longitude)
            geo_score = max(0.0, 1 - distance / 8) * 18
            if geo_score > 0:
                score += geo_score
                components["geo_distance"] = round(geo_score, 2)
                reasons.append(f"空间距离 {distance:.2f} 公里")

        vehicle_tool_score = CaseIntelligenceService._tag_overlap_score(base_by_category, other_by_category, {"vehicle", "tool"})
        if vehicle_tool_score:
            components["vehicle_tool"] = round(vehicle_tool_score * 22, 2)
            score += components["vehicle_tool"]
            reasons.append("车辆类型或工具痕迹相似")

        field_matches = []
        for field, label in (
            ("case_type", "案件类型"),
            ("facility_type", "设施类型"),
            ("oil_nature", "油品性质"),
            ("source_type", "发现方式"),
        ):
            left = getattr(base_case, field, None)
            right = getattr(other, field, None)
            if left and right and left == right:
                field_matches.append(label)
        if field_matches:
            field_score = min(14, len(field_matches) * 4)
            score += field_score
            components["structured_fields"] = field_score
            reasons.append(f"结构化字段一致：{CaseIntelligenceService._join_cn(field_matches)}")

        duplicate_warnings = CaseIntelligenceService._duplicate_anchor_warnings(base_case, other)
        if duplicate_warnings:
            reasons.append("检测到同人/同车锚点，优先按重复录入或同案拆分核验，不作为多案规律。")

        return {
            "case": CaseIntelligenceService._case_brief(other),
            "similarity_score": round(min(score, 100), 1),
            "components": components,
            "reasons": reasons or ["相似度较低，仅作为弱参考。"],
            "duplicate_warnings": duplicate_warnings,
            "shared_tags": sorted(
                list({tag["label"] for tag in base_tags} & {tag["label"] for tag in other_tags})
            ),
        }

    @staticmethod
    def _safe_case_context(db: Session, case: Case) -> Dict[str, Any]:
        try:
            return JurisdictionService.build_case_risk_context(db, case.id)
        except Exception:
            return {
                "case_id": case.id,
                "has_geo": case.latitude is not None and case.longitude is not None,
                "nearest": {},
                "risk_conditions": [],
                "prevention_opportunities": [],
                "risk_score": 0,
            }

    @staticmethod
    def _case_text_pool(case: Case) -> str:
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
            _text(case.involved_items),
            _text(case.features),
        ]
        return " ".join(_text(value) for value in values if value)

    @staticmethod
    def _tag_sets_by_category(tags: List[Tag]) -> Dict[str, set[str]]:
        result: Dict[str, set[str]] = defaultdict(set)
        for tag in tags:
            result[tag.get("category") or "unknown"].add(tag.get("key") or tag.get("label"))
        return result

    @staticmethod
    def _tag_overlap_score(
        left: Dict[str, set[str]],
        right: Dict[str, set[str]],
        categories: set[str],
    ) -> float:
        scores = []
        for category in categories:
            l_values = left.get(category) or set()
            r_values = right.get(category) or set()
            if l_values and r_values:
                scores.append(len(l_values & r_values) / len(l_values | r_values))
        return sum(scores) / len(scores) if scores else 0.0

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
        if "道路通达" in labels and ("偏远井场" in labels or "贴近生产目标" in labels):
            rules.append("道路可直达且贴近生产目标的偏远点位，应作为相似条件关注对象。")
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
        if "道路通达" in labels:
            points.append("相似区域是否同样具备车辆快速接近和撤离条件。")
        if "靠近村屯" in labels:
            points.append("村屯周边小路、院落、隐蔽停车点是否与案发点条件接近。")
        if labels & {"近距离技防不足", "技防覆盖待核实"}:
            points.append("同类点位的监控、照明、报警覆盖是否真实可用。")
        if labels & {"油桶装载痕迹", "软管/管线工具", "抽油泵工具"}:
            points.append("类似工具痕迹是否在其他已破案件中反复出现。")
        return points or ["补齐案件字段后再生成更具体的关注要点。"]

    @staticmethod
    def _duplicate_anchor_warnings(left: Case, right: Case) -> List[str]:
        warnings = []
        left_plates = CaseIntelligenceService._case_plate_set(left)
        right_plates = CaseIntelligenceService._case_plate_set(right)
        if left_plates and right_plates and left_plates & right_plates:
            warnings.append(f"相同车牌：{CaseIntelligenceService._join_cn(sorted(left_plates & right_plates))}")
        left_persons = CaseIntelligenceService._case_person_set(left)
        right_persons = CaseIntelligenceService._case_person_set(right)
        if left_persons and right_persons and left_persons & right_persons:
            warnings.append(f"相同人员：{CaseIntelligenceService._join_cn(sorted(left_persons & right_persons))}")
        return warnings

    @staticmethod
    def _case_plate_set(case: Case) -> set[str]:
        plates = set()
        for vehicle in case.vehicles or []:
            if vehicle.plate_number:
                plates.add(vehicle.plate_number)
        if isinstance(case.vehicle_info, dict):
            plate = case.vehicle_info.get("plate_number") or case.vehicle_info.get("plate")
            if plate:
                plates.add(str(plate))
        elif isinstance(case.vehicle_info, list):
            for item in case.vehicle_info:
                if isinstance(item, dict):
                    plate = item.get("plate_number") or item.get("plate")
                    if plate:
                        plates.add(str(plate))
        return plates

    @staticmethod
    def _case_person_set(case: Case) -> set[str]:
        persons = set()
        for person in case.persons or []:
            if person.name:
                persons.add(person.name)
            elif person.id_number:
                persons.add(person.id_number)
        if isinstance(case.involved_persons, list):
            for item in case.involved_persons:
                if isinstance(item, dict):
                    value = item.get("name") or item.get("id_number")
                    if value:
                        persons.add(str(value))
        return persons

    @staticmethod
    def _fallback_case_grid_profiles(cases: List[Case]) -> List[Dict[str, Any]]:
        grid: Dict[Tuple[int, int], List[Case]] = defaultdict(list)
        for case in cases:
            grid[(round(case.latitude, 2), round(case.longitude, 2))].append(case)
        profiles = []
        for index, ((lat, lon), grid_cases) in enumerate(grid.items(), start=1):
            score = min(100, 25 + len(grid_cases) * 20)
            profiles.append({
                "asset": {
                    "id": f"grid-{index}",
                    "name": f"案件热点网格 {lat},{lon}",
                    "asset_type": "case_grid",
                    "latitude": lat,
                    "longitude": lon,
                },
                "risk_score": score,
                "risk_level": CaseIntelligenceService._risk_level(score),
                "case_count": len(grid_cases),
                "related_cases": [CaseIntelligenceService._case_brief(case) for case in grid_cases[:8]],
                "common_tags": [],
                "top_hours": [],
                "risk_reasons": ["辖区底座不足，暂按案件坐标网格形成临时画像。"],
            })
        return profiles

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
    def _asset_brief(asset: JurisdictionAsset) -> Dict[str, Any]:
        return {
            "id": asset.id,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "geometry_type": asset.geometry_type,
            "latitude": asset.latitude,
            "longitude": asset.longitude,
            "risk_level": asset.risk_level,
            "verified": asset.verified,
            "tags": asset.tags or [],
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
    def _risk_level(score: float) -> str:
        if score >= 80:
            return "high"
        if score >= 55:
            return "medium"
        return "low"

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
