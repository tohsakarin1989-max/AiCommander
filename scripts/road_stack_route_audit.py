"""Visit every concrete application route against the owned synthetic stack."""
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit


def audit_routes(context, base, output):
    """Record real page/API results; distinguish feature redirects from pages."""
    source = Path(__file__).resolve().parents[1] / 'frontend/src/App.tsx'
    paths = re.findall(r'<Route\s+path="([^"]+)"', source.read_text())
    paths = [path for path in paths if path != '*' and ':' not in path]
    records = []
    page = context.new_page()
    try:
        for index, path in enumerate(paths):
            errors, responses = [], []
            on_error = lambda error: errors.append(error.stack or str(error))
            on_response = lambda response: responses.append({
                'path': urlsplit(response.url).path, 'status': response.status,
            }) if '/api/' in response.url else None
            page.on('pageerror', on_error)
            page.on('response', on_response)
            started = time.perf_counter()
            navigation_error = None
            try:
                page.goto(base + path, wait_until='networkidle', timeout=30000)
                page.get_by_text('模块加载中', exact=True).wait_for(state='hidden', timeout=15000)
                body = page.locator('body').inner_text()
                record = {
                    'requested_path': path, 'rendered_path': urlsplit(page.url).path,
                    'headings': page.get_by_role('heading').all_text_contents(),
                    'body': body, 'responses': responses, 'page_errors': errors,
                    'elapsed_ms': round((time.perf_counter() - started) * 1000, 2),
                    'horizontal_overflow': page.evaluate(
                        'document.documentElement.scrollWidth > window.innerWidth + 2'),
                }
                record['redirected'] = record['rendered_path'] != path
                record['expected_unavailable_responses'] = [row for row in responses
                    if row['status'] == 404 and row['path'] == '/api/showcase/runs'
                    and path == '/showcase' and '展示服务未启用' in body]
                record['unexpected_api_errors'] = [row for row in responses
                    if row['status'] >= 400
                    and row not in record['expected_unavailable_responses']]
                record['passed'] = (not errors and bool(body.strip())
                    and not record['unexpected_api_errors']
                    and page.get_by_role('button', name='登录系统', exact=True).count() == 0
                    and page.get_by_text('页面未找到', exact=True).count() == 0)
            except Exception as error:
                navigation_error = str(error)
                record = {'requested_path': path, 'passed': False, 'error': navigation_error,
                          'responses': responses, 'page_errors': errors}
            finally:
                page.remove_listener('pageerror', on_error)
                page.remove_listener('response', on_response)
            screenshot = f'route-{index:02d}.png'
            try:
                page.screenshot(path=str(output / screenshot), full_page=True, timeout=10000)
                record['screenshot'] = screenshot
            except Exception as error:
                record['screenshot_error'] = str(error)
            records.append(record)
            # Retain partial evidence even when a later route fails.
            (output / 'route-audit.json').write_text(json.dumps({
                'api_mocking': False, 'role': 'admin', 'expected_routes': len(paths),
                'visited_routes': len(records), 'passed': all(row['passed'] for row in records),
                'routes': records,
            }, ensure_ascii=False, indent=2))
        failed = [row['requested_path'] for row in records if not row['passed']]
        assert not failed, f'route_audit_failed:{failed}'
        return {'completed': True, 'visited': len(records),
                'redirected': [row['requested_path'] for row in records if row.get('redirected')],
                'scope': 'admin route rendering and initial real API responses; not all interactions'}
    finally:
        page.close()
