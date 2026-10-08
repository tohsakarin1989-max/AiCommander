#!/usr/bin/env python3
"""One real browser journey on serve-v8-verification, no mocked API/model."""
import json
from pathlib import Path
from zipfile import ZipFile

from playwright.sync_api import expect, sync_playwright

BASE = 'http://127.0.0.1:13084'
OUTPUT = Path(__file__).resolve().parents[1] / 'output/playwright/v8'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width': 1600, 'height': 1100}, accept_downloads=True)
        blocked, errors, writes = [], [], []
        def local_only(route):
            if route.request.url.startswith(BASE + '/'):
                route.continue_()
            else:
                blocked.append(route.request.url)
                route.abort()
        context.route('**/*', local_only)
        page = context.new_page()
        page.set_default_timeout(25000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: writes.append(request.url) if '/api/' in request.url
                and request.method not in {'GET', 'HEAD', 'OPTIONS'} else None)
        try:
            page.goto(BASE + '/')
            page.get_by_label('用户名', exact=True).fill('v8-check')
            page.get_by_label('密码', exact=True).fill('Disposable-V8-Only!')
            page.get_by_role('button', name='登录系统', exact=True).click()
            expect(page.get_by_role('heading', name='日常工作', exact=True)).to_be_visible()
            page.goto(BASE + '/dashboard')
            expect(page.get_by_label('大屏时间口径')).to_have_value('discovery')
            expect(page.get_by_text('本期记录', exact=True)).to_be_visible()
            expect(page.get_by_label('大屏周期')).to_have_value('30')
            summary = context.request.get(BASE + '/api/cases/dashboard-summary?operational_area_id=1&days=30&time_basis=discovery').json()
            assert summary['metrics']['cases'] == 1, summary
            assert summary['temporal_comparison']['change_origins']['late_entry']['count'] == 2
            assert summary['map']['cases'][0]['location_role'] == 'discovery'
            page.screenshot(path=str(OUTPUT / 'discovery-dashboard.png'), full_page=True)
            page.goto(BASE + '/cases?caseId=1')
            expect(page.get_by_role('link', name='以本条记录查历史参考（全部授权历史）', exact=True)).to_be_visible()
            writes.clear()
            page.get_by_role('link', name='以本条记录查历史参考（全部授权历史）', exact=True).click()
            expect(page.get_by_role('heading', name='直接回答业务问题', exact=True)).to_be_visible()
            assert not writes, writes
            page.get_by_role('button', name='这条记录有什么历史参考？', exact=True).click()
            answer = page.get_by_role('region', name='业务问题的完整回答', exact=True)
            expect(answer).to_be_visible()
            expect(answer).to_contain_text('可核对的参考')
            history_id = page.url.split('query=')[1].split('&')[0]
            data = context.request.get(BASE + f'/api/intelligent-queries/{history_id}').json()
            assert data['result']['usage']['model_requests'] == 0
            assert data['result']['answer']['schema_version'] == 'business-answer-8.4-1'
            assert len(data['result']['cards'][0]['data']['items']) <= 3
            page.get_by_text('展开本回答的同源地图', exact=True).click()
            expect(page.get_by_role('region', name='回答同源地图', exact=True)).to_be_visible()
            expect(page.get_by_role('region', name='回答同源地图', exact=True)).to_contain_text('发现地不等于盗取地')
            page.screenshot(path=str(OUTPUT / 'grounded-history-map.png'), full_page=True)
            with page.expect_download(timeout=60000) as download:
                page.get_by_role('button', name='导出 Word', exact=True).click()
            document = download.value
            assert document.failure() is None
            target = OUTPUT / 'frozen-business-answer.docx'
            document.save_as(str(target))
            with ZipFile(target) as archive:
                xml = archive.read('word/document.xml').decode()
                assert data['result']['answer']['direct_answer'] in xml
            page.get_by_role('link', name='在统一材料中阅读与判断', exact=True).click()
            expect(page.get_by_role('article', name='固定版本正文', exact=True)).to_contain_text(data['result']['answer']['direct_answer'])
            page.screenshot(path=str(OUTPUT / 'same-answer-material.png'), full_page=True)
            # No case in the context -> ask just one clarification, then resume.
            page.goto(BASE + '/assistant')
            page.get_by_role('button', name='这条记录有什么历史参考？', exact=True).click()
            clarification = page.get_by_role('region', name='补充一个关键条件', exact=True)
            expect(clarification).to_be_visible()
            clarification.get_by_label('查找案件', exact=True).fill('SYN-V8-1')
            clarification.get_by_role('button', name='查找案件', exact=True).click()
            clarification.get_by_role('button', name='选择此案', exact=True).click()
            expect(page.get_by_role('region', name='业务问题的完整回答', exact=True)).to_be_visible()
            page.goto(BASE + '/assistant?operational_area_id=1')
            page.get_by_role('button', name='最近发生了哪些实质变化？', exact=True).click()
            expect(page.get_by_role('region', name='业务问题的完整回答', exact=True)).to_contain_text('补录历史情况 2 起')
            page.screenshot(path=str(OUTPUT / 'late-entry-explanation.png'), full_page=True)
            assert not errors, errors
            assert not blocked, blocked
            result = {'status':'passed', 'synthetic_only':True, 'real_model_verified':False,
                'target_server_verified':False, 'public_requests':blocked, 'page_errors':errors,
                'checks':['discovery time default', 'late entry separated', 'sparse record opens',
                    'history plus contrast rules', 'same snapshot map and Word/material',
                    'one clarification resumes', 'no model requests'], 'history_query_id':history_id}
            (OUTPUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception:
            page.screenshot(path=str(OUTPUT / 'failure.png'), full_page=True)
            (OUTPUT / 'failure-text.txt').write_text(page.locator('body').inner_text())
            raise
        finally:
            browser.close()


if __name__ == '__main__':
    main()
