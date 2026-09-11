"""Additional real-API browser journeys on the disposable synthetic stack."""
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit


def prepare_information_gap(client, area, output):
    original = '合成信息不足验收：未发现车辆，具体位置不明，油品种类待核。'
    response = client.post('/api/cases/', json={'case_number': 'SYNTHETIC-GAP-002',
        'occurred_time': (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        'location': '具体位置待核', 'case_type': '涉油盗窃', 'description': original, **area})
    assert response.status_code == 200, response.text
    identifier = response.json()['id']
    deadline = time.monotonic() + 75
    while True:
        reply = client.get(f'/api/cases/{identifier}/results/latest')
        if (reply.status_code == 200 and reply.json().get('freshness') == 'current'
                and reply.json()['content']['versions'].get('analysis_run_id')):
            break
        assert reply.status_code in (200, 404), reply.text
        assert time.monotonic() < deadline, 'information_gap_result_not_ready'
        time.sleep(1)
    result = reply.json()
    assert result['content']['candidates'] == []
    assert result['content']['analysis_status'] == 'degraded'
    assert '案件缺少经纬度，无法执行案件—地图空间融合' in result['content']['information_gaps']['analysis']
    source = client.get(f'/api/cases/{identifier}').json()
    assert source['latitude'] is None and source['longitude'] is None
    assert source['description'] == original
    (output / 'information-gap-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return {'case_id': identifier, 'result_id': result['id'], 'content_sha256': result['content_sha256']}


def information_gap_journey(page, base, output):
    page.goto(base + '/cases')
    page.wait_for_load_state('networkidle')
    page.get_by_text('SYNTHETIC-GAP-002', exact=True).click()
    result = page.locator('section[aria-label="统一研判成果"]')
    result.wait_for(timeout=30000)
    result.get_by_text('尚无可展示候选，不代表不存在相关线索。', exact=True).wait_for(timeout=30000)
    assert result.get_by_role('button', name='查看参考路径', exact=True).count() == 0
    result.screenshot(path=str(output / 'information-gap-browser.png'))
    return {'completed': True, 'invented_candidates': 0, 'exact_location_inferred': False}


def period_brief_journey(page, base, output):
    area = json.loads((output / 'coverage-baseline.json').read_text())['input_snapshot']['area_id']
    reply = page.request.post(base + f'/api/admin/situation/briefs/generate?operational_area_id={area}&period_type=daily',
                              headers={'Origin': base})
    assert reply.status == 200, reply.text()
    brief = reply.json()
    (output / 'period-brief.json').write_text(json.dumps(brief, ensure_ascii=False, indent=2))
    comparison = brief['comparison_snapshot']
    assert comparison['current']['case_count'] == 1
    assert comparison['previous']['case_count'] == 0
    assert comparison['current']['profile_versions_generated'] == 0
    assert brief['recommendations'] == [], 'small_fixture_change_must_not_force_advice'
    assert comparison['timezone'] == 'Asia/Shanghai'
    current, previous = comparison['current'], comparison['previous']
    interval = lambda value: datetime.fromisoformat(value['end']) - datetime.fromisoformat(value['start'])
    assert interval(current) == interval(previous) == timedelta(days=1)
    assert previous['end'] == current['start']
    page.goto(base + '/situation')
    page.wait_for_load_state('networkidle')
    section = page.get_by_role('region', name='完整周期比较')
    section.wait_for()
    assert '案发 1 起' in section.inner_text()
    assert '案发 0 起' in section.inner_text()
    assert '本期生成画像版本 0 份，仅代表处理进度。' in section.inner_text()
    assert page.get_by_role('region', name='自动部署建议').locator('article').count() == 0
    page.screenshot(path=str(output / 'period-brief-browser.png'), full_page=True)
    return {'completed': True, 'brief_id': brief['id'], 'case_time_not_processing_time': True,
            'trigger': 'authorized_admin_api', 'forced_recommendations': 0}


def coverage_journey(page, output):
    panel = page.get_by_role('region', name='空间覆盖方案比较')
    endpoint = '/api/deployment-sandbox/spatial-compare'
    with page.expect_response(lambda reply: urlsplit(reply.url).path == endpoint) as first:
        panel.get_by_role('button', name='计算当前覆盖', exact=True).click()
    assert first.value.status == 200, first.value.text()
    baseline = first.value.json()
    (output / 'coverage-baseline.json').write_text(json.dumps(baseline, ensure_ascii=False, indent=2))
    assert baseline['baseline']['target_count'] == 1
    assert baseline['baseline']['covered_count'] == 1
    assert baseline['baseline']['unknown_count'] == 0
    panel.get_by_role('table').first.wait_for()
    panel.get_by_text('调整假设方案', exact=True).click()
    resource = next(row['resource_id'] for row in baseline['baseline']['resources'] if row['state'] == 'usable')
    panel.get_by_role('combobox', name='假设移动一个设备').click()
    page.get_by_title(f'设备 {resource}', exact=True).click()
    assert panel.get_by_role('button', name='计算并保存方案').is_disabled()
    panel.get_by_role('spinbutton', name='假设纬度', exact=True).fill('46.55')
    panel.get_by_role('spinbutton', name='假设经度', exact=True).fill('125.20')
    with page.expect_response(lambda reply: urlsplit(reply.url).path == endpoint) as second:
        panel.get_by_role('button', name='计算并保存方案').click()
    assert second.value.status == 200, second.value.text()
    scenario = second.value.json()
    (output / 'coverage-scenario.json').write_text(json.dumps(scenario, ensure_ascii=False, indent=2))
    assert scenario['baseline']['covered_count'] == 1
    assert scenario['scenario']['covered_count'] == 0
    assert scenario['scenario']['unknown_count'] == 0
    panel.get_by_role('row', name='名义覆盖井点 1 0 -1').wait_for()
    panel.screenshot(path=str(output / 'coverage-moved.png'))
    with page.expect_response(lambda reply: urlsplit(reply.url).path == endpoint) as reread:
        panel.get_by_role('button', name='计算当前覆盖', exact=True).click()
    assert reread.value.status == 200
    current = reread.value.json()
    assert current['baseline']['covered_count'] == current['scenario']['covered_count'] == 1
    assert current['input_snapshot']['resources'] == baseline['input_snapshot']['resources']
    (output / 'coverage-browser.json').write_text(json.dumps({'baseline': baseline,
        'scenario': scenario, 'reread_current': current, 'api_mocking': False}, ensure_ascii=False, indent=2))
    return {'completed': True, 'baseline_covered': 1, 'moved_covered': 0,
            'comparison_id': scenario['id'], 'formal_resource_moved': False}


def query_degradation_journey(page, base, output):
    page.goto(base + '/assistant')
    page.wait_for_load_state('networkidle')
    page.get_by_label('查询问题', exact=True).fill('统计当前授权范围的案件数量')
    with page.expect_response(lambda reply: urlsplit(reply.url).path == '/api/intelligent-queries'
                             and reply.request.method == 'POST') as submitted:
        page.get_by_role('button', name='提交查询', exact=True).click()
    assert submitted.value.status == 201, submitted.value.text()
    created = submitted.value.json()
    page.get_by_text('内网模型不可用，请联系管理员检查配置；案件和地图功能仍可使用。', exact=True).wait_for(timeout=60000)
    assert page.get_by_role('button', name='继续追问', exact=True).count() == 0
    page.screenshot(path=str(output / 'assistant-model-unavailable.png'), full_page=True)
    return {'completed': True, 'run_id': created['id'], 'real_model_connected': False,
            'expected_model_unavailable': True}
