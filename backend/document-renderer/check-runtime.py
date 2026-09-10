"""Offline image smoke test using synthetic text only; never connects to a DB."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

if os.environ.get('AIC_DISPOSABLE_RENDER_CHECK') != '1':
    raise RuntimeError('explicit_synthetic_check_required')
if os.getuid() == 0 or not os.statvfs('/').f_flag & os.ST_RDONLY:
    raise RuntimeError('nonroot_readonly_container_required')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.case_result_document import CaseResultDocument, DocumentBlock, DOCUMENT_SCHEMA
from app.services.case_result_export import render_docx
from app.services.case_result_pdf import _convert_generated_docx
from playwright.sync_api import sync_playwright

text = '离线合成报告：地图空白不代表没有道路。仅用于运行环境验证。'
document = CaseResultDocument(DOCUMENT_SCHEMA, 'synthetic-runtime', 'a' * 64, (
    DocumentBlock('heading', '离线报告运行环境验证'), DocumentBlock('paragraph', text),
    DocumentBlock('table', '合成记录', (('来源', '合成数据'), ('状态', '待核验'))),
))
docx = render_docx(document)
with ZipFile(io.BytesIO(docx)) as archive:
    assert text in archive.read('word/document.xml').decode()
pdf = _convert_generated_docx(docx)
assert pdf.startswith(b'%PDF-')
font = subprocess.run(['fc-match', '-f', '%{family}', 'Noto Sans CJK SC'], capture_output=True,
                      text=True, check=True, timeout=10).stdout
assert 'Noto Sans CJK SC' in font, font
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, timeout=15000)
    try:
        page = browser.new_page()
        page.route('**/*', lambda route: route.abort())
        page.set_content('<html lang="zh-CN"><p>离线浏览器：合成文字</p><canvas></canvas></html>')
        assert page.locator('p').inner_text() == '离线浏览器：合成文字'
        assert page.evaluate("Boolean(document.querySelector('canvas').getContext('webgl2'))")
        assert page.screenshot().startswith(b'\x89PNG')
    finally:
        browser.close()
print(json.dumps({'offline_runtime_smoke': 'passed', 'uid': os.getuid(),
                  'readonly_root': True,
                  'docx_bytes': len(docx), 'pdf_bytes': len(pdf), 'chinese_font': font,
                  'browser_webgl2': True, 'scope': 'synthetic runtime smoke; not full map export or visual PDF acceptance'}))
