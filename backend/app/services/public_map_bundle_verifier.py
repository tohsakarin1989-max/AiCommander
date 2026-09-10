"""联网区出包和内网导入前共用的离线地图包深度验收。"""
from __future__ import annotations

import hashlib
import io
import math
import sqlite3
import tempfile
import zlib
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.services.offline_map_service import OfflineMapService
from app.services.public_map_bundle_builder import _iter_tiles, _tile_format


MAX_VERIFIED_TILE_COUNT = 100_000
MAX_VERIFIED_TILE_BYTES = 2 * 1024 * 1024


class PublicMapBundleVerifier:
    """校验 ZIP、清单、MBTiles 完整性并逐瓦片读回。"""

    @staticmethod
    def verify_bytes(content: bytes) -> dict[str, Any]:
        manifest, mbtiles = OfflineMapService._read_validated_archive(content)
        report = PublicMapBundleVerifier.verify_archive(manifest, mbtiles)
        report["package_sha256"] = hashlib.sha256(content).hexdigest()
        return report

    @staticmethod
    def verify_archive(manifest: dict[str, Any], mbtiles: bytes) -> dict[str, Any]:
        """对已经完成 ZIP 基础校验的内容逐瓦片验收。"""
        declared_tile_count = manifest.get("tile_count")
        if (
            isinstance(declared_tile_count, bool)
            or not isinstance(declared_tile_count, int)
            or not 0 <= declared_tile_count <= MAX_VERIFIED_TILE_COUNT
        ):
            raise ValueError("tile_count_limit_exceeded")
        temporary = tempfile.NamedTemporaryFile(suffix=".mbtiles", delete=False)
        path = Path(temporary.name)
        try:
            temporary.write(mbtiles)
            temporary.close()
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if not {"tiles", "metadata"}.issubset(tables):
                    raise ValueError("invalid_mbtiles")
                metadata = dict(connection.execute("SELECT name, value FROM metadata"))
                bounded_row_count = connection.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM tiles LIMIT ?)",
                    (MAX_VERIFIED_TILE_COUNT + 1,),
                ).fetchone()
                if not bounded_row_count or bounded_row_count[0] > MAX_VERIFIED_TILE_COUNT:
                    raise ValueError("tile_count_limit_exceeded")
                rows = connection.execute(
                    "SELECT zoom_level, tile_column, tile_row, tile_data "
                    "FROM tiles"
                )
                tile_count = 0
                min_zoom: int | None = None
                max_zoom: int | None = None
                formats: set[str] = set()
                coordinates: set[tuple[int, int, int]] = set()
                for zoom, x, tms_y, tile in rows:
                    tile_count += 1
                    if tile_count > MAX_VERIFIED_TILE_COUNT:
                        raise ValueError("tile_count_limit_exceeded")
                    if not isinstance(zoom, int) or not 0 <= zoom <= 22:
                        raise ValueError("invalid_tile_coordinate")
                    limit = 1 << zoom
                    if not isinstance(x, int) or not isinstance(tms_y, int):
                        raise ValueError("invalid_tile_coordinate")
                    if not (0 <= x < limit and 0 <= tms_y < limit):
                        raise ValueError("invalid_tile_coordinate")
                    coordinate = (zoom, x, tms_y)
                    if coordinate in coordinates:
                        raise ValueError("duplicate_tile_coordinate")
                    coordinates.add(coordinate)
                    if not isinstance(tile, (bytes, bytearray, memoryview)):
                        raise ValueError("invalid_mbtiles")
                    tile_bytes = bytes(tile)
                    if not tile_bytes or len(tile_bytes) > MAX_VERIFIED_TILE_BYTES:
                        raise ValueError("tile_too_large")
                    tile_format = _tile_format(tile_bytes)
                    PublicMapBundleVerifier._validate_tile_image(tile_bytes, tile_format)
                    formats.add(tile_format)
                    min_zoom = zoom if min_zoom is None else min(min_zoom, zoom)
                    max_zoom = zoom if max_zoom is None else max(max_zoom, zoom)
            except sqlite3.Error as exc:
                raise ValueError("invalid_mbtiles") from exc
            finally:
                connection.close()
        finally:
            if not temporary.closed:
                temporary.close()
            path.unlink(missing_ok=True)

        if tile_count == 0 or min_zoom is None or max_zoom is None:
            raise ValueError("empty_tile_set")
        if len(formats) != 1:
            raise ValueError("mixed_tile_formats")
        tile_format = next(iter(formats))
        if metadata.get("format", "").lower() != tile_format:
            raise ValueError("tile_format_mismatch")

        if declared_tile_count != tile_count:
            raise ValueError("tile_count_mismatch")
        if manifest.get("min_zoom") is not None and manifest["min_zoom"] != min_zoom:
            raise ValueError("zoom_range_mismatch")
        if manifest.get("max_zoom") is not None and manifest["max_zoom"] != max_zoom:
            raise ValueError("zoom_range_mismatch")
        PublicMapBundleVerifier._validate_declared_coverage(
            manifest,
            metadata,
            coordinates,
            min_zoom,
            max_zoom,
        )
        return {
            "status": "passed",
            "bundle_id": manifest["bundle_id"],
            "provider": manifest["provider"],
            "source_version": manifest["source_version"],
            "license": manifest["license"],
            "bounds": manifest["bounds"],
            "tile_count": tile_count,
            "min_zoom": min_zoom,
            "max_zoom": max_zoom,
            "tile_format": tile_format,
            "mbtiles_sha256": hashlib.sha256(mbtiles).hexdigest(),
            "contains_internal_data": False,
        }

    @staticmethod
    def _validate_declared_coverage(
        manifest: dict[str, Any],
        metadata: dict[str, str],
        coordinates: set[tuple[int, int, int]],
        min_zoom: int,
        max_zoom: int,
    ) -> None:
        """把清单范围与 MBTiles 元数据、实际瓦片坐标三方绑定。"""
        try:
            manifest_bounds = [float(value) for value in manifest["bounds"]]
            metadata_bounds = [
                float(value.strip()) for value in metadata["bounds"].split(",")
            ]
            metadata_min_zoom = int(metadata["minzoom"])
            metadata_max_zoom = int(metadata["maxzoom"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("tile_coverage_mismatch") from exc
        if len(metadata_bounds) != 4 or any(
            not math.isclose(expected, actual, rel_tol=0, abs_tol=1e-7)
            for expected, actual in zip(manifest_bounds, metadata_bounds, strict=True)
        ):
            raise ValueError("tile_coverage_mismatch")
        if metadata_min_zoom != min_zoom or metadata_max_zoom != max_zoom:
            raise ValueError("tile_coverage_mismatch")

        expected_all: set[tuple[int, int, int]] = set()
        for zoom in range(min_zoom, max_zoom + 1):
            for _, x, y in _iter_tiles(manifest_bounds, zoom, zoom):
                expected_all.add((zoom, x, (1 << zoom) - 1 - y))
                if len(expected_all) > MAX_VERIFIED_TILE_COUNT:
                    raise ValueError("tile_count_limit_exceeded")
        if not expected_all or coordinates != expected_all:
            raise ValueError("tile_coverage_mismatch")

    @staticmethod
    def _validate_tile_image(content: bytes, tile_format: str) -> None:
        """对 PNG/JPEG/WebP 同时执行容器检查与完整像素解码。"""
        if not content or len(content) > MAX_VERIFIED_TILE_BYTES:
            raise ValueError("tile_too_large")
        try:
            expected = {
                "png": "PNG",
                "jpg": "JPEG",
                "webp": "WEBP",
            }.get(tile_format)
            if expected is None:
                raise ValueError("unsupported_tile_format")
            with Image.open(io.BytesIO(content)) as image:
                if image.format != expected or image.width <= 0 or image.height <= 0:
                    raise ValueError("corrupt_tile_image")
                if image.width > 2048 or image.height > 2048:
                    raise ValueError("tile_dimensions_too_large")
                image.verify()
            # verify 校验容器；重新打开并 load，确保压缩载荷能够完整解码。
            with Image.open(io.BytesIO(content)) as image:
                image.load()
            if tile_format == "png":
                PublicMapBundleVerifier._validate_png(content)
            elif tile_format == "jpg":
                PublicMapBundleVerifier._validate_jpeg(content)
            elif tile_format == "webp":
                PublicMapBundleVerifier._validate_webp(content)
            else:
                raise ValueError("unsupported_tile_format")
        except (IndexError, OverflowError, UnidentifiedImageError, OSError, zlib.error) as exc:
            raise ValueError("corrupt_tile_image") from exc

    @staticmethod
    def _validate_png(content: bytes) -> None:
        if len(content) < 45 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("corrupt_tile_image")
        offset = 8
        chunk_index = 0
        saw_idat = False
        saw_ihdr = False
        saw_iend = False
        while offset + 12 <= len(content):
            size = int.from_bytes(content[offset : offset + 4], "big")
            chunk_type = content[offset + 4 : offset + 8]
            end = offset + 12 + size
            if end > len(content):
                raise ValueError("corrupt_tile_image")
            data = content[offset + 8 : offset + 8 + size]
            expected_crc = int.from_bytes(content[offset + 8 + size : end], "big")
            if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != expected_crc:
                raise ValueError("corrupt_tile_image")
            if chunk_index == 0:
                if chunk_type != b"IHDR" or size != 13:
                    raise ValueError("corrupt_tile_image")
                width = int.from_bytes(data[0:4], "big")
                height = int.from_bytes(data[4:8], "big")
                if width <= 0 or height <= 0:
                    raise ValueError("corrupt_tile_image")
                saw_ihdr = True
            elif chunk_type == b"IDAT":
                saw_idat = True
            elif chunk_type == b"IEND":
                if size != 0 or end != len(content):
                    raise ValueError("corrupt_tile_image")
                saw_iend = True
                break
            offset = end
            chunk_index += 1
        if not saw_ihdr or not saw_idat or not saw_iend:
            raise ValueError("corrupt_tile_image")

    @staticmethod
    def _validate_jpeg(content: bytes) -> None:
        if len(content) < 16 or not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9"):
            raise ValueError("corrupt_tile_image")
        offset = 2
        saw_frame = False
        saw_scan = False
        frame_markers = {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }
        while offset < len(content) - 2:
            if content[offset] != 0xFF:
                if saw_scan:
                    offset += 1
                    continue
                raise ValueError("corrupt_tile_image")
            while offset < len(content) and content[offset] == 0xFF:
                offset += 1
            if offset >= len(content):
                raise ValueError("corrupt_tile_image")
            marker = content[offset]
            offset += 1
            if marker == 0x00 or 0xD0 <= marker <= 0xD7:
                if not saw_scan:
                    raise ValueError("corrupt_tile_image")
                continue
            if marker == 0xD9:
                break
            if marker in {0x01, 0xD8}:
                continue
            if offset + 2 > len(content):
                raise ValueError("corrupt_tile_image")
            size = int.from_bytes(content[offset : offset + 2], "big")
            if size < 2 or offset + size > len(content):
                raise ValueError("corrupt_tile_image")
            if marker in frame_markers:
                if size < 7:
                    raise ValueError("corrupt_tile_image")
                height = int.from_bytes(content[offset + 3 : offset + 5], "big")
                width = int.from_bytes(content[offset + 5 : offset + 7], "big")
                if width <= 0 or height <= 0:
                    raise ValueError("corrupt_tile_image")
                saw_frame = True
            if marker == 0xDA:
                saw_scan = True
            offset += size
        if not saw_frame or not saw_scan:
            raise ValueError("corrupt_tile_image")

    @staticmethod
    def _validate_webp(content: bytes) -> None:
        if (
            len(content) < 20
            or content[:4] != b"RIFF"
            or content[8:12] != b"WEBP"
            or int.from_bytes(content[4:8], "little") + 8 != len(content)
        ):
            raise ValueError("corrupt_tile_image")
        offset = 12
        saw_image = False
        while offset + 8 <= len(content):
            chunk_type = content[offset : offset + 4]
            size = int.from_bytes(content[offset + 4 : offset + 8], "little")
            data_start = offset + 8
            data_end = data_start + size
            if data_end > len(content):
                raise ValueError("corrupt_tile_image")
            payload = content[data_start:data_end]
            if chunk_type == b"VP8 ":
                if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a":
                    raise ValueError("corrupt_tile_image")
                saw_image = True
            elif chunk_type == b"VP8L":
                if len(payload) < 5 or payload[0] != 0x2F:
                    raise ValueError("corrupt_tile_image")
                saw_image = True
            elif chunk_type == b"VP8X":
                if len(payload) != 10:
                    raise ValueError("corrupt_tile_image")
            offset = data_end + (size % 2)
        if offset != len(content) or not saw_image:
            raise ValueError("corrupt_tile_image")
