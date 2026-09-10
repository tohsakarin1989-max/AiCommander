"""统一空间查询入口；当前兼容 SQLite，经纬度边界预筛后做精确距离计算。"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshotFeature
from app.utils.geo import bounding_box, haversine_km


class SpatialRepository:
    @staticmethod
    def nearby_assets(
        db: Session,
        *,
        latitude: float,
        longitude: float,
        asset_types: Iterable[str],
        radius_km: float,
        operational_area_id: int | None,
        snapshot_id: str | None = None,
        limit: int = 100,
    ) -> list[tuple[JurisdictionAsset | MapSnapshotFeature, float]]:
        model = MapSnapshotFeature if snapshot_id else JurisdictionAsset
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            return SpatialRepository._postgis_nearby_assets(
                db,
                latitude=latitude,
                longitude=longitude,
                asset_types=asset_types,
                radius_km=radius_km,
                operational_area_id=operational_area_id,
                snapshot_id=snapshot_id,
                limit=limit,
            )
        min_lat, max_lat, min_lon, max_lon = bounding_box(latitude, longitude, radius_km)
        query = db.query(model).filter(
            model.asset_type.in_(list(asset_types)),
            model.status == "active",
            model.latitude.between(min_lat, max_lat),
            model.longitude.between(min_lon, max_lon),
        )
        if snapshot_id is not None:
            query = query.filter(MapSnapshotFeature.snapshot_id == snapshot_id)
        if operational_area_id is not None:
            query = query.filter(model.operational_area_id == operational_area_id)
        items = []
        approximate_distance = (
            (model.latitude - latitude) * (model.latitude - latitude)
            + (model.longitude - longitude) * (model.longitude - longitude)
        )
        for asset in query.order_by(approximate_distance, model.id).limit(max(limit * 10, 500)).all():
            distance = haversine_km(latitude, longitude, asset.latitude, asset.longitude)
            if distance <= radius_km:
                items.append((asset, round(distance, 4)))
        items.sort(key=lambda item: (item[1], item[0].id))
        return items[:limit]

    @staticmethod
    def nearby_cases(
        db: Session,
        *,
        case: Case,
        radius_km: float,
        limit: int = 100,
    ) -> list[tuple[Case, float]]:
        if case.latitude is None or case.longitude is None:
            return []
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            return SpatialRepository._postgis_nearby_cases(
                db,
                case=case,
                radius_km=radius_km,
                limit=limit,
            )
        min_lat, max_lat, min_lon, max_lon = bounding_box(
            case.latitude,
            case.longitude,
            radius_km,
        )
        query = db.query(Case).filter(
            Case.id != case.id,
            Case.latitude.between(min_lat, max_lat),
            Case.longitude.between(min_lon, max_lon),
        )
        if case.operational_area_id is not None:
            query = query.filter(Case.operational_area_id == case.operational_area_id)
        items = []
        for candidate in query.limit(max(limit * 4, 100)).all():
            distance = haversine_km(
                case.latitude,
                case.longitude,
                candidate.latitude,
                candidate.longitude,
            )
            if distance <= radius_km:
                items.append((candidate, round(distance, 4)))
        items.sort(key=lambda item: (item[1], item[0].id))
        return items[:limit]

    @staticmethod
    def _point(longitude, latitude):
        return func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)

    @staticmethod
    def _postgis_nearby_assets(
        db: Session,
        *,
        latitude: float,
        longitude: float,
        asset_types: Iterable[str],
        radius_km: float,
        operational_area_id: int | None,
        snapshot_id: str | None,
        limit: int,
    ) -> list[tuple[JurisdictionAsset | MapSnapshotFeature, float]]:
        model = MapSnapshotFeature if snapshot_id else JurisdictionAsset
        origin = SpatialRepository._point(longitude, latitude)
        asset_point = SpatialRepository._point(
            model.longitude,
            model.latitude,
        )
        distance_m = func.ST_DistanceSphere(asset_point, origin)
        query = db.query(model, distance_m.label("distance_m")).filter(
            model.asset_type.in_(list(asset_types)),
            model.status == "active",
            model.latitude.isnot(None),
            model.longitude.isnot(None),
            func.ST_DWithin(
                func.geography(asset_point),
                func.geography(origin),
                radius_km * 1000,
            ),
        )
        if snapshot_id is not None:
            query = query.filter(MapSnapshotFeature.snapshot_id == snapshot_id)
        if operational_area_id is not None:
            query = query.filter(model.operational_area_id == operational_area_id)
        rows = query.order_by(distance_m, model.id).limit(limit).all()
        return [(asset, round(float(distance) / 1000.0, 4)) for asset, distance in rows]

    @staticmethod
    def _postgis_nearby_cases(
        db: Session,
        *,
        case: Case,
        radius_km: float,
        limit: int,
    ) -> list[tuple[Case, float]]:
        origin = SpatialRepository._point(case.longitude, case.latitude)
        case_point = SpatialRepository._point(Case.longitude, Case.latitude)
        distance_m = func.ST_DistanceSphere(case_point, origin)
        query = db.query(Case, distance_m.label("distance_m")).filter(
            Case.id != case.id,
            Case.latitude.isnot(None),
            Case.longitude.isnot(None),
            func.ST_DWithin(
                func.geography(case_point),
                func.geography(origin),
                radius_km * 1000,
            ),
        )
        if case.operational_area_id is not None:
            query = query.filter(Case.operational_area_id == case.operational_area_id)
        rows = query.order_by(distance_m, Case.id).limit(limit).all()
        return [(candidate, round(float(distance) / 1000.0, 4)) for candidate, distance in rows]
