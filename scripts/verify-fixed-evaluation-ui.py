"""Synthetic API browser check; separate from real worker integration evidence."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:13045'


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel='chrome')
        page = browser.new_page(viewport={'width': 1366, 'height': 900})
        errors, external = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        overview = {'business_agents': [], 'versions': {'algorithms': [], 'scope_policy': {'version': 'test', 'checksum': 'a' * 64}},
                    'formal_case_mutations_allowed': False, 'execution_task_creation_allowed': False, 'external_model_required': False}
        dataset = {'id': 1, 'name': '合成固定集', 'version': '1', 'kind': 'case', 'sample_count': 3, 'checksum': 'a' * 64}
        records = [{'id': str(i), 'dataset_id': 1, 'status': 'completed', 'started_at': f'2026-09-11T0{i}:00:00Z',
                    'algorithm_manifest': {'evaluation_schema': 'fixed-evaluation-4.5-1', 'scorer_policy': 'captured'},
                    'metrics': {'case_count': 3, 'failed_case_count': 0, 'unlabeled_case_count': 3, 'positive_top3_hit_rate': None}}
                   for i in (1, 2)]
        road_status, road_submissions = 'pending', []
        def route(request):
            nonlocal road_status
            path = request.request.url.removeprefix(BASE)
            if not request.request.url.startswith(BASE):
                external.append(request.request.url)
                request.abort()
            elif not path.startswith('/api/'):
                request.continue_()
            elif path == '/api/auth/me':
                request.fulfill(json={'id': 1, 'username': 'synthetic', 'display_name': '合成管理员', 'role': 'admin', 'is_active': True})
            elif path == '/api/auth/me/area-scopes':
                request.fulfill(json=[])
            elif path.startswith('/api/admin/intelligence-runtime/overview'):
                request.fulfill(json=overview)
            elif path.split('?')[0] == '/api/admin/evaluations/fixed-datasets':
                request.fulfill(json={'items': [dataset], 'next_before_id': None})
            elif path == '/api/admin/evaluations/fixed-datasets/1/labels':
                request.fulfill(json={'dataset_id': 1, 'name': dataset['name'], 'version': '1', 'case_ids': [1, 2, 3],
                    'cases': [{'id': i, 'case_number': f'合成案件{i}'} for i in (1, 2, 3)],
                    'label_assets': [], 'ground_truth': {}, 'negative_case_ids': [], 'checksum': 'a' * 64})
            elif path.startswith('/api/admin/evaluations/fixed-datasets/1/label-assets?'):
                request.fulfill(json={'items': [{'id': 123, 'name': '合成核验设施', 'asset_type': 'well'}], 'has_more': False})
            elif path == '/api/admin/evaluations/fixed-datasets/1/label-versions':
                submitted = request.request.post_data_json
                assert submitted['ground_truth'] == {'1': [{'hypothesis_type': 'possible_source', 'expected_asset_ids': [123]}]}
                assert submitted['negative_case_ids'] == [] and submitted['version'] == '2'
                request.fulfill(status=201, json={'id': 2})
            elif path.startswith('/api/admin/evaluations/runs'):
                request.fulfill(json=records)
            elif path.startswith('/api/admin/evaluations/road-jobs?'):
                request.fulfill(json={'total': 1, 'items': [{'event_id': 'saved-road-task',
                    'status': road_status, 'created_at': '2026-09-11T00:00:00Z',
                    'dataset_id': 2, 'source_available': True}]})
            elif path == '/api/admin/evaluations/road-jobs/saved-road-task/cancel':
                road_status = 'cancelled'
                request.fulfill(json={'event_id': 'saved-road-task', 'status': road_status})
            elif path == '/api/admin/evaluations/road-jobs/saved-road-task':
                request.fulfill(json={'event_id': 'saved-road-task', 'status': road_status,
                    'result_status': None, 'metrics': None})
            elif path == '/api/admin/evaluations/road-jobs':
                road_submissions.append(request.request.post_data_json)
                request.fulfill(status=500, json={'detail': 'must not resubmit existing task'})
            elif path == '/api/admin/evaluations/fixed-run':
                assert request.request.post_data_json == {'dataset_id': 1, 'scorer_policy': 'captured'}
                request.fulfill(json=records[0])
            else:
                request.fulfill(status=404, json={'detail': 'synthetic_unavailable'})
        page.route('**/*', route)
        try:
            page.goto(BASE + '/agents', wait_until='networkidle')
            page.get_by_role('heading', name='固定输入评测', exact=True).wait_for()
            page.get_by_role('combobox', name='已冻结的数据集', exact=True).click()
            page.locator('.ant-select-item-option-content').filter(has_text='合成固定集').click()
            page.get_by_text('未标注或不可计算', exact=True).first.wait_for()
            page.get_by_role('button', name='运行评测', exact=True).click()
            page.wait_for_load_state('networkidle')
            page.reload(wait_until='networkidle')
            page.get_by_role('button', name='打开任务', exact=True).click()
            page.get_by_role('button', name='取消此任务', exact=True).click()
            page.get_by_text('道路评测：已取消', exact=True).wait_for()
            assert road_submissions == []
            page.get_by_role('combobox', name='已冻结的数据集', exact=True).click()
            page.locator('.ant-select-item-option-content').filter(has_text='合成固定集').click()
            page.get_by_text('人工标签与版本修订', exact=True).click()
            page.get_by_text('尚未标注，不计正确率', exact=True).click()
            page.locator('.ant-select-item-option-content').filter(has_text='有人工确认目标').click()
            page.get_by_role('combobox', name='核验设施1', exact=True).click()
            page.locator('.ant-select-item-option-content').filter(has_text='合成核验设施').click()
            page.get_by_label('新标签版本', exact=True).fill('2')
            page.get_by_label('修订原因与核验依据', exact=True).fill('合成样本界面检查，不是真实核验')
            page.get_by_role('button', name='另存标签版本', exact=True).click()
            page.get_by_text('新标签版本已保存，请在数据集列表选择新版本后运行评测。', exact=True).wait_for()
            output = Path('output/fixed-evaluation-ui')
            output.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output / 'desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.wait_for_function('document.documentElement.scrollWidth <= window.innerWidth + 2')
            page.screenshot(path=str(output / 'mobile.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 2')
            assert not errors, errors
            assert not external, external
            print(json.dumps({'passed': True, 'synthetic_api': True, 'widths': [1366, 390],
                              'existing_task_reopened_and_cancelled': True, 'road_resubmissions': len(road_submissions)}))
        finally:
            browser.close()


if __name__ == '__main__':
    main()
