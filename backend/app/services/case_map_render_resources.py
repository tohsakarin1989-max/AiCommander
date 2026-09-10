"""离屏地图资源入口：URL仅用于本地分派，不建立HTTP连接。"""
from __future__ import annotations

import json
import re
from urllib.parse import unquote, urlsplit

from sqlalchemy.orm import Session

from app.services.case_result_service import CaseResultService
from app.services.map_glyph_service import read_glyph
from app.services.map_render_service import read_sprite, read_style
from app.services.offline_map_service import OfflineMapService


RENDER_ORIGIN = "https://aic-map.invalid"
MAX_REQUESTS = 256
MAX_RESOURCE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 48 * 1024 * 1024


class MapRenderResourceError(ValueError):
    pass


def _resource_request(url: str, snapshot_id: str) -> tuple[str, tuple]:
    if (not isinstance(url, str) or len(url) > 2048 or "\\" in url
            or any(ord(char) <= 32 or ord(char) == 127 for char in url)):
        raise MapRenderResourceError("map_render_resource_denied")
    try:
        parts = urlsplit(url)
        path = unquote(parts.path, errors="strict")
    except ValueError:
        raise MapRenderResourceError("map_render_resource_denied") from None
    if (parts.scheme != "https" or parts.netloc != "aic-map.invalid"
            or parts.query or parts.fragment):
        raise MapRenderResourceError("map_render_resource_denied")
    if (any(part in {".", ".."} for part in path.split("/")) or "%" in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        raise MapRenderResourceError("map_render_resource_denied")
    prefix = f"/api/maps/{snapshot_id}/"
    if path == prefix + "style.json":
        return "style", ()
    if path.startswith(prefix + "sprite"):
        suffix = path[len(prefix + "sprite"):]
        if suffix in {".json", ".png", "@2x.json", "@2x.png"}:
            return "sprite", (suffix,)
    glyph = re.fullmatch(re.escape(prefix) + r"glyphs/([^/]{1,200})/([0-9]{1,5}-[0-9]{1,5})\.pbf", path)
    if glyph:
        return "glyph", (glyph[1], glyph[2])
    tile = re.fullmatch(re.escape(f"/api/maps/tiles/{snapshot_id}/") + r"([0-9]{1,2})/([0-9]{1,8})/([0-9]{1,8})", path)
    if tile:
        z, x, y = (int(part) for part in tile.groups())
        if 0 <= z <= 22 and x < 2**z and y < 2**z:
            return "tile", (z, x, y)
    raise MapRenderResourceError("map_render_resource_denied")


class CaseMapRenderResources:
    """一个渲染任务一个实例；不得跨用户缓存已授权字节。"""

    def __init__(self, db: Session, result_id: str):
        self.db = db
        self.result_id = result_id
        result = CaseResultService.read(db, result_id)
        self.snapshot_id = result["content"]["versions"]["map_snapshot_id"]
        self.content_sha256 = result["content_sha256"]
        if not self.snapshot_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,36}", self.snapshot_id):
            raise MapRenderResourceError("map_render_snapshot_required")
        self.requests = 0
        self.bytes_read = 0

    def read(self, url: str) -> tuple[bytes, str]:
        # 失败请求同样消耗预算，避免坏包或异常样式无限重试。
        self.requests += 1
        if self.requests > MAX_REQUESTS or self.bytes_read >= MAX_TOTAL_BYTES:
            raise MapRenderResourceError("map_render_budget_exceeded")
        kind, args = _resource_request(url, self.snapshot_id)
        current = CaseResultService.read(self.db, self.result_id)
        if current["content_sha256"] != self.content_sha256:
            raise MapRenderResourceError("map_render_result_changed")
        try:
            if kind == "style":
                content = json.dumps(read_style(self.db, self.snapshot_id), ensure_ascii=False, allow_nan=False).encode()
                media_type = "application/json"
            elif kind == "sprite":
                content, media_type = read_sprite(self.db, self.snapshot_id, *args)
            elif kind == "glyph":
                content, media_type = read_glyph(self.db, self.snapshot_id, *args), "application/x-protobuf"
            else:
                content, media_type = OfflineMapService.read_tile(self.db, self.snapshot_id, *args)
        except (ValueError, OSError):
            raise MapRenderResourceError("map_render_resource_unavailable") from None
        size = len(content)
        self.bytes_read += size
        if not size or size > MAX_RESOURCE_BYTES or self.bytes_read > MAX_TOTAL_BYTES:
            raise MapRenderResourceError("map_render_budget_exceeded")
        return content, media_type
