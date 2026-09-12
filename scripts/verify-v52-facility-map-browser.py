"""Synthetic component interaction only; no business DB, native engine or basemap acceptance."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:13048"
OUTPUT = Path(__file__).resolve().parents[1] / "output/playwright/v52-facility-map"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 1100})
        requests, errors = [], []

        def isolated(route):
            url = route.request.url
            if not url.startswith(BASE + "/"):
                route.abort()
            elif "/api/" in url:
                requests.append((route.request.method, url))
                route.fulfill(status=503, content_type="application/json", body='{"detail":"synthetic map outage"}')
            else:
                route.continue_()

        context.route("**/*", isolated)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_default_timeout(15000)
        try:
            page.goto(BASE + "/verification/facility-map.html")
            expect(page.get_by_role("heading", name="候选地图交互验收（隔离合成样本）")).to_be_visible()
            expect(page.locator(".leaflet-marker-icon")).to_have_count(3)
            expect(page.get_by_text("底图来源暂不可用，生产图层未加载；冻结入口标记仍可查看。", exact=True)).to_be_visible()
            print(page.locator("main").aria_snapshot()[:3500])
            second = page.get_by_role("listitem", name="候选 2：合成井场2")
            second.get_by_role("button", name="地图定位").click()
            expect(second.get_by_role("button", name="地图定位")).to_have_attribute("aria-pressed", "true")
            expect(page.locator(".leaflet-popup-content")).to_contain_text("2. 合成井场2（可信入口）")
            first_marker = page.get_by_role("button", name="1. 合成井场1（可信入口）", exact=True)
            first_marker.click()
            first = page.get_by_role("listitem", name="候选 1：合成井场1")
            expect(first).to_be_focused()
            expect(first.get_by_role("button", name="地图定位")).to_have_attribute("aria-pressed", "true")
            expect(page.locator(".leaflet-overlay-pane path")).to_have_count(0)
            expect(page.get_by_text("原活动区域候选继续保留", exact=True)).to_have_count(0)
            page.get_by_text("查看原空间分析与其他类型候选", exact=True).click()
            expect(page.get_by_text("原活动区域候选继续保留", exact=True)).to_be_visible()
            page.screenshot(path=str(OUTPUT / "desktop.png"), full_page=True)
            page.set_viewport_size({"width": 430, "height": 900})
            page.screenshot(path=str(OUTPUT / "narrow.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "horizontal overflow"
            assert requests and all(method == "GET" for method, _ in requests), requests
            assert not errors, errors
            print(json.dumps({"passed": True, "synthetic_only": True,
                "checks": ["three frozen points", "list to map", "map to evidence focus", "no invented path",
                           "legacy content retained", "no business writes", "no page errors", "narrow layout"],
                "not_verified": ["real basemap", "backend authorization", "native routing", "production server"]}, ensure_ascii=False))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
