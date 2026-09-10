"""v3.2 受控地图包、地图快照与内网瓦片 API。"""
from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import Response as BinaryResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import get_db
from app.models.map_foundation import MapSnapshot, PublicMapBundle
from app.services.offline_map_service import MAX_BUNDLE_BYTES, OfflineMapService


router = APIRouter()

TRANSPARENT_GIF = base64.b64decode("R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=")


class MapSnapshotBuildRequest(BaseModel):
    operational_area_id: int
    public_bundle_id: int


def _principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None and settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def _require_admin(request: Request):
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role != "admin":
        raise HTTPException(status_code=403, detail="仅地图管理员可以发布或回滚离线地图")
    return principal


def _user_id(principal) -> int | None:
    return getattr(principal, "user_id", getattr(principal, "id", None))


def _error(exc: ValueError) -> HTTPException:
    code = str(exc)
    messages = {
        "unsupported_bundle": "仅支持受控 ZIP 地图更新包",
        "empty_bundle": "地图更新包为空",
        "bundle_too_large": "地图更新包超过 256MB 限制",
        "invalid_bundle": "地图更新包无法解析",
        "invalid_bundle_members": "地图更新包目录不符合规范",
        "bundle_uncompressed_too_large": "地图更新包解压后体积异常",
        "manifest_too_large": "地图包来源清单异常",
        "invalid_manifest": "地图包来源清单不完整或不符合规范",
        "invalid_bounds": "地图包边界范围无效",
        "internal_data_declared": "联网区地图包不得包含内网生产或案件数据",
        "bundle_checksum_mismatch": "地图包文件校验失败",
        "bundle_size_mismatch": "地图包文件大小校验失败",
        "invalid_mbtiles": "离线瓦片文件无效",
        "unsupported_tile_format": "离线瓦片格式不受支持",
        "unknown_tile_format": "离线瓦片包含损坏或不支持的图片",
        "empty_tile_set": "离线瓦片包没有可用瓦片",
        "invalid_tile_coordinate": "离线瓦片坐标无效",
        "duplicate_tile_coordinate": "离线瓦片包含重复坐标",
        "mixed_tile_formats": "同一离线瓦片包包含混合图片格式",
        "tile_format_mismatch": "瓦片实际格式与清单不一致",
        "corrupt_tile_image": "离线瓦片图片已损坏或被截断",
        "tile_dimensions_too_large": "离线瓦片图片尺寸异常",
        "tile_count_mismatch": "瓦片数量与清单不一致",
        "tile_count_limit_exceeded": "离线瓦片数量超过受控上限",
        "tile_too_large": "单张离线瓦片超过 2MB 限制",
        "zoom_range_mismatch": "瓦片层级与清单不一致",
        "tile_coverage_mismatch": "离线瓦片未覆盖清单声明的地域范围",
        "bundle_id_exists": "同一地图包版本已存在，但文件摘要不同",
        "operational_area_not_found": "厂区不存在或已停用",
        "bundle_not_found": "公共地图包不存在或未通过校验",
        "bundle_artifact_missing": "离线瓦片文件缺失，未改变当前地图版本",
        "map_conflicts_pending": "仍有地图数据异常待处理，未生成新地图版本",
        "map_coverage_unverifiable": "厂区边界和生产点均未配置，无法核验地图包范围",
        "map_bundle_outside_operational_area": "地图包范围未完整覆盖厂区",
        "snapshot_not_found": "地图版本不存在",
        "snapshot_not_publishable": "当前地图版本不能发布",
        "tile_not_found": "所请求瓦片不在离线地图包内",
        "tile_store_unavailable": "离线瓦片库暂不可用",
    }
    if code in {"bundle_not_found", "operational_area_not_found", "snapshot_not_found", "tile_not_found"}:
        status = 404
    elif code in {"bundle_id_exists", "map_conflicts_pending", "snapshot_not_publishable"}:
        status = 409
    elif code == "bundle_too_large":
        status = 413
    elif code in {"tile_store_unavailable", "bundle_artifact_missing"}:
        status = 503
    elif code in {"unsupported_bundle", "empty_bundle", "invalid_bundle"}:
        status = 400
    else:
        status = 422
    return HTTPException(status_code=status, detail=messages.get(code, code))


@router.post("/map-bundles/import", status_code=201)
async def import_map_bundle(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_admin(request)
    content = await file.read(MAX_BUNDLE_BYTES + 1)
    try:
        bundle, replay = await run_in_threadpool(
            lambda: OfflineMapService.import_bundle(
                db,
                filename=file.filename or "",
                content=content,
                imported_by=_user_id(principal),
            )
        )
    except ValueError as exc:
        raise _error(exc) from exc
    response.status_code = 200 if replay else 201
    return OfflineMapService.bundle_to_dict(bundle, idempotent_replay=replay)


@router.get("/map-bundles")
def list_map_bundles(
    request: Request,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_admin(request)
    bundles = db.query(PublicMapBundle).order_by(PublicMapBundle.imported_at.desc()).all()
    return [OfflineMapService.bundle_to_dict(item) for item in bundles]


@router.post("/map-snapshots/build", status_code=201)
def build_map_snapshot(
    payload: MapSnapshotBuildRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_admin(request)
    try:
        snapshot, replay = OfflineMapService.build_snapshot(
            db,
            operational_area_id=payload.operational_area_id,
            public_bundle_id=payload.public_bundle_id,
            built_by=_user_id(principal),
        )
    except ValueError as exc:
        raise _error(exc) from exc
    response.status_code = 200 if replay else 201
    return OfflineMapService.snapshot_to_dict(snapshot, idempotent_replay=replay)


@router.get("/map-snapshots")
def list_map_snapshots(
    request: Request,
    operational_area_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_admin(request)
    query = db.query(MapSnapshot)
    if operational_area_id is not None:
        query = query.filter(MapSnapshot.operational_area_id == operational_area_id)
    snapshots = query.order_by(MapSnapshot.built_at.desc()).all()
    return [OfflineMapService.snapshot_to_dict(item) for item in snapshots]


@router.post("/map-snapshots/{snapshot_id}/publish")
def publish_map_snapshot(
    snapshot_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    try:
        snapshot = OfflineMapService.publish_snapshot(db, snapshot_id)
    except ValueError as exc:
        raise _error(exc) from exc
    return OfflineMapService.snapshot_to_dict(snapshot)


@router.post("/map-snapshots/{snapshot_id}/rollback")
def rollback_map_snapshot(
    snapshot_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    try:
        snapshot = OfflineMapService.rollback_snapshot(db, snapshot_id)
    except ValueError as exc:
        raise _error(exc) from exc
    return OfflineMapService.snapshot_to_dict(snapshot)


@router.get("/maps/{snapshot_ref}/manifest")
def map_manifest(
    snapshot_ref: str,
    request: Request,
    operational_area_id: int | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _principal(request)
    try:
        snapshot = OfflineMapService.resolve_snapshot(
            db,
            snapshot_ref,
            area_id=operational_area_id,
        )
        return OfflineMapService.resolved_manifest(db, snapshot)
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/maps/{snapshot_ref}/layers")
def map_snapshot_layers(
    snapshot_ref: str,
    request: Request,
    operational_area_id: int | None = None,
    asset_ids: str | None = None,
    limit: int = 5000,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _principal(request)
    if limit < 1 or limit > 5000:
        raise HTTPException(status_code=422, detail="地图图层单次最多返回 5000 个要素")
    parsed_asset_ids: list[int] | None = None
    if asset_ids is not None:
        try:
            parsed_asset_ids = sorted({int(value) for value in asset_ids.split(",") if value})
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="地图要素编号格式无效") from exc
        if not parsed_asset_ids or len(parsed_asset_ids) > 50 or any(value <= 0 for value in parsed_asset_ids):
            raise HTTPException(status_code=422, detail="一次最多查询 50 个有效地图要素")
    try:
        return OfflineMapService.read_layers(
            db,
            snapshot_ref,
            area_id=operational_area_id,
            asset_ids=parsed_asset_ids,
            limit=limit,
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/maps/tiles/{snapshot_ref}/{z}/{x}/{y}")
def map_tile(
    snapshot_ref: str,
    z: int,
    x: int,
    y: int,
    request: Request,
    operational_area_id: int | None = None,
    blank_missing: bool = False,
    db: Session = Depends(get_db),
) -> BinaryResponse:
    _principal(request)
    try:
        content, media_type = OfflineMapService.read_tile(
            db,
            snapshot_ref,
            z,
            x,
            y,
            area_id=operational_area_id,
        )
    except ValueError as exc:
        if str(exc) == "tile_not_found" and blank_missing:
            cache_control = (
                "private, no-cache"
                if snapshot_ref == "current"
                else "private, max-age=31536000, immutable"
            )
            return BinaryResponse(
                content=TRANSPARENT_GIF,
                media_type="image/gif",
                headers={
                    "Cache-Control": cache_control,
                    "Vary": "Cookie, Authorization",
                    "X-Map-Coverage": "outside",
                },
            )
        raise _error(exc) from exc
    cache_control = (
        "private, no-cache"
        if snapshot_ref == "current"
        else "private, max-age=31536000, immutable"
    )
    return BinaryResponse(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": cache_control,
            "Vary": "Cookie, Authorization",
        },
    )
