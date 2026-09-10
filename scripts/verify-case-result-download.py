"""Real authenticated API + browser downloads, synthetic fixture only."""
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

from playwright.sync_api import sync_playwright


BASE = "http://127.0.0.1:13043"
REAL_MAP = os.environ.get('AIC_PUBLIC_MAP_FIXTURE') == '1'
OUTPUT = Path("output/playwright/case-result-download-real-map" if REAL_MAP else "output/playwright/case-result-download")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 1000})
            external = []

            def route(request):
                if not request.request.url.startswith(BASE + "/"):
                    external.append(request.request.url)
                    request.abort()
                else:
                    request.continue_()

            context.route("**/*", route)
            assert context.request.get(BASE + "/api/cases/1/results/latest").status == 401
            login = context.request.post(BASE + "/api/auth/login", headers={"Origin": BASE},
                data={"username": "showcase-check", "password": "Disposable-showcase-0910!"})
            assert login.status == 200
            result = context.request.get(BASE + "/api/cases/1/results/latest").json()
            if REAL_MAP:
                assert result['content']['versions']['map_snapshot_id']
            original = context.request.get(BASE + "/api/cases/1").json()
            assert original["case_number"] == "SYNTHETIC-SEMANTIC-001"
            page = context.new_page()
            errors, downloaded = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            paths = ["/cases?caseId=1", "/case-intelligence?caseId=1", "/reports?resultId=" + result["id"]]
            for index, path in enumerate(paths):
                page.goto(BASE + path)
                panel = page.get_by_role("region", name="统一研判成果", exact=True)
                panel.get_by_role("button", name="下载 Word", exact=True).wait_for()
                page.wait_for_load_state("networkidle")
                for format in ("docx", "pdf"):
                    with page.expect_download(timeout=180000) as event:
                        panel.get_by_role("button", name="下载 Word" if format == "docx" else "下载 PDF", exact=True).click()
                    download = event.value
                    assert download.suggested_filename == f"case-result-{result['content_sha256'][:16]}.{format}"
                    target = OUTPUT / f"page-{index}.{format}"
                    download.save_as(target)
                    assert download.failure() is None
                    if format == "docx":
                        with ZipFile(target) as archive:
                            assert "原文否定" in archive.read("word/document.xml").decode()
                            if REAL_MAP:
                                images = [name for name in archive.namelist() if name.startswith('word/media/') and name.endswith('.png')]
                                assert len(images) == 1
                                assert len(archive.read(images[0])) > 10000
                    else:
                        reader = os.environ.get("AIC_PDF_CHECK_PYTHON", sys.executable)
                        text = subprocess.run([reader, "-c",
                            "import sys; from pypdf import PdfReader; print('\\n'.join(p.extract_text() for p in PdfReader(sys.argv[1]).pages))",
                            str(target)], capture_output=True, check=True).stdout.decode()
                        assert "原文否定" in text and result["content_sha256"][:20] in text
                    downloaded.append({"page": path, "format": format, "bytes": target.stat().st_size})
                for width in (1440, 420):
                    page.set_viewport_size({"width": width, "height": 1000})
                    controls = panel.locator(".case-result__download")
                    controls.scroll_into_view_if_needed()
                    assert controls.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
                    controls.screenshot(path=str(OUTPUT / f"controls-{index}-{width}.png"))
                page.set_viewport_size({"width": 1440, "height": 1000})
            assert context.request.get(BASE + "/api/cases/1").json()["description"] == original["description"]
            assert not errors and not external
            (OUTPUT / "report.json").write_text(json.dumps({"passed": True, "apiMocking": False,
                "syntheticData": True, "realPublicMap": REAL_MAP, "contentSha256": result['content_sha256'],
                "downloads": downloaded, "errors": errors, "external": external}, ensure_ascii=False, indent=2))
            print("case_result_download_passed")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
