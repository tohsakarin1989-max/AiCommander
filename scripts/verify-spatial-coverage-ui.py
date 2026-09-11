"""Browser interaction with synthetic API responses, not backend integration."""
import json
import base64
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:13044'


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel='chrome')
        context = browser.new_context(viewport={'width': 1366, 'height': 900})
        page = context.new_page()
        submissions, errors, map_requests, external_requests, road_submissions = [], [], [], [], []
        denied = False
        road_status = 'pending'
        page.on('pageerror', lambda error: errors.append(str(error)))
        baseline = {'target_count': 3, 'covered_count': 1, 'overlap_count': 1,
                    'unknown_count': 1, 'outside_known_count': 1,
                    'resources': [{'resource_id': 1, 'state': 'usable'},
                                  {'resource_id': 2, 'state': 'unknown_coverage_radius'}], 'targets': []}
        geometry = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'properties': {'kind': kind}, 'geometry': {'type': 'Polygon',
             'coordinates': [[[125, 47], [125 + size, 47], [125 + size, 47 + size], [125, 47]]]}}
            for kind, size in [('registered_boundary', .02), ('known_coverage', .01), ('unique_overlap', .005)]]}
        baseline['area_coverage'] = {'state': 'partial', 'map_geometry': geometry,
            'boundary_area_m2': 200, 'known_covered_area_m2': 100, 'unique_overlap_area_m2': 20,
            'outside_known_coverage_area_m2': 100, 'uncovered_area_m2': None}
        result = {'id': 'synthetic-comparison', 'baseline': baseline, 'scenario': baseline,
                  'boundary': '仅计算名义覆盖，不证明实际防控效果。', 'algorithm_version': 'fixture',
                  'input_digest': 'a' * 64, 'persisted': True,
                  'input_snapshot': {'area_id': 1, 'as_of': '2026-09-11T00:00:00Z', 'resources': [],
                                     'map_snapshot_id': 'synthetic-map'}}

        def intercept(route):
            nonlocal road_status
            path = route.request.url.removeprefix(BASE)
            if not route.request.url.startswith(BASE):
                external_requests.append(route.request.url)
                route.abort()
            elif not path.startswith('/api/'):
                route.continue_()
            elif path == '/api/auth/me':
                route.fulfill(json={'id': 1, 'username': 'synthetic', 'display_name': '隔离测试',
                                    'role': 'analyst', 'is_active': True, 'created_at': '2026-09-11'})
            elif path == '/api/auth/me/area-scopes':
                route.fulfill(json=[])
            elif path.startswith('/api/maps/'):
                map_requests.append(path)
                if path.startswith('/api/maps/synthetic-map/manifest'):
                    route.fulfill(json={'snapshot_id': 'synthetic-map', 'min_zoom': 6, 'max_zoom': 16,
                        'tile_url': '/api/maps/tiles/synthetic-map/{z}/{x}/{y}', 'attribution': '合成测试底图'})
                elif path.startswith('/api/maps/tiles/synthetic-map/'):
                    route.fulfill(content_type='image/png', body=base64.b64decode(
                        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg=='))
                else:
                    route.fulfill(status=404, json={'detail': 'unavailable'})
            elif path == '/api/deployment-sandbox/spatial-compare':
                submissions.append(route.request.post_data_json)
                route.fulfill(json=result)
            elif path.startswith('/api/deployment-sandbox/spatial-comparisons?'):
                route.fulfill(json={'total': 1, 'items': [{'id': result['id'], 'operational_area_id': 1,
                    'created_at': '2026-09-11T00:00:00Z'}]})
            elif path.endswith('/road-jobs') and route.request.method == 'POST':
                body = route.request.post_data_json
                road_submissions.append(body)
                assert body['vehicle']['source'] == 'explicit_reference_assumption'
                assert body['distance_budget_m'] == 3000
                route.fulfill(status=202, json={'event_id': 'synthetic-road-job'})
            elif '/road-jobs?' in path and route.request.method == 'GET':
                route.fulfill(json={'total': 1, 'items': [{'event_id': 'synthetic-road-job',
                    'status': road_status, 'created_at': '2026-09-11T00:00:00Z'}]})
            elif path == '/api/deployment-sandbox/road-jobs/synthetic-road-job/cancel':
                road_status = 'cancelled'
                route.fulfill(json={'status': road_status})
            elif path == '/api/deployment-sandbox/road-jobs/synthetic-road-job':
                route.fulfill(json={'event_id': 'synthetic-road-job', 'status': road_status, 'artifact': None})
            elif path.startswith('/api/deployment-sandbox/spatial-comparisons/'):
                route.fulfill(status=404 if denied else 200,
                              json={'detail': 'unavailable'} if denied else {
                                  **result, 'historical': True, 'freshness': 'conditions_expired'})
            else:
                route.fulfill(status=404, json={'detail': 'synthetic_missing'})

        context.route('**/*', intercept)
        try:
            page.goto(BASE + '/situation')
            page.wait_for_load_state('networkidle')
            panel = page.get_by_role('region', name='空间覆盖方案比较')
            panel.get_by_text('历史方案目录', exact=True).click()
            panel.get_by_role('button').filter(has_text='辖区 1 · syntheti').wait_for()
            panel.get_by_role('button', name='计算当前覆盖').click()
            panel.get_by_role('table').wait_for()
            assert submissions == [{'disabled_resource_ids': [], 'movements': []}]
            assert panel.get_by_role('row', name='覆盖未知 1 1 0').count() == 1
            panel.get_by_text('在离线底图上比较覆盖范围', exact=True).click()
            panel.locator('.leaflet-overlay-pane path').first.wait_for()
            assert panel.locator('.leaflet-overlay-pane path').count() == 3
            panel.get_by_text('方案覆盖', exact=True).click()
            panel.get_by_role('button', name='复位地图').click()
            assert all('synthetic-map' in path for path in map_requests)
            assert map_requests and not external_requests
            panel.get_by_text('在离线底图上比较覆盖范围', exact=True).click()
            panel.get_by_text('机动车道路关联', exact=True).click()
            panel.get_by_role('button', name='提交道路计算').click()
            panel.get_by_text('排队中', exact=True).wait_for()
            panel.get_by_role('button', name='取消道路计算').click()
            panel.get_by_text('已取消', exact=True).wait_for()
            panel.get_by_text('找回已提交的道路任务', exact=True).click()
            panel.get_by_role('button').filter(has_text='2026-09-11T00:00:00Z · 已取消').click()
            assert len(road_submissions) == 1
            panel.get_by_text('找回已提交的道路任务', exact=True).click()
            panel.get_by_text('调整假设方案', exact=True).click()
            panel.get_by_role('combobox', name='假设移动一个设备').click()
            page.get_by_title('设备 1', exact=True).click()
            assert panel.get_by_role('button', name='计算并保存方案').is_disabled()
            panel.get_by_role('spinbutton', name='假设纬度', exact=True).fill('47')
            panel.get_by_role('spinbutton', name='假设经度', exact=True).fill('124')
            panel.get_by_role('button', name='计算并保存方案').click()
            panel.get_by_role('table').wait_for()
            assert submissions[-1]['movements'] == [{'resource_id': 1, 'latitude': 47, 'longitude': 124}]
            output = Path('output/playwright/spatial-coverage')
            output.mkdir(parents=True, exist_ok=True)
            panel.screenshot(path=str(output / 'desktop.png'))
            page.set_viewport_size({'width': 390, 'height': 844})
            panel.screenshot(path=str(output / 'mobile.png'))
            assert panel.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
            denied = True
            panel.get_by_role('combobox', name='查看已保存方案').click()
            page.get_by_title('方案 1 · syntheti', exact=True).click()
            panel.get_by_role('alert').wait_for()
            assert panel.get_by_role('table').count() == 0
            assert errors == [], errors
            print(json.dumps({'passed': True, 'synthetic_api_only': True, 'submissions': len(submissions),
                'coverage_geometry_rendered': True, 'pinned_offline_requests_only': True}))
        finally:
            browser.close()


if __name__ == '__main__':
    main()
