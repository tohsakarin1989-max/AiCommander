#!/usr/bin/env python3
"""Retained v1-v3 workflows against serve-legacy-verification.py; no API mocking."""
import json
from pathlib import Path
import re
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:13046"
OUTPUT = Path(__file__).resolve().parents[1] / "output/legacy-verification-2026-09-12"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    suffix = uuid4().hex[:6]
    moderator_name, analyst_name = f"合成主持-{suffix}", f"合成分析-{suffix}"
    personnel_name, location_name = f"合成测试人员-{suffix}", f"合成测试重点部位-{suffix}"
    results, errors, http_errors, expected_states = [], [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1100}, accept_downloads=True)
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(BASE) else route.abort())
        page = context.new_page()
        page.set_default_timeout(15_000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("response", lambda response: http_errors.append({"url": response.url, "status": response.status})
                if "/api/" in response.url and response.status >= 400 and "/auth/me" not in response.url else None)

        def visit(path):
            page.goto(BASE + path)
            page.wait_for_load_state("networkidle")

        def record(name, detail):
            page.screenshot(path=str(OUTPUT / f"{name}.png"), full_page=True)
            results.append({"name": name, "detail": detail})
            print("PASS", name, flush=True)

        def choose(label, option):
            page.get_by_label(label, exact=True).locator("xpath=ancestor::*[contains(@class, 'ant-select-selector')][1]").click()
            page.locator(".ant-select-dropdown:visible").locator(".ant-select-item-option-content").filter(has_text=re.compile("^" + re.escape(option) + r"(?: \(|$)")).click()
            page.locator(".ant-modal-title:visible").last.click()

        def save(dialog):
            dialog.get_by_role("button", name=re.compile(r"^(OK|确\s*定)$")).click()
            expect(dialog).not_to_be_visible()

        def api(path):
            response = context.request.get(BASE + path)
            assert response.ok, (path, response.status, response.text())
            return response.json()

        try:
            visit("/settings")
            page.get_by_label("用户名", exact=True).fill("legacy-admin")
            page.get_by_label("密码", exact=True).fill("Disposable-Legacy-0912!")
            page.get_by_role("button", name="登录系统", exact=True).click()
            expect(page.get_by_role("heading", name="系统配置", exact=True)).to_be_visible()
            assert any(cookie["name"] == "aic_legacy_verification" for cookie in context.cookies()), "wrong fixture"
            # Re-running is allowed only after proving this is our disposable fixture.
            for old in api("/api/events/"):
                if old.get("title") == "合成留存事件转案验证":
                    assert context.request.delete(BASE + f"/api/events/{old['id']}", headers={"Origin": BASE}).ok
            visit("/settings")
            # Models use a non-listening local URL and synthetic credentials; connection is not tested here.
            for role, name in (("主持人", moderator_name), ("分析员", analyst_name)):
                page.get_by_role("button", name=re.compile("添加模型")).click()
                dialog = page.get_by_role("dialog")
                dialog.get_by_label("模型名称", exact=True).fill(name)
                dialog.get_by_label("模型名称/部署名", exact=True).fill("synthetic-model")
                dialog.get_by_label("API 密钥", exact=True).fill("synthetic-key-no-network")
                choose("角色", role)
                dialog.get_by_label("API Base URL（可选）", exact=True).fill("http://127.0.0.1:1/v1")
                save(dialog)
                expect(page.get_by_role("row").filter(has_text=name)).to_be_visible()
            model_list = api("/api/models/")
            assert len([item for item in model_list if item["name"] in {moderator_name, analyst_name}]) == 2
            assert all("api_key" not in item for item in model_list)
            row = page.get_by_role("row").filter(has_text=moderator_name)
            row.get_by_role("button", name="设为默认").click()
            expect(row.get_by_role("button", name="设为默认")).not_to_be_visible()
            row.get_by_role("button", name=re.compile("编辑")).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("描述", exact=True).fill("仅合成验证配置，禁止外部调用")
            save(dialog)
            assert next(item for item in api("/api/models/") if item["name"] == moderator_name)["is_default"]
            record("models-lifecycle", "页面新增主持/分析配置、默认主持、编辑及接口回读；未调用真实模型")

            visit("/meetings")
            page.get_by_role("button", name="＋ 发起新会议", exact=True).first.click()
            choose("主持人模型（综合报告生成者）", moderator_name)
            choose("分析员模型（建议 3-5 名）", analyst_name)
            page.get_by_role("button", name=re.compile("保存为模板")).click()
            dialog = page.get_by_role("dialog").filter(has=page.get_by_label("模板名称", exact=True))
            dialog.get_by_label("模板名称", exact=True).fill(f"合成历史会议模板-{suffix}")
            save(dialog)
            assert any(item["name"] == f"合成历史会议模板-{suffix}" for item in api("/api/meeting-templates/"))
            record("meeting-template", "选择当前有效模型→保存会议模板→真实接口回读")
            page.get_by_role("dialog").get_by_role("button", name=re.compile(r"取\s*消")).click()

            visit("/reports?meetingId=HISTORICAL-000")
            expect(page.locator(".rp-card-footer")).to_be_visible()
            with page.expect_download() as report_download:
                page.locator(".rp-card-footer").get_by_role("button", name=re.compile("导出")).click()
            report_path = OUTPUT / "historical-meeting-report.md"
            report_download.value.save_as(str(report_path))
            assert "合成历史报告" in report_path.read_text()
            page.locator(".rp-card-footer").get_by_role("button", name=re.compile("会议")).click()
            page.wait_for_url(re.compile(r"/meetings\?meetingId=HISTORICAL-000"))
            expect(page.get_by_role("dialog")).to_be_visible()
            record("historical-meeting-report", "超出默认前100条的历史报告→深链接→实际Markdown下载→会议详情")

            visit("/events")
            page.get_by_role("button", name="＋ 录入事件", exact=True).click()
            choose("事件类型", "查获车辆")
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("事件标题", exact=True).fill("合成留存事件转案验证")
            dialog.get_by_label("地点", exact=True).fill("合成测试场所")
            dialog.get_by_label("事件描述", exact=True).fill("仅为历史功能回归构造的查获车辆事件。")
            dialog.get_by_role("button", name="保存事件", exact=True).click()
            expect(dialog).not_to_be_visible()
            event = next(item for item in api("/api/events/") if item["title"] == "合成留存事件转案验证")
            row = page.get_by_role("row").filter(has_text=event["title"])
            row.get_by_role("button", name="转案件", exact=True).click()
            page.wait_for_url(re.compile(r"/cases\?caseId=\d+"))
            event_after = api(f"/api/events/{event['id']}")
            case = api(f"/api/cases/{event_after['related_case_id']}")
            assert "合成测试场所" in case["location"]
            replay = context.request.post(BASE + f"/api/events/{event['id']}/convert-to-case", headers={"Origin": BASE})
            assert replay.ok and replay.json()["case_id"] == case["id"]
            expect(page.get_by_text("成果尚未生成、引用已失效或当前不可访问。后台完成后自动显示，无需手动运行智能体。", exact=True)).to_be_visible()
            expected_states.extend(item for item in http_errors if item["status"] == 404 and item["url"] == BASE + f"/api/cases/{case['id']}/results/latest")
            http_errors[:] = [item for item in http_errors if item not in expected_states]
            record("event-case-bridge", "页面录入事件→转案件→详情跳转→回读关联→重复转案复用原案件")

            visit("/workbench")
            expect(page.locator(".wb-task-row").first).to_be_visible()
            task = api("/api/workbench/today")["tasks"][0]
            page.locator(".wb-task-row").filter(has_text=task["case_number"]).first.click()
            page.locator(".wb-start").click()
            page.wait_for_url(BASE + task["target_path"])
            active = api("/api/workbench/sessions/active")
            assert active and active["source_id"] == task["source_id"], active
            page.locator(".active-work-session").get_by_role("button", name="放弃", exact=True).click()
            expect(page.locator(".active-work-session")).not_to_be_visible()
            assert api("/api/workbench/sessions/active") is None
            record("workbench-handoff", "任务分流→开始处理→目标页面跳转→真实活动会话回读→结束本次合成测量")

            visit("/graphs/serial")
            page.get_by_placeholder("或手动输入 ID，逗号分隔：1,2,3").fill("1,2,3")
            with page.expect_response(lambda response: "/api/graphs/serial" in response.url) as graph_response:
                page.get_by_role("button", name=re.compile("生成图谱")).click()
            assert graph_response.value.ok
            graph = graph_response.value.json()
            assert len(graph["nodes"]) == 3 and graph["edges"]
            with page.expect_download() as download:
                page.get_by_title("导出 PNG", exact=True).click()
            download.value.save_as(str(OUTPUT / "serial-graph.png"))
            assert (OUTPUT / "serial-graph.png").stat().st_size > 1000
            record("serial-graph", "三案生成有边图谱→浏览器实际PNG下载")

            visit("/graphs/evidence?caseId=1")
            expect(page.get_by_role("button", name="导出证据摘要")).to_be_enabled()
            with page.expect_download() as download:
                page.get_by_role("button", name="导出证据摘要").click()
            evidence_path = OUTPUT / "evidence-summary.txt"
            download.value.save_as(str(evidence_path))
            assert "LEGACY-001" in evidence_path.read_text()
            page.locator(".eg-issues button").first.click() if page.locator(".eg-issues button").count() else None
            record("evidence-export", "指定案件读取证据关系→实际下载摘要并核对案件编号")

            visit("/gangs")
            with page.expect_response(lambda response: "/api/gangs/identify" in response.url) as identify:
                page.get_by_role("button", name=re.compile("开始分析")).click()
            assert identify.value.ok and identify.value.json()
            page.get_by_role("button", name=re.compile("画像详情")).click()
            expect(page.get_by_role("dialog")).to_be_visible()
            record("condition-cluster", "页面执行相似条件聚类→真实结果→画像详情")
            page.get_by_role("dialog").get_by_role("button", name="Close", exact=True).click()

            visit("/settings")
            page.get_by_role("tab", name=re.compile("保卫人员")).click()
            page.get_by_role("button", name=re.compile("添加人员")).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("姓名", exact=True).fill(personnel_name)
            dialog.get_by_label("工号/警号", exact=True).fill(f"SYNTHETIC-{suffix}")
            save(dialog)
            expect(page.get_by_role("row").filter(has_text=personnel_name)).to_be_visible()
            assert any(item["name"] == personnel_name for item in api("/api/personnel/"))
            record("legacy-personnel", "显式启用兼容模块→页面新增人员→列表及接口回读")
            page.get_by_role("tab", name=re.compile("重要部位")).click()
            page.get_by_role("button", name=re.compile("添加部位")).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("名称", exact=True).fill(location_name)
            choose("类型", "储油罐区")
            save(dialog)
            expect(page.get_by_role("row").filter(has_text=location_name)).to_be_visible()
            assert any(item["name"] == location_name for item in api("/api/key-locations/"))
            record("legacy-location", "显式启用兼容模块→页面新增重点部位→真实回读")
            # A new synthetic case intentionally has no asynchronous v4 result in this fixture.
            # Its explicit empty state was checked before leaving the case view above.
            expected_urls = {item["url"] for item in expected_states}
            late_expected = [item for item in http_errors if item["status"] == 404 and item["url"] in expected_urls]
            expected_states.extend(late_expected)
            http_errors[:] = [item for item in http_errors if item not in late_expected]
            assert not errors, errors
            assert not http_errors, http_errors
        finally:
            (OUTPUT / "browser-result.json").write_text(json.dumps({
                "passed": len(results) == 10 and not errors and not http_errors,
                "flows": results, "page_errors": errors, "http_errors": http_errors, "expected_states": expected_states,
                "boundary": "临时SQLite全API，无真实外部模型，无生产数据，无HTTP响应模拟",
            }, ensure_ascii=False, indent=2))
            if len(results) != 10:
                (OUTPUT / "failure-body.txt").write_text(page.locator("body").inner_text())
                page.screenshot(path=str(OUTPUT / "failure.png"), full_page=True)
            browser.close()


if __name__ == "__main__":
    main()
