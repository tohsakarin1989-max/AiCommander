"""Real authenticated browser workflow against disposable synthetic storage only."""
import json
import os
from time import monotonic
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout, expect, sync_playwright

BASE = "http://127.0.0.1:13043"
OUTPUT = Path("output/playwright/internal-roads")
REAL_MAP = os.environ.get("AIC_PUBLIC_MAP_FIXTURE") == "1"
if REAL_MAP:
    OUTPUT = Path("output/playwright/internal-roads-real-map")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            external = []

            def restrict(route):
                if route.request.url.startswith(BASE + "/"):
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort()

            context.route("**/*", restrict)
            assert context.request.get(BASE + "/api/map-sources").status == 401
            assert context.request.post(BASE + "/api/auth/login", headers={"Origin": BASE},
                data={"username": "showcase-check", "password": "Disposable-showcase-0910!"}).status == 200
            original = context.request.get(BASE + "/api/cases/1").json()
            assert original["case_number"] == "SYNTHETIC-SEMANTIC-001"
            assets_before = context.request.get(BASE + "/api/jurisdiction/assets").json()
            created = context.request.post(BASE + "/api/map-sources", headers={"Origin": BASE},
                data={"source_key": "synthetic-roads", "name": "合成道路测试来源", "source_type": "internal_gis"})
            assert created.status == 201, created.text()
            source = created.json()["id"]
            manifest_checks = []
            for suffix in ("", "?operational_area_id=1"):
                start = monotonic()
                response = context.request.get(BASE + "/api/maps/current/manifest" + suffix, timeout=5000)
                manifest_checks.append({"suffix": suffix, "status": response.status,
                                        "elapsed_ms": round((monotonic() - start) * 1000)})
                assert response.status == (200 if REAL_MAP else 404), response.text()
                if REAL_MAP:
                    manifest_checks[-1]['snapshot_id'] = response.json()['snapshot_id']
                    manifest_checks[-1]['schema_version'] = response.json()['schema_version']
            print("direct_manifest_checks", manifest_checks, flush=True)
            feature = {"type": "Feature", "id": "test-road-1", "geometry": {
                "type": "MultiLineString", "coordinates": [[[125.0, 46.0], [125.01, 46.01]],
                                                            [[125.02, 46.02], [125.03, 46.03]]]},
                "properties": {"kind": "road", "name": "合成生产路", "conditions": {"gate": "unknown"}}}
            payload = {"type": "FeatureCollection", "coordinate_system": "EPSG:4326", "features": [feature]}
            page = context.new_page()
            errors = []
            map_resources = []
            def record_map_resource(response):
                if '/api/maps/' in response.url and any(part in response.url for part in ('/tiles/', '/glyphs/', '/style.json')):
                    map_resources.append({'url': response.url, 'status': response.status})
            page.on('response', record_map_resource)
            pending = set()
            manifest_requests = []
            page.on("response", lambda response: manifest_requests.append({"url": response.url, "status": response.status})
                    if "/api/maps/current/manifest" in response.url else None)
            page.on("request", lambda request: pending.add(request.url))
            page.on("requestfinished", lambda request: pending.discard(request.url))
            page.on("requestfailed", lambda request: pending.discard(request.url))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(BASE + "/jurisdiction")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeout:
                print("network_not_idle", sorted(pending), flush=True)
            page.screenshot(path=str(OUTPUT / "initial-page.png"), full_page=True)
            # Inspect actual rendered surface before following the observed controls.
            text = page.locator("body").inner_text()
            print("initial_text", text[:7000], flush=True)
            assert "内部道路与入口" in text
            panel = page.locator(".ant-card").filter(has=page.locator(".ant-card-head-title", has_text="内部道路与入口"))
            panel.get_by_role("combobox", name="内部道路来源").click()
            page.get_by_title("合成道路测试来源", exact=False).last.click()
            upload = panel.locator('input[type="file"]')
            upload.set_input_files({"name": "roads.geojson", "mimeType": "application/geo+json",
                                    "buffer": json.dumps(payload).encode()})
            save = panel.get_by_role("button", name="保存待核资料")
            expect(save).to_be_enabled()
            save.click()
            expect(panel.get_by_role("button", name="核对资料")).to_be_visible()
            geometry_map = panel.get_by_role("region", name="道路来源图形核对")
            path = geometry_map.locator("path.leaflet-interactive")
            expect(path).to_have_count(1)
            assert path.get_attribute("d").count("M") == 2, "separate_segments_must_not_be_joined"
            panel.get_by_role("button", name="核对资料").click()
            expect(path).to_have_attribute("stroke-width", "6")
            if REAL_MAP:
                expect(geometry_map.locator('.maplibregl-canvas')).to_be_visible(timeout=30000)
                expect(geometry_map.get_by_role('status')).to_have_count(0, timeout=30000)
                assert any('/tiles/' in row['url'] and row['status'] == 200 for row in map_resources)
                assert any('/glyphs/' in row['url'] and row['status'] == 200 for row in map_resources)
                disclosure = geometry_map.locator('details[aria-label="底图来源与空白说明"]')
                expect(disclosure).to_be_visible()
                disclosure.locator('summary').click()
                expect(disclosure.get_by_text('公开地图按来源已有资料显示', exact=False)).to_be_visible()
                geometry_map.screenshot(path=str(OUTPUT / 'source-boundary.png'))
                disclosure.locator('summary').click()
            geometry_map.screenshot(path=str(OUTPUT / "source-geometry.png"))
            form = panel.get_by_role("region", name="核验 合成生产路")
            form.get_by_label("核验决定", exact=True).click()
            page.get_by_title("资料已核验", exact=True).last.click()
            form.get_by_label("核验依据（台账、核查记录等）", exact=True).fill("合成资料第1页")
            form.get_by_label("核验说明", exact=True).fill("仅核对合成来源，通行和入口仍未知")
            form.get_by_role("button", name="记录核验决定").click()
            expect(panel.get_by_role("cell", name="资料已核验", exact=True)).to_be_visible()
            panel.get_by_role("button", name="刷新所选批次").click()
            expect(panel.get_by_role("cell", name="资料已核验", exact=True)).to_be_visible()
            listing = context.request.get(BASE + f"/api/map-sources/{source}/roads/imports").json()
            assert len(listing["items"]) == 1
            record_id = listing["items"][0]["id"]
            record_url = BASE + f"/api/map-sources/{source}/roads/imports/{record_id}"
            record = context.request.get(record_url).json()
            assert record["features"] == [feature]
            assert record["feature_reviews"][feature["id"]]["decision"] == "verified"
            assert record["routing_available"] is False
            # Same uploaded file must reuse the existing import, not create another road batch.
            upload.set_input_files({"name": "roads.geojson", "mimeType": "application/geo+json",
                                    "buffer": json.dumps(payload).encode()})
            expect(save).to_be_enabled()
            save.click()
            expect(panel.get_by_text(f"来源批次 {record_id} 已保存或复用，请核对资料。尚未发布路网。")).to_be_visible()
            assert len(context.request.get(BASE + f"/api/map-sources/{source}/roads/imports").json()["items"]) == 1
            panel.get_by_role("button", name="设为比较基准", exact=True).click()
            changed = json.loads(json.dumps(payload))
            changed["features"][0]["properties"]["conditions"]["gate"] = "closed"
            upload.set_input_files({"name": "changed-roads.geojson", "mimeType": "application/geo+json",
                                    "buffer": json.dumps(changed).encode()})
            expect(save).to_be_enabled()
            save.click()
            comparison = panel.get_by_role("region", name="道路版本比较结果")
            expect(comparison.get_by_text("涉及已核验资料，请核对", exact=True)).to_be_visible()
            expect(comparison.get_by_role("cell", name="通行条件", exact=True)).to_be_visible()
            imports = context.request.get(BASE + f"/api/map-sources/{source}/roads/imports").json()["items"]
            assert len(imports) == 2
            new_record = context.request.get(BASE + f"/api/map-sources/{source}/roads/imports/{imports[0]['id']}").json()
            assert new_record["feature_reviews"][feature["id"]] is None
            assert new_record["features"] == changed["features"]
            assert context.request.get(record_url).json()["features"] == [feature]
            assert not new_record["routing_available"]
            comparison.screenshot(path=str(OUTPUT / "version-comparison.png"))
            catalog = panel.get_by_role("region", name="跨批次道路目录")
            expect(catalog.get_by_text("有待核更新，历史核验未覆盖", exact=True)).to_be_visible()
            expect(catalog.get_by_role("button", name=f"历史核验批次 {record_id}", exact=True)).to_be_visible()
            panel.get_by_role("button", name="清除比较", exact=True).click()
            entrance = {"type": "Feature", "id": "entry-1", "geometry": {"type": "Point", "coordinates": [125, 46]},
                        "properties": {"kind": "entrance", "name": "合成入口", "road_id": feature["id"]}}
            upload.set_input_files({"name": "entrance.geojson", "mimeType": "application/geo+json", "buffer": json.dumps({
                "type": "FeatureCollection", "coordinate_system": "EPSG:4326", "features": [entrance]}).encode()})
            expect(save).to_be_enabled()
            save.click()
            expect(panel.get_by_role("heading", name="批次 3 的来源资料", exact=True)).to_be_visible()
            panel.get_by_role("button", name="核对资料", exact=True).click()
            entrance_form = panel.get_by_role("region", name="核验 合成入口")
            expect(entrance_form.get_by_text("入口与来源道路端点重合，实际连接仍待核验", exact=True)).to_be_visible()
            entrance_record = context.request.get(BASE + f"/api/map-sources/{source}/roads/imports/3").json()
            assert entrance_record["features"] == [entrance]
            assert entrance_record["entrance_checks"][0]["road_import_id"] == new_record["id"]
            assert entrance_record["entrance_checks"][0]["connected"] is None
            expect(catalog.get_by_role("cell", name="合成生产路", exact=True)).to_be_visible()
            expect(catalog.get_by_role("cell", name="合成入口", exact=True)).to_be_visible()
            entrance_form.screenshot(path=str(OUTPUT / "entrance-check.png"))
            entrance_form.get_by_label("核验决定", exact=True).click()
            page.get_by_title("资料已核验", exact=True).last.click()
            entrance_form.get_by_label("入口连接记录（可选，仅资料已核验时填写）", exact=True).click()
            page.get_by_title("连接已核验", exact=True).last.click()
            entrance_form.get_by_label("核验依据（台账、核查记录等）", exact=True).fill("合成入口核查记录")
            entrance_form.get_by_label("核验说明", exact=True).fill("仅合成测试确认连接，不代表通行许可")
            entrance_form.get_by_role("button", name="记录核验决定").click()
            expect(panel.get_by_role("cell", name="资料已核验", exact=True)).to_be_visible()
            checked = context.request.get(BASE + f"/api/map-sources/{source}/roads/imports/3").json()
            evidence = checked["entrance_checks"][0]["recorded_connection_evidence"]
            assert evidence["status"] == "connected" and evidence["road_import_id"] == new_record["id"]
            assert checked["routing_available"] is False
            panel.get_by_role("button", name="核对资料", exact=True).click()
            expect(entrance_form.get_by_text("该次连接记录：", exact=False)).to_be_visible()
            entrance_form.screenshot(path=str(OUTPUT / "connection-evidence.png"))
            entrance_form.get_by_label("核验决定", exact=True).click()
            page.get_by_title("待核验", exact=True).last.click()
            entrance_form.get_by_label("核验依据（台账、核查记录等）", exact=True).fill("合成撤回记录")
            entrance_form.get_by_label("核验说明", exact=True).fill("发现资料不足，连接恢复待核")
            entrance_form.get_by_role("button", name="记录核验决定").click()
            expect(panel.get_by_role("cell", name="待核验", exact=True).last).to_be_visible()
            revoked = context.request.get(BASE + f"/api/map-sources/{source}/roads/imports/3").json()
            assert revoked["entrance_checks"][0]["recorded_connection_evidence"] is None
            assert revoked["features"] == [entrance]
            for width in (1440, 420):
                page.set_viewport_size({"width": width, "height": 1000})
                panel.scroll_into_view_if_needed()
                panel.screenshot(path=str(OUTPUT / f"roads-{width}.png"))
            assert context.request.get(BASE + "/api/cases/1").json()["description"] == original["description"]
            assert context.request.get(BASE + "/api/jurisdiction/assets").json() == assets_before
            assert not errors, errors
            assert not external, external
            (OUTPUT / "report.json").write_text(json.dumps({"passed": True, "mockedResponses": False,
                "syntheticData": True, "realPublicMap": REAL_MAP, "mapResources": map_resources,
                "unchangedCaseAndAssets": True, "errors": errors,
                "blockedExternalRequests": external, "importId": record_id,
                "comparedImportId": new_record["id"], "newVersionNotAutoVerified": True,
                "entranceHistoricalReference": True, "catalogPreservesOmittedRoad": True,
                "connectionEvidenceSavedAndRevoked": True}, ensure_ascii=False, indent=2))
            (OUTPUT / "manifest-checks.json").write_text(json.dumps({"direct": manifest_checks,
                "browserResponses": manifest_requests, "pendingAtEnd": sorted(pending)}, indent=2))
            print("internal_road_browser_workflow_passed")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
