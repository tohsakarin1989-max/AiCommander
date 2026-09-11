"""Frozen dual-domain v3.4 scoring implementation; add a new module for rule changes."""
from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature
from app.repositories.spatial_repository import SpatialRepository

VERSION = "dual-domain-3.4.0"
SOURCE_TYPES = {"well", "pipeline_node", "station", "valve", "production_target"}
STORAGE_TYPES = {"storage", "oil_depot", "village", "residential", "settlement"}
ROAD_TYPES = {"road", "path", "access_road", "internal_route", "temporary_route"}


class DualDomainV34:
    @staticmethod
    def _build_candidates(
        db: Session,
        case: Case,
        profile: CaseAnalysisProfile,
        snapshot: MapSnapshot,
        repository=SpatialRepository,
    ) -> list[dict[str, Any]]:
        candidates = []
        candidates.extend(DualDomainV34._source_candidates(db, case, profile, snapshot, repository))
        candidates.extend(DualDomainV34._storage_candidates(db, case, profile, snapshot, repository))
        activity = DualDomainV34._activity_candidate(db, case, profile, snapshot, repository)
        if activity:
            candidates.append(activity)
        candidates.extend(DualDomainV34._route_candidates(db, case, profile, snapshot, repository))
        candidates.sort(key=lambda item: (-item["score"], item["hypothesis_type"], item["title"]))
        return candidates[:3]

    @staticmethod
    def _source_candidates(db: Session, case: Case, profile: CaseAnalysisProfile, snapshot: MapSnapshot, repository=SpatialRepository) -> list[dict[str, Any]]:
        nearby = repository.nearby_assets(
            db,
            latitude=case.latitude,
            longitude=case.longitude,
            asset_types=SOURCE_TYPES,
            radius_km=20,
            operational_area_id=case.operational_area_id or snapshot.operational_area_id,
            snapshot_id=snapshot.id,
            limit=10,
        )
        if not nearby:
            return []
        scored_assets = []
        for candidate_asset, candidate_distance in nearby:
            attributes = candidate_asset.attributes or {}
            distance_score = max(0.0, 80.0 - candidate_distance * 8)
            oil_match = (
                10.0
                if case.oil_type and attributes.get("oil_type") == case.oil_type
                else 0.0
            )
            try:
                production_output = float(attributes.get("production_output") or 0)
            except (TypeError, ValueError):
                production_output = 0.0
            production = 10.0 if production_output >= 80 else 0.0
            score = round(min(100.0, distance_score + oil_match + production), 2)
            scored_assets.append(
                (
                    -score,
                    candidate_distance,
                    DualDomainV34._source_asset_id(candidate_asset),
                    candidate_asset,
                    distance_score,
                    oil_match,
                    production,
                )
            )
        (
            negative_score,
            distance,
            _,
            asset,
            distance_score,
            oil_match,
            production,
        ) = min(scored_assets)
        score = -negative_score
        counter = ["空间接近不等同于已确认盗取来源"]
        if not asset.verified:
            counter.append("该设施尚未通过内部来源核验")
        gaps = [] if case.oil_type else ["案件未记录油品类型，无法核验油品匹配"]
        return [{
            "hypothesis_type": "possible_source",
            "title": f"可能盗取来源候选：{asset.name}",
            "claim": f"该生产设施距案发点约 {distance:.2f} 公里，建议作为来源核查候选。",
            "score": score,
            "confidence": DualDomainV34._confidence(score),
            "region": DualDomainV34._point_region(asset.latitude, asset.longitude, 500),
            "evidence_refs": [f"case_profile:{profile.id}", f"map_asset:{DualDomainV34._source_asset_id(asset)}@snapshot:{snapshot.id}"],
            "supporting_evidence": [f"设施与案发点距离约 {distance:.2f} 公里", f"设施类型为 {asset.asset_type}"],
            "counter_evidence": counter,
            "information_gaps": gaps,
            "score_components": {"distance": round(distance_score, 2), "oil_match": oil_match, "production": production},
        }]

    @staticmethod
    def _storage_candidates(db: Session, case: Case, profile: CaseAnalysisProfile, snapshot: MapSnapshot, repository=SpatialRepository) -> list[dict[str, Any]]:
        nearby = repository.nearby_assets(
            db,
            latitude=case.latitude,
            longitude=case.longitude,
            asset_types=STORAGE_TYPES,
            radius_km=15,
            operational_area_id=case.operational_area_id or snapshot.operational_area_id,
            snapshot_id=snapshot.id,
            limit=10,
        )
        if not nearby:
            return []
        asset, distance = nearby[0]
        score = round(max(20.0, 72.0 - distance * 5 + (8 if asset.verified else 0)), 2)
        return [{
            "hypothesis_type": "storage_area",
            "title": f"囤储核查候选区：{asset.name}",
            "claim": f"该区域距案发点约 {distance:.2f} 公里，具备进一步核查的空间条件。",
            "score": score,
            "confidence": DualDomainV34._confidence(score),
            "region": DualDomainV34._point_region(asset.latitude, asset.longitude, 800),
            "evidence_refs": [f"case_profile:{profile.id}", f"map_asset:{DualDomainV34._source_asset_id(asset)}@snapshot:{snapshot.id}"],
            "supporting_evidence": [f"距案发点约 {distance:.2f} 公里", f"地图类型为 {asset.asset_type}"],
            "counter_evidence": ["地图用途或聚落属性不能证明存在非法囤储行为"],
            "information_gaps": ["缺少现场核查、车辆停留或技防事件佐证"],
            "score_components": {"distance": round(max(0.0, 72.0 - distance * 5), 2), "verified": 8 if asset.verified else 0},
        }]

    @staticmethod
    def _activity_candidate(db: Session, case: Case, profile: CaseAnalysisProfile, snapshot: MapSnapshot, repository=SpatialRepository) -> dict[str, Any] | None:
        historical = [
            (item, distance)
            for item, distance in repository.nearby_cases(db, case=case, radius_km=30, limit=50)
            if item.case_type == case.case_type or (item.modus_operandi and item.modus_operandi == case.modus_operandi)
        ]
        if len(historical) < 2:
            return None
        selected = historical[:10]
        center_lat = sum(item.latitude for item, _ in selected) / len(selected)
        center_lon = sum(item.longitude for item, _ in selected) / len(selected)
        score = min(85.0, 45.0 + len(selected) * 8)
        return {
            "hypothesis_type": "activity_area",
            "title": "可能活动或落脚候选区",
            "claim": f"{len(selected)} 起同类或同手法历史案件在该区域形成空间聚集，建议按网格核查。",
            "score": score,
            "confidence": DualDomainV34._confidence(score),
            "region": DualDomainV34._point_region(center_lat, center_lon, 1500),
            "evidence_refs": [f"case_profile:{profile.id}", *[f"case:{item.id}" for item, _ in selected]],
            "supporting_evidence": [f"同类或同手法历史案件 {len(selected)} 起", "仅输出区域网格，不输出具体住址"],
            "counter_evidence": ["历史案件聚集可能由报案密度或生产设施分布造成"],
            "information_gaps": ["缺少人员活动、车辆停留或技防聚合数据"],
            "score_components": {"historical_case_count": len(selected), "cluster_score": score},
        }

    @staticmethod
    def _route_candidates(db: Session, case: Case, profile: CaseAnalysisProfile, snapshot: MapSnapshot, repository=SpatialRepository) -> list[dict[str, Any]]:
        roads = repository.nearby_assets(
            db,
            latitude=case.latitude,
            longitude=case.longitude,
            asset_types=ROAD_TYPES,
            radius_km=5,
            operational_area_id=case.operational_area_id or snapshot.operational_area_id,
            snapshot_id=snapshot.id,
            limit=10,
        )
        if not roads:
            return []
        asset, distance = roads[0]
        score = round(max(20.0, 68.0 - distance * 8), 2)
        return [{
            "hypothesis_type": "transfer_route",
            "title": f"可能转运方向候选：{asset.name}",
            "claim": f"该道路距案发点约 {distance:.2f} 公里，可作为转运方向核查线索。",
            "score": score,
            "confidence": DualDomainV34._confidence(score),
            "region": DualDomainV34._point_region(asset.latitude, asset.longitude, 500),
            "evidence_refs": [f"case_profile:{profile.id}", f"map_asset:{DualDomainV34._source_asset_id(asset)}@snapshot:{snapshot.id}"],
            "supporting_evidence": [f"道路与案发点距离约 {distance:.2f} 公里"],
            "counter_evidence": ["道路接近只说明通行条件，不能证明实际经过"],
            "information_gaps": ["缺少卡口、车辆或时段通行事件佐证"],
            "score_components": {"distance": score},
        }]

    @staticmethod
    def _confidence(score: float) -> float:
        return round(max(0.2, min(0.9, score / 100)), 2)

    @staticmethod
    def _source_asset_id(asset: JurisdictionAsset | MapSnapshotFeature) -> int:
        """返回原始地图要素编号，避免证据引用快照内部行号。"""
        return asset.asset_id if isinstance(asset, MapSnapshotFeature) else asset.id

    @staticmethod
    def _point_region(latitude: float, longitude: float, radius_m: int) -> dict[str, Any]:
        return {
            "type": "circle",
            "center": [round(longitude, 6), round(latitude, 6)],
            "radius_m": radius_m,
            "precision": "area_only",
        }
