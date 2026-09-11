"""Browser component check with real public routing geometry and mocked HTTP.

Not a production login, database, map-data or end-to-end release acceptance.
Run against an isolated Vite development server. Never points at business APIs.
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

from app.services.road_access_policy import VehicleAssumption
from app.services.road_graph_artifact import graph_inventory_sha256
from app.services.vehicle_router import VehicleRouter, RoadLocation
from valhalla._valhalla import decode_polyline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:13049')
    parser.add_argument('--tiles', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--native-alternatives-report', help='Previously verified synthetic native graph report')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    # A failed rerun must not leave a previous successful report looking fresh.
    (output / 'report.json').write_text(json.dumps({'passed': False, 'status': 'started', 'apiMocking': True}))
    digest = graph_inventory_sha256(Path(args.tiles))
    engine = VehicleRouter(Path(args.tiles))
    native = engine.route(RoadLocation(longitude=125.1852727, latitude=46.54446175),
        RoadLocation(longitude=125.18509545, latitude=46.5444392),
        VehicleAssumption(kind='auto', source='explicit_reference_assumption'))
    if args.native_alternatives_report:
        evidence = json.loads(Path(args.native_alternatives_report).read_text())
        assert evidence['passed'] and evidence['synthetic_native_graph']
        native = evidence['car']
        assert len(native['alternatives']) == 1
    network = '11111111-1111-4111-8111-111111111111'
    stamp = '2026-09-11T00:00:00+00:00'
    comparison = {'schema_version': 'case-road-comparison-4.2.0-1', 'result_id': 'ui-fixture',
        'content_sha256': 'a' * 64, 'map_snapshot_id': 'frozen-public-fixture',
        'targets': [{'asset_id': 1, 'name': '合成目标甲', 'candidate_id': 'a', 'evidence_ref': 'synthetic:1'},
                    {'asset_id': 2, 'name': '合成目标乙', 'candidate_id': 'b', 'evidence_ref': 'synthetic:2'}],
        'information_gaps': [], 'boundary': '合成界面验证，不是案件判断',
        'matrix': {'network_id': network, 'graph_sha256': digest, 'policy_revision': 1, 'analysis_at': stamp,
                   'cells': [{'source_index': 0, 'target_index': i, 'status': 'calculated',
                              'distance_m': native['distance_m']} for i in range(2)]}}
    html = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1"></head><body>
      <main id="root" class="case-result" style="max-width:900px;margin:24px auto;padding:16px"></main>
      <script type="module">
      import RefreshRuntime from '/@react-refresh';
      RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => t => t;
      window.__vite_plugin_react_preamble_installed__ = true;
      const {default: React} = await import('/node_modules/.vite/deps/react.js');
      const {default: ReactDOM} = await import('/node_modules/.vite/deps/react-dom_client.js');
      await import('/src/styles/design-system.css');
      await import('/src/components/CaseResult/CaseResultPanel.css');
      const {default: Panel} = await import('/src/components/CaseResult/CaseRoadComparison.tsx');
      ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(Panel, {resultId:'ui-fixture',hash:'a'.repeat(64)}));
      </script></body></html>'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={'width': 1200, 'height': 1000})
            errors, external, route_calls, posts = [], [], [], []
            mode = {'fail': False, 'history_fail': False, 'automatic': 'completed'}
            saved_route = {'schema_version': 'case-road-route-4.2.0-1',
                'result_id': comparison['result_id'], 'content_sha256': comparison['content_sha256'],
                'map_snapshot_id': comparison['map_snapshot_id'], 'target': comparison['targets'][0],
                'boundary': comparison['boundary'], 'route': {**native, 'network_id': network,
                    'graph_sha256': digest, 'analysis_at': stamp}}
            def intercept(route):
                url = route.request.url
                if not url.startswith(args.base + '/'):
                    external.append(url); route.abort(); return
                if url.endswith('/road-ui-check'):
                    route.fulfill(content_type='text/html', body=html); return
                if '/api/road-analysis/' in url:
                    if route.request.method == 'POST':
                        posts.append(url)
                    if '/artifacts?' in url:
                        assert route.request.method == 'GET'
                        older = 'before_id=' in url
                        route.fulfill(json={'items': [{'id': 'older' if older else 'saved',
                            'availability': 'available', 'operation': 'comparison' if older else 'route',
                            'created_at': stamp, 'content_sha256': 'b' * 64}],
                            'next_before_id': None if older else 'saved'}); return
                    if '/artifacts/' in url:
                        assert route.request.method == 'GET'
                        if mode['history_fail']:
                            route.fulfill(status=404, json={'detail': 'synthetic permission revoked'}); return
                        artifact_id = url.rsplit('/', 1)[1]
                        route.fulfill(json={'id': artifact_id, 'created_at': stamp, 'content_sha256': 'b' * 64,
                            'content': comparison if artifact_id == 'older' else saved_route}); return
                    if url.endswith('/comparison'):
                        route.fulfill(json=comparison); return
                    if url.endswith('/reachable-roads'):
                        body = route.request.post_data_json
                        assert 'origin' not in body and 'vehicle' not in body
                        assert body['graph_sha256'] == digest and body['network_id'] == network
                        # Synthetic display fixture, NOT a native reachability acceptance.
                        points = decode_polyline(native['shape_polyline6'], 6, 'latlng')
                        route.fulfill(json={'schema_version': 'case-reachable-roads-4.2.0-1',
                            'result_id': comparison['result_id'], 'content_sha256': comparison['content_sha256'],
                            'map_snapshot_id': comparison['map_snapshot_id'], 'metric': body['metric'],
                            'budget': body.get('distance_m', body.get('seconds')), 'boundary': '合成预算道路显示验证',
                            'information_gaps': [], 'reachability': {'native_completion_contract': 'completed-v1',
                                'network_id': network, 'graph_sha256': digest, 'analysis_at': stamp,
                                'vehicle': {'kind': 'auto', 'source': 'explicit_reference_assumption'},
                                'roads': {'type': 'FeatureCollection', 'features': [{'type': 'Feature',
                                    'geometry': {'type': 'LineString', 'coordinates': [[lng, lat] for lat, lng in points]}}]}}}); return
                    if url.endswith('/automatic-comparison'):
                        assert route.request.method == 'GET'
                        route.fulfill(json={'result_id': comparison['result_id'],
                            'content_sha256': comparison['content_sha256'], 'status': mode['automatic'],
                            'artifact': ({'id': 'automatic', 'created_at': stamp, 'content_sha256': 'b' * 64,
                                         'content': comparison} if mode['automatic'] == 'completed' else None)}); return
                    asset = int(url.rsplit('/', 1)[1])
                    body = route.request.post_data_json
                    assert body['graph_sha256'] == digest and body['network_id'] == network
                    route_calls.append(asset)
                    if mode['fail']:
                        route.fulfill(status=403, json={'detail': 'synthetic permission revoked'}); return
                    route.fulfill(json={'schema_version': 'case-road-route-4.2.0-1',
                        'result_id': comparison['result_id'], 'content_sha256': comparison['content_sha256'],
                        'map_snapshot_id': comparison['map_snapshot_id'], 'target': comparison['targets'][asset - 1],
                        'boundary': comparison['boundary'], 'route': {**native, 'network_id': network,
                            'graph_sha256': digest, 'analysis_at': stamp}}); return
                if '/api/case-results/ui-fixture/document.pdf?' in url:
                    assert route.request.method == 'GET' and 'road_artifact_id=saved' in url
                    route.fulfill(content_type='application/pdf', body=b'%PDF-synthetic-browser-download', headers={
                        'X-Result-Content-SHA256': 'a' * 64, 'X-Road-Artifact-ID': 'saved',
                        'X-Road-Artifact-SHA256': 'b' * 64}); return
                if '/api/' in url:
                    # Deliberately missing basemap: route geometry and failure
                    # notice must coexist without calling public tile services.
                    route.fulfill(status=503, json={'detail': 'synthetic basemap unavailable'}); return
                route.continue_()
            context.route('**/*', intercept)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(args.base + '/road-ui-check')
            page.wait_for_load_state('networkidle')
            page.screenshot(path=str(output / 'initial.png'), full_page=True)
            print('rendered_buttons:', page.get_by_role('button').all_text_contents())
            print('initial_page_errors:', errors)
            assert len(posts) == 1 and posts[0].endswith('/reachable-roads')
            budget_panel = page.get_by_role('region', name='案件预算道路参考')
            expect(budget_panel.locator('.leaflet-overlay-pane canvas')).to_have_count(1)
            budget_panel.get_by_role('button', name='参考 10 分钟', exact=True).click()
            expect(budget_panel.get_by_text('时间按已知道路速度及转向条件估算，不是实时交通或准确到达时间。')).to_be_visible()
            expect(budget_panel.locator('.leaflet-overlay-pane canvas')).to_have_count(1)
            assert len(posts) == 2
            page.get_by_role('button', name='查看参考路径', exact=True).first.click()
            expect(page.locator('.leaflet-overlay-pane path')).to_have_count(1)
            decoded = page.evaluate("async encoded => (await import('/src/components/Map/roadPolyline.ts')).roadPolyline(encoded)", native['shape_polyline6'])
            native_points = decode_polyline(native['shape_polyline6'], 6, 'latlng')
            assert len(decoded) == len(native_points)
            assert all(abs(a - b) < 1e-9 for point, expected in zip(decoded, native_points) for a, b in zip(point, expected))
            expect(page.get_by_text('合成目标甲附近道路参考路径，不是实际行驶轨迹。', exact=True)).to_be_visible()
            if args.native_alternatives_report:
                choices = page.get_by_role('group', name='主路径与备选路径')
                primary = choices.get_by_role('button', name='主路径：')
                alternate = choices.get_by_role('button', name='备选路径：')
                before_switch = len(posts)
                primary_shape = page.locator('.leaflet-overlay-pane path').get_attribute('d')
                alternate.click()
                expect(alternate).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('.leaflet-overlay-pane path')).not_to_have_attribute('d', primary_shape)
                expect(page.get_by_text('绕行基准采用路径实际道路端点', exact=False)).to_be_visible()
                primary.click()
                expect(primary).to_have_attribute('aria-pressed', 'true')
                assert len(posts) == before_switch
            page.get_by_role('button', name='查看参考路径', exact=True).nth(1).click()
            expect(page.get_by_text('合成目标乙附近道路参考路径，不是实际行驶轨迹。', exact=True)).to_be_visible()
            expect(page.locator('.leaflet-overlay-pane path')).to_have_count(1)
            for width in (1200, 420):
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.locator('#root').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                page.screenshot(path=str(output / f'route-{width}.png'), full_page=True)
            mode['fail'] = True
            page.get_by_role('button', name='查看参考路径', exact=True).first.click()
            expect(page.get_by_role('button', name='刷新结果', exact=True)).to_be_visible()
            expect(page.locator('.leaflet-overlay-pane path')).to_have_count(0)
            before_history_posts = len(posts)
            page.get_by_text('历史道路成果', exact=True).click()
            page.get_by_role('button', name='查看留存路径').click()
            history = page.get_by_role('region', name='已保存道路成果')
            expect(history.get_by_text('历史留存，不重新计算；不代表当前道路仍可通行。')).to_be_visible()
            expect(history.locator('.leaflet-overlay-pane path')).to_have_count(1)
            with page.expect_download() as downloaded:
                history.get_by_role('button', name='下载 PDF', exact=True).click()
            assert '-road-' in downloaded.value.suggested_filename
            assert page.locator('#root').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
            page.screenshot(path=str(output / 'history-420.png'), full_page=True)
            page.get_by_role('button', name='更早记录', exact=True).click()
            expect(page.locator('.leaflet-overlay-pane path')).to_have_count(0)
            page.get_by_role('button', name='查看留存距离比较').click()
            expect(history.get_by_text('合成目标乙', exact=True)).to_be_visible()
            page.get_by_role('button', name='刷新历史列表', exact=True).click()
            mode['history_fail'] = True
            page.get_by_role('button', name='查看留存路径').click()
            expect(page.get_by_text('历史成果暂不可用，权限或来源版本可能已变化。未重新计算，请刷新历史列表后重试。')).to_be_visible()
            expect(history).to_have_count(0)
            expect(page.locator('.leaflet-overlay-pane path')).to_have_count(0)
            assert len(posts) == before_history_posts
            page.get_by_text('历史道路成果', exact=True).click()
            expect(page.get_by_role('button', name='刷新历史列表', exact=True)).to_have_count(0)
            before_refresh_posts = len(posts)
            mode['automatic'] = 'processing'
            page.reload()
            expect(page.get_by_text('后台正在处理，完成后自动显示；可以继续查看案件。')).to_be_visible()
            page.get_by_role('button', name='暂停刷新', exact=True).click()
            expect(page.get_by_text('已暂停页面刷新，后台任务仍会继续。')).to_be_visible()
            mode['automatic'] = 'completed'
            page.get_by_role('button', name='刷新结果', exact=True).click()
            expect(page.get_by_role('button', name='查看参考路径', exact=True)).to_have_count(2)
            expect(page.locator('.leaflet-overlay-pane path')).to_have_count(0)
            expect(page.get_by_role('region', name='案件预算道路参考').locator('.leaflet-overlay-pane canvas')).to_have_count(1)
            assert len(posts) == before_refresh_posts + 1
            before_refresh_posts = len(posts)
            mode['automatic'] = 'waiting_network'
            page.reload()
            expect(page.get_by_text('路网或通行授权尚未就绪，系统会在可用后继续。案件录入和原研判内容不受影响。')).to_be_visible()
            page.get_by_role('button', name='暂停刷新', exact=True).click()
            expect(page.get_by_text('已暂停页面刷新，后台任务仍会继续。')).to_be_visible()
            assert len(posts) == before_refresh_posts
            assert not errors and not external
            (output / 'report.json').write_text(json.dumps({'passed': True, 'apiMocking': True,
                'productionLoginTested': False, 'basemapFailureInjected': True,
                'realPublicGraphSha256': digest, 'nativeDistanceM': native['distance_m'],
                'displayRouteSource': 'synthetic_native_graph' if args.native_alternatives_report else 'public_native_graph',
                'alternativeSwitchWithoutRequest': bool(args.native_alternatives_report),
                'nativeDecoderParity': True, 'decodedPointCount': len(decoded),
                'historyGetOnly': True, 'historyPagination': True, 'historyFailureClearsView': True,
                'historyDownloadWiring': True,
                'initialComparisonGetOnly': True,
                'automaticBudgetRoadQuery': True, 'budgetGeometryMocked': True,
                'budgetCanvasRendering': True, 'budgetSwitch': True,
                'pauseAndRefreshNoBusinessWrites': True,
                'waitingNetworkState': True,
                'nativeShape': native['shape_polyline6'], 'routeCalls': route_calls,
                'pageErrors': errors, 'externalRequests': external}, ensure_ascii=False, indent=2))
            print('road_comparison_browser_component_passed')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
