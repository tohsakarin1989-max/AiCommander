"""在隔离数据库中验证离线地图导入、发布、读取与回滚闭环。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapPackageArtifact, OperationalArea
from app.release_checks.postgis_v36 import validate_disposable_database_name
from app.services.offline_map_service import OfflineMapService
from app.services.public_map_bundle_verifier import PublicMapBundleVerifier


def _first_tile(path: Path) -> tuple[int, int, int]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT zoom_level, tile_column, tile_row FROM tiles "
            "ORDER BY zoom_level, tile_column, tile_row LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise RuntimeError("offline_package_has_no_tile")
    zoom, x, tms_y = (int(value) for value in row)
    return zoom, x, (1 << zoom) - 1 - tms_y


def verify(
    database_url: str,
    bundle_path: Path,
    *,
    retain_artifact: bool = False,
) -> dict[str, Any]:
    database_name = make_url(database_url).database or ""
    validate_disposable_database_name(database_name)
    bundle_path = bundle_path.resolve()
    content = bundle_path.read_bytes()
    package_report = PublicMapBundleVerifier.verify_bytes(content)
    package_hash = hashlib.sha256(content).hexdigest()
    storage_key = f"bundles/{package_hash}.mbtiles"
    artifact_path = OfflineMapService._storage_path(storage_key)
    artifact_existed = artifact_path.exists()

    engine = create_engine(database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        area = db.query(OperationalArea).order_by(OperationalArea.is_default.desc()).first()
        if area is None:
            area = OperationalArea(
                code=f"release-check-{uuid.uuid4().hex[:12]}",
                name="v3.6离线地图发布验收区",
                boundary=None,
                is_default=True,
                status="active",
            )
            db.add(area)
        else:
            area.name = "v3.6离线地图发布验收区"
            area.boundary = None
            area.is_default = True
            area.status = "active"
        db.flush()
        west, south, east, north = (
            float(item) for item in package_report["bounds"]
        )
        asset = JurisdictionAsset(
            operational_area_id=area.id,
            canonical_key=f"release-check:{uuid.uuid4().hex}",
            name="离线验收设施-v1",
            asset_type="well",
            geometry_type="point",
            latitude=(south + north) / 2,
            longitude=(west + east) / 2,
            source="release_check",
            status="active",
            verified=True,
            verification_state="verified",
            coordinate_system="EPSG:4326",
            attributes={"synthetic_release_check": True},
        )
        db.add(asset)
        db.commit()

        bundle, replay = OfflineMapService.import_bundle(
            db,
            filename=bundle_path.name,
            content=content,
            imported_by=None,
        )
        if replay:
            raise RuntimeError("disposable_database_was_not_empty")
        first_snapshot, snapshot_replay = OfflineMapService.build_snapshot(
            db,
            operational_area_id=area.id,
            public_bundle_id=bundle.id,
            built_by=None,
        )
        if snapshot_replay:
            raise RuntimeError("disposable_database_was_not_empty")
        OfflineMapService.publish_snapshot(db, first_snapshot.id)

        artifact = (
            db.query(MapPackageArtifact)
            .filter(
                MapPackageArtifact.public_bundle_id == bundle.id,
                MapPackageArtifact.artifact_kind == "mbtiles",
            )
            .one()
        )
        stored_path = OfflineMapService._storage_path(artifact.storage_key)
        zoom, x, y = _first_tile(stored_path)
        tile, content_type = OfflineMapService.read_tile(
            db,
            "current",
            zoom,
            x,
            y,
            area_id=area.id,
        )
        first_layers = OfflineMapService.read_layers(
            db,
            "current",
            area_id=area.id,
        )
        if first_layers["features"][0]["properties"]["name"] != "离线验收设施-v1":
            raise RuntimeError("first_snapshot_layer_mismatch")

        asset.name = "离线验收设施-v2"
        db.commit()
        second_snapshot, second_replay = OfflineMapService.build_snapshot(
            db,
            operational_area_id=area.id,
            public_bundle_id=bundle.id,
            built_by=None,
        )
        if second_replay or second_snapshot.id == first_snapshot.id:
            raise RuntimeError("updated_production_layer_not_versioned")
        OfflineMapService.publish_snapshot(db, second_snapshot.id)
        current_layers = OfflineMapService.read_layers(
            db,
            "current",
            area_id=area.id,
        )
        if current_layers["features"][0]["properties"]["name"] != "离线验收设施-v2":
            raise RuntimeError("second_snapshot_layer_mismatch")

        rolled_back = OfflineMapService.rollback_snapshot(db, first_snapshot.id)
        rollback_layers = OfflineMapService.read_layers(
            db,
            "current",
            area_id=area.id,
        )
        if rolled_back.id != first_snapshot.id:
            raise RuntimeError("rollback_snapshot_mismatch")
        if rollback_layers["features"][0]["properties"]["name"] != "离线验收设施-v1":
            raise RuntimeError("rollback_layer_mismatch")

        return {
            "status": "passed",
            "database": database_name,
            "package": package_report,
            "import_status": "passed",
            "tile_read_status": "passed",
            "tile": {
                "z": zoom,
                "x": x,
                "y": y,
                "bytes": len(tile),
                "content_type": content_type,
            },
            "production_layer_status": "passed",
            "snapshot_count": 2,
            "rollback_status": "passed",
        }
    finally:
        db.close()
        engine.dispose()
        if not artifact_existed and not retain_artifact:
            artifact_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在一次性验证数据库中执行 v3.6 离线地图包导入、发布和回滚验收。"
    )
    parser.add_argument("--bundle", required=True, type=Path, help="待验收的离线地图包")
    parser.add_argument(
        "--database-url",
        help="一次性验证数据库连接；省略时读取应用 DATABASE_URL。",
    )
    parser.add_argument(
        "--retain-artifact",
        action="store_true",
        help="保留验收导入的地图文件，供同一隔离环境继续执行健康检查和备份。",
    )
    args = parser.parse_args()
    if args.database_url:
        database_url = args.database_url
    else:
        from app.config import settings

        database_url = settings.DATABASE_URL
    print(
        json.dumps(
            verify(database_url, args.bundle, retain_artifact=args.retain_artifact),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
