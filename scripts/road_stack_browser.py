"""Real browser observations for the owned stack; never substitutes API replies."""
from pathlib import Path
import json
import time
import os
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def observe_stack(base, cookie, output, credentials=None):
    """Cookie stays in memory. The caller owns and removes the synthetic stack."""
    target = urlsplit(base)
    if target.hostname != '127.0.0.1' or target.scheme not in ('http', 'https'):
        raise ValueError('browser_probe_requires_loopback_stack')
    output = Path(output)
    observations, errors, external = [], [], []
    case_journey = {'requested': os.environ.get('AIC_STACK_CASE_JOURNEY') == '1',
                    'completed': False, 'downloads': []}
    extended = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel='chrome',
            args=['--enable-unsafe-swiftshader'])
        try:
            context = browser.new_context(viewport={'width': 1920, 'height': 1080},
                ignore_https_errors=target.scheme == 'https')
            # Browser-managed cookies survive the API's same-origin trailing-
            # slash redirect. This HTTP-loopback fixture does not certify TLS
            # or the server's Secure-cookie delivery; server flags stay intact.
            if target.scheme == 'https':
                assert credentials, 'https_fixture_requires_real_login'
                login = context.request.post(base + '/api/auth/login', data=credentials)
                assert login.status == 200, 'https_fixture_login_failed'
                assert any(item['secure'] and item['httpOnly'] for item in context.cookies(base))
            else:
                context.add_cookies([{'name': part.partition('=')[0].strip(),
                    'value': part.partition('=')[2], 'url': base, 'httpOnly': True,
                    'sameSite': 'Strict'} for part in cookie.split('; ')])
            def restrict(route):
                url = urlsplit(route.request.url)
                if (url.scheme, url.netloc) != (target.scheme, target.netloc):
                    external.append(url.netloc)
                    route.abort()
                else:
                    route.continue_()
            context.route('**/*', restrict)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(error.stack or str(error)))
            for name, path in [('cases-map', '/cases/map'), ('dashboard', '/dashboard'),
                               ('situation', '/situation'), ('cases', '/cases')]:
                responses = []
                listener = lambda response: responses.append({
                    'path': urlsplit(response.url).path, 'status': response.status,
                    'elapsed_ms': round((time.perf_counter() - started) * 1000, 2)})
                page.on('response', listener)
                started = time.perf_counter()
                page.goto(base + path)
                page.wait_for_load_state('networkidle')
                page.screenshot(path=str(output / f'{name}-initial.png'), full_page=True)
                (output / f'{name}-initial.json').write_text(json.dumps({
                    'url': page.url, 'text': page.locator('body').inner_text(),
                    'responses': responses, 'errors': errors}, ensure_ascii=False, indent=2))
                assert page.get_by_role('button', name='登录系统', exact=True).count() == 0, 'browser_authentication_failed'
                if name == 'cases-map':
                    page.locator('.maplibregl-canvas').first.wait_for(timeout=30000)
                    page.wait_for_load_state('networkidle')
                    assert any('/tiles/' in row['path'] and row['status'] == 200
                               for row in responses), 'real_map_tiles_not_loaded'
                page.screenshot(path=str(output / f'{name}.png'), full_page=True)
                if name == 'situation':
                    assert page.get_by_text('尚无简报', exact=True).is_visible()
                    assert not any(row['path'] == '/api/situation/overview' for row in responses)
                    legacy = page.locator('details.sw-history-controls')
                    assert legacy.get_attribute('open') is None
                    with page.expect_response(lambda response: urlsplit(response.url).path == '/api/situation/overview') as fetched:
                        legacy.locator('summary').click()
                    assert fetched.value.status == 200
                    legacy.get_by_text('优先核查事项', exact=True).wait_for()
                    page.screenshot(path=str(output / 'situation-legacy-expanded.png'), full_page=True)
                    legacy.locator('summary').click()
                    assert not legacy.get_by_text('优先核查事项', exact=True).is_visible()
                    # Regression: close while cached charts are still mounting.
                    for _ in range(3):
                        legacy.locator('summary').click()
                        legacy.locator('summary').click()
                    assert legacy.get_attribute('open') is None
                    page.get_by_role('heading', name='自动态势与部署参谋', exact=True).wait_for()
                    if os.environ.get('AIC_STACK_EXTENDED_SHOWCASE') == '1':
                        from road_stack_showcase import coverage_journey
                        extended['coverage'] = coverage_journey(page, output)
                if name == 'cases' and os.environ.get('AIC_STACK_CASE_JOURNEY') == '1':
                    page.get_by_text('SYNTHETIC-STACK-001', exact=True).click()
                    page.wait_for_load_state('networkidle')
                    (output / 'case-detail.json').write_text(json.dumps({
                        'text': page.locator('body').inner_text(),
                        'buttons': page.get_by_role('button').all_text_contents(),
                    }, ensure_ascii=False, indent=2))
                    page.screenshot(path=str(output / 'case-detail.png'), full_page=True)
                    result = page.locator('section[aria-label="统一研判成果"]')
                    result.wait_for(timeout=30000)
                    roads = result.locator('section[aria-label="道路参考比较"]')
                    roads.get_by_role('button', name='查看参考路径', exact=True).first.wait_for(timeout=60000)
                    with page.expect_response(lambda response: '/routes/' in urlsplit(response.url).path,
                                              timeout=30000) as route_response:
                        roads.get_by_role('button', name='查看参考路径', exact=True).first.click()
                    route_reply = route_response.value
                    (output / 'case-route-response.json').write_text(json.dumps({
                        'status': route_reply.status, 'body': route_reply.json(),
                    }, ensure_ascii=False, indent=2))
                    assert route_reply.status == 200, f'route_http_{route_reply.status}'
                    path_view = roads.locator('[aria-label="已知道路参考路径"]')
                    try:
                        path_view.get_by_text('附近道路参考路径，不是实际行驶轨迹。', exact=False).wait_for(timeout=60000)
                    finally:
                        (output / 'case-road-state.json').write_text(json.dumps({
                            'text': page.locator('body').inner_text(),
                            'responses': responses, 'errors': errors,
                        }, ensure_ascii=False, indent=2))
                        page.screenshot(path=str(output / 'case-road-state.png'), full_page=True)
                    page.screenshot(path=str(output / 'case-road-path.png'), full_page=True)
                    downloads = roads.locator('[aria-label="下载含道路附件的成果"]')
                    for label, extension in [('下载 Word', 'docx'), ('下载 PDF', 'pdf')]:
                        with page.expect_download(timeout=120000) as pending:
                            downloads.get_by_role('button', name=label, exact=True).click()
                        download = pending.value
                        assert download.failure() is None
                        destination = output / f'case-ui-road-report.{extension}'
                        download.save_as(destination)
                        signature = destination.read_bytes()[:4]
                        assert signature.startswith(b'PK' if extension == 'docx' else b'%PDF')
                        case_journey['downloads'].append({'format': extension,
                            'bytes': destination.stat().st_size, 'file': destination.name})
                    case_journey['completed'] = True
                observations.append({'page': path, 'elapsed_ms': round((time.perf_counter() - started) * 1000, 2),
                    'headings': page.get_by_role('heading').all_text_contents(),
                    'buttons': page.get_by_role('button').all_text_contents(),
                    'responses': responses,
                    'horizontal_overflow': page.evaluate('document.documentElement.scrollWidth > window.innerWidth')})
                page.remove_listener('response', listener)
            if os.environ.get('AIC_STACK_EXTENDED_SHOWCASE') == '1':
                from road_stack_showcase import query_degradation_journey
                extended['query'] = query_degradation_journey(page, base, output)
            if os.environ.get('AIC_STACK_INFORMATION_GAP') == '1':
                from road_stack_showcase import information_gap_journey
                extended['information_gap'] = information_gap_journey(page, base, output)
            if os.environ.get('AIC_STACK_PERIOD_BRIEF') == '1':
                from road_stack_showcase import period_brief_journey
                extended['period_brief'] = period_brief_journey(page, base, output)
            if os.environ.get('AIC_STACK_ALL_ROUTES') == '1':
                from road_stack_route_audit import audit_routes
                extended['route_audit'] = audit_routes(context, base, output)
            (output / 'browser-errors.json').write_text(json.dumps(errors, ensure_ascii=False, indent=2))
            assert not errors, errors
            assert not external, external
            return {'observed': True, 'api_mocking': False, 'fresh_browser_context': True,
                    'cookie_injected_for_loopback_http': target.scheme == 'http',
                    'real_https_login_secure_cookie': target.scheme == 'https',
                    'self_signed_fixture_certificate': target.scheme == 'https',
                    'origin_header_overridden': False,
                    'public_requests': 0, 'page_errors': errors, 'pages': observations,
                    'case_journey': case_journey,
                    'extended_journeys': extended,
                    'complete_showcase_round': False, 'production_tls_verified': False}
        except Exception:
            if 'page' in locals() and not page.is_closed():
                (output / 'browser-failure.json').write_text(json.dumps({
                    'url': page.url, 'text': page.locator('body').inner_text(),
                    'errors': errors, 'responses': responses if 'responses' in locals() else [],
                }, ensure_ascii=False, indent=2))
                page.screenshot(path=str(output / 'browser-failure.png'), full_page=True)
            raise
        finally:
            browser.close()
