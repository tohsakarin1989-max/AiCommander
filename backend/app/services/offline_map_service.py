"""受控公共地图包、内网地图快照和离线瓦片服务。"""
from __future__ import annotations

import hashlib
import html
import io
import json
import os
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import (
    MapFeatureClaim,
    MapPackageArtifact,
    MapSnapshot,
    MapSnapshotFeature,
    MapSource,
    OperationalArea,
    PublicMapBundle,
    JurisdictionAssetVersion,
)


MAX_BUNDLE_BYTES = 256 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
ALLOWED_ARCHIVE_MEMBERS = {"manifest.json", "basemap.mbtiles"}


def _runtime_settings():
    """让独立验包工具无需加载在线服务密钥配置。"""
    from app.config import settings

    return settings


class OfflineMapService:
    """地图数据仅从校验包写入固定目录，不解压任意路径。"""

    @staticmethod
    def import_bundle(
        db: Session,
        *,
        filename: str,
        content: bytes,
        imported_by: int | None,
    ) -> tuple[PublicMapBundle, bool]:
        if not filename.lower().endswith(".zip"):
            raise ValueError("unsupported_bundle")
        if not content:
            raise ValueError("empty_bundle")
        if len(content) > MAX_BUNDLE_BYTES:
            raise ValueError("bundle_too_large")
        package_hash = hashlib.sha256(content).hexdigest()
        existing = db.query(PublicMapBundle).filter(PublicMapBundle.package_hash == package_hash).first()
        if existing:
            return existing, True

        manifest, tile_bytes = OfflineMapService._read_validated_archive(content)
        # API 导入与联网区验包使用同一套逐瓦片门禁，不能让空包、损坏图片或
        # 与清单不一致的层级进入 accepted 状态。
        from app.services.public_map_bundle_verifier import PublicMapBundleVerifier

        verification = PublicMapBundleVerifier.verify_archive(manifest, tile_bytes)
        manifest = dict(manifest)
        manifest.setdefault("tile_count", verification["tile_count"])
        manifest.setdefault("min_zoom", verification["min_zoom"])
        manifest.setdefault("max_zoom", verification["max_zoom"])
        existing_id = (
            db.query(PublicMapBundle)
            .filter(PublicMapBundle.bundle_id == manifest["bundle_id"])
            .first()
        )
        if existing_id:
            raise ValueError("bundle_id_exists")

        storage_key = f"bundles/{package_hash}.mbtiles"
        target = OfflineMapService._storage_path(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(tile_bytes)
        try:
            OfflineMapService._validate_mbtiles(temporary)
            try:
                os.link(temporary, target)
            except FileExistsError:
                # 内容寻址目标已由并发请求落盘；相同 SHA-256 必然指向相同包内容。
                pass
        except Exception:
            raise
        finally:
            temporary.unlink(missing_ok=True)

        bundle = PublicMapBundle(
            bundle_id=manifest["bundle_id"],
            provider=manifest["provider"],
            source_version=manifest["source_version"],
            license_record=manifest["license"],
            bounds=manifest["bounds"],
            manifest=manifest,
            package_hash=package_hash,
            status="accepted",
            imported_by=imported_by,
        )
        db.add(bundle)
        db.flush()
        db.add(
            MapPackageArtifact(
                public_bundle_id=bundle.id,
                artifact_kind="mbtiles",
                storage_key=storage_key,
                sha256=hashlib.sha256(tile_bytes).hexdigest(),
                size_bytes=len(tile_bytes),
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.query(PublicMapBundle).filter(
                PublicMapBundle.package_hash == package_hash
            ).first()
            if existing:
                return existing, True
            raise
        db.refresh(bundle)
        return bundle, False

    @staticmethod
    def build_snapshot(
        db: Session,
        *,
        operational_area_id: int,
        public_bundle_id: int,
        built_by: int | None,
    ) -> tuple[MapSnapshot, bool]:
        area_query = db.query(OperationalArea).filter(
            OperationalArea.id == operational_area_id,
            OperationalArea.status == "active",
        )
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            area_query = area_query.with_for_update()
        area = area_query.first()
        if not area:
            raise ValueError("operational_area_not_found")
        bundle = (
            db.query(PublicMapBundle)
            .filter(PublicMapBundle.id == public_bundle_id, PublicMapBundle.status == "accepted")
            .first()
        )
        if not bundle:
            raise ValueError("bundle_not_found")
        artifact = OfflineMapService._bundle_artifact(db, bundle.id)
        if not artifact or not OfflineMapService._artifact_is_usable(artifact):
            raise ValueError("bundle_artifact_missing")

        open_conflicts = (
            db.query(func.count(MapFeatureClaim.id))
            .join(MapSource, MapSource.id == MapFeatureClaim.source_id)
            .filter(
                MapSource.operational_area_id == area.id,
                MapFeatureClaim.status.in_(("conflict", "quarantined")),
            )
            .scalar()
            or 0
        )
        if open_conflicts:
            raise ValueError("map_conflicts_pending")

        asset_query = db.query(JurisdictionAsset).filter(
            JurisdictionAsset.operational_area_id == area.id
        ).order_by(JurisdictionAsset.id)
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            asset_query = asset_query.with_for_update()
        assets = asset_query.all()
        asset_count = len(assets)
        coverage_basis = OfflineMapService._validate_bundle_coverage(
            area,
            bundle,
            (
                (asset.longitude, asset.latitude)
                for asset in assets
                if asset.longitude is not None and asset.latitude is not None
            ),
        )
        production_grid_hashes = OfflineMapService._production_grid_hashes(assets)
        feature_watermark = hashlib.sha256(
            json.dumps(
                production_grid_hashes,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:32]
        identity = hashlib.sha256(
            f"{area.id}:{bundle.package_hash}:{feature_watermark}:{asset_count}".encode()
        ).hexdigest()[:16]
        version = f"{area.code}-{bundle.source_version}-{identity}"
        existing = db.query(MapSnapshot).filter(MapSnapshot.version == version).first()
        if existing:
            return existing, True

        snapshot_id = str(uuid.uuid4())
        manifest = {
            "schema_version": "1.0",
            "snapshot_id": snapshot_id,
            "version": version,
            "operational_area": {"id": area.id, "code": area.code, "name": area.name},
            "public_bundle": {
                "id": bundle.id,
                "bundle_id": bundle.bundle_id,
                "provider": bundle.provider,
                "source_version": bundle.source_version,
                "license": bundle.license_record,
                "sha256": bundle.package_hash,
            },
            "bounds": bundle.bounds,
            "coverage_verified": True,
            "coverage_basis": coverage_basis,
            "production_feature_count": asset_count or 0,
            "production_grid_hashes": production_grid_hashes,
            "public_bundle_changed_grids": bundle.manifest.get("changed_grids"),
            "feature_watermark": feature_watermark,
            "tile_url": f"/api/maps/tiles/{snapshot_id}/{{z}}/{{x}}/{{y}}",
            "production_layer_url": f"/api/maps/{snapshot_id}/layers",
            "min_zoom": OfflineMapService._zoom_value(bundle.manifest.get("min_zoom"), 0),
            "max_zoom": OfflineMapService._zoom_value(bundle.manifest.get("max_zoom"), 22),
            "attribution": OfflineMapService._bundle_attribution(bundle),
            "network_required": False,
        }
        snapshot = MapSnapshot(
            id=snapshot_id,
            version=version,
            operational_area_id=area.id,
            public_bundle_id=bundle.id,
            status="ready",
            manifest=manifest,
            feature_watermark=feature_watermark,
            built_by=built_by,
        )
        db.add(snapshot)
        db.flush()
        asset_ids = [item.id for item in assets]
        latest_versions: dict[int, JurisdictionAssetVersion] = {}
        if asset_ids:
            for version_item in (
                db.query(JurisdictionAssetVersion)
                .filter(JurisdictionAssetVersion.asset_id.in_(asset_ids))
                .order_by(JurisdictionAssetVersion.asset_id, JurisdictionAssetVersion.version)
                .all()
            ):
                latest_versions[version_item.asset_id] = version_item
        for asset in assets:
            latest_version = latest_versions.get(asset.id)
            frozen_attributes = dict(asset.attributes or {})
            frozen_attributes["_snapshot_display"] = {
                "address": asset.address,
                "description": asset.description,
                "risk_level": asset.risk_level,
                "confidence_score": asset.confidence_score,
                "tags": list(asset.tags or []),
            }
            db.add(
                MapSnapshotFeature(
                    snapshot_id=snapshot.id,
                    operational_area_id=area.id,
                    asset_id=asset.id,
                    asset_version_id=latest_version.id if latest_version else None,
                    name=asset.name,
                    asset_type=asset.asset_type,
                    geometry_type=asset.geometry_type or "point",
                    latitude=asset.latitude,
                    longitude=asset.longitude,
                    geometry=asset.geometry,
                    source=asset.source,
                    status=asset.status or "active",
                    verified=bool(asset.verified),
                    verification_state=asset.verification_state,
                    attributes=frozen_attributes,
                )
            )
        db.commit()
        db.refresh(snapshot)
        return snapshot, False

    @staticmethod
    def publish_snapshot(db: Session, snapshot_id: str) -> MapSnapshot:
        snapshot_area_id = db.query(MapSnapshot.operational_area_id).filter(
            MapSnapshot.id == snapshot_id
        ).scalar()
        if snapshot_area_id is None:
            raise ValueError("snapshot_not_found")
        area_query = db.query(OperationalArea).filter(OperationalArea.id == snapshot_area_id)
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            area_query = area_query.with_for_update()
        area = area_query.first()
        if area is None or area.status != "active":
            raise ValueError("operational_area_not_found")
        snapshot = db.query(MapSnapshot).filter(MapSnapshot.id == snapshot_id).first()
        if not snapshot:
            raise ValueError("snapshot_not_found")
        if snapshot.status not in {"ready", "superseded"}:
            raise ValueError("snapshot_not_publishable")
        if not OfflineMapService._snapshot_artifact_exists(
            db,
            snapshot,
            verify_hash=True,
        ):
            raise ValueError("bundle_artifact_missing")
        bundle = db.query(PublicMapBundle).filter(
            PublicMapBundle.id == snapshot.public_bundle_id,
            PublicMapBundle.status == "accepted",
        ).first()
        if bundle is None:
            raise ValueError("bundle_not_found")
        frozen_points = db.query(
            MapSnapshotFeature.longitude,
            MapSnapshotFeature.latitude,
        ).filter(
            MapSnapshotFeature.snapshot_id == snapshot.id,
            MapSnapshotFeature.longitude.isnot(None),
            MapSnapshotFeature.latitude.isnot(None),
        ).all()
        OfflineMapService._validate_bundle_coverage(area, bundle, frozen_points)
        now = datetime.now(timezone.utc)
        current_items = (
            db.query(MapSnapshot)
            .filter(
                MapSnapshot.operational_area_id == snapshot.operational_area_id,
                MapSnapshot.status == "current",
                MapSnapshot.id != snapshot.id,
            )
            .all()
        )
        previous = current_items[0] if current_items else None
        for current in current_items:
            current.status = "superseded"
            current.superseded_at = now
        # PostgreSQL 的部分唯一索引会逐条检查；必须先释放旧 current，
        # 再激活新版本，同时仍保留在同一事务内，失败时可整体回滚。
        if current_items:
            db.flush()
        snapshot.status = "current"
        snapshot.published_at = now
        snapshot.superseded_at = None
        from app.models.case import Case
        from app.models.case_pipeline import CaseAnalysisProfile
        from app.services.case_insight_service import CaseInsightService

        affected_grids = OfflineMapService._affected_grids(previous, snapshot)
        profiles = (
            db.query(CaseAnalysisProfile)
            .join(Case, Case.id == CaseAnalysisProfile.case_id)
            .filter(
                CaseAnalysisProfile.is_current.is_(True),
                (Case.operational_area_id == snapshot.operational_area_id)
                | (Case.operational_area_id.is_(None)),
            )
            .all()
        )
        for profile in profiles:
            if affected_grids is not None:
                profile_grid = str((profile.payload or {}).get("spatial_grid") or "")
                if profile_grid not in affected_grids:
                    continue
            CaseInsightService.enqueue_analysis(db, profile, snapshot)
        db.commit()
        db.refresh(snapshot)
        return snapshot

    @staticmethod
    def rollback_snapshot(db: Session, snapshot_id: str) -> MapSnapshot:
        return OfflineMapService.publish_snapshot(db, snapshot_id)

    @staticmethod
    def current_snapshot(db: Session, area_id: int | None = None) -> MapSnapshot | None:
        if area_id is None:
            area_id = db.info.get("default_operational_area_id")
        query = db.query(MapSnapshot).filter(MapSnapshot.status == "current")
        if area_id is not None:
            query = query.filter(MapSnapshot.operational_area_id == area_id)
        return query.order_by(MapSnapshot.published_at.desc()).first()

    @staticmethod
    def resolved_manifest(db: Session, snapshot: MapSnapshot) -> dict[str, Any]:
        """返回固定到具体快照的运行清单，并兼容早期未写入展示字段的快照。"""
        manifest = dict(snapshot.manifest or {})
        bundle = db.query(PublicMapBundle).filter(
            PublicMapBundle.id == snapshot.public_bundle_id
        ).first()
        bundle_manifest = dict(bundle.manifest or {}) if bundle else {}
        manifest.update(
            {
                "snapshot_id": snapshot.id,
                "version": snapshot.version,
                "tile_url": f"/api/maps/tiles/{snapshot.id}/{{z}}/{{x}}/{{y}}",
                "production_layer_url": f"/api/maps/{snapshot.id}/layers",
                "min_zoom": OfflineMapService._zoom_value(
                    bundle_manifest.get("min_zoom", manifest.get("min_zoom")),
                    0,
                ),
                "max_zoom": OfflineMapService._zoom_value(
                    bundle_manifest.get("max_zoom", manifest.get("max_zoom")),
                    22,
                ),
                "attribution": (
                    OfflineMapService._bundle_attribution(bundle)
                    if bundle
                    else str(manifest.get("attribution") or "内部离线地图")
                ),
                "network_required": False,
            }
        )
        if manifest["min_zoom"] > manifest["max_zoom"]:
            manifest["min_zoom"], manifest["max_zoom"] = (
                manifest["max_zoom"],
                manifest["min_zoom"],
            )
        return manifest

    @staticmethod
    def resolve_snapshot(
        db: Session,
        snapshot_ref: str,
        area_id: int | None = None,
    ) -> MapSnapshot:
        if snapshot_ref == "current":
            snapshot = OfflineMapService.current_snapshot(db, area_id=area_id)
        else:
            query = db.query(MapSnapshot).filter(
                (MapSnapshot.id == snapshot_ref) | (MapSnapshot.version == snapshot_ref),
                MapSnapshot.status.in_(("current", "superseded")),
            )
            if area_id is not None:
                query = query.filter(MapSnapshot.operational_area_id == area_id)
            snapshot = query.first()
        if not snapshot:
            raise ValueError("snapshot_not_found")
        return snapshot

    @staticmethod
    def read_tile(
        db: Session,
        snapshot_ref: str,
        z: int,
        x: int,
        y: int,
        *,
        area_id: int | None = None,
    ) -> tuple[bytes, str]:
        if z < 0 or z > 22 or x < 0 or y < 0 or x >= 2**z or y >= 2**z:
            raise ValueError("tile_not_found")
        snapshot = OfflineMapService.resolve_snapshot(db, snapshot_ref, area_id=area_id)
        artifact = OfflineMapService._bundle_artifact(db, snapshot.public_bundle_id)
        if not artifact:
            raise ValueError("tile_not_found")
        path = OfflineMapService._storage_path(artifact.storage_key)
        tms_y = (1 << z) - 1 - y
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            row = connection.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                (z, x, tms_y),
            ).fetchone()
        except sqlite3.Error as exc:
            raise ValueError("tile_store_unavailable") from exc
        finally:
            if "connection" in locals():
                connection.close()
        if not row:
            raise ValueError("tile_not_found")
        tile = bytes(row[0])
        return tile, OfflineMapService._content_type(tile)

    @staticmethod
    def read_layers(
        db: Session,
        snapshot_ref: str,
        *,
        area_id: int | None = None,
        asset_ids: list[int] | None = None,
        limit: int = 5000,
    ) -> dict[str, Any]:
        snapshot = OfflineMapService.resolve_snapshot(db, snapshot_ref, area_id=area_id)
        query = db.query(MapSnapshotFeature).filter(MapSnapshotFeature.snapshot_id == snapshot.id)
        if asset_ids is not None:
            query = query.filter(MapSnapshotFeature.asset_id.in_(asset_ids))
        fetched = query.order_by(MapSnapshotFeature.id).limit(limit + 1).all()
        truncated = len(fetched) > limit
        features = fetched[:limit]
        return {
            "type": "FeatureCollection",
            "snapshot_id": snapshot.id,
            "snapshot_version": snapshot.version,
            "truncated": truncated,
            "features": [OfflineMapService._snapshot_feature_geojson(item) for item in features],
        }

    @staticmethod
    def health(db: Session) -> dict[str, Any]:
        areas = db.query(OperationalArea).filter(
            OperationalArea.status == "active"
        ).order_by(OperationalArea.is_default.desc(), OperationalArea.id).all()
        if not areas:
            return {
                "status": "not_configured",
                "active_area_count": 0,
                "ready_area_count": 0,
                "missing_area_count": 0,
                "network_required": False,
                "affects_core_readiness": False,
            }
        area_ids = [area.id for area in areas]
        snapshots = db.query(MapSnapshot).filter(
            MapSnapshot.status == "current",
            MapSnapshot.operational_area_id.in_(area_ids),
        ).all()
        snapshot_by_area = {snapshot.operational_area_id: snapshot for snapshot in snapshots}
        ready_area_ids = {
            area_id
            for area_id, snapshot in snapshot_by_area.items()
            if OfflineMapService._snapshot_artifact_exists(
                db,
                snapshot,
                verify_hash=True,
            )
        }
        missing_area_ids = [area_id for area_id in area_ids if area_id not in ready_area_ids]
        if len(ready_area_ids) == len(area_ids):
            status = "ready"
        elif not snapshots:
            status = "not_configured"
        else:
            status = "degraded"
        result = {
            "status": status,
            "active_area_count": len(area_ids),
            "ready_area_count": len(ready_area_ids),
            "missing_area_count": len(missing_area_ids),
            "network_required": False,
            "affects_core_readiness": False,
        }
        if _runtime_settings().ENVIRONMENT == "production":
            return result
        primary = snapshot_by_area.get(areas[0].id)
        result.update(
            {
                "current_snapshot": primary.id if primary else None,
                "version": primary.version if primary else None,
                "tile_store": (
                    "available"
                    if primary and primary.operational_area_id in ready_area_ids
                    else "missing"
                ),
                "missing_area_ids": missing_area_ids,
            }
        )
        return result

    @staticmethod
    def bundle_to_dict(bundle: PublicMapBundle, *, idempotent_replay: bool = False) -> dict[str, Any]:
        return {
            "id": bundle.id,
            "bundle_id": bundle.bundle_id,
            "provider": bundle.provider,
            "source_version": bundle.source_version,
            "license": bundle.license_record,
            "bounds": bundle.bounds,
            "sha256": bundle.package_hash,
            "status": bundle.status,
            "imported_at": bundle.imported_at,
            "idempotent_replay": idempotent_replay,
        }

    @staticmethod
    def snapshot_to_dict(snapshot: MapSnapshot, *, idempotent_replay: bool = False) -> dict[str, Any]:
        return {
            "id": snapshot.id,
            "version": snapshot.version,
            "operational_area_id": snapshot.operational_area_id,
            "public_bundle_id": snapshot.public_bundle_id,
            "status": snapshot.status,
            "manifest": snapshot.manifest,
            "feature_watermark": snapshot.feature_watermark,
            "built_at": snapshot.built_at,
            "published_at": snapshot.published_at,
            "idempotent_replay": idempotent_replay,
        }

    @staticmethod
    def _read_validated_archive(content: bytes) -> tuple[dict[str, Any], bytes]:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = archive.infolist()
                names = {item.filename for item in members}
                if names != ALLOWED_ARCHIVE_MEMBERS:
                    raise ValueError("invalid_bundle_members")
                if any(item.is_dir() or Path(item.filename).name != item.filename for item in members):
                    raise ValueError("invalid_bundle_members")
                if sum(item.file_size for item in members) > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("bundle_uncompressed_too_large")
                if any(
                    item.file_size / max(item.compress_size, 1) > 100
                    for item in members
                    if item.file_size > 1024 * 1024
                ):
                    raise ValueError("bundle_uncompressed_too_large")
                manifest_raw = archive.read("manifest.json")
                if len(manifest_raw) > 1024 * 1024:
                    raise ValueError("manifest_too_large")
                manifest = json.loads(manifest_raw.decode("utf-8"))
                tile_bytes = archive.read("basemap.mbtiles")
        except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid_bundle") from exc
        OfflineMapService._validate_manifest(manifest, tile_bytes)
        return manifest, tile_bytes

    @staticmethod
    def _validate_manifest(manifest: Any, tile_bytes: bytes) -> None:
        required = {
            "schema_version",
            "bundle_id",
            "provider",
            "source_version",
            "license",
            "attribution",
            "bounds",
            "contains_internal_data",
            "files",
        }
        if not isinstance(manifest, dict) or not required.issubset(manifest):
            raise ValueError("invalid_manifest")
        if manifest["schema_version"] != "1.0" or manifest["contains_internal_data"] is not False:
            raise ValueError("invalid_manifest")
        if any(key in manifest for key in ("cases", "wells", "pipelines", "tech_defense", "internal_results")):
            raise ValueError("internal_data_declared")
        text_fields = ("bundle_id", "provider", "source_version", "license", "attribution")
        if not all(
            isinstance(manifest[key], str)
            and manifest[key].strip()
            and len(manifest[key]) <= 500
            and not any(ord(character) < 32 for character in manifest[key])
            for key in text_fields
        ):
            raise ValueError("invalid_manifest")
        bounds = manifest["bounds"]
        if not (
            isinstance(bounds, list)
            and len(bounds) == 4
            and all(isinstance(item, (int, float)) for item in bounds)
            and -180 <= bounds[0] < bounds[2] <= 180
            and -90 <= bounds[1] < bounds[3] <= 90
        ):
            raise ValueError("invalid_bounds")
        files = manifest["files"]
        if (
            not isinstance(files, list)
            or len(files) != 1
            or not isinstance(files[0], dict)
            or files[0].get("name") != "basemap.mbtiles"
        ):
            raise ValueError("invalid_manifest")
        expected_hash = str(files[0].get("sha256") or "")
        if expected_hash != hashlib.sha256(tile_bytes).hexdigest():
            raise ValueError("bundle_checksum_mismatch")
        if files[0].get("size") != len(tile_bytes):
            raise ValueError("bundle_size_mismatch")

    @staticmethod
    def _validate_mbtiles(path: Path) -> None:
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if not {"tiles", "metadata"}.issubset(tables):
                raise ValueError("invalid_mbtiles")
            integrity = connection.execute("PRAGMA quick_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("invalid_mbtiles")
            formats = dict(connection.execute("SELECT name, value FROM metadata").fetchall())
            if formats.get("format", "png").lower() not in {"png", "jpg", "jpeg", "webp"}:
                raise ValueError("unsupported_tile_format")
        except sqlite3.Error as exc:
            raise ValueError("invalid_mbtiles") from exc
        finally:
            if "connection" in locals():
                connection.close()

    @staticmethod
    def _zoom_value(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return min(22, max(0, parsed))

    @staticmethod
    def _validate_bundle_coverage(
        area: OperationalArea,
        bundle: PublicMapBundle,
        production_points,
    ) -> str:
        """阻止把错误地域的合法离线包发布为厂区底图。"""
        west, south, east, north = (float(value) for value in bundle.bounds)
        boundary_points = OfflineMapService._boundary_points(area.boundary)
        located_assets = [
            (float(longitude), float(latitude))
            for longitude, latitude in production_points
            if longitude is not None and latitude is not None
        ]
        points = boundary_points + located_assets
        if not points:
            raise ValueError("map_coverage_unverifiable")
        if any(
            not (-180 <= longitude <= 180 and -90 <= latitude <= 90)
            or not (west <= longitude <= east and south <= latitude <= north)
            for longitude, latitude in points
        ):
            raise ValueError("map_bundle_outside_operational_area")
        if boundary_points and located_assets:
            return "boundary_and_production_features"
        if boundary_points:
            return "operational_area_boundary"
        return "production_features"

    @staticmethod
    def _boundary_points(boundary: Any) -> list[tuple[float, float]]:
        if not isinstance(boundary, dict):
            return []
        if boundary.get("type") == "Feature":
            return OfflineMapService._boundary_points(boundary.get("geometry"))
        if boundary.get("type") == "FeatureCollection":
            points: list[tuple[float, float]] = []
            for feature in boundary.get("features") or []:
                points.extend(OfflineMapService._boundary_points(feature))
            return points
        coordinates = boundary.get("coordinates")
        points: list[tuple[float, float]] = []

        def collect(value: Any) -> None:
            if (
                isinstance(value, (list, tuple))
                and len(value) >= 2
                and isinstance(value[0], (int, float))
                and isinstance(value[1], (int, float))
            ):
                points.append((float(value[0]), float(value[1])))
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    collect(item)

        collect(coordinates)
        return points

    @staticmethod
    def _bundle_attribution(bundle: PublicMapBundle) -> str:
        manifest = dict(bundle.manifest or {})
        value = str(
            manifest.get("attribution") or f"{bundle.provider} · {bundle.license_record}"
        )
        # Leaflet 将 attribution 作为 innerHTML 渲染，因此这里必须只下发
        # 已转义的纯文本，兼容升级前已入库的旧清单。
        return html.escape(value[:500], quote=True)

    @staticmethod
    def _storage_path(storage_key: str) -> Path:
        root = Path(_runtime_settings().MAP_PACKAGE_ROOT).expanduser().resolve()
        target = (root / storage_key).resolve()
        if root != target and root not in target.parents:
            raise ValueError("invalid_storage_key")
        return target

    @staticmethod
    def _bundle_artifact(db: Session, bundle_id: int) -> MapPackageArtifact | None:
        return (
            db.query(MapPackageArtifact)
            .filter(
                MapPackageArtifact.public_bundle_id == bundle_id,
                MapPackageArtifact.artifact_kind == "mbtiles",
            )
            .first()
        )

    @staticmethod
    def _snapshot_artifact_exists(
        db: Session,
        snapshot: MapSnapshot,
        *,
        verify_hash: bool = False,
    ) -> bool:
        artifact = OfflineMapService._bundle_artifact(db, snapshot.public_bundle_id)
        return bool(
            artifact
            and OfflineMapService._artifact_is_usable(
                artifact,
                verify_hash=verify_hash,
            )
        )

    @staticmethod
    def _artifact_is_usable(
        artifact: MapPackageArtifact,
        *,
        verify_hash: bool = False,
    ) -> bool:
        path = OfflineMapService._storage_path(artifact.storage_key)
        try:
            if not path.is_file():
                return False
            stat = path.stat()
            if stat.st_size != artifact.size_bytes:
                return False
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if not {"tiles", "metadata"}.issubset(tables):
                    return False
                metadata = connection.execute(
                    "SELECT value FROM metadata WHERE name = 'format'"
                ).fetchone()
                tile = connection.execute(
                    "SELECT length(tile_data) FROM tiles LIMIT 1"
                ).fetchone()
                if not metadata or not tile or not tile[0]:
                    return False
            finally:
                connection.close()
            if verify_hash:
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != artifact.sha256:
                    return False
            return True
        except (OSError, sqlite3.Error):
            return False

    @staticmethod
    def _content_type(tile: bytes) -> str:
        if tile.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if tile.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if tile.startswith(b"RIFF") and tile[8:12] == b"WEBP":
            return "image/webp"
        return "application/octet-stream"

    @staticmethod
    def _snapshot_feature_geojson(item: MapSnapshotFeature) -> dict[str, Any]:
        attributes = dict(item.attributes or {})
        display = attributes.pop("_snapshot_display", {})
        geometry = item.geometry
        if geometry is None and item.latitude is not None and item.longitude is not None:
            geometry = {
                "type": "Point",
                "coordinates": [item.longitude, item.latitude],
            }
        return {
            "type": "Feature",
            "id": item.id,
            "geometry": geometry,
            "properties": {
                "snapshot_feature_id": item.id,
                "asset_id": item.asset_id,
                "asset_version_id": item.asset_version_id,
                "name": item.name,
                "asset_type": item.asset_type,
                "source": item.source,
                "status": item.status,
                "verified": item.verified,
                "verification_state": item.verification_state,
                "address": display.get("address"),
                "description": display.get("description"),
                "risk_level": display.get("risk_level"),
                "confidence_score": display.get("confidence_score"),
                "tags": display.get("tags") or [],
                "attributes": attributes,
            },
        }

    @staticmethod
    def _production_grid_hashes(assets: list[JurisdictionAsset]) -> dict[str, str]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for asset in assets:
            grid = (
                f"{asset.latitude:.2f}:{asset.longitude:.2f}"
                if asset.latitude is not None and asset.longitude is not None
                else "__unlocated__"
            )
            grouped.setdefault(grid, []).append(
                {
                    "id": asset.id,
                    "name": asset.name,
                    "type": asset.asset_type,
                    "status": asset.status,
                    "verified": bool(asset.verified),
                    "verification_state": asset.verification_state,
                    "source": asset.source,
                    "risk": asset.risk_level,
                    "confidence": asset.confidence_score,
                    "address": asset.address,
                    "description": asset.description,
                    "tags": asset.tags or [],
                    "lat": round(asset.latitude, 6) if asset.latitude is not None else None,
                    "lon": round(asset.longitude, 6) if asset.longitude is not None else None,
                    "geometry": asset.geometry,
                    "attributes": asset.attributes or {},
                }
            )
        return {
            grid: hashlib.sha256(
                json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            for grid, values in sorted(grouped.items())
        }

    @staticmethod
    def _affected_grids(
        previous: MapSnapshot | None,
        current: MapSnapshot,
    ) -> set[str] | None:
        """None 表示公共底图变化范围未知，需要保守重算全部案件。"""
        if previous is None:
            return None
        old_hashes = (previous.manifest or {}).get("production_grid_hashes") or {}
        new_hashes = (current.manifest or {}).get("production_grid_hashes") or {}
        production_changes = {
            grid
            for grid in set(old_hashes) | set(new_hashes)
            if grid != "__unlocated__" and old_hashes.get(grid) != new_hashes.get(grid)
        }
        if previous.public_bundle_id != current.public_bundle_id:
            changed = (current.manifest or {}).get("public_bundle_changed_grids")
            if not isinstance(changed, list):
                return None
            base = {str(item) for item in changed} | production_changes
        else:
            base = production_changes
        return OfflineMapService._expand_grids(base, radius_degrees=0.25)

    @staticmethod
    def _expand_grids(grids: set[str], *, radius_degrees: float) -> set[str]:
        expanded: set[str] = set()
        steps = max(0, int(round(radius_degrees / 0.01)))
        for item in grids:
            try:
                latitude_raw, longitude_raw = item.split(":", 1)
                latitude = float(latitude_raw)
                longitude = float(longitude_raw)
            except (TypeError, ValueError):
                continue
            for lat_step in range(-steps, steps + 1):
                for lon_step in range(-steps, steps + 1):
                    expanded.add(
                        f"{latitude + lat_step * 0.01:.2f}:{longitude + lon_step * 0.01:.2f}"
                    )
        return expanded
