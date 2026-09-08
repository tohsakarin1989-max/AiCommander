"""v3.0 双域态势研判：增量变化、热点、井点关注与一页简报。"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.services.geo_analysis_service import GeoAnalysisService
from app.utils.geo import bounding_box, haversine_km


class SituationAnalysisError(ValueError):
    pass


class SituationAnalysisService:
    """只读分析相邻时间窗口，不做犯罪预测或执行调度。"""

    MAX_CASES = 5000
    MAX_WELLS = 3000

    @staticmethod
    def build_overview(
        db: Session,
        *,
        window_days: int = 30,
        as_of: datetime | None = None,
        area_keyword: str | None = None,
        hotspot_radius_km: float = 1.5,
        well_radius_km: float = 5.0,
        min_cases: int = 2,
    ) -> dict[str, Any]:
        SituationAnalysisService._validate_scope(
            window_days=window_days,
            area_keyword=area_keyword,
            hotspot_radius_km=hotspot_radius_km,
            well_radius_km=well_radius_km,
            min_cases=min_cases,
        )
        normalized_as_of = SituationAnalysisService._naive_utc(
            as_of or datetime.now(timezone.utc)
        )
        area = (area_keyword or "").strip() or None
        current_start = normalized_as_of - timedelta(days=window_days)
        previous_start = current_start - timedelta(days=window_days)

        current_query = SituationAnalysisService._case_query(
            db,
            start=current_start,
            end=normalized_as_of,
            end_inclusive=True,
            area_keyword=area,
        )
        previous_query = SituationAnalysisService._case_query(
            db,
            start=previous_start,
            end=current_start,
            end_inclusive=False,
            area_keyword=area,
        )
        current_count = current_query.count()
        previous_count = previous_query.count()
        current_cases = (
            current_query.order_by(Case.occurred_time.asc(), Case.id.asc())
            .limit(SituationAnalysisService.MAX_CASES)
            .all()
        )
        previous_cases = (
            previous_query.order_by(Case.occurred_time.asc(), Case.id.asc())
            .limit(SituationAnalysisService.MAX_CASES)
            .all()
        )
        current_geo = [item for item in current_cases if SituationAnalysisService._has_geo(item)]
        previous_geo = [item for item in previous_cases if SituationAnalysisService._has_geo(item)]

        timeline = SituationAnalysisService._timeline(previous_cases, current_cases, current_start)
        pattern_shifts = SituationAnalysisService._pattern_shifts(previous_cases, current_cases)
        hotspots = SituationAnalysisService._hotspots(
            current_geo,
            previous_geo,
            radius_km=hotspot_radius_km,
            min_cases=min_cases,
        )
        case_points = [SituationAnalysisService._case_point(item) for item in current_geo]
        well_attention = SituationAnalysisService._well_attention(
            db,
            current_geo,
            previous_geo,
            radius_km=well_radius_km,
        )
        summary = SituationAnalysisService._summary(
            current_count=current_count,
            previous_count=previous_count,
            current_loaded=len(current_cases),
            geocoded_count=len(current_geo),
            hotspots=hotspots,
            well_attention=well_attention,
        )
        priorities = SituationAnalysisService._priorities(
            summary,
            current_cases,
            hotspots,
            well_attention,
            pattern_shifts,
        )
        window = {
            "days": window_days,
            "current_start": current_start.isoformat(),
            "current_end": normalized_as_of.isoformat(),
            "previous_start": previous_start.isoformat(),
            "previous_end": current_start.isoformat(),
            "area_keyword": area,
        }
        boundary = {
            "read_only": True,
            "historical_association_only": True,
            "statements": [
                "本结果比较相邻历史时间窗口，只描述已登记数据变化，不构成犯罪预测。",
                "案件与井点的空间接近只作为核查入口，不能证明两者存在事实关联。",
                "系统不读取或返回人员、电话、证件号和车辆身份信息。",
                "所有建议必须人工核查，本模块不自动调度、不生成巡逻任务。",
            ],
        }
        brief = SituationAnalysisService._brief(
            window=window,
            summary=summary,
            hotspots=hotspots,
            well_attention=well_attention,
            pattern_shifts=pattern_shifts,
            priorities=priorities,
            boundary=boundary,
        )
        pipeline = [
            {
                "step": "scope",
                "label": "锁定时间与区域",
                "status": "completed",
                "result": f"本期{current_count}起、上期{previous_count}起",
            },
            {
                "step": "change",
                "label": "识别增量与模式变化",
                "status": "completed",
                "result": f"形成{len(pattern_shifts['case_types']) + len(pattern_shifts['modus_operandi'])}项分布对比",
            },
            {
                "step": "spatial",
                "label": "计算热点与井点参考",
                "status": "completed",
                "result": f"{len(hotspots)}个聚集热点、{len(well_attention)}口关联井点",
            },
            {
                "step": "brief",
                "label": "生成研判重点与简报",
                "status": "completed",
                "result": f"{len(priorities)}项优先核查建议",
            },
        ]
        canonical = {
            "window": window,
            "summary": summary,
            "timeline": timeline,
            "pattern_shifts": pattern_shifts,
            "case_points": case_points,
            "hotspots": hotspots,
            "well_attention": well_attention,
            "priorities": priorities,
            "brief": brief,
            "pipeline": pipeline,
            "boundary": boundary,
        }
        data_version = sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "as_of": normalized_as_of.isoformat(),
            "window": window,
            "source_snapshot": {
                "algorithm": "sha256",
                "data_version": data_version,
            },
            "summary": summary,
            "timeline": timeline,
            "pattern_shifts": pattern_shifts,
            "case_points": case_points,
            "hotspots": hotspots,
            "well_attention": well_attention,
            "priorities": priorities,
            "pipeline": pipeline,
            "brief": brief,
            "boundary": boundary,
        }

    @staticmethod
    def _validate_scope(
        *,
        window_days: int,
        area_keyword: str | None,
        hotspot_radius_km: float,
        well_radius_km: float,
        min_cases: int,
    ) -> None:
        if not 7 <= window_days <= 90:
            raise SituationAnalysisError("invalid_window_days")
        if not 0.5 <= hotspot_radius_km <= 5:
            raise SituationAnalysisError("invalid_hotspot_radius")
        if not 0.5 <= well_radius_km <= 20:
            raise SituationAnalysisError("invalid_well_radius")
        if not 2 <= min_cases <= 10:
            raise SituationAnalysisError("invalid_min_cases")
        if len((area_keyword or "").strip()) > 50:
            raise SituationAnalysisError("invalid_area_keyword")

    @staticmethod
    def _case_query(
        db: Session,
        *,
        start: datetime,
        end: datetime,
        end_inclusive: bool,
        area_keyword: str | None,
    ):
        query = db.query(Case).filter(Case.occurred_time >= start)
        query = query.filter(Case.occurred_time <= end if end_inclusive else Case.occurred_time < end)
        if area_keyword:
            escaped = (
                area_keyword.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            query = query.filter(Case.location.ilike(f"%{escaped}%", escape="\\"))
        return query

    @staticmethod
    def _naive_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _has_geo(case: Case) -> bool:
        return case.latitude is not None and case.longitude is not None

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return SituationAnalysisService._naive_utc(value).isoformat() if value else None

    @staticmethod
    def _case_point(case: Case) -> dict[str, Any]:
        return {
            "id": case.id,
            "case_number": case.case_number,
            "occurred_time": SituationAnalysisService._iso(case.occurred_time),
            "location": case.location or "未登记地点",
            "case_type": case.case_type or "未分类",
            "modus_operandi": case.modus_operandi or "未标注手法",
            "latitude": case.latitude,
            "longitude": case.longitude,
        }

    @staticmethod
    def _timeline(
        previous_cases: list[Case],
        current_cases: list[Case],
        current_start: datetime,
    ) -> list[dict[str, Any]]:
        counts: Counter[tuple[str, str]] = Counter()
        for case in [*previous_cases, *current_cases]:
            occurred = SituationAnalysisService._naive_utc(case.occurred_time)
            period = "current" if occurred >= current_start else "previous"
            counts[(occurred.date().isoformat(), period)] += 1
        return [
            {"date": date, "period": period, "count": count}
            for (date, period), count in sorted(counts.items())
        ]

    @staticmethod
    def _distribution_shift(
        previous_cases: list[Case],
        current_cases: list[Case],
        attribute: str,
        *,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        previous = Counter(
            str(getattr(case, attribute) or "未标注").strip() or "未标注"
            for case in previous_cases
        )
        current = Counter(
            str(getattr(case, attribute) or "未标注").strip() or "未标注"
            for case in current_cases
        )
        rows = []
        for name in set(previous) | set(current):
            delta = current[name] - previous[name]
            rows.append(
                {
                    "name": name,
                    "current_count": current[name],
                    "previous_count": previous[name],
                    "delta": delta,
                    "direction": "rising" if delta > 0 else "falling" if delta < 0 else "stable",
                }
            )
        rows.sort(key=lambda item: (-item["current_count"], -item["delta"], item["name"]))
        return rows[:limit]

    @staticmethod
    def _pattern_shifts(previous_cases: list[Case], current_cases: list[Case]) -> dict[str, Any]:
        hours = Counter(
            SituationAnalysisService._naive_utc(case.occurred_time).hour
            for case in current_cases
        )
        return {
            "case_types": SituationAnalysisService._distribution_shift(
                previous_cases, current_cases, "case_type"
            ),
            "modus_operandi": SituationAnalysisService._distribution_shift(
                previous_cases, current_cases, "modus_operandi"
            ),
            "peak_hours": [
                {"hour": hour, "count": count}
                for hour, count in sorted(hours.items(), key=lambda item: (-item[1], item[0]))[:3]
            ],
        }

    @staticmethod
    def _dominant(cases: list[Case], attribute: str) -> str:
        values = Counter(
            str(getattr(case, attribute) or "未标注").strip() or "未标注"
            for case in cases
        )
        return sorted(values.items(), key=lambda item: (-item[1], item[0]))[0][0]

    @staticmethod
    def _hotspots(
        current_cases: list[Case],
        previous_cases: list[Case],
        *,
        radius_km: float,
        min_cases: int,
    ) -> list[dict[str, Any]]:
        raw = GeoAnalysisService.find_hotspots(
            cases=current_cases,
            radius_km=radius_km,
            min_cases=min_cases,
        )
        hotspots = []
        for index, item in enumerate(raw[:10], 1):
            case_ids = sorted(item["case_ids"])
            cluster_cases = [case for case in current_cases if case.id in case_ids]
            previous_count = sum(
                haversine_km(
                    item["center_latitude"],
                    item["center_longitude"],
                    case.latitude,
                    case.longitude,
                ) <= radius_km
                for case in previous_cases
            )
            hotspots.append(
                {
                    "id": f"hotspot:{sha256(','.join(map(str, case_ids)).encode()).hexdigest()[:10]}",
                    "label": f"热点组 {index:02d}",
                    "center": {
                        "latitude": round(item["center_latitude"], 6),
                        "longitude": round(item["center_longitude"], 6),
                    },
                    "case_count": item["case_count"],
                    "previous_case_count": previous_count,
                    "case_delta": item["case_count"] - previous_count,
                    "case_ids": case_ids,
                    "case_numbers": [case.case_number for case in cluster_cases],
                    "dominant_case_type": SituationAnalysisService._dominant(cluster_cases, "case_type"),
                    "dominant_modus_operandi": SituationAnalysisService._dominant(
                        cluster_cases, "modus_operandi"
                    ),
                    "latest_case_at": max(
                        SituationAnalysisService._naive_utc(case.occurred_time)
                        for case in cluster_cases
                    ).isoformat(),
                    "radius_km": radius_km,
                    "boundary": "本项只描述已登记案件的历史空间聚集，不代表未来一定发生案件。",
                }
            )
        hotspots.sort(key=lambda item: (-item["case_delta"], -item["case_count"], item["id"]))
        return hotspots

    @staticmethod
    def _production_output(asset: JurisdictionAsset) -> float | None:
        attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
        for key in ("日产量", "daily_output", "production_output", "产量"):
            try:
                if attributes.get(key) not in (None, ""):
                    return float(attributes[key])
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _is_high_production(asset: JurisdictionAsset, max_output: float | None) -> bool:
        attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
        tags = set(asset.tags or []) if isinstance(asset.tags, list) else set()
        flag = (
            attributes.get("is_high_production")
            or attributes.get("high_production")
            or attributes.get("高产井")
        )
        if flag is True or str(flag).strip().lower() in {"true", "yes", "1", "是"}:
            return True
        if {"high_production", "高产井", "高产"} & tags:
            return True
        output = SituationAnalysisService._production_output(asset)
        return bool(output is not None and max_output and output >= max_output * 0.8)

    @staticmethod
    def _latitude_index(
        cases: Iterable[Case],
    ) -> tuple[list[float], list[Case]]:
        ordered = sorted(cases, key=lambda case: (float(case.latitude), case.id))
        return [float(case.latitude) for case in ordered], ordered

    @staticmethod
    def _nearby_cases(
        index: tuple[list[float], list[Case]],
        asset: JurisdictionAsset,
        radius_km: float,
    ) -> list[tuple[float, Case]]:
        latitudes, cases = index
        min_lat, max_lat, min_lon, max_lon = bounding_box(
            float(asset.latitude),
            float(asset.longitude),
            radius_km,
        )
        start = bisect_left(latitudes, min_lat)
        end = bisect_right(latitudes, max_lat)
        matches = []
        for case in cases[start:end]:
            if not min_lon <= float(case.longitude) <= max_lon:
                continue
            distance = haversine_km(
                asset.latitude,
                asset.longitude,
                case.latitude,
                case.longitude,
            )
            if distance <= radius_km:
                matches.append((distance, case))
        return sorted(matches, key=lambda item: (item[0], item[1].id))

    @staticmethod
    def _well_attention(
        db: Session,
        current_cases: list[Case],
        previous_cases: list[Case],
        *,
        radius_km: float,
    ) -> list[dict[str, Any]]:
        if not current_cases:
            return []
        case_bounds = [
            bounding_box(
                float(case.latitude),
                float(case.longitude),
                radius_km,
            )
            for case in current_cases
        ]
        wells = (
            db.query(JurisdictionAsset)
            .filter(
                JurisdictionAsset.asset_type == "well",
                JurisdictionAsset.status == "active",
                JurisdictionAsset.latitude.isnot(None),
                JurisdictionAsset.longitude.isnot(None),
                JurisdictionAsset.latitude >= min(item[0] for item in case_bounds),
                JurisdictionAsset.latitude <= max(item[1] for item in case_bounds),
                JurisdictionAsset.longitude >= min(item[2] for item in case_bounds),
                JurisdictionAsset.longitude <= max(item[3] for item in case_bounds),
            )
            .order_by(JurisdictionAsset.id.asc())
            .limit(SituationAnalysisService.MAX_WELLS)
            .all()
        )
        max_output = max(
            (
                output
                for item in wells
                if (output := SituationAnalysisService._production_output(item)) is not None
            ),
            default=None,
        )
        current_index = SituationAnalysisService._latitude_index(current_cases)
        previous_index = SituationAnalysisService._latitude_index(previous_cases)
        rows = []
        for well in wells:
            current = SituationAnalysisService._nearby_cases(current_index, well, radius_km)
            if not current:
                continue
            previous = SituationAnalysisService._nearby_cases(previous_index, well, radius_km)
            delta = len(current) - len(previous)
            high_production = SituationAnalysisService._is_high_production(well, max_output)
            score = min(
                100,
                min(60, len(current) * 18)
                + min(20, max(0, delta) * 7)
                + (12 if high_production else 0)
                + (8 if well.verified else 0),
            )
            attributes = well.attributes if isinstance(well.attributes, dict) else {}
            reasons = [f"限定半径内本期{len(current)}起案件"]
            if delta > 0:
                reasons.append(f"较上一窗口增加{delta}起")
            if high_production:
                reasons.append("登记为高产井或产量处于当前井点高位")
            if not well.verified:
                reasons.append("井点坐标尚未人工核验，仅作低置信参考")
            rows.append(
                {
                    "asset_id": well.id,
                    "name": well.name,
                    "latitude": well.latitude,
                    "longitude": well.longitude,
                    "verified": bool(well.verified),
                    "is_high_production": high_production,
                    "region": attributes.get("作业区") or attributes.get("region") or "未登记作业区",
                    "nearby_case_count": len(current),
                    "previous_nearby_case_count": len(previous),
                    "case_delta": delta,
                    "minimum_distance_km": round(current[0][0], 3),
                    "latest_case_at": max(
                        SituationAnalysisService._naive_utc(case.occurred_time)
                        for _, case in current
                    ).isoformat(),
                    "case_ids": [case.id for _, case in current],
                    "attention_score": score,
                    "attention_level": "high" if score >= 60 else "medium" if score >= 35 else "low",
                    "reasons": reasons,
                    "boundary": "空间接近只能作为核查参考，不能证明案件与井点存在事实关联。",
                }
            )
        rows.sort(
            key=lambda item: (
                -item["attention_score"],
                -item["nearby_case_count"],
                item["asset_id"],
            )
        )
        return rows[:20]

    @staticmethod
    def _summary(
        *,
        current_count: int,
        previous_count: int,
        current_loaded: int,
        geocoded_count: int,
        hotspots: list[dict[str, Any]],
        well_attention: list[dict[str, Any]],
    ) -> dict[str, Any]:
        delta = current_count - previous_count
        delta_percent = (
            round(delta / previous_count * 100)
            if previous_count
            else (100 if current_count else 0)
        )
        return {
            "current_case_count": current_count,
            "previous_case_count": previous_count,
            "case_delta": delta,
            "case_delta_percent": delta_percent,
            "change_direction": "rising" if delta > 0 else "falling" if delta < 0 else "stable",
            "geocoded_case_count": geocoded_count,
            "data_readiness_percent": round(geocoded_count / current_loaded * 100) if current_loaded else 0,
            "hotspot_count": len(hotspots),
            "well_attention_count": len(well_attention),
            "analysis_status": "ready" if current_count else "no_current_data",
            "source_truncated": current_count > SituationAnalysisService.MAX_CASES,
        }

    @staticmethod
    def _priorities(
        summary: dict[str, Any],
        current_cases: list[Case],
        hotspots: list[dict[str, Any]],
        well_attention: list[dict[str, Any]],
        pattern_shifts: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not current_cases:
            return []
        priorities: list[dict[str, Any]] = []
        if hotspots:
            item = hotspots[0]
            priorities.append(
                {
                    "id": f"priority:{item['id']}",
                    "rank": 0,
                    "type": "hotspot_change",
                    "level": "high" if item["case_delta"] > 0 else "medium",
                    "title": (
                        f"{item['label']}形成新增聚集"
                        if item["case_delta"] > 0
                        else f"{item['label']}保持历史聚集"
                    ),
                    "finding": f"本期{item['case_count']}起，较上一窗口变化{item['case_delta']:+d}起。",
                    "action": "核对共同发生时段、作案手法和现场条件，形成专题核查清单。",
                    "evidence_refs": [f"case:{case_id}" for case_id in item["case_ids"]],
                    "map_focus": item["center"],
                    "boundary": item["boundary"],
                }
            )
        if well_attention:
            item = well_attention[0]
            priorities.append(
                {
                    "id": f"priority:well:{item['asset_id']}",
                    "rank": 0,
                    "type": "well_attention",
                    "level": item["attention_level"],
                    "title": f"{item['name']}周边出现案件集中",
                    "finding": (
                        f"最短距离{item['minimum_distance_km']:.2f}公里，"
                        f"本期关联{item['nearby_case_count']}起。"
                    ),
                    "action": "结合井点核验状态和历史案件，人工判断是否纳入近期防控关注清单。",
                    "evidence_refs": [
                        f"well:{item['asset_id']}",
                        *[f"case:{case_id}" for case_id in item["case_ids"]],
                    ],
                    "map_focus": {"latitude": item["latitude"], "longitude": item["longitude"]},
                    "boundary": item["boundary"],
                }
            )
        mode_rows = [item for item in pattern_shifts["modus_operandi"] if item["delta"] > 0]
        if mode_rows:
            item = mode_rows[0]
            refs = [
                f"case:{case.id}"
                for case in current_cases
                if (case.modus_operandi or "未标注手法") == item["name"]
            ]
            priorities.append(
                {
                    "id": f"priority:modus:{sha256(item['name'].encode()).hexdigest()[:10]}",
                    "rank": 0,
                    "type": "modus_change",
                    "level": "high" if item["delta"] >= 2 else "medium",
                    "title": f"“{item['name']}”手法本期增加",
                    "finding": f"本期{item['current_count']}起，较上一窗口增加{item['delta']}起。",
                    "action": "复盘相关案件的目标设施、发生时段和现场薄弱条件。",
                    "evidence_refs": refs,
                    "map_focus": None,
                    "boundary": "手法分布变化只描述已登记案件，不代表同一人员或团伙作案。",
                }
            )
        if not priorities:
            priorities.append(
                {
                    "id": "priority:window-change",
                    "rank": 0,
                    "type": "window_change",
                    "level": "medium",
                    "title": "核对本期新增案件共同条件",
                    "finding": f"本期登记{summary['current_case_count']}起案件。",
                    "action": "从案件类型、设施条件和发生时段入手完成一次集中复盘。",
                    "evidence_refs": [f"case:{case.id}" for case in current_cases[:20]],
                    "map_focus": None,
                    "boundary": "仅作为人工研判入口，不自动形成串案或处置结论。",
                }
            )
        priorities = priorities[:3]
        for index, item in enumerate(priorities, 1):
            item["rank"] = index
        return priorities

    @staticmethod
    def _brief(
        *,
        window: dict[str, Any],
        summary: dict[str, Any],
        hotspots: list[dict[str, Any]],
        well_attention: list[dict[str, Any]],
        pattern_shifts: dict[str, Any],
        priorities: list[dict[str, Any]],
        boundary: dict[str, Any],
    ) -> dict[str, Any]:
        current = summary["current_case_count"]
        delta = summary["case_delta"]
        if not current:
            headline = "当前窗口没有匹配案件，未形成热点或井点关注建议。"
        elif delta > 0:
            headline = f"本期新增{current}起案件，较上一窗口增加{delta}起。"
        elif delta < 0:
            headline = f"本期新增{current}起案件，较上一窗口减少{abs(delta)}起。"
        else:
            headline = f"本期新增{current}起案件，与上一窗口数量持平。"
        facts = [
            f"统计窗口为{window['days']}天，本期{current}起、上一窗口{summary['previous_case_count']}起。",
            f"本期{summary['geocoded_case_count']}起案件具备坐标，空间分析就绪率{summary['data_readiness_percent']}%。",
            f"形成{len(hotspots)}个聚集热点，{len(well_attention)}口井点进入空间参考清单。",
        ]
        findings = []
        if hotspots:
            top = hotspots[0]
            findings.append(
                f"{top['label']}包含{top['case_count']}起案件，主要手法为{top['dominant_modus_operandi']}。"
            )
        if well_attention:
            top = well_attention[0]
            findings.append(
                f"{top['name']}限定半径内本期{top['nearby_case_count']}起案件，最短距离{top['minimum_distance_km']:.2f}公里。"
            )
        if pattern_shifts["peak_hours"]:
            hours = "、".join(f"{item['hour']}时" for item in pattern_shifts["peak_hours"])
            findings.append(f"本期登记案件相对集中的发生时点为{hours}。")
        suggestions = [item["action"] for item in priorities]
        lines = [
            "# 双域态势研判简报",
            "",
            headline,
            "",
            "## 事实摘要",
            *[f"- {item}" for item in facts],
            "",
            "## 研判发现",
            *([f"- {item}" for item in findings] or ["- 当前数据未形成可报告的聚集或井点空间参考。"]),
            "",
            "## 建议核查",
            *([f"- {item}" for item in suggestions] or ["- 当前窗口无新增核查建议。"]),
            "",
            "## 使用边界",
            *[f"- {item}" for item in boundary["statements"]],
        ]
        return {
            "title": "双域态势研判简报",
            "headline": headline,
            "facts": facts,
            "findings": findings,
            "suggestions": suggestions,
            "markdown": "\n".join(lines),
        }
