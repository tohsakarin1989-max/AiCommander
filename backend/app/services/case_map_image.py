"""固定本地资源离屏渲染；可选依赖缺失不影响案件主流程。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import BoundedSemaphore

from app.services.case_map_render_resources import CaseMapRenderResources, RENDER_ORIGIN
from app.services.case_result_map import load_result_map_context
from app.services.case_result_service import CaseResultService
from app.services.document_budget import remaining_seconds


RENDERER = Path(__file__).resolve().parents[2] / "document-renderer"
SLOTS = BoundedSemaphore(1)
STATIC_NAMES = frozenset({"maplibre-gl.mjs", "maplibre-gl-shared.mjs", "maplibre-gl-worker.mjs", "maplibre-gl.css"})
HTML = b'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<link rel="stylesheet" href="/static/maplibre-gl.css">
<style>body{margin:0;background:white;font:16px sans-serif;color:#17212b}#map{height:500px}
#legend{font-size:22px;padding:12px;white-space:pre-wrap;line-height:1.5;overflow-wrap:anywhere}</style>
<div id="map"></div><div id="legend"></div><script type="module" src="/render.mjs"></script></html>'''


class CaseMapImageError(ValueError):
    pass


def render_case_map_image(db, result_id: str) -> bytes:
    context = load_result_map_context(db, result_id)
    if context["basemap"] is None:
        raise CaseMapImageError("map_snapshot_required")
    if len(json.dumps(context, ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise CaseMapImageError("map_render_input_too_large")
    resources = CaseMapRenderResources(db, result_id)
    if not SLOTS.acquire(blocking=False):
        raise CaseMapImageError("map_renderer_busy")
    try:
        return _render(db, context, resources)
    finally:
        SLOTS.release()


def _render(db, context, resources) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise CaseMapImageError("map_renderer_not_installed") from None
    failures = []

    def route_request(route):
        url = route.request.url
        try:
            if route.request.method != "GET":
                raise ValueError("method_denied")
            if url == RENDER_ORIGIN + "/":
                content, media_type = HTML, "text/html"
            elif url == RENDER_ORIGIN + "/render.mjs":
                content, media_type = (RENDERER / "map-render.mjs").read_bytes(), "text/javascript"
            elif url in {RENDER_ORIGIN + "/static/" + name for name in STATIC_NAMES}:
                name = url.rsplit("/", 1)[1]
                content = (RENDERER / "node_modules/maplibre-gl/dist" / name).read_bytes()
                media_type = "text/css" if name.endswith(".css") else "text/javascript"
            else:
                content, media_type = resources.read(url)
            route.fulfill(body=content, content_type=media_type, headers={"Cache-Control": "no-store"})
        except (ValueError, OSError):
            failures.append("map_resource_failed")
            route.abort()

    try:
        with sync_playwright() as playwright:
            browser_env = {name: os.environ[name] for name in ("PATH", "LANG", "HOME", "TMPDIR", "SYSTEMROOT")
                           if name in os.environ}
            browser = playwright.chromium.launch(headless=True, timeout=remaining_seconds(15) * 1000, env=browser_env)
            try:
                browser_context = browser.new_context(viewport={"width": 960, "height": 700},
                    device_scale_factor=1, service_workers="block", accept_downloads=False)
                browser_context.route("**/*", route_request)
                browser_context.route_web_socket("**/*", lambda socket: socket.close())
                page = browser_context.new_page()
                page.set_default_timeout(20000)
                page.goto(RENDER_ORIGIN + "/", wait_until="networkidle", timeout=remaining_seconds(20) * 1000)
                page.wait_for_function("typeof window.renderFrozenMap === 'function'", timeout=remaining_seconds(20) * 1000)
                # 不把异步渲染Promise直接交给evaluate无限等待；使用有界状态等待。
                page.evaluate("input => { window.renderFrozenMap(input).catch(() => { window.mapRenderError = 'failed'; }); }", context)
                page.wait_for_function("window.mapRenderDone || window.mapRenderError", timeout=remaining_seconds(20) * 1000)
                if failures or page.evaluate("Boolean(window.mapRenderError)"):
                    raise CaseMapImageError("map_render_failed")
                if page.locator("#legend").bounding_box(timeout=remaining_seconds(20) * 1000)["height"] > 1000:
                    raise CaseMapImageError("map_legend_too_large")
                image = page.screenshot(type="png", full_page=True, timeout=remaining_seconds(20) * 1000)
            finally:
                browser.close()
    except CaseMapImageError:
        raise
    except Exception:
        raise CaseMapImageError("map_renderer_unavailable") from None
    # 图片生成后重新授权，撤权时不交付旧图片。
    result = CaseResultService.read(db, context["result_id"])
    if result["content_sha256"] != context["content_sha256"]:
        raise CaseMapImageError("map_result_changed")
    if not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image) > 8 * 1024 * 1024:
        raise CaseMapImageError("map_render_output_invalid")
    return image
