"""联网区公共 XYZ 瓦片采集与受控离线地图包生成。"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Callable, Iterable


MAX_MERCATOR_LATITUDE = 85.05112878
DEFAULT_MAX_TILE_COUNT = 50_000
ABSOLUTE_MAX_TILE_COUNT = 100_000
DEFAULT_MAX_TILE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_PACKAGE_BYTES = 240 * 1024 * 1024
TileFetcher = Callable[[int, int, int], bytes]


def _validate_remote_url(
    url: str,
    allowed_hosts: set[str],
    *,
    redirect: bool,
) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("unsafe_tile_redirect" if redirect else "https_required")
    if parsed.username or parsed.password:
        raise ValueError(
            "unsafe_tile_redirect" if redirect else "tile_url_credentials_forbidden"
        )
    if not parsed.hostname or parsed.hostname.lower() not in allowed_hosts:
        raise ValueError("unsafe_tile_redirect" if redirect else "tile_host_not_allowed")


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """在发起重定向请求前复核目标，避免先访问后检查。"""

    def __init__(self, allowed_hosts: set[str]):
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_remote_url(newurl, self.allowed_hosts, redirect=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _tile_format(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "webp"
    raise ValueError("unsupported_tile_format")


def _coordinate_to_tile(longitude: float, latitude: float, zoom: int) -> tuple[int, int]:
    latitude = max(-MAX_MERCATOR_LATITUDE, min(MAX_MERCATOR_LATITUDE, latitude))
    tile_count = 1 << zoom
    x = int(math.floor((longitude + 180.0) / 360.0 * tile_count))
    latitude_radians = math.radians(latitude)
    y = int(
        math.floor(
            (1.0 - math.asinh(math.tan(latitude_radians)) / math.pi)
            / 2.0
            * tile_count
        )
    )
    return (
        max(0, min(tile_count - 1, x)),
        max(0, min(tile_count - 1, y)),
    )


def _iter_tiles(bounds: list[float], min_zoom: int, max_zoom: int) -> Iterable[tuple[int, int, int]]:
    west, south, east, north = bounds
    for zoom in range(min_zoom, max_zoom + 1):
        min_x, min_y = _coordinate_to_tile(west, north, zoom)
        max_x, max_y = _coordinate_to_tile(
            math.nextafter(east, west),
            math.nextafter(south, north),
            zoom,
        )
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                yield zoom, x, y


@dataclass(frozen=True)
class PublicTileFetchPolicy:
    """限制联网采集器只能请求显式批准的 HTTPS XYZ 主机。"""

    url_template: str
    allowed_hosts: set[str]
    timeout_seconds: float = 15.0
    request_delay_seconds: float = 0.0
    user_agent: str = "AiCommander-PublicMapBundleBuilder/1.0"
    max_tile_bytes: int = DEFAULT_MAX_TILE_BYTES

    def __post_init__(self) -> None:
        normalized_hosts = {item.strip().lower() for item in self.allowed_hosts if item.strip()}
        object.__setattr__(self, "allowed_hosts", normalized_hosts)
        _validate_remote_url(self.url_template, normalized_hosts, redirect=False)
        if not all(token in self.url_template for token in ("{z}", "{x}", "{y}")):
            raise ValueError("invalid_tile_url_template")
        if self.timeout_seconds <= 0 or self.request_delay_seconds < 0:
            raise ValueError("invalid_fetch_timing")
        if self.max_tile_bytes <= 0:
            raise ValueError("invalid_tile_size_limit")

    def fetch(self, zoom: int, x: int, y: int) -> bytes:
        url = self.url_template.format(z=zoom, x=x, y=y)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "image/png,image/jpeg,image/webp"},
        )
        opener = urllib.request.build_opener(
            _AllowlistedRedirectHandler(self.allowed_hosts)
        )
        with opener.open(request, timeout=self.timeout_seconds) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or not final.hostname:
                raise ValueError("unsafe_tile_redirect")
            if final.hostname.lower() not in self.allowed_hosts:
                raise ValueError("unsafe_tile_redirect")
            content = response.read(self.max_tile_bytes + 1)
        if len(content) > self.max_tile_bytes:
            raise ValueError("tile_too_large")
        if self.request_delay_seconds:
            time.sleep(self.request_delay_seconds)
        return content


class PublicMapBundleBuilder:
    """将批准的公共 XYZ 瓦片生成内网可验收的 ZIP + MBTiles 更新包。"""

    @staticmethod
    def build(
        *,
        output_path: Path,
        bounds: list[float],
        min_zoom: int,
        max_zoom: int,
        bundle_id: str,
        provider: str,
        source_version: str,
        license_record: str,
        attribution: str,
        fetch_tile: TileFetcher,
        max_tile_count: int = DEFAULT_MAX_TILE_COUNT,
        max_package_bytes: int = DEFAULT_MAX_PACKAGE_BYTES,
    ) -> dict[str, object]:
        normalized_bounds = PublicMapBundleBuilder._validate_inputs(
            output_path=output_path,
            bounds=bounds,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            bundle_id=bundle_id,
            provider=provider,
            source_version=source_version,
            license_record=license_record,
            attribution=attribution,
            max_tile_count=max_tile_count,
            max_package_bytes=max_package_bytes,
        )
        tiles = list(
            islice(
                _iter_tiles(normalized_bounds, min_zoom, max_zoom),
                max_tile_count + 1,
            )
        )
        if not tiles or len(tiles) > max_tile_count:
            raise ValueError("tile_count_limit_exceeded")

        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            raise ValueError("output_exists")
        mbtiles_file = tempfile.NamedTemporaryFile(
            prefix=".public-map-",
            suffix=".mbtiles",
            dir=output_path.parent,
            delete=False,
        )
        mbtiles_path = Path(mbtiles_file.name)
        mbtiles_file.close()
        package_file = tempfile.NamedTemporaryFile(
            prefix=".public-map-",
            suffix=".zip",
            dir=output_path.parent,
            delete=False,
        )
        package_path = Path(package_file.name)
        package_file.close()
        try:
            tile_format, tile_bytes_total = PublicMapBundleBuilder._write_mbtiles(
                mbtiles_path,
                tiles=tiles,
                bounds=normalized_bounds,
                min_zoom=min_zoom,
                max_zoom=max_zoom,
                attribution=attribution,
                fetch_tile=fetch_tile,
                max_package_bytes=max_package_bytes,
            )
            mbtiles_size = mbtiles_path.stat().st_size
            if mbtiles_size > max_package_bytes:
                raise ValueError("package_size_limit_exceeded")
            mbtiles_hash = PublicMapBundleBuilder._sha256_file(mbtiles_path)
            manifest = {
                "schema_version": "1.0",
                "bundle_id": bundle_id.strip(),
                "provider": provider.strip(),
                "source_version": source_version.strip(),
                "license": license_record.strip(),
                "attribution": attribution.strip(),
                "bounds": normalized_bounds,
                "contains_internal_data": False,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "tile_count": len(tiles),
                "tile_bytes": tile_bytes_total,
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
                "files": [
                    {
                        "name": "basemap.mbtiles",
                        "sha256": mbtiles_hash,
                        "size": mbtiles_size,
                        "format": tile_format,
                    }
                ],
            }
            PublicMapBundleBuilder._write_archive(package_path, manifest, mbtiles_path)
            if package_path.stat().st_size > max_package_bytes:
                raise ValueError("package_size_limit_exceeded")
            os.replace(package_path, output_path)
            return {
                "output": str(output_path),
                "bundle_id": bundle_id.strip(),
                "tile_count": len(tiles),
                "tile_format": tile_format,
                "size_bytes": output_path.stat().st_size,
                "sha256": PublicMapBundleBuilder._sha256_file(output_path),
            }
        finally:
            mbtiles_path.unlink(missing_ok=True)
            package_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_inputs(
        *,
        output_path: Path,
        bounds: list[float],
        min_zoom: int,
        max_zoom: int,
        bundle_id: str,
        provider: str,
        source_version: str,
        license_record: str,
        attribution: str,
        max_tile_count: int,
        max_package_bytes: int,
    ) -> list[float]:
        if output_path.suffix.lower() != ".zip":
            raise ValueError("output_must_be_zip")
        if len(bounds) != 4 or not all(isinstance(value, (int, float)) for value in bounds):
            raise ValueError("invalid_bounds")
        normalized = [float(value) for value in bounds]
        west, south, east, north = normalized
        if not (-180 <= west < east <= 180 and -85 <= south < north <= 85):
            raise ValueError("invalid_bounds")
        if not (0 <= min_zoom <= max_zoom <= 22):
            raise ValueError("invalid_zoom_range")
        if (
            max_tile_count <= 0
            or max_tile_count > ABSOLUTE_MAX_TILE_COUNT
            or max_package_bytes <= 0
        ):
            raise ValueError("invalid_limits")
        for value in (bundle_id, provider, source_version, license_record, attribution):
            if not value or not value.strip() or "\x00" in value or "\n" in value or "\r" in value:
                raise ValueError("invalid_manifest_value")
        return normalized

    @staticmethod
    def _write_mbtiles(
        path: Path,
        *,
        tiles: list[tuple[int, int, int]],
        bounds: list[float],
        min_zoom: int,
        max_zoom: int,
        attribution: str,
        fetch_tile: TileFetcher,
        max_package_bytes: int,
    ) -> tuple[str, int]:
        connection = sqlite3.connect(path)
        detected_format: str | None = None
        total_bytes = 0
        try:
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)")
            connection.execute(
                "CREATE TABLE tiles ("
                "zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX tile_index ON tiles "
                "(zoom_level, tile_column, tile_row)"
            )
            for zoom, x, y in tiles:
                content = fetch_tile(zoom, x, y)
                current_format = _tile_format(content)
                if detected_format is None:
                    detected_format = current_format
                elif detected_format != current_format:
                    raise ValueError("mixed_tile_formats")
                total_bytes += len(content)
                if total_bytes > max_package_bytes:
                    raise ValueError("package_size_limit_exceeded")
                tms_y = (1 << zoom) - 1 - y
                connection.execute(
                    "INSERT INTO tiles VALUES (?, ?, ?, ?)",
                    (zoom, x, tms_y, content),
                )
            if detected_format is None:
                raise ValueError("empty_tile_set")
            metadata = {
                "name": "AiCommander approved public basemap",
                "type": "baselayer",
                "version": "1",
                "description": "Public-only offline basemap; internal production data is merged inside AiCommander.",
                "format": detected_format,
                "bounds": ",".join(format(value, ".12g") for value in bounds),
                "minzoom": str(min_zoom),
                "maxzoom": str(max_zoom),
                "attribution": attribution,
            }
            connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
            connection.commit()
        finally:
            connection.close()
        return detected_format, total_bytes

    @staticmethod
    def _write_archive(path: Path, manifest: dict[str, object], mbtiles_path: Path) -> None:
        manifest_bytes = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            manifest_info = zipfile.ZipInfo("manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
            manifest_info.compress_type = zipfile.ZIP_DEFLATED
            manifest_info.external_attr = 0o600 << 16
            archive.writestr(manifest_info, manifest_bytes)
            tile_info = zipfile.ZipInfo("basemap.mbtiles", date_time=(1980, 1, 1, 0, 0, 0))
            tile_info.compress_type = zipfile.ZIP_DEFLATED
            tile_info.external_attr = 0o600 << 16
            with mbtiles_path.open("rb") as source, archive.open(tile_info, "w") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
