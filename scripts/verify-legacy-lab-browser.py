#!/usr/bin/env python3
"""Verify restored Lab routes only against the disposable legacy HTTP fixture."""
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


BASE = "http://127.0.0.1:13046"
OUTPUT = Path(__file__).resolve().parents[1] / "output/legacy-verification-2026-09-12"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results, page_errors, http_errors, mutations = [], [], [], []
    expected_states, initialization = [], []
    contexts, pages = [], []
    run_id = None
    failure = None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)

        def visit(page, path, idle=True):
            page.goto(BASE + path, wait_until="domcontentloaded")
            if idle:
                page.wait_for_load_state("networkidle")

        def login(role, path):
            context = browser.new_context(viewport={"width": 1600, "height": 1100})
            contexts.append(context)
            context.route("**/*", lambda route: route.continue_()
                          if route.request.url.startswith(BASE) else route.abort())
            page = context.new_page()
            pages.append(page)
            page.set_default_timeout(15_000)
            page.on("pageerror", lambda error: page_errors.append({"role": role, "error": str(error)}))
            page.on("response", lambda response: http_errors.append({
                "role": role, "url": response.url, "status": response.status,
            }) if "/api/" in response.url and response.status >= 400
                and "/auth/me" not in response.url else None)
            page.on("request", lambda request: mutations.append({
                "role": role, "url": request.url, "method": request.method,
            }) if "/api/" in request.url and request.method not in {"GET", "HEAD", "OPTIONS"} else None)
            visit(page, path)
            page.get_by_label("用户名", exact=True).fill(f"legacy-{role}")
            page.get_by_label("密码", exact=True).fill("Disposable-Legacy-0912!")
            page.get_by_role("button", name="登录系统", exact=True).click()
            page.locator(".account-identity").first.wait_for()
            page.wait_for_load_state("networkidle")
            assert any(cookie["name"] == "aic_legacy_verification" for cookie in context.cookies()), "wrong fixture"
            assert get(context, "/api/auth/me")["role"] == role
            return context, page

        def get(context, path):
            response = context.request.get(BASE + path)
            assert response.ok, (path, response.status, response.text())
            return response.json()

        def record(page, name, details):
            page.screenshot(path=str(OUTPUT / f"lab-browser-{name}.png"), full_page=True)
            (OUTPUT / f"lab-browser-{name}.txt").write_text(page.locator("body").inner_text())
            results.append({"name": name, "details": details})
            print("PASS", name, flush=True)

        try:
            admin, page = login("admin", "/agent-lab")
            expect(page.get_by_role("heading", name="油盾 · 双域研判智能体", exact=True)).to_be_visible()
            assert get(admin, "/api/runtime/status")["features"]["agent_lab"] is True
            if "--initialize-models" in sys.argv:
                catalog = get(admin, "/api/meetings/model-options")
                for role, label in (("moderator", "主持"), ("analyst", "分析")):
                    if any(item["role"] == role for item in catalog):
                        continue
                    response = admin.request.post(BASE + "/api/models/", headers={"Origin": BASE}, data={
                        "name": f"合成Lab{label}-{uuid4().hex[:6]}", "provider": "openai", "role": role,
                        "model_name": "synthetic-model", "api_key": "synthetic-no-network",
                        "config": {"api_base_url": "http://127.0.0.1:1/v1"},
                        "description": "仅本轮隔离浏览器初始化；不调用模型",
                    })
                    assert response.ok, response.text()
                    initialization.append({"model_id": response.json()["id"], "role": role})
            if "--read-only" not in sys.argv:
                assets = get(admin, "/api/jurisdiction/assets?status=active&limit=500")
                asset = next(item for item in assets if item["name"] == "合成验证井")
                source_fields = ("name", "latitude", "longitude", "geometry", "verified")
                asset_before = {key: asset.get(key) for key in source_fields}
                query = f"合成Lab浏览器验证-{uuid4().hex[:8]}：只检查所选一处地图资源，仅核验排队与取消，不调用模型或写入资源。"
                creator = page.locator(".agent-create-card")
                expect(creator).to_contain_text("地图数据管家")
                creator.get_by_role("combobox").nth(2).click()
                page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter(
                    has_text=f"{asset['name']} · {asset['asset_type']} · #{asset['id']}"
                ).click()
                creator.locator("textarea").fill(query)
                creator.locator(".card-head").click()
                with page.expect_response(lambda response: response.request.method == "POST"
                                          and response.url.rstrip("/") == BASE + "/api/agent-runs") as created:
                    creator.get_by_role("button", name=re.compile("启动任务$")).click()
                response = created.value
                assert response.ok, response.text()
                run = response.json()
                run_id = run["id"]
                assert run["status"] == "queued" and run["task_type"] == "map_data_quality", run
                payload = response.request.post_data_json
                assert payload["case_ids"] == [] and payload["asset_ids"] == [asset["id"]], payload
                expect(page.locator(".agent-run-detail")).to_contain_text(run_id[:8])
                queued_readback = get(admin, f"/api/agent-runs/{run_id}")
                assert queued_readback["id"] == run_id and queued_readback["status"] == "queued"
                record(page, "queued", {"run_id": run_id, "asset_ids": payload["asset_ids"],
                                        "status": "queued", "api_readback_status": queued_readback["status"]})

                with page.expect_response(lambda response: response.request.method == "POST"
                                          and response.url == BASE + f"/api/agent-runs/{run_id}/cancel") as cancelled:
                    page.locator(".agent-run-detail").get_by_role("button", name="取消", exact=True).click()
                assert cancelled.value.ok and cancelled.value.json()["status"] == "cancelled"
                visit(page, f"/agent-lab?runId={run_id}")
                expect(page.locator(".agent-run-detail")).to_contain_text(run_id[:8])
                expect(page.locator(".agent-run-detail").get_by_role("button", name="取消", exact=True)).to_have_count(0)
                readback = get(admin, f"/api/agent-runs/{run_id}")
                assert readback["id"] == run_id and readback["status"] == "cancelled" and readback["query"] == query
                assert readback["performance"]["model_calls"] == 0
                asset_after = next(item for item in get(admin, "/api/jurisdiction/assets?status=active&limit=500")
                                   if item["id"] == asset["id"])
                assert {key: asset_after.get(key) for key in source_fields} == asset_before
                record(page, "cancelled-deeplink", {"run_id": run_id, "status": readback["status"],
                                                   "model_calls": 0, "source_asset_unchanged": True})

            visit(page, "/agents")
            expect(page.get_by_role("heading", name="智能运行运维中心", exact=True)).to_be_visible()
            expect(page.get_by_text("地理底座智能体", exact=True)).to_be_visible()
            record(page, "v3-runtime", "新运行中心独立读取版本、业务智能体与评测概览，不跳旧 Lab")

            analyst, analyst_page = login("analyst", "/meetings")
            options = get(analyst, "/api/meetings/model-options")
            assert options and all(set(option) == {"id", "name", "role", "is_active"} for option in options)
            moderator = next(option for option in options if option["role"] == "moderator")
            participant = next(option for option in options if option["role"] == "analyst")
            analyst_page.get_by_role("button", name="＋ 发起新会议", exact=True).first.click()
            dialog = analyst_page.get_by_role("dialog")
            for label, name in (("主持人模型（综合报告生成者）", moderator["name"]),
                                ("分析员模型（建议 3-5 名）", participant["name"])):
                dialog.get_by_label(label, exact=True).click()
                analyst_page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter(
                    has_text=re.compile("^" + re.escape(name) + "$")) .click()
                dialog.locator(".ant-modal-title").click()
                expect(dialog.locator(".ant-select-selection-item").filter(has_text=name)).to_be_visible()
            record(analyst_page, "analyst-meeting-options", {"available_roles": [moderator["role"], participant["role"]],
                                                            "safe_fields": sorted(options[0])})
            for path in ("/agent-lab", "/agents"):
                visit(analyst_page, path, idle=False)
                analyst_page.wait_for_url(BASE + "/dashboard")
            notice = analyst_page.get_by_role("status").filter(
                has_text="底图未配置或加载失败；当前覆盖物不代表底图完整，请联系管理员。")
            expect(notice).to_be_visible()
            manifest = analyst.request.get(BASE + "/api/maps/current/manifest?operational_area_id=1")
            assert manifest.status == 404, manifest.text()
            assert manifest.json().get("detail") == "地图版本不存在", manifest.text()
            expected_states.append({"role": "analyst", "url": manifest.url, "status": manifest.status,
                                    "response": manifest.json(), "visible_notice": notice.inner_text()})
            record(analyst_page, "analyst-admin-routes", "分析员访问两种管理员运行页面均被前端权限路由拦截，未发旧Lab写请求")

            viewer, viewer_page = login("viewer", "/meetings")
            for button in viewer_page.get_by_role("button", name="＋ 发起新会议", exact=True).all():
                expect(button).to_be_disabled()
            visit(viewer_page, "/events")
            expect(viewer_page.get_by_role("button", name="＋ 录入事件", exact=True)).to_be_disabled()
            visit(viewer_page, "/conclusions")
            for label in ("从案件生成", "草稿预览", "从会议生成"):
                expect(viewer_page.get_by_role("button", name=re.compile(re.escape(label) + "$"))).to_be_disabled()
            record(viewer_page, "viewer-readonly", "会议、事件和结论生成入口禁用，未触发业务写请求")
            assert not page_errors, page_errors
            expected_states.extend(item for item in http_errors if item["role"] == "analyst"
                                   and item["status"] == 404
                                   and item["url"] == BASE + "/api/maps/current/manifest?operational_area_id=1")
            http_errors[:] = [item for item in http_errors if item not in expected_states]
            assert not http_errors, http_errors
            unexpected = [item for item in mutations if not item["url"].endswith("/api/auth/login")
                          and not (item["role"] == "admin" and item["url"].rstrip("/") in {
                              BASE + "/api/agent-runs", BASE + f"/api/agent-runs/{run_id}/cancel"})]
            assert not unexpected, unexpected
        except Exception as exc:
            failure = repr(exc)
            for index, page in enumerate(pages):
                if not page.is_closed():
                    page.screenshot(path=str(OUTPUT / f"lab-browser-failure-{index}.png"), full_page=True)
            raise
        finally:
            (OUTPUT / ("lab-browser-readonly-result.json" if "--read-only" in sys.argv else "lab-browser-result.json")).write_text(json.dumps({
                "passed": len(results) == (4 if "--read-only" in sys.argv else 6) and failure is None and not page_errors and not http_errors,
                "read_only_probe": "--read-only" in sys.argv, "flows": results, "page_errors": page_errors, "http_errors": http_errors,
                "mutations": mutations, "model_initialization": initialization,
                "expected_states": expected_states, "failure": failure, "created_run_id": run_id,
                "boundary": "新浏览器上下文；本机临时合成库；Agent shadow隔离队列无Worker，仅验证queued→cancelled及深链接，不声称规则执行完成或模型调用效果；权限重定向的大屏未配置地图快照，其manifest 404单列环境状态。",
            }, ensure_ascii=False, indent=2))
            for context in contexts:
                context.close()
            browser.close()


if __name__ == "__main__":
    main()
