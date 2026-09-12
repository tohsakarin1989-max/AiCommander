#!/usr/bin/env python3
"""One focused browser journey against disposable v5.0 full services; no API mocks."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:13150"
OUTPUT = Path(__file__).resolve().parents[1] / "output/v50-verification-2026-09-12"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1100}, accept_downloads=True)
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith(BASE) else route.abort())
        page = context.new_page()
        page.set_default_timeout(15000)
        errors, writes = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: writes.append(request.url)
                if "/api/" in request.url and request.method not in {"GET", "HEAD", "OPTIONS"} else None)
        try:
            page.goto(BASE + "/")
            page.wait_for_load_state("networkidle")
            page.get_by_label("用户名", exact=True).fill("v50-analyst")
            page.get_by_label("密码", exact=True).fill("Disposable-V50-0912!")
            page.get_by_role("button", name="登录系统", exact=True).click()
            expect(page.get_by_role("heading", name="日常工作", exact=True)).to_be_visible()
            assert any(cookie["name"] == "aic_v50_verification" for cookie in context.cookies())
            writes.clear()
            expect(page.get_by_role("link", name="查看案件 V50-SYNTHETIC-001", exact=True)).to_be_visible()
            page.screenshot(path=str(OUTPUT / "daily-workbench.png"), full_page=True)
            daily = context.request.get(BASE + "/api/workbench/daily").json()
            assert daily["summary"]["total_cases"] == 1
            assert daily["summary"]["analysis_ready"] == 1, daily
            page.get_by_role("link", name="查看案件 V50-SYNTHETIC-001", exact=True).click()
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("region", name="统一研判成果")).to_be_visible()
            expect(page.get_by_role("region", name="历史案件与经验参考")).to_be_visible()
            expect(page.get_by_role("region", name="历史案件与经验参考")).to_contain_text("语义向量索引未启用")
            with page.expect_download() as download_info:
                page.get_by_role("button", name="下载 Word", exact=True).click()
            download = download_info.value
            assert download.failure() is None
            download.save_as(str(OUTPUT / "same-version-report.docx"))
            expect(page.get_by_role("button", name="预处理", exact=True)).to_have_count(0)
            expect(page.get_by_text("本页批量复核", exact=True)).to_have_count(0)
            workspace = context.request.get(BASE + "/api/cases/1/workspace").json()
            result = workspace["result"]["data"]
            assert result is not None, workspace
            assert workspace["case"]["status"] == "pending"
            history_before = context.request.get(BASE + "/api/cases/1/results/history").json()
            page.screenshot(path=str(OUTPUT / "case-workspace.png"), full_page=True)
            page.get_by_role("link", name="在报告中心查看此版本", exact=True).click()
            page.wait_for_load_state("networkidle")
            assert f"resultId={result['id']}" in page.url
            expect(page.get_by_role("region", name="统一研判成果")).to_be_visible()
            history_after = context.request.get(BASE + "/api/cases/1/results/history").json()
            assert history_before == history_after, "reading created another snapshot"
            assert writes == [], writes
            page.screenshot(path=str(OUTPUT / "same-version-report.png"), full_page=True)
            # Page context is visible before submit; opening the assistant runs no task.
            page.goto(BASE + "/assistant?caseId=1&statuses=pending")
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("region", name="带入的案件与筛选条件")).to_be_visible()
            expect(page.get_by_role("region", name="带入的案件与筛选条件")).to_contain_text("1")
            assert writes == [], writes
            page.screenshot(path=str(OUTPUT / "assistant-context.png"), full_page=True)
            # Explicit draft action is distinct from browsing/formal approval.
            first = context.request.post(BASE + "/api/conclusions/generate", data={"case_id": 1}, headers={"Origin": BASE})
            assert first.ok, (first.status, first.text())
            second = context.request.post(BASE + "/api/conclusions/generate", data={"case_id": 1}, headers={"Origin": BASE})
            assert second.ok and first.json()["id"] == second.json()["id"]
            assert first.json()["status"] == "needs_review"
            assert first.json()["evidence"]["source_result"]["result_id"] == result["id"]
            assert first.json()["confidence_available"] is False
            page.goto(BASE + "/workbench")
            page.wait_for_load_state("networkidle")
            preview = page.get_by_role("region", name="待人工判断的结论")
            expect(preview.get_by_role("link", name="查看依据并判断")).to_have_count(1)
            assert writes == [], writes
            page.screenshot(path=str(OUTPUT / "daily-review-preview.png"), full_page=True)
            assert not errors, errors
            report = {"status": "passed", "scope": "synthetic SQLite, real HTTP and Chromium, Agent off",
                      "checks": ["authenticated daily workspace", "case deep link", "no manual preprocess",
                                 "same frozen report and Word download", "zero browsing writes", "idempotent draft reuse",
                                 "assistant inherits page selection without running", "daily preview shows actual draft once",
                                 "history reference section reads without writes and labels lexical fallback"],
                      "result_id": result["id"], "page_errors": errors,
                      "not_verified": ["production server", "real model", "PostgreSQL concurrent requests", "new road data"]}
            (OUTPUT / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False), flush=True)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
