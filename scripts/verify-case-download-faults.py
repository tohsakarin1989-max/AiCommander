"""Real login/UI with explicitly injected export faults; no successful-export claim."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE = 'http://127.0.0.1:13043'
OUTPUT = Path('output/playwright/case-download-faults')


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(accept_downloads=True)
            login = context.request.post(BASE + '/api/auth/login', headers={'Origin': BASE},
                data={'username': 'showcase-check', 'password': 'Disposable-showcase-0910!'})
            assert login.status == 200
            page = context.new_page()
            errors, downloads, held = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('download', lambda download: downloads.append(download.suggested_filename))
            mode = {'value': 'failure'}

            def fault(route):
                if mode['value'] == 'hold':
                    held.append(route)
                elif mode['value'] == 'wrong-version':
                    route.fulfill(status=200, headers={'x-result-content-sha256': '0' * 64},
                        content_type='application/pdf', body=b'%PDF-synthetic-invalid-version')
                else:
                    route.fulfill(status=503, content_type='application/json', body='{"detail":"renderer_unavailable"}')

            page.route('**/api/case-results/*/document.*', fault)
            page.goto(BASE + '/cases?caseId=1')
            page.wait_for_load_state('networkidle')
            panel = page.get_by_role('region', name='统一研判成果', exact=True)
            button = panel.get_by_role('button', name='下载 PDF', exact=True)
            for value in ('failure', 'wrong-version'):
                mode['value'] = value
                button.click()
                panel.get_by_text('报告暂未生成成功，请稍后重试；地图或转换服务不可用时不会下载缺失内容的文件。', exact=True).wait_for()
                assert button.is_enabled()
                assert not downloads

            mode['value'] = 'hold'
            button.click()
            panel.get_by_role('button', name='停止等待', exact=True).wait_for()
            page.wait_for_function('document.querySelector(".case-result__download-actions button").disabled')
            panel.get_by_role('button', name='停止等待', exact=True).click()
            panel.get_by_text('已停止等待下载，后台正在执行的渲染可能仍会完成。', exact=True).wait_for()
            assert button.is_enabled()
            assert len(held) == 1, 'cancel scenario must reach the intercepted endpoint'
            # Flush any intercepted request after cancellation; it must never download.
            for route in held:
                route.abort()
            held.clear()
            button.click()
            panel.get_by_role('button', name='停止等待', exact=True).wait_for()
            page.wait_for_timeout(100)
            assert len(held) == 1, 'navigation scenario must have an in-flight request'
            page.goto(BASE + '/reports')
            for route in held:
                route.abort()
            page.wait_for_load_state('networkidle')
            assert not downloads and not errors
            (OUTPUT / 'report.json').write_text(json.dumps({'passed': True,
                'realAuthentication': True, 'exportFaultInjection': True,
                'checks': ['503', 'wrong_version', 'cancel', 'navigate_while_pending'],
                'unexpectedDownloads': downloads, 'pageErrors': errors}, indent=2))
            print('case_download_faults_passed')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
