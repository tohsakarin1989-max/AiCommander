"""高产井周边风险迹象聚合、关注热力与大模型研判。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.ai.utils import parse_llm_json_response
from app.models.case import Case
from app.models.event import Event, EVENT_TYPES
from app.models.jurisdiction import JurisdictionAsset
from app.services.agent_service import AgentService
from app.services.system_config_service import SystemConfigService
from app.utils.geo import haversine_km
from app.utils.logger import logger


OBSERVATION_EVENT_TYPES = {
    "vehicle_trace",
    "oil_trace",
    "footprint_trace",
    "tool_trace",
    "facility_anomaly",
    "defense_outage",
    "suspect_activity",
    "damage_found",
}

OBSERVATION_WEIGHTS = {
    "vehicle_trace": 78,
    "oil_trace": 72,
    "footprint_trace": 58,
    "tool_trace": 84,
    "facility_anomaly": 76,
    "defense_outage": 54,
    "suspect_activity": 48,
    "damage_found": 68,
}

OBSERVATION_HALF_LIFE_DAYS = {
    "vehicle_trace": 3,
    "oil_trace": 7,
    "footprint_trace": 3,
    "tool_trace": 10,
    "facility_anomaly": 14,
    "defense_outage": 7,
    "suspect_activity": 5,
    "damage_found": 14,
}

TECH_TYPES = {"camera", "lighting", "alarm", "fence", "checkpoint", "blind_spot"}
PRODUCTION_KEYS = (
    "daily_output",
    "production_rate",
    "oil_output",
    "日产量",
    "日产油",
    "产量",
)
REGION_KEYS = ("region", "area", "operation_area", "作业区", "区块", "区域")
AI_SNAPSHOT_KEY = "well_attention_ai_snapshot"
ATTENTION_WEIGHTS = {
    "recent_observations": 0.40,
    "defense_gaps": 0.20,
    "asset_exposure": 0.20,
    "historical_cases": 0.20,
}


class WellAttentionService:
    """把井点、现场痕迹、历史案件和防控覆盖转成可解释关注度。"""

    @staticmethod
    def build_overview(
        db: Session,
        days_back: int = 30,
        radius_km: float = 1.0,
        include_cached_ai: bool = True,
        operational_area_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days_back)
        history_cutoff = now - timedelta(days=365)

        wells_query = db.query(JurisdictionAsset).filter(
            JurisdictionAsset.asset_type == "well",
            JurisdictionAsset.status == "active",
            JurisdictionAsset.latitude.isnot(None),
            JurisdictionAsset.longitude.isnot(None),
        )
        observations_query = db.query(Event).filter(
            Event.event_type.in_(OBSERVATION_EVENT_TYPES),
            Event.occurred_time >= cutoff,
        )
        cases_query = db.query(Case).filter(
            Case.occurred_time >= history_cutoff,
            Case.latitude.isnot(None),
            Case.longitude.isnot(None),
        )
        tech_assets_query = db.query(JurisdictionAsset).filter(
            JurisdictionAsset.asset_type.in_(TECH_TYPES),
            JurisdictionAsset.status == "active",
            JurisdictionAsset.latitude.isnot(None),
            JurisdictionAsset.longitude.isnot(None),
        )
        if operational_area_id is not None:
            wells_query = wells_query.filter(
                JurisdictionAsset.operational_area_id == operational_area_id
            )
            observations_query = observations_query.filter(
                Event.operational_area_id == operational_area_id
            )
            cases_query = cases_query.filter(Case.operational_area_id == operational_area_id)
            tech_assets_query = tech_assets_query.filter(
                JurisdictionAsset.operational_area_id == operational_area_id
            )
        wells = wells_query.all()
        observations = observations_query.all()
        cases = cases_query.all()
        tech_assets = tech_assets_query.all()

        outputs = [
            value
            for value in (WellAttentionService._production_output(well) for well in wells)
            if value is not None and value > 0
        ]
        max_output = max(outputs) if outputs else None
        assigned = WellAttentionService._assign_observations(wells, observations, radius_km)
        profiles = [
            WellAttentionService._build_well_profile(
                well=well,
                observations=assigned.get(well.id, []),
                cases=cases,
                tech_assets=tech_assets,
                now=now,
                radius_km=radius_km,
                max_output=max_output,
            )
            for well in wells
        ]
        profiles.sort(key=lambda item: (item["attention_score"], item["signal_count"]), reverse=True)

        serialized_observations = [
            item
            for profile in profiles
            for item in profile["observations"]
        ]
        serialized_observations.sort(key=lambda item: item.get("occurred_time") or "", reverse=True)
        regions = WellAttentionService._build_regions(profiles)
        trend = WellAttentionService._build_signal_trend(serialized_observations, now)
        verified_wells = sum(1 for well in wells if well.verified)
        production_ready = sum(1 for profile in profiles if profile["production_output"] is not None)

        overview = {
            "generated_at": now.isoformat(),
            "operational_area_id": operational_area_id,
            "days_back": days_back,
            "radius_km": radius_km,
            "summary": {
                "total_wells": len(wells),
                "high_production_wells": sum(1 for profile in profiles if profile["is_high_production"]),
                "attention_wells": sum(1 for profile in profiles if profile["attention_score"] >= 45),
                "high_attention_wells": sum(1 for profile in profiles if profile["attention_score"] >= 70),
                "recent_observations": len(serialized_observations),
                "attention_regions": sum(1 for region in regions if region["attention_score"] >= 45),
                "verified_well_rate": round(verified_wells / len(wells) * 100, 1) if wells else 0,
                "production_data_rate": round(production_ready / len(wells) * 100, 1) if wells else 0,
            },
            "weights": {
                **ATTENTION_WEIGHTS,
            },
            "wells": profiles,
            "regions": regions,
            "observations": serialized_observations[:100],
            "signal_trend": trend,
            "data_gaps": WellAttentionService._overview_gaps(wells, profiles, serialized_observations),
            "boundary": [
                "关注度表示井点周边风险迹象和防控条件的综合强弱，不是犯罪预测。",
                "大模型输出属于研判辅助建议，必须结合现场复核后使用。",
                "系统不自动派发任务，不把未复核痕迹表达为已发生案件。",
            ],
        }
        cached_ai = (
            WellAttentionService._load_cached_ai(db)
            if include_cached_ai and operational_area_id is None
            else None
        )
        overview["ai_analysis"] = (
            cached_ai
            if cached_ai
            and cached_ai.get("source_signature") == WellAttentionService._overview_signature(overview)
            else None
        )
        return overview

    @staticmethod
    async def refresh_ai_analysis(
        db: Session,
        days_back: int = 30,
        radius_km: float = 1.0,
    ) -> Dict[str, Any]:
        overview = WellAttentionService.build_overview(
            db,
            days_back=days_back,
            radius_km=radius_km,
            include_cached_ai=False,
        )
        fallback = WellAttentionService._fallback_ai_analysis(overview)
        if not overview["wells"] or not overview["observations"]:
            WellAttentionService._store_ai(db, fallback)
            overview["ai_analysis"] = fallback
            return overview

        llm = AgentService._get_llm(db)
        if llm is None:
            WellAttentionService._store_ai(db, fallback)
            overview["ai_analysis"] = fallback
            return overview

        compact_context = {
            "summary": overview["summary"],
            "regions": overview["regions"][:8],
            "wells": [
                {
                    key: well[key]
                    for key in (
                        "asset_id",
                        "name",
                        "region",
                        "attention_score",
                        "attention_level",
                        "signal_count",
                        "signal_types",
                        "score_components",
                        "reasons",
                        "data_gaps",
                    )
                }
                for well in overview["wells"][:12]
            ],
            "observations": overview["observations"][:20],
        }
        prompt = f"""你是涉油区域风险迹象研判助手。请只根据输入事实生成领导大屏使用的关注研判 JSON。
必须遵守：
1. 只能表达“建议关注、需要复核”，不得声称将要发生案件，不得预测下一起案件位置；
2. 区分事实依据、研判推断、布置建议和信息缺口；
3. 不做人员画像，不自动派发巡逻或处置任务；
4. 每个结论必须引用井点ID、事件ID或明确的数据缺口；
5. 数据不足时降低 confidence，不能补写不存在的车辆、人员、案件或设施。

输出 JSON：
{{
  "attention_regions": [{{"name":"", "level":"high|medium|watch", "confidence":0.0, "reasons":[], "evidence_refs":[]}}],
  "attention_wells": [{{"asset_id":1, "name":"", "level":"high|medium|watch", "confidence":0.0, "reasons":[], "information_gaps":[]}}],
  "deployment_suggestions": [{{"target":"", "priority":"high|medium|low", "action":"", "basis":""}}],
  "boundary": []
}}

输入：{json.dumps(compact_context, ensure_ascii=False, default=str)}
"""
        try:
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            payload, error = parse_llm_json_response(content, {})
            if error or not payload:
                raise ValueError(error or "empty_model_payload")
            analysis = WellAttentionService._sanitize_ai_analysis(payload, overview)
            analysis["model_status"] = "llm_success"
        except Exception as exc:
            logger.warning("井点关注研判模型调用失败，使用规则降级: %s", exc)
            analysis = fallback
            analysis["model_status"] = "llm_failed_fallback"
            analysis["model_error"] = str(exc)[:200]

        WellAttentionService._store_ai(db, analysis)
        overview["ai_analysis"] = analysis
        return overview

    @staticmethod
    def _build_well_profile(
        well: JurisdictionAsset,
        observations: List[Dict[str, Any]],
        cases: Iterable[Case],
        tech_assets: Iterable[JurisdictionAsset],
        now: datetime,
        radius_km: float,
        max_output: Optional[float],
    ) -> Dict[str, Any]:
        output = WellAttentionService._production_output(well)
        is_high = WellAttentionService._is_high_production(well, output, max_output)
        exposure_score = 0.0
        if output is not None and max_output:
            exposure_score = min(100.0, 30.0 + 70.0 * output / max_output)
        elif is_high:
            exposure_score = 85.0

        signal_raw = sum(item["weighted_score"] for item in observations)
        signal_score = min(100.0, 100.0 * (1.0 - math.exp(-signal_raw / 60.0)))
        history_items = []
        history_raw = 0.0
        for case in cases:
            distance = haversine_km(well.latitude, well.longitude, case.latitude, case.longitude)
            if distance > radius_km:
                continue
            age_days = WellAttentionService._age_days(case.occurred_time, now)
            contribution = 32.0 * math.exp(-math.log(2) * age_days / 180.0)
            history_raw += contribution
            history_items.append({
                "case_id": case.id,
                "case_number": case.case_number,
                "distance_km": round(distance, 3),
                "occurred_time": case.occurred_time.isoformat() if case.occurred_time else None,
            })
        history_score = min(100.0, 100.0 * (1.0 - math.exp(-history_raw / 90.0)))

        nearby_tech = []
        blind_spots = []
        for asset in tech_assets:
            distance = haversine_km(well.latitude, well.longitude, asset.latitude, asset.longitude)
            if distance > 0.5:
                continue
            brief = {"asset_id": asset.id, "name": asset.name, "type": asset.asset_type, "distance_km": round(distance, 3)}
            if asset.asset_type == "blind_spot":
                blind_spots.append(brief)
            else:
                nearby_tech.append(brief)
        defense_status = str((well.attributes or {}).get("defense_coverage_status") or "").strip().lower()
        if blind_spots:
            defense_score = min(100.0, 70.0 + len(blind_spots) * 10.0)
        elif defense_status in {"uncovered", "verified_gap", "未覆盖", "明确缺口"}:
            defense_score = 90.0
        elif defense_status in {"partial", "部分覆盖"}:
            defense_score = 55.0
        elif defense_status in {"covered", "已覆盖"} or nearby_tech:
            defense_score = max(5.0, 35.0 - min(len(nearby_tech), 3) * 10.0)
        else:
            defense_score = 0.0

        attention_score = round(
            signal_score * ATTENTION_WEIGHTS["recent_observations"]
            + defense_score * ATTENTION_WEIGHTS["defense_gaps"]
            + exposure_score * ATTENTION_WEIGHTS["asset_exposure"]
            + history_score * ATTENTION_WEIGHTS["historical_cases"],
            1,
        )
        reasons = []
        if observations:
            reasons.append(f"近30天关联风险迹象 {len(observations)} 条。")
        if is_high:
            reasons.append("井点被标记为高产井或产量处于当前井点高位。")
        if blind_spots:
            reasons.append(f"500米内登记监控盲区 {len(blind_spots)} 处。")
        elif defense_score >= 55:
            reasons.append("井点已明确登记为防控未覆盖或部分覆盖。")
        if history_items:
            reasons.append(f"1公里内近一年关联案件 {len(history_items)} 起。")
        if not reasons:
            reasons.append("暂无明显风险迹象，当前仅保留基础监测。")

        data_gaps = []
        if output is None:
            data_gaps.append("缺少井点产量指标，无法确认高产井暴露度。")
        if not well.verified:
            data_gaps.append("井点坐标尚未人工校验。")
        if not nearby_tech and not blind_spots and not defense_status:
            data_gaps.append("缺少井点周边防控覆盖核验结果，不能据此判定为监控盲区。")

        return {
            "asset_id": well.id,
            "name": well.name,
            "latitude": well.latitude,
            "longitude": well.longitude,
            "region": WellAttentionService._asset_region(well),
            "production_output": output,
            "is_high_production": is_high,
            "attention_score": attention_score,
            "attention_level": WellAttentionService._attention_level(attention_score),
            "signal_count": len(observations),
            "signal_types": sorted({item["observation_type"] for item in observations}),
            "score_components": {
                "recent_observations": round(signal_score, 1),
                "defense_gaps": round(defense_score, 1),
                "asset_exposure": round(exposure_score, 1),
                "historical_cases": round(history_score, 1),
            },
            "reasons": reasons,
            "data_gaps": data_gaps,
            "nearby_tech": nearby_tech,
            "blind_spots": blind_spots,
            "related_cases": history_items,
            "observations": observations,
        }

    @staticmethod
    def _assign_observations(
        wells: List[JurisdictionAsset],
        observations: List[Event],
        radius_km: float,
    ) -> Dict[int, List[Dict[str, Any]]]:
        well_by_id = {well.id: well for well in wells}
        assigned: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        now = datetime.now(timezone.utc)
        for event in observations:
            if (event.review_status or "pending_review") == "rejected":
                continue
            well = well_by_id.get(event.related_asset_id)
            distance = 0.0 if well else None
            if well is None and event.latitude is not None and event.longitude is not None:
                candidates = [
                    (candidate, haversine_km(event.latitude, event.longitude, candidate.latitude, candidate.longitude))
                    for candidate in wells
                ]
                if candidates:
                    well, distance = min(candidates, key=lambda item: item[1])
                    if distance > radius_km:
                        well = None
            if well is None:
                continue

            observation_type = event.observation_type or event.event_type
            base = OBSERVATION_WEIGHTS.get(observation_type, OBSERVATION_WEIGHTS.get(event.event_type, 45))
            severity = max(1, min(5, event.severity or 3))
            severity_factor = 0.65 + (severity - 1) * 0.15
            confidence = max(0.0, min(1.0, event.confidence_score if event.confidence_score is not None else 0.65))
            review_factor = 1.0 if event.review_status == "confirmed" else 0.75
            age_days = WellAttentionService._age_days(event.occurred_time, now)
            half_life = OBSERVATION_HALF_LIFE_DAYS.get(observation_type, 7)
            time_factor = math.exp(-math.log(2) * age_days / half_life)
            freshness_factor = {"fresh": 1.0, "recent": 0.8, "unknown": 0.55}.get(event.freshness or "unknown", 0.65)
            distance_factor = 1.0 if event.related_asset_id == well.id else max(0.25, 1.0 - (distance or 0.0) / radius_km)
            weighted_score = base * severity_factor * confidence * review_factor * time_factor * freshness_factor * distance_factor
            assigned[well.id].append({
                "event_id": event.id,
                "event_number": event.event_number,
                "observation_type": observation_type,
                "observation_label": EVENT_TYPES.get(observation_type, EVENT_TYPES.get(event.event_type, observation_type)),
                "title": event.title or EVENT_TYPES.get(event.event_type, event.event_type),
                "description": event.description,
                "occurred_time": event.occurred_time.isoformat() if event.occurred_time else None,
                "latitude": event.latitude if event.latitude is not None else well.latitude,
                "longitude": event.longitude if event.longitude is not None else well.longitude,
                "severity": severity,
                "freshness": event.freshness or "unknown",
                "confidence_score": round(confidence, 2),
                "review_status": event.review_status or "pending_review",
                "distance_km": round(distance or 0.0, 3),
                "weighted_score": round(weighted_score, 2),
                "related_asset_id": well.id,
                "related_asset_name": well.name,
            })
        return assigned

    @staticmethod
    def _build_regions(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for profile in profiles:
            grouped[profile["region"]].append(profile)
        regions = []
        for name, items in grouped.items():
            score = round(max(item["attention_score"] for item in items) * 0.7 + sum(item["attention_score"] for item in items) / len(items) * 0.3, 1)
            regions.append({
                "name": name,
                "attention_score": score,
                "attention_level": WellAttentionService._attention_level(score),
                "well_count": len(items),
                "attention_well_count": sum(1 for item in items if item["attention_score"] >= 45),
                "signal_count": sum(item["signal_count"] for item in items),
                "top_wells": [item["name"] for item in sorted(items, key=lambda item: item["attention_score"], reverse=True)[:3]],
            })
        return sorted(regions, key=lambda item: item["attention_score"], reverse=True)

    @staticmethod
    def _build_signal_trend(observations: List[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
        counts = defaultdict(int)
        for observation in observations:
            occurred = observation.get("occurred_time")
            if occurred:
                counts[occurred[:10]] += 1
        result = []
        for days_ago in range(6, -1, -1):
            day = (now - timedelta(days=days_ago)).date().isoformat()
            result.append({"date": day, "count": counts.get(day, 0)})
        return result

    @staticmethod
    def _fallback_ai_analysis(overview: Dict[str, Any]) -> Dict[str, Any]:
        top_wells = [well for well in overview["wells"] if well["attention_score"] >= 20][:6]
        top_regions = [region for region in overview["regions"] if region["attention_score"] >= 20][:4]
        suggestions = []
        for well in top_wells[:4]:
            signal_types = set(well["signal_types"])
            if "vehicle_trace" in signal_types:
                action = "复核井点周边可用视频、卡口和车迹出现方向，补齐时间链证据。"
            elif "oil_trace" in signal_types:
                action = "区分工艺性漏油与外力痕迹，补拍井口、阀门和地面连续痕迹。"
            elif well["score_components"]["defense_gaps"] >= 60:
                action = "核验监控、照明和报警覆盖及夜间可用性，形成防控补强清单。"
            else:
                action = "对近期异常迹象进行现场复核，补齐照片、时间和位置依据。"
            suggestions.append({
                "target": well["name"],
                "priority": "high" if well["attention_score"] >= 70 else "medium",
                "action": action,
                "basis": "；".join(well["reasons"][:2]),
            })
        if not overview["wells"]:
            suggestions.append({
                "target": "井点基础数据",
                "priority": "high",
                "action": "先导入井号、坐标、作业区和产量等级，再建立井点关注热力。",
                "basis": "当前系统没有可用于计算的井点资产。",
            })
        elif not overview["observations"]:
            suggestions.append({
                "target": "现场痕迹采集",
                "priority": "high",
                "action": "录入陌生车迹、油迹、设施异常等现场事实，并关联具体井点。",
                "basis": "当前周期没有已录入的井点周边风险迹象。",
            })
        status = "deterministic_fallback" if overview["wells"] and overview["observations"] else "insufficient_data"
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days_back": overview["days_back"],
            "source_signature": WellAttentionService._overview_signature(overview),
            "model_status": status,
            "attention_regions": [
                {
                    "name": region["name"],
                    "level": region["attention_level"],
                    "confidence": 0.62,
                    "reasons": [f"区域关联风险迹象 {region['signal_count']} 条，关注井点 {region['attention_well_count']} 口。"],
                    "evidence_refs": region["top_wells"],
                }
                for region in top_regions
            ],
            "attention_wells": [
                {
                    "asset_id": well["asset_id"],
                    "name": well["name"],
                    "level": well["attention_level"],
                    "confidence": 0.66 if well["signal_count"] else 0.45,
                    "reasons": well["reasons"][:3],
                    "information_gaps": well["data_gaps"],
                }
                for well in top_wells
            ],
            "deployment_suggestions": suggestions,
            "boundary": overview["boundary"],
        }

    @staticmethod
    def _sanitize_ai_analysis(payload: Dict[str, Any], overview: Dict[str, Any]) -> Dict[str, Any]:
        well_by_id = {well["asset_id"]: well for well in overview["wells"]}
        region_by_name = {region["name"]: region for region in overview["regions"]}
        valid_levels = {"high", "medium", "watch"}
        valid_priorities = {"high", "medium", "low"}

        def clean_list(value: Any, limit: int = 5) -> List[str]:
            if not isinstance(value, list):
                return []
            return [str(item).strip()[:160] for item in value if str(item).strip()][:limit]

        regions = []
        for item in payload.get("attention_regions", []):
            if not isinstance(item, dict) or item.get("name") not in region_by_name:
                continue
            source = region_by_name[item["name"]]
            confidence = WellAttentionService._safe_float(item.get("confidence"))
            regions.append({
                "name": item["name"],
                "level": item.get("level") if item.get("level") in valid_levels else source["attention_level"],
                "confidence": round(max(0.0, min(1.0, confidence if confidence is not None else 0.5)), 2),
                "reasons": clean_list(item.get("reasons")),
                "evidence_refs": clean_list(item.get("evidence_refs")),
            })
            if len(regions) >= 6:
                break

        wells = []
        for item in payload.get("attention_wells", []):
            if not isinstance(item, dict) or item.get("asset_id") not in well_by_id:
                continue
            source = well_by_id[item["asset_id"]]
            confidence = WellAttentionService._safe_float(item.get("confidence"))
            wells.append({
                "asset_id": source["asset_id"],
                "name": source["name"],
                "level": item.get("level") if item.get("level") in valid_levels else source["attention_level"],
                "confidence": round(max(0.0, min(1.0, confidence if confidence is not None else 0.5)), 2),
                "reasons": clean_list(item.get("reasons")),
                "information_gaps": clean_list(item.get("information_gaps")),
            })
            if len(wells) >= 8:
                break

        allowed_targets = set(region_by_name) | {well["name"] for well in overview["wells"]}
        suggestions = []
        for item in payload.get("deployment_suggestions", []):
            if not isinstance(item, dict) or str(item.get("target") or "").strip() not in allowed_targets:
                continue
            action = str(item.get("action") or "").strip()
            if not action:
                continue
            suggestions.append({
                "target": str(item["target"]).strip(),
                "priority": item.get("priority") if item.get("priority") in valid_priorities else "medium",
                "action": action[:240],
                "basis": str(item.get("basis") or "需结合已录入事实人工复核").strip()[:240],
            })
            if len(suggestions) >= 8:
                break

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days_back": overview["days_back"],
            "source_signature": WellAttentionService._overview_signature(overview),
            "attention_regions": regions,
            "attention_wells": wells,
            "deployment_suggestions": suggestions,
            "boundary": list(dict.fromkeys([
                *overview["boundary"],
                *clean_list(payload.get("boundary"), limit=2),
            ]))[:5],
        }

    @staticmethod
    def _overview_signature(overview: Dict[str, Any]) -> str:
        source = {
            "days_back": overview.get("days_back"),
            "well_ids": sorted(well["asset_id"] for well in overview.get("wells", [])),
            "event_ids": sorted(item["event_id"] for item in overview.get("observations", [])),
        }
        encoded = json.dumps(source, ensure_ascii=True, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:20]

    @staticmethod
    def _store_ai(db: Session, analysis: Dict[str, Any]) -> None:
        SystemConfigService.set_config(
            db,
            config_key=AI_SNAPSHOT_KEY,
            config_value=json.dumps(analysis, ensure_ascii=False, default=str),
            config_type="json",
            category="analysis",
            description="井点风险迹象关注研判最新快照",
        )

    @staticmethod
    def _load_cached_ai(db: Session) -> Optional[Dict[str, Any]]:
        raw = SystemConfigService.get_config_value(db, AI_SNAPSHOT_KEY, "")
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            return payload if isinstance(payload, dict) else None
        except (TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _overview_gaps(
        wells: List[JurisdictionAsset],
        profiles: List[Dict[str, Any]],
        observations: List[Dict[str, Any]],
    ) -> List[str]:
        gaps = []
        if not wells:
            gaps.append("缺少井点资产，请导入井号、坐标、作业区和产量指标。")
        elif not observations:
            gaps.append("当前周期没有井点周边风险迹象记录。")
        if wells and not any(profile["production_output"] is not None for profile in profiles):
            gaps.append("井点资产缺少日产量/产量等级，暂不能识别高产井暴露度。")
        if wells and not any(profile["nearby_tech"] or profile["blind_spots"] for profile in profiles):
            gaps.append("缺少井点周边监控、照明、报警、卡口和盲区数据。")
        return gaps

    @staticmethod
    def _production_output(asset: JurisdictionAsset) -> Optional[float]:
        attributes = asset.attributes or {}
        for key in PRODUCTION_KEYS:
            value = WellAttentionService._safe_float(attributes.get(key))
            if value is not None:
                return value
        return None

    @staticmethod
    def _is_high_production(asset: JurisdictionAsset, output: Optional[float], max_output: Optional[float]) -> bool:
        attributes = asset.attributes or {}
        tags = {str(item).strip().lower() for item in (asset.tags or [])}
        flag = attributes.get("is_high_production") or attributes.get("high_production") or attributes.get("高产井")
        if str(flag).strip().lower() in {"1", "true", "yes", "是", "高产"}:
            return True
        if {"high_production", "高产井", "高产"} & tags:
            return True
        return bool(output is not None and max_output and output >= max_output * 0.75)

    @staticmethod
    def _asset_region(asset: JurisdictionAsset) -> str:
        attributes = asset.attributes or {}
        for key in REGION_KEYS:
            value = attributes.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return asset.address or "未分区井点"

    @staticmethod
    def _attention_level(score: float) -> str:
        if score >= 70:
            return "high"
        if score >= 45:
            return "medium"
        if score >= 20:
            return "watch"
        return "stable"

    @staticmethod
    def _age_days(value: Optional[datetime], now: datetime) -> float:
        if value is None:
            return 0.0
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return max(0.0, (now - value).total_seconds() / 86400.0)

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
