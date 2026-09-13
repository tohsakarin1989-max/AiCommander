"""真实页面读取已执行的合成查询；模拟规划器不构成真实模型验收。"""
import json
from pathlib import Path
from zipfile import ZipFile

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:13150"
OUTPUT = Path(__file__).resolve().parents[1] / "output/v51-history-browser"


def main():
    fixture = json.loads((OUTPUT / "fixture.json").read_text())
    assert fixture["synthetic_only"] and fixture["planner"] == "simulation_not_real_model"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1100}, accept_downloads=True)
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(BASE) else route.abort())
        page = context.new_page()
        errors, writes = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: writes.append(request.url)
                if "/api/" in request.url and request.method not in {"GET", "HEAD", "OPTIONS"} else None)
        page.set_default_timeout(15000)
        try:
            page.goto(BASE)
            page.wait_for_load_state("networkidle")
            page.get_by_label("用户名", exact=True).fill("v50-analyst")
            page.get_by_label("密码", exact=True).fill("Disposable-V50-0912!")
            page.get_by_role("button", name="登录系统", exact=True).click()
            expect(page.get_by_role("heading", name="日常工作", exact=True)).to_be_visible()
            writes.clear()
            page.goto(BASE + f"/cases?caseId={fixture['source_case_id']}")
            page.wait_for_load_state("networkidle")
            history = page.get_by_role("region", name="历史案件与经验参考")
            expect(history).to_contain_text("V51-HISTORY-OLD")
            expect(history).to_contain_text("语义向量索引未启用")
            history.screenshot(path=str(OUTPUT / "case-history.png"))
            page.goto(BASE + f"/assistant?query={fixture['query_id']}")
            page.wait_for_load_state("networkidle")
            result = page.get_by_role("region", name="历史案件与经验参考")
            expect(result).to_contain_text("V51-HISTORY-OLD")
            expect(result).to_contain_text("相似条件")
            result.screenshot(path=str(OUTPUT / "assistant-history.png"))
            response = context.request.get(BASE + f"/api/intelligent-queries/{fixture['query_id']}/document.docx")
            assert response.ok, response.status
            target = OUTPUT / "history-query.docx"
            target.write_bytes(response.body())
            with ZipFile(target) as archive:
                xml = archive.read("word/document.xml").decode()
            assert "V51-HISTORY-OLD" in xml and "实际检索覆盖" in xml
            assert not errors and not writes, (errors, writes)
            report = {"status": "passed", "query_id": fixture["query_id"],
                "checks": ["authenticated nonempty case history", "same assistant history card",
                           "actual frozen Word export", "no browsing writes", "no page errors"],
                "not_verified": ["real model", "production server", "live planner interaction", "pgvector"]}
            (OUTPUT / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
