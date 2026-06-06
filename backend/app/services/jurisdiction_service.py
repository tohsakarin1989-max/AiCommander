"""辖区风险底座与案件空间上下文服务。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Dict, Iterable, List, Optional

import httpx

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset, JurisdictionFeedback
from app.models.patrol import PatrolRecord
from app.services.patrol_service import PatrolService
from app.utils.geo import haversine_km


ROAD_TYPES = {
    "road",
    "path",
    "access_road",
    "internal_route",
    "temporary_route",
    "abandoned_road",
    "risk_route",
}
VILLAGE_TYPES = {"village", "residential", "settlement"}
PRODUCTION_TARGET_TYPES = {
    "well",
    "station",
    "valve",
    "storage",
    "oil_depot",
    "pipeline_node",
    "key_location",
}
TECH_TYPES = {"camera", "lighting", "alarm", "fence", "checkpoint", "blind_spot"}
PATROL_TYPES = {"patrol_point", "checkpoint", "high_risk_area"}
PUBLIC_MAP_REFERENCE_TYPES = {
    "road",
    "path",
    "access_road",
    "village",
    "residential",
    "settlement",
    "river",
    "bridge",
    "intersection",
    "public_place",
}
BUSINESS_ASSET_TYPES = (
    PRODUCTION_TARGET_TYPES
    | TECH_TYPES
    | PATROL_TYPES
    | {"internal_route", "temporary_route", "abandoned_road", "risk_route"}
)
BUSINESS_REQUIREMENT_GROUPS = {
    "production_target": PRODUCTION_TARGET_TYPES,
    "technical_protection": TECH_TYPES,
}
ASSET_LAYER_LABELS = {
    "public_map_reference": "公共地图参考",
    "oil_business_asset": "油区业务资产",
    "analysis_derived": "研判派生条件",
    "other": "其他要素",
}
REQUIREMENT_LABELS = {
    "production_target": "井点/管线节点/站库等生产目标",
    "technical_protection": "监控/卡口/照明/报警等防控设施",
}
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_PUBLIC_MAP_RADIUS_KM = 6.0
MAX_PUBLIC_MAP_RADIUS_KM = 20.0


@dataclass(frozen=True)
class AssetDistance:
    asset: JurisdictionAsset
    distance_km: float


class JurisdictionService:
    """把地图/业务点位转成案件研判可用的空间环境特征。"""

    @staticmethod
    def create_asset(db: Session, data: Dict[str, Any]) -> JurisdictionAsset:
        asset = JurisdictionAsset(**data)
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset

    @staticmethod
    def update_asset(db: Session, asset_id: int, data: Dict[str, Any]) -> JurisdictionAsset:
        asset = db.query(JurisdictionAsset).filter(JurisdictionAsset.id == asset_id).first()
        if not asset:
            raise ValueError("asset_not_found")
        geometry_type = str(data.get("geometry_type") or asset.geometry_type or "point").lower()
        latitude = data.get("latitude", asset.latitude)
        longitude = data.get("longitude", asset.longitude)
        if "geometry" not in data and geometry_type == "point" and latitude is not None and longitude is not None:
            data["geometry"] = {"type": "Point", "coordinates": [longitude, latitude]}
        for key, value in data.items():
            setattr(asset, key, value)
        db.commit()
        db.refresh(asset)
        return asset

    @staticmethod
    def deactivate_asset(db: Session, asset_id: int) -> JurisdictionAsset:
        return JurisdictionService.update_asset(db, asset_id, {"status": "inactive"})

    @staticmethod
    def bulk_create_assets(db: Session, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        created = []
        for item in items:
            payload = {
                "geometry_type": "point",
                "source": "import",
                "status": "active",
                "risk_level": 1,
                **item,
            }
            asset = JurisdictionAsset(**payload)
            db.add(asset)
            created.append(asset)
        db.commit()
        for asset in created:
            db.refresh(asset)
        return {
            "total": len(items),
            "created": len(created),
            "items": [JurisdictionService._asset_to_dict(asset) for asset in created],
        }

    @staticmethod
    def import_geojson(db: Session, geojson: Dict[str, Any], source: str = "map") -> Dict[str, Any]:
        features = geojson.get("features") if geojson.get("type") == "FeatureCollection" else None
        if not isinstance(features, list):
            return {"total": 0, "created": 0, "updated": 0, "errors": ["仅支持 FeatureCollection"], "items": []}

        created = 0
        updated = 0
        errors: List[str] = []
        items: List[JurisdictionAsset] = []
        for index, feature in enumerate(features):
            try:
                payload = JurisdictionService._payload_from_geojson_feature(feature, source=source)
                asset, was_created = JurisdictionService._upsert_asset(db, payload)
                created += 1 if was_created else 0
                updated += 0 if was_created else 1
                items.append(asset)
            except ValueError as exc:
                errors.append(f"feature[{index}]: {exc}")

        db.commit()
        for asset in items:
            db.refresh(asset)
        return {
            "total": len(features),
            "created": created,
            "updated": updated,
            "errors": errors,
            "items": [JurisdictionService._asset_to_dict(asset) for asset in items],
        }

    @staticmethod
    def sync_public_map_references(
        db: Session,
        *,
        south: Optional[float] = None,
        west: Optional[float] = None,
        north: Optional[float] = None,
        east: Optional[float] = None,
        center_lat: Optional[float] = None,
        center_lng: Optional[float] = None,
        radius_km: float = DEFAULT_PUBLIC_MAP_RADIUS_KM,
        max_features: int = 160,
    ) -> Dict[str, Any]:
        """从公共地图服务拉取道路、村屯等参考要素并写入辖区要素库。"""
        bounds = JurisdictionService._resolve_public_map_bounds(
            db,
            south=south,
            west=west,
            north=north,
            east=east,
            center_lat=center_lat,
            center_lng=center_lng,
            radius_km=radius_km,
        )
        query = JurisdictionService._build_overpass_public_map_query(bounds)
        elements = JurisdictionService._fetch_public_map_elements(query)
        features = JurisdictionService._osm_elements_to_geojson_features(elements, max_features=max_features)
        result = JurisdictionService.import_geojson(
            db,
            {"type": "FeatureCollection", "features": features},
            source="map",
        )
        result.update({
            "provider": "openstreetmap",
            "bounds": bounds,
            "pulled": len(elements),
            "usable": len(features),
        })
        return result

    @staticmethod
    def import_tabular_assets(
        db: Session,
        rows: List[Dict[str, Any]],
        source: str = "ledger",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        created = 0
        updated = 0
        valid = 0
        errors: List[Dict[str, Any]] = []
        items: List[Any] = []

        for index, row in enumerate(rows, start=2):
            try:
                payload = JurisdictionService._payload_from_tabular_row(row, source=source)
                valid += 1
                if dry_run:
                    items.append(payload)
                    continue
                asset, was_created = JurisdictionService._upsert_asset(db, payload)
                created += 1 if was_created else 0
                updated += 0 if was_created else 1
                items.append(asset)
            except ValueError as exc:
                errors.append({"row": index, "error": str(exc)})

        if dry_run:
            return {
                "total": len(rows),
                "valid": valid,
                "created": 0,
                "updated": 0,
                "errors": errors,
                "items": items[:20],
            }

        db.commit()
        for asset in items:
            db.refresh(asset)
        return {
            "total": len(rows),
            "valid": valid,
            "created": created,
            "updated": updated,
            "errors": errors,
            "items": [JurisdictionService._asset_to_dict(asset) for asset in items],
        }

    @staticmethod
    def list_assets(
        db: Session,
        asset_type: Optional[str] = None,
        source: Optional[str] = None,
        status: Optional[str] = "active",
        limit: int = 200,
        skip: int = 0,
    ) -> List[JurisdictionAsset]:
        query = db.query(JurisdictionAsset)
        if asset_type:
            query = query.filter(JurisdictionAsset.asset_type == asset_type)
        if source:
            query = query.filter(JurisdictionAsset.source == source)
        if status:
            query = query.filter(JurisdictionAsset.status == status)
        return query.order_by(JurisdictionAsset.id.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def summarize_assets(db: Session) -> Dict[str, Any]:
        assets = db.query(JurisdictionAsset).all()
        by_type: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        by_layer: Dict[str, int] = {}
        for asset in assets:
            by_type[asset.asset_type] = by_type.get(asset.asset_type, 0) + 1
            by_source[asset.source or "unknown"] = by_source.get(asset.source or "unknown", 0) + 1
            by_status[asset.status or "unknown"] = by_status.get(asset.status or "unknown", 0) + 1
            layer = JurisdictionService._asset_data_layer(asset)
            by_layer[layer] = by_layer.get(layer, 0) + 1

        return {
            "total": len(assets),
            "by_type": by_type,
            "by_source": by_source,
            "by_status": by_status,
            "by_layer": by_layer,
            "layer_labels": ASSET_LAYER_LABELS,
        }

    @staticmethod
    def audit_data_quality(db: Session) -> Dict[str, Any]:
        assets = db.query(JurisdictionAsset).all()
        total = len(assets)
        missing_coordinates = sum(
            1 for asset in assets
            if asset.latitude is None or asset.longitude is None
        )
        unverified_count = sum(1 for asset in assets if not asset.verified)
        duplicate_candidates = JurisdictionService._count_duplicate_candidates(assets)
        type_counts: Dict[str, int] = {}
        for asset in assets:
            type_counts[asset.asset_type] = type_counts.get(asset.asset_type, 0) + 1

        missing_public_reference_types = [
            asset_type
            for asset_type in ["road", "village"]
            if type_counts.get(asset_type, 0) == 0
        ]
        missing_required_types = [
            group
            for group, asset_types in BUSINESS_REQUIREMENT_GROUPS.items()
            if not any(type_counts.get(asset_type, 0) > 0 for asset_type in asset_types)
        ]
        penalties = (
            missing_coordinates * 12
            + duplicate_candidates * 8
            + unverified_count * 3
            + len(missing_required_types) * 18
        )
        coverage_score = max(0, min(100, 100 - penalties))
        recommendations = []
        if missing_coordinates:
            recommendations.append(f"补齐 {missing_coordinates} 个要素坐标，否则无法参与空间研判。")
        if duplicate_candidates:
            recommendations.append(f"核并 {duplicate_candidates} 组疑似重复要素，避免风险统计重复。")
        if unverified_count:
            recommendations.append(f"校验 {unverified_count} 个未确认要素，区分地图事实和业务事实。")
        if missing_required_types:
            labels = [REQUIREMENT_LABELS.get(item, item) for item in missing_required_types]
            recommendations.append(f"补齐油区业务资产/防控设施：{'、'.join(labels)}。")
        if missing_public_reference_types:
            labels = "、".join("道路" if item == "road" else "村屯" for item in missing_public_reference_types)
            recommendations.append(
                f"{labels}属于公共地图参考数据，建议从地图服务或离线地图自动导入，不建议人工逐条维护。"
            )
        if not recommendations:
            recommendations.append("底座质量较好，可进入常态化风险画像和布防规划。")

        return {
            "total_assets": total,
            "missing_coordinates": missing_coordinates,
            "unverified_count": unverified_count,
            "duplicate_candidates": duplicate_candidates,
            "type_counts": type_counts,
            "missing_required_types": missing_required_types,
            "missing_public_reference_types": missing_public_reference_types,
            "coverage_score": coverage_score,
            "recommendations": recommendations,
        }

    @staticmethod
    def build_case_risk_context(db: Session, case_id: int) -> Dict[str, Any]:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError("case_not_found")

        base = {
            "case_id": case.id,
            "case_number": case.case_number,
            "case_type": case.case_type,
            "occurred_time": case.occurred_time,
            "has_geo": bool(case.latitude is not None and case.longitude is not None),
            "nearest": {},
            "risk_conditions": [],
            "prevention_opportunities": [],
            "risk_score": 0,
        }
        if not base["has_geo"]:
            base["risk_conditions"].append("案件缺少经纬度，无法计算辖区空间条件。")
            base["prevention_opportunities"].append("先补录案件坐标，再进行道路、村屯、技防和巡逻覆盖分析。")
            return base

        nearest = {
            "road": JurisdictionService._nearest_asset(db, case.latitude, case.longitude, ROAD_TYPES),
            "village": JurisdictionService._nearest_asset(db, case.latitude, case.longitude, VILLAGE_TYPES),
            "production_target": JurisdictionService._nearest_asset(
                db, case.latitude, case.longitude, PRODUCTION_TARGET_TYPES
            ),
            "tech": JurisdictionService._nearest_asset(db, case.latitude, case.longitude, TECH_TYPES),
            "patrol_point": JurisdictionService._nearest_asset(db, case.latitude, case.longitude, PATROL_TYPES),
        }
        base["nearest"] = {
            key: JurisdictionService._distance_to_dict(value)
            for key, value in nearest.items()
        }

        risk_conditions, opportunities, score = JurisdictionService._evaluate_context(case, nearest)
        base["risk_conditions"] = risk_conditions
        base["prevention_opportunities"] = opportunities
        base["risk_score"] = min(100, score)
        return base

    @staticmethod
    def find_similar_targets(db: Session, case_id: int, limit: int = 10) -> Dict[str, Any]:
        context = JurisdictionService.build_case_risk_context(db, case_id)
        if not context["has_geo"]:
            return {"case_id": case_id, "items": [], "basis": context}

        basis_nearest = context["nearest"]
        source_target_id = (
            basis_nearest.get("production_target", {}).get("asset", {}).get("id")
            if basis_nearest.get("production_target") else None
        )
        candidates = db.query(JurisdictionAsset).filter(
            JurisdictionAsset.asset_type.in_(PRODUCTION_TARGET_TYPES),
            JurisdictionAsset.status == "active",
            JurisdictionAsset.latitude.isnot(None),
            JurisdictionAsset.longitude.isnot(None),
        ).all()

        items = []
        for asset in candidates:
            if asset.id == source_target_id:
                continue
            scored = JurisdictionService._score_similar_target(db, asset, basis_nearest)
            if scored["similarity_score"] > 0:
                items.append(scored)

        items.sort(key=lambda item: item["similarity_score"], reverse=True)
        return {
            "case_id": case_id,
            "items": items[:limit],
            "basis": context,
        }

    @staticmethod
    def build_case_experience_card(db: Session, case_id: int) -> Dict[str, Any]:
        case = JurisdictionService._get_case_or_raise(db, case_id)
        context = JurisdictionService.build_case_risk_context(db, case_id)
        time_pattern = JurisdictionService._time_pattern(case.occurred_time)
        modus_tags = [
            value for value in [
                case.modus_operandi,
                case.case_type,
                case.oil_type,
                case.facility_type,
            ] if value
        ]
        defense_gaps = [
            item for item in context["risk_conditions"]
            if "未发现" in item or "缺少" in item or "不足" in item
        ]
        if not defense_gaps:
            defense_gaps = context["prevention_opportunities"][:2]

        reusable_lessons = []
        if time_pattern["period"] in {"夜间", "凌晨"}:
            reusable_lessons.append(f"同类点位应在{time_pattern['period']}加密巡逻或视频巡查。")
        reusable_lessons.extend(context["prevention_opportunities"])
        if case.source_type:
            reusable_lessons.append(f"保留并强化“{case.source_type}”这一有效发现渠道。")

        return {
            "case_id": case.id,
            "case_number": case.case_number,
            "summary": case.description or case.location or case.case_type or "未填写案情摘要",
            "time_pattern": time_pattern,
            "spatial_conditions": context["risk_conditions"],
            "modus_tags": modus_tags,
            "defense_gaps": defense_gaps,
            "reusable_lessons": reusable_lessons,
            "evidence_basis": {
                "nearest": context["nearest"],
                "risk_score": context["risk_score"],
                "source_type": case.source_type,
            },
        }

    @staticmethod
    def build_asset_risk_profile(
        db: Session,
        asset_id: int,
        radius_km: float = 1.0,
    ) -> Dict[str, Any]:
        asset = db.query(JurisdictionAsset).filter(JurisdictionAsset.id == asset_id).first()
        if not asset:
            raise ValueError("asset_not_found")

        related_cases = JurisdictionService._related_cases_near_asset(db, asset, radius_km)
        nearest = {}
        if asset.latitude is not None and asset.longitude is not None:
            nearest = {
                "road": JurisdictionService._distance_to_dict(
                    JurisdictionService._nearest_asset(db, asset.latitude, asset.longitude, ROAD_TYPES)
                ),
                "village": JurisdictionService._distance_to_dict(
                    JurisdictionService._nearest_asset(db, asset.latitude, asset.longitude, VILLAGE_TYPES)
                ),
                "tech": JurisdictionService._distance_to_dict(
                    JurisdictionService._nearest_asset(db, asset.latitude, asset.longitude, TECH_TYPES)
                ),
                "patrol_point": JurisdictionService._distance_to_dict(
                    JurisdictionService._nearest_asset(db, asset.latitude, asset.longitude, PATROL_TYPES)
                ),
            }

        risk_score = min(100, (asset.risk_level or 1) * 8 + len(related_cases) * 22)
        risk_reasons = []
        recommendations = []
        if related_cases:
            risk_reasons.append(f"{radius_km:g} 公里范围内关联已破案件 {len(related_cases)} 起。")
        if nearest.get("road") and nearest["road"]["distance_km"] <= 0.5:
            risk_score = min(100, risk_score + 18)
            risk_reasons.append("临近道路或便道，具备车辆快速接近条件。")
            recommendations.append("围绕邻近道路布置控线巡逻和临时卡控。")
        if not nearest.get("tech") or nearest["tech"]["distance_km"] > 0.5:
            risk_score = min(100, risk_score + 15)
            risk_reasons.append("近距离技防覆盖不足。")
            recommendations.append("补充监控、照明或报警覆盖，并校验夜间可用性。")
        if not nearest.get("patrol_point") or nearest["patrol_point"]["distance_km"] > 1:
            risk_score = min(100, risk_score + 10)
            risk_reasons.append("巡逻签到或卡控点覆盖不足。")
            recommendations.append("设置巡逻签到点或随机回访点。")
        if not risk_reasons:
            risk_reasons.append("暂无明显风险暴露，建议维持基础巡防和数据补全。")

        return {
            "asset": JurisdictionService._asset_to_dict(asset),
            "risk_score": round(risk_score, 1),
            "risk_level": JurisdictionService._risk_level(risk_score),
            "nearest": nearest,
            "related_cases": [
                JurisdictionService._case_to_brief(case, distance_km=distance)
                for case, distance in related_cases
            ],
            "risk_reasons": risk_reasons,
            "recommendations": recommendations,
        }

    @staticmethod
    def build_patrol_plan(
        db: Session,
        case_id: Optional[int] = None,
        asset_ids: Optional[List[int]] = None,
        limit: int = 6,
    ) -> Dict[str, Any]:
        basis: Dict[str, Any] = {}
        targets: List[Dict[str, Any]] = []
        if case_id is not None:
            basis = JurisdictionService.build_case_experience_card(db, case_id)
            similar = JurisdictionService.find_similar_targets(db, case_id, limit=limit)
            target_from_case = similar["basis"]["nearest"].get("production_target")
            if target_from_case:
                targets.append({
                    "asset": target_from_case["asset"],
                    "reason": "已破案件关联生产目标，优先复盘补防。",
                    "priority": 1,
                })
            targets.extend(
                {
                    "asset": item["asset"],
                    "reason": "与已破案件空间条件相似；" + "；".join(item["reasons"][:2]),
                    "priority": index + 2,
                }
                for index, item in enumerate(similar["items"][:limit])
            )
        elif asset_ids:
            assets = db.query(JurisdictionAsset).filter(JurisdictionAsset.id.in_(asset_ids)).all()
            for asset in assets:
                profile = JurisdictionService.build_asset_risk_profile(db, asset.id)
                targets.append({
                    "asset": profile["asset"],
                    "reason": "基于点位风险画像纳入布防。",
                    "priority": 2,
                })
        else:
            assets = db.query(JurisdictionAsset).filter(
                JurisdictionAsset.asset_type.in_(PRODUCTION_TARGET_TYPES),
                JurisdictionAsset.status == "active",
            ).limit(limit).all()
            for asset in assets:
                targets.append({
                    "asset": JurisdictionService._asset_to_dict(asset),
                    "reason": "生产目标基础巡防。",
                    "priority": 3,
                })

        time_windows = JurisdictionService._time_windows_from_basis(basis)
        roads = []
        if case_id is not None:
            context = JurisdictionService.build_case_risk_context(db, case_id)
            road = context["nearest"].get("road")
            if road:
                roads.append({
                    "name": road["asset"]["name"],
                    "type": "road",
                    "reason": "已破案件邻近通道，适合控线巡逻和撤离方向拦截。",
                })

        return {
            "case_id": case_id,
            "control_points": targets[:limit],
            "control_lines": roads,
            "control_areas": [
                {"name": "案件相似条件区域", "reason": "围绕相似井口、道路、村屯组合开展面上巡防。"}
            ],
            "time_windows": time_windows,
            "tactics": [
                "固定巡查 + 随机回访，避免巡逻规律被摸清。",
                "道路入口控线，井口周边控点，村屯周边核查可疑停留车辆。",
                "技防不足点位优先补充视频巡查、照明或临时报警。",
            ],
            "basis": basis,
        }

    @staticmethod
    def materialize_patrol_plan(
        db: Session,
        case_id: Optional[int] = None,
        asset_ids: Optional[List[int]] = None,
        limit: int = 6,
        officer_count: int = 1,
        officer_names: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """把布防建议真正落成巡逻计划记录，形成可执行闭环。"""
        plan = JurisdictionService.build_patrol_plan(
            db,
            case_id=case_id,
            asset_ids=asset_ids,
            limit=limit,
        )
        patrol_records: List[PatrolRecord] = []
        skipped_records: List[PatrolRecord] = []
        related_case_ids = [case_id] if case_id is not None else None

        for item in plan.get("control_points", [])[:limit]:
            asset = item.get("asset") or {}
            area_name = asset.get("name") or "未命名风险点"
            existing = JurisdictionService._find_existing_active_patrol(
                db,
                area_name=area_name,
                case_id=case_id,
                asset_id=asset.get("id"),
            )
            if existing:
                skipped_records.append(existing)
                continue
            area_coordinates = JurisdictionService._control_point_coordinates(asset, item)
            patrol = PatrolService.create_patrol(
                db=db,
                area_name=area_name,
                patrol_type="targeted",
                area_coordinates=area_coordinates,
                officer_count=officer_count,
                officer_names=officer_names,
                related_case_ids=related_case_ids,
                created_by=created_by or "jurisdiction-workbench",
            )
            patrol_records.append(patrol)

        return {
            "created_count": len(patrol_records),
            "skipped_count": len(skipped_records),
            "plan": plan,
            "patrol_records": [
                JurisdictionService._patrol_record_to_dict(record)
                for record in [*patrol_records, *skipped_records]
            ],
        }

    @staticmethod
    def build_roundtable_briefing(db: Session, case_id: int) -> Dict[str, Any]:
        card = JurisdictionService.build_case_experience_card(db, case_id)
        plan = JurisdictionService.build_patrol_plan(db, case_id=case_id)
        top_points = [item["asset"]["name"] for item in plan["control_points"][:3]]
        return {
            "case_id": case_id,
            "agenda": [
                "议题一：复盘已破案件暴露出的作案条件和防控缺口。",
                "议题二：确认相似风险点和本周重点布防范围。",
                "议题三：明确巡逻、技防、核查任务和复盘指标。",
            ],
            "risk_summary": card["spatial_conditions"][:5],
            "recommended_decisions": [
                f"将{', '.join(top_points) if top_points else '相似风险点'}纳入本周重点巡防。",
                "对近距离道路和技防薄弱点同步开展控线与补防。",
            ],
            "tasks": [
                {
                    "title": "相似风险点现场核验",
                    "owner": "属地保卫班",
                    "target": point,
                    "due_in_days": 3,
                    "status": "pending",
                }
                for point in top_points
            ] or [
                {
                    "title": "补录油区业务资产和防控设施",
                    "owner": "研判员",
                    "target": "井点、管线节点、站库、监控、卡口、盲区；道路村屯走地图参考导入",
                    "due_in_days": 5,
                    "status": "pending",
                }
            ],
            "patrol_plan": plan,
        }

    @staticmethod
    def record_feedback(db: Session, data: Dict[str, Any]) -> JurisdictionFeedback:
        feedback = JurisdictionFeedback(**data)
        db.add(feedback)
        db.commit()
        db.refresh(feedback)
        return feedback

    @staticmethod
    def summarize_effectiveness(db: Session) -> Dict[str, Any]:
        feedback_items = db.query(JurisdictionFeedback).all()
        scores = [
            item.effectiveness_score for item in feedback_items
            if item.effectiveness_score is not None
        ]
        adopted_count = sum(1 for item in feedback_items if item.adopted)
        by_type: Dict[str, int] = {}
        for item in feedback_items:
            by_type[item.feedback_type] = by_type.get(item.feedback_type, 0) + 1
        return {
            "total_feedback": len(feedback_items),
            "adopted_count": adopted_count,
            "adoption_rate": round(adopted_count / len(feedback_items), 3) if feedback_items else 0,
            "average_effectiveness": round(sum(scores) / len(scores), 1) if scores else None,
            "by_type": by_type,
            "recent": [
                JurisdictionService._feedback_to_dict(item)
                for item in feedback_items[-10:]
            ],
        }

    @staticmethod
    def build_prevention_workbench(db: Session, case_id: Optional[int] = None) -> Dict[str, Any]:
        data_quality = JurisdictionService.audit_data_quality(db)
        effectiveness = JurisdictionService.summarize_effectiveness(db)
        payload: Dict[str, Any] = {
            "case_id": case_id,
            "data_quality": data_quality,
            "effectiveness": effectiveness,
        }
        if case_id is None:
            payload["patrol_plan"] = JurisdictionService.build_patrol_plan(db)
            payload["summary"] = "未选择案件，展示地图参考、业务资产质量和基础巡防建议。"
            return payload

        payload.update({
            "experience_card": JurisdictionService.build_case_experience_card(db, case_id),
            "risk_context": JurisdictionService.build_case_risk_context(db, case_id),
            "similar_targets": JurisdictionService.find_similar_targets(db, case_id, limit=8),
            "patrol_plan": JurisdictionService.build_patrol_plan(db, case_id=case_id, limit=8),
            "roundtable_briefing": JurisdictionService.build_roundtable_briefing(db, case_id),
        })
        return payload

    @staticmethod
    def _nearest_asset(
        db: Session,
        latitude: float,
        longitude: float,
        asset_types: Iterable[str],
    ) -> Optional[AssetDistance]:
        assets = db.query(JurisdictionAsset).filter(
            JurisdictionAsset.asset_type.in_(list(asset_types)),
            JurisdictionAsset.status == "active",
            JurisdictionAsset.latitude.isnot(None),
            JurisdictionAsset.longitude.isnot(None),
        ).all()
        if not assets:
            return None

        nearest = min(
            assets,
            key=lambda asset: haversine_km(latitude, longitude, asset.latitude, asset.longitude),
        )
        return AssetDistance(
            asset=nearest,
            distance_km=haversine_km(latitude, longitude, nearest.latitude, nearest.longitude),
        )

    @staticmethod
    def _asset_data_layer(asset: JurisdictionAsset) -> str:
        asset_type = asset.asset_type or ""
        source = asset.source or ""
        if asset_type.startswith("derived_"):
            return "analysis_derived"
        if asset_type in PUBLIC_MAP_REFERENCE_TYPES:
            return "public_map_reference"
        if asset_type in BUSINESS_ASSET_TYPES or source in {"manual", "ledger", "import"}:
            return "oil_business_asset"
        return "other"

    @staticmethod
    def _resolve_public_map_bounds(
        db: Session,
        *,
        south: Optional[float],
        west: Optional[float],
        north: Optional[float],
        east: Optional[float],
        center_lat: Optional[float],
        center_lng: Optional[float],
        radius_km: float,
    ) -> Dict[str, float]:
        if None not in (south, west, north, east):
            resolved = {
                "south": float(south),
                "west": float(west),
                "north": float(north),
                "east": float(east),
            }
            JurisdictionService._validate_bounds(resolved)
            return resolved

        center: Optional[tuple[float, float]] = None
        if center_lat is not None and center_lng is not None:
            center = (float(center_lat), float(center_lng))
        else:
            coordinates = JurisdictionService._reference_coordinates(db)
            if coordinates:
                center = (
                    sum(item[0] for item in coordinates) / len(coordinates),
                    sum(item[1] for item in coordinates) / len(coordinates),
                )

        if center is None:
            raise ValueError("缺少案件或业务资产坐标，无法自动确定公共地图拉取范围")

        radius = max(0.2, min(float(radius_km or DEFAULT_PUBLIC_MAP_RADIUS_KM), MAX_PUBLIC_MAP_RADIUS_KM))
        return JurisdictionService._bounds_from_center(center[0], center[1], radius)

    @staticmethod
    def _reference_coordinates(db: Session) -> List[tuple[float, float]]:
        coordinates: List[tuple[float, float]] = []
        cases = db.query(Case.latitude, Case.longitude).filter(
            Case.latitude.isnot(None),
            Case.longitude.isnot(None),
        ).limit(200).all()
        assets = db.query(JurisdictionAsset.latitude, JurisdictionAsset.longitude).filter(
            JurisdictionAsset.latitude.isnot(None),
            JurisdictionAsset.longitude.isnot(None),
            JurisdictionAsset.status == "active",
        ).limit(200).all()
        for latitude, longitude in [*cases, *assets]:
            try:
                coordinates.append((float(latitude), float(longitude)))
            except (TypeError, ValueError):
                continue
        return coordinates

    @staticmethod
    def _bounds_from_center(latitude: float, longitude: float, radius_km: float) -> Dict[str, float]:
        lat_delta = radius_km / 111.32
        lng_factor = max(math.cos(math.radians(latitude)), 0.2)
        lng_delta = radius_km / (111.32 * lng_factor)
        bounds = {
            "south": max(-90.0, latitude - lat_delta),
            "west": max(-180.0, longitude - lng_delta),
            "north": min(90.0, latitude + lat_delta),
            "east": min(180.0, longitude + lng_delta),
        }
        return {key: round(value, 6) for key, value in bounds.items()}

    @staticmethod
    def _validate_bounds(bounds: Dict[str, float]) -> None:
        if bounds["south"] >= bounds["north"] or bounds["west"] >= bounds["east"]:
            raise ValueError("地图拉取范围无效")
        lat_span_km = (bounds["north"] - bounds["south"]) * 111.32
        center_lat = (bounds["north"] + bounds["south"]) / 2
        lng_span_km = (bounds["east"] - bounds["west"]) * 111.32 * max(math.cos(math.radians(center_lat)), 0.2)
        if max(lat_span_km, lng_span_km) > MAX_PUBLIC_MAP_RADIUS_KM * 2:
            raise ValueError("地图拉取范围过大，请缩小到约 40 公里以内")

    @staticmethod
    def _build_overpass_public_map_query(bounds: Dict[str, float]) -> str:
        bbox = f"{bounds['south']},{bounds['west']},{bounds['north']},{bounds['east']}"
        return f"""
[out:json][timeout:25];
(
  way["highway"]({bbox});
  node["place"~"^(village|hamlet|town|neighbourhood|suburb|isolated_dwelling)$"]({bbox});
  way["waterway"~"^(river|stream|canal|ditch)$"]({bbox});
  way["bridge"="yes"]({bbox});
  node["highway"~"^(traffic_signals|crossing|stop|give_way)$"]({bbox});
);
out body geom qt;
"""

    @staticmethod
    def _fetch_public_map_elements(query: str) -> List[Dict[str, Any]]:
        with httpx.Client(timeout=30.0, headers={"User-Agent": "AiCommander/1.0 public-map-sync"}) as client:
            response = client.post(OVERPASS_API_URL, data={"data": query})
            response.raise_for_status()
            payload = response.json()
        elements = payload.get("elements", [])
        return elements if isinstance(elements, list) else []

    @staticmethod
    def _osm_elements_to_geojson_features(elements: List[Dict[str, Any]], max_features: int) -> List[Dict[str, Any]]:
        features: List[Dict[str, Any]] = []
        for element in elements:
            feature = JurisdictionService._osm_element_to_geojson_feature(element)
            if not feature:
                continue
            features.append(feature)
            if len(features) >= max_features:
                break
        return features

    @staticmethod
    def _osm_element_to_geojson_feature(element: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        tags = element.get("tags") or {}
        asset_type = JurisdictionService._asset_type_from_osm_tags(tags)
        if not asset_type:
            return None

        geometry = JurisdictionService._geometry_from_osm_element(element)
        if not geometry:
            return None

        osm_type = str(element.get("type") or "element")
        osm_id = str(element.get("id") or "")
        name = (
            tags.get("name:zh")
            or tags.get("name")
            or tags.get("official_name")
            or JurisdictionService._fallback_osm_name(asset_type, osm_id)
        )
        return {
            "type": "Feature",
            "properties": {
                "id": f"osm:{osm_type}:{osm_id}",
                "name": name,
                "asset_type": asset_type,
                "description": "OpenStreetMap 公共地图参考自动拉取",
                "status": "active",
                "risk_level": 1,
                "confidence_score": 0.78,
                "verified": True,
                "provider": "openstreetmap",
                "osm_type": osm_type,
                "osm_id": osm_id,
                "osm_tags": tags,
            },
            "geometry": geometry,
        }

    @staticmethod
    def _asset_type_from_osm_tags(tags: Dict[str, Any]) -> Optional[str]:
        if tags.get("bridge") == "yes":
            return "bridge"
        if tags.get("highway") in {"traffic_signals", "crossing", "stop", "give_way"}:
            return "intersection"
        if tags.get("waterway"):
            return "river"
        place = tags.get("place")
        if place in {"village", "hamlet", "isolated_dwelling"}:
            return "village"
        if place in {"town", "suburb", "neighbourhood"}:
            return "settlement"
        if tags.get("highway"):
            return "road"
        return None

    @staticmethod
    def _geometry_from_osm_element(element: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        element_type = element.get("type")
        if element_type == "node":
            lat = element.get("lat")
            lon = element.get("lon")
            if lat is None or lon is None:
                return None
            return {"type": "Point", "coordinates": [float(lon), float(lat)]}

        if element_type == "way":
            geometry = element.get("geometry")
            if not isinstance(geometry, list):
                return None
            coordinates = [
                [float(point["lon"]), float(point["lat"])]
                for point in geometry
                if isinstance(point, dict) and point.get("lat") is not None and point.get("lon") is not None
            ]
            if len(coordinates) < 2:
                return None
            return {"type": "LineString", "coordinates": coordinates}
        return None

    @staticmethod
    def _fallback_osm_name(asset_type: str, osm_id: str) -> str:
        labels = {
            "road": "未命名道路",
            "village": "未命名村屯",
            "settlement": "未命名聚落",
            "river": "未命名水系",
            "bridge": "未命名桥梁",
            "intersection": "交通节点",
        }
        return f"{labels.get(asset_type, '地图要素')}-{osm_id}"

    @staticmethod
    def _payload_from_geojson_feature(feature: Dict[str, Any], source: str) -> Dict[str, Any]:
        if feature.get("type") != "Feature":
            raise ValueError("不是 GeoJSON Feature")
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if not geometry:
            raise ValueError("缺少 geometry")
        latitude, longitude = JurisdictionService._geometry_center(geometry)
        asset_type = properties.get("asset_type") or properties.get("type") or "other"
        name = properties.get("name") or properties.get("NAME") or properties.get("title")
        if not name:
            raise ValueError("缺少 name")
        return {
            "external_id": str(properties.get("id") or properties.get("external_id") or name),
            "name": str(name),
            "asset_type": str(asset_type),
            "geometry_type": str(geometry.get("type", "point")).lower(),
            "latitude": latitude,
            "longitude": longitude,
            "geometry": geometry,
            "address": properties.get("address"),
            "description": properties.get("description"),
            "source": source,
            "status": properties.get("status") or "active",
            "risk_level": int(properties.get("risk_level") or 1),
            "confidence_score": float(properties.get("confidence_score") or 0.7),
            "verified": bool(properties.get("verified") or False),
            "last_seen_at": datetime.utcnow(),
            "tags": properties.get("tags"),
            "attributes": {
                key: value
                for key, value in properties.items()
                if key not in {
                    "id", "external_id", "name", "NAME", "title", "asset_type",
                    "type", "address", "description", "status", "risk_level",
                    "confidence_score", "verified", "tags",
                }
            },
        }

    @staticmethod
    def _payload_from_tabular_row(row: Dict[str, Any], source: str) -> Dict[str, Any]:
        normalized = {
            str(key).strip(): value
            for key, value in row.items()
            if key is not None and str(key).strip()
        }
        name = JurisdictionService._clean_text(
            normalized.get("name") or normalized.get("名称") or normalized.get("要素名称")
        )
        asset_type = JurisdictionService._clean_text(
            normalized.get("asset_type") or normalized.get("类型") or normalized.get("要素类型")
        )
        if not name:
            raise ValueError("缺少 name/名称")
        if not asset_type:
            raise ValueError("缺少 asset_type/类型")

        row_source = JurisdictionService._clean_text(normalized.get("source") or normalized.get("来源")) or source
        latitude = JurisdictionService._optional_float(normalized.get("latitude") or normalized.get("纬度"))
        longitude = JurisdictionService._optional_float(normalized.get("longitude") or normalized.get("经度"))
        geometry = None
        if latitude is not None and longitude is not None:
            geometry = {"type": "Point", "coordinates": [longitude, latitude]}

        return {
            "external_id": JurisdictionService._clean_text(
                normalized.get("external_id") or normalized.get("id") or normalized.get("外部ID")
            ),
            "name": name,
            "asset_type": asset_type,
            "geometry_type": JurisdictionService._clean_text(normalized.get("geometry_type") or normalized.get("几何类型")) or "point",
            "latitude": latitude,
            "longitude": longitude,
            "geometry": geometry,
            "address": JurisdictionService._clean_text(normalized.get("address") or normalized.get("地址")),
            "description": JurisdictionService._clean_text(normalized.get("description") or normalized.get("说明") or normalized.get("备注")),
            "source": row_source,
            "status": JurisdictionService._clean_text(normalized.get("status") or normalized.get("状态")) or "active",
            "risk_level": JurisdictionService._optional_int(normalized.get("risk_level") or normalized.get("风险等级"), default=1),
            "confidence_score": JurisdictionService._optional_float(
                normalized.get("confidence_score") or normalized.get("置信度"),
                default=0.8,
            ),
            "verified": JurisdictionService._optional_bool(normalized.get("verified") or normalized.get("已校验")),
            "tags": JurisdictionService._parse_tags(normalized.get("tags") or normalized.get("标签")),
            "attributes": {
                key: value for key, value in normalized.items()
                if key not in {
                    "external_id", "id", "外部ID", "name", "名称", "要素名称",
                    "asset_type", "类型", "要素类型", "geometry_type", "几何类型",
                    "latitude", "纬度", "longitude", "经度", "address", "地址",
                    "description", "说明", "备注", "source", "来源", "status", "状态",
                    "risk_level", "风险等级", "confidence_score", "置信度",
                    "verified", "已校验", "tags", "标签",
                }
            },
        }

    @staticmethod
    def _geometry_center(geometry: Dict[str, Any]) -> tuple[float, float]:
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        points = JurisdictionService._flatten_coordinates(geometry_type, coordinates)
        if not points:
            raise ValueError("geometry 坐标为空")
        lon = sum(point[0] for point in points) / len(points)
        lat = sum(point[1] for point in points) / len(points)
        return round(lat, 6), round(lon, 6)

    @staticmethod
    def _flatten_coordinates(geometry_type: str, coordinates: Any) -> List[List[float]]:
        if geometry_type == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
            return [coordinates]
        if geometry_type == "LineString" and isinstance(coordinates, list):
            return [point for point in coordinates if isinstance(point, list) and len(point) >= 2]
        if geometry_type == "Polygon" and isinstance(coordinates, list):
            return [
                point
                for ring in coordinates if isinstance(ring, list)
                for point in ring if isinstance(point, list) and len(point) >= 2
            ]
        return []

    @staticmethod
    def _clean_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text if text and text.lower() != "none" else None

    @staticmethod
    def _optional_float(value: Any, default: Optional[float] = None) -> Optional[float]:
        if value in (None, "", "None"):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _optional_int(value: Any, default: Optional[int] = None) -> Optional[int]:
        if value in (None, "", "None"):
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _optional_bool(value: Any, default: bool = False) -> bool:
        if value in (None, "", "None"):
            return default
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "是", "已", "已校验"}:
            return True
        if text in {"0", "false", "no", "n", "否", "未", "未校验"}:
            return False
        return default

    @staticmethod
    def _parse_tags(value: Any) -> List[str]:
        text = JurisdictionService._clean_text(value)
        if not text:
            return []
        for separator in (";", "；", ",", "，"):
            text = text.replace(separator, "|")
        return [item.strip() for item in text.split("|") if item.strip()]

    @staticmethod
    def _upsert_asset(db: Session, payload: Dict[str, Any]) -> tuple[JurisdictionAsset, bool]:
        existing = None
        external_id = payload.get("external_id")
        if external_id:
            existing = db.query(JurisdictionAsset).filter(
                JurisdictionAsset.external_id == external_id,
                JurisdictionAsset.source == payload.get("source"),
            ).first()
        if existing is None:
            existing = db.query(JurisdictionAsset).filter(
                JurisdictionAsset.name == payload["name"],
                JurisdictionAsset.asset_type == payload["asset_type"],
                JurisdictionAsset.source == payload.get("source"),
            ).first()

        if existing is None:
            asset = JurisdictionAsset(**payload)
            db.add(asset)
            return asset, True

        for key, value in payload.items():
            setattr(existing, key, value)
        return existing, False

    @staticmethod
    def _count_duplicate_candidates(assets: List[JurisdictionAsset]) -> int:
        duplicate_keys: set[tuple[str, str]] = set()
        seen: Dict[tuple[str, str], JurisdictionAsset] = {}
        for asset in assets:
            key = (asset.name, asset.asset_type)
            if key in seen:
                duplicate_keys.add(key)
                continue
            seen[key] = asset
        return len(duplicate_keys)

    @staticmethod
    def _get_case_or_raise(db: Session, case_id: int) -> Case:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError("case_not_found")
        return case

    @staticmethod
    def _time_pattern(occurred_time: Optional[datetime]) -> Dict[str, Any]:
        if not occurred_time:
            return {"period": "未知", "hour": None, "weekday": None}
        hour = occurred_time.hour
        if 0 <= hour < 6:
            period = "凌晨"
        elif 6 <= hour < 12:
            period = "上午"
        elif 12 <= hour < 18:
            period = "下午"
        else:
            period = "夜间"
        return {
            "period": period,
            "hour": hour,
            "weekday": occurred_time.weekday(),
            "is_night": period in {"夜间", "凌晨"},
        }

    @staticmethod
    def _related_cases_near_asset(
        db: Session,
        asset: JurisdictionAsset,
        radius_km: float,
    ) -> List[tuple[Case, float]]:
        if asset.latitude is None or asset.longitude is None:
            return []
        cases = db.query(Case).filter(
            Case.latitude.isnot(None),
            Case.longitude.isnot(None),
        ).all()
        related = []
        for case in cases:
            distance = haversine_km(asset.latitude, asset.longitude, case.latitude, case.longitude)
            if distance <= radius_km:
                related.append((case, round(distance, 3)))
        related.sort(key=lambda item: item[1])
        return related

    @staticmethod
    def _time_windows_from_basis(basis: Dict[str, Any]) -> List[Dict[str, str]]:
        period = basis.get("time_pattern", {}).get("period")
        if period == "凌晨":
            return [{"period": "00:00-04:00", "reason": "样本案件发生于凌晨，建议重点覆盖。"}]
        if period == "夜间":
            return [{"period": "22:00-02:00", "reason": "样本案件发生于夜间，建议前后延伸巡防。"}]
        return [{"period": "23:00-04:00", "reason": "涉油盗窃高隐蔽时段，建议作为默认重点窗口。"}]

    @staticmethod
    def _risk_level(score: float) -> str:
        if score >= 80:
            return "critical"
        if score >= 60:
            return "high"
        if score >= 35:
            return "medium"
        return "low"

    @staticmethod
    def _case_to_brief(case: Case, distance_km: Optional[float] = None) -> Dict[str, Any]:
        return {
            "id": case.id,
            "case_number": case.case_number,
            "case_type": case.case_type,
            "occurred_time": case.occurred_time,
            "location": case.location,
            "modus_operandi": case.modus_operandi,
            "distance_km": distance_km,
        }

    @staticmethod
    def _feedback_to_dict(feedback: JurisdictionFeedback) -> Dict[str, Any]:
        return {
            "id": feedback.id,
            "case_id": feedback.case_id,
            "asset_id": feedback.asset_id,
            "feedback_type": feedback.feedback_type,
            "adopted": feedback.adopted,
            "result": feedback.result,
            "effectiveness_score": feedback.effectiveness_score,
            "notes": feedback.notes,
            "created_at": feedback.created_at,
        }

    @staticmethod
    def _control_point_coordinates(asset: Dict[str, Any], item: Dict[str, Any]) -> List[Dict[str, Any]]:
        latitude = asset.get("latitude")
        longitude = asset.get("longitude")
        if latitude is None or longitude is None:
            return []
        return [{
            "asset_id": asset.get("id"),
            "name": asset.get("name"),
            "latitude": latitude,
            "longitude": longitude,
            "priority": item.get("priority"),
            "reason": item.get("reason"),
        }]

    @staticmethod
    def _find_existing_active_patrol(
        db: Session,
        area_name: str,
        case_id: Optional[int],
        asset_id: Optional[int],
    ) -> Optional[PatrolRecord]:
        patrols = db.query(PatrolRecord).filter(
            PatrolRecord.area_name == area_name,
            PatrolRecord.status.in_(("planned", "in_progress")),
        ).all()
        for patrol in patrols:
            related_case_ids = patrol.related_case_ids or []
            if case_id is not None and case_id in related_case_ids:
                return patrol
            for point in patrol.area_coordinates or []:
                if asset_id is not None and point.get("asset_id") == asset_id:
                    return patrol
        return None

    @staticmethod
    def _patrol_record_to_dict(record: PatrolRecord) -> Dict[str, Any]:
        return {
            "id": record.id,
            "patrol_number": record.patrol_number,
            "patrol_type": record.patrol_type,
            "area_name": record.area_name,
            "area_coordinates": record.area_coordinates or [],
            "officer_count": record.officer_count,
            "officer_names": record.officer_names,
            "status": record.status,
            "related_case_ids": record.related_case_ids or [],
            "risk_before": record.risk_before,
            "created_by": record.created_by,
            "created_at": record.created_at,
        }

    @staticmethod
    def _evaluate_context(
        case: Case,
        nearest: Dict[str, Optional[AssetDistance]],
    ) -> tuple[List[str], List[str], int]:
        conditions: List[str] = []
        opportunities: List[str] = []
        score = 0

        road = nearest.get("road")
        if road and road.distance_km <= 0.5:
            score += 25
            conditions.append(f"距最近道路约 {road.distance_km:.2f} 公里，车辆接近和撤离便利。")
            opportunities.append("围绕邻近道路设置夜间巡逻回访和临时卡控点。")
        elif road:
            conditions.append(f"距最近道路约 {road.distance_km:.2f} 公里，道路通达性需结合现场核验。")

        village = nearest.get("village")
        if village and 0.3 <= village.distance_km <= 3:
            score += 15
            conditions.append(f"距最近村屯约 {village.distance_km:.2f} 公里，具备人员车辆短时流动条件。")
            opportunities.append("对村屯周边停车点、修理点和夜间车辆流动开展针对性核查。")
        elif village:
            conditions.append(f"距最近村屯约 {village.distance_km:.2f} 公里。")

        target = nearest.get("production_target")
        if target and target.distance_km <= 0.5:
            score += 20
            conditions.append(f"距生产目标约 {target.distance_km:.2f} 公里，案件与油区目标条件高度相关。")

        tech = nearest.get("tech")
        if tech is None or tech.distance_km > 0.5:
            score += 15
            conditions.append("500 米范围内未发现有效技防设施，存在监控或照明覆盖不足风险。")
            opportunities.append("补齐监控、照明、报警或视频巡查覆盖，并校验夜间可用性。")
        else:
            conditions.append(f"距最近技防设施约 {tech.distance_km:.2f} 公里，可复核覆盖角度和夜间成像效果。")

        patrol_point = nearest.get("patrol_point")
        if patrol_point is None or patrol_point.distance_km > 1:
            score += 10
            conditions.append("1 公里范围内缺少巡逻签到或卡控点，巡逻覆盖需要补强。")
            opportunities.append("将附近道路入口、井场周边纳入巡逻签到点或随机回访点。")

        if case.modus_operandi:
            score += 10
            conditions.append(f"已记录作案方式：{case.modus_operandi}，可用于相似条件检索。")
        if case.source_type:
            conditions.append(f"发现来源为{case.source_type}，可反推有效发现机制和薄弱环节。")

        return conditions, opportunities, score

    @staticmethod
    def _score_similar_target(
        db: Session,
        asset: JurisdictionAsset,
        basis_nearest: Dict[str, Any],
    ) -> Dict[str, Any]:
        candidate_nearest = {
            "road": JurisdictionService._nearest_asset(db, asset.latitude, asset.longitude, ROAD_TYPES),
            "village": JurisdictionService._nearest_asset(db, asset.latitude, asset.longitude, VILLAGE_TYPES),
            "tech": JurisdictionService._nearest_asset(db, asset.latitude, asset.longitude, TECH_TYPES),
            "patrol_point": JurisdictionService._nearest_asset(db, asset.latitude, asset.longitude, PATROL_TYPES),
        }

        score = 0
        reasons: List[str] = []
        gaps: List[str] = []
        score += 15
        reasons.append("同属油区生产目标，可复用已破案件经验。")

        score += JurisdictionService._distance_similarity_points(
            label="道路",
            basis=basis_nearest.get("road"),
            candidate=candidate_nearest.get("road"),
            tolerance_km=0.3,
            points=25,
            reasons=reasons,
        )
        score += JurisdictionService._distance_similarity_points(
            label="村屯",
            basis=basis_nearest.get("village"),
            candidate=candidate_nearest.get("village"),
            tolerance_km=0.8,
            points=20,
            reasons=reasons,
        )

        basis_tech_distance = JurisdictionService._extract_distance(basis_nearest.get("tech"))
        candidate_tech_distance = candidate_nearest["tech"].distance_km if candidate_nearest["tech"] else None
        if (basis_tech_distance is None or basis_tech_distance > 0.5) and (
            candidate_tech_distance is None or candidate_tech_distance > 0.5
        ):
            score += 15
            reasons.append("同样存在近距离技防覆盖不足特征。")
            gaps.append("建议核验监控、照明和报警覆盖。")

        patrol_distance = candidate_nearest["patrol_point"].distance_km if candidate_nearest["patrol_point"] else None
        if patrol_distance is None or patrol_distance > 1:
            score += 10
            gaps.append("建议补充巡逻签到点或随机回访。")

        return {
            "asset": JurisdictionService._asset_to_dict(asset),
            "similarity_score": min(100, score),
            "reasons": reasons,
            "risk_gaps": gaps,
            "nearest": {
                key: JurisdictionService._distance_to_dict(value)
                for key, value in candidate_nearest.items()
            },
        }

    @staticmethod
    def _distance_similarity_points(
        label: str,
        basis: Optional[Dict[str, Any]],
        candidate: Optional[AssetDistance],
        tolerance_km: float,
        points: int,
        reasons: List[str],
    ) -> int:
        basis_distance = JurisdictionService._extract_distance(basis)
        if basis_distance is None or candidate is None:
            return 0
        diff = abs(candidate.distance_km - basis_distance)
        if diff <= tolerance_km:
            reasons.append(
                f"{label}距离相似：样本 {basis_distance:.2f} 公里，目标 {candidate.distance_km:.2f} 公里。"
            )
            return points
        return 0

    @staticmethod
    def _extract_distance(distance_payload: Optional[Dict[str, Any]]) -> Optional[float]:
        if not distance_payload:
            return None
        distance = distance_payload.get("distance_km")
        return float(distance) if distance is not None else None

    @staticmethod
    def _distance_to_dict(distance: Optional[AssetDistance]) -> Optional[Dict[str, Any]]:
        if distance is None:
            return None
        return {
            "asset": JurisdictionService._asset_to_dict(distance.asset),
            "distance_km": round(distance.distance_km, 3),
        }

    @staticmethod
    def _asset_to_dict(asset: JurisdictionAsset) -> Dict[str, Any]:
        return {
            "id": asset.id,
            "external_id": asset.external_id,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "geometry_type": asset.geometry_type,
            "latitude": asset.latitude,
            "longitude": asset.longitude,
            "address": asset.address,
            "description": asset.description,
            "source": asset.source,
            "status": asset.status,
            "risk_level": asset.risk_level,
            "confidence_score": asset.confidence_score,
            "verified": asset.verified,
            "last_seen_at": asset.last_seen_at,
            "tags": asset.tags or [],
            "attributes": asset.attributes or {},
        }
