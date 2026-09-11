"""Synthetic browser check of the real review form; no business API writes."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:13052'
OUTPUT = Path('output/playwright/new-road-entry-v42')
HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div>
<script type="module">
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>t=>t;
window.__vite_plugin_react_preamble_installed__=true;
const {default:React}=await import('/node_modules/.vite/deps/react.js');
const {default:ReactDOM}=await import('/node_modules/.vite/deps/react-dom_client.js');
const source=await (await fetch('/src/pages/Jurisdiction/InternalRoadManager.tsx')).text();
const url=source.match(/from\\s*["']([^"']*\\/antd\\.js[^"']*)["']/)[1];
const {ConfigProvider,theme}=await import(url);
const {RoadReviewForm}=await import('/src/pages/Jurisdiction/InternalRoadManager.tsx');
const {getThemeTokens}=await import('/src/theme/themeMode.ts');
await import('/src/styles/design-system.css');
const feature={type:'Feature',id:'test-road',properties:{kind:'road',name:'合成内部道路'},
geometry:{type:'LineString',coordinates:[[125,46],[125,46.001]]}};
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(ConfigProvider,
{theme:{algorithm:theme.darkAlgorithm,token:getThemeTokens('dark').tokens}},React.createElement(RoadReviewForm,
{source:1,record:{id:2,input_sha256:'a'.repeat(64),features:[feature],warnings:[]},feature,refresh:()=>{window.saved=true;}})));
</script></html>'''


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    requests, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 900, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            def intercept(route):
                if route.request.url == BASE + '/new-road-check':
                    route.fulfill(content_type='text/html', body=HTML)
                elif '/api/map-sources/1/roads/imports/2/features/test-road/reviews' in route.request.url:
                    requests.append(route.request.post_data_json)
                    route.fulfill(content_type='application/json', status=201, body='{"id":1}')
                elif not route.request.url.startswith(BASE + '/') or '/api/' in route.request.url:
                    route.abort()
                else:
                    route.continue_()
            page.route('**/*', intercept)
            page.goto(BASE + '/new-road-check')
            page.wait_for_load_state('networkidle')
            expect(page.get_by_label('公共道路源版本（SHA-256）')).to_have_count(0)
            page.get_by_label('核验决定').click()
            page.get_by_text('资料已核验', exact=True).click()
            page.get_by_text('不记录新增道路连接', exact=True).click()
            page.get_by_text('记录公共地图未收录道路的连接依据', exact=True).click()
            page.get_by_label('公共道路源版本（SHA-256）').fill('b' * 64)
            page.get_by_label('公共节点编号').fill('12345678901')
            page.get_by_label('核验依据（台账、核查记录等）').fill('合成端点核查记录')
            page.get_by_label('核验说明').fill('仅测试记录，不涉及业务道路')
            page.get_by_role('button', name='记录核验决定').click()
            page.wait_for_function('window.saved === true')
            assert len(requests) == 1
            assert requests[0]['connection_evidence']['connections'] == [
                {'component': 0, 'endpoint': 'start', 'osm_node_id': 12345678901}]
            expect(page.locator('.ant-select-dropdown:visible')).to_have_count(0)
            page.set_viewport_size({'width': 420, 'height': 1000})
            page.screenshot(path=str(OUTPUT / 'form.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.evaluate(
                "Array.from(document.querySelectorAll('*')).filter(e=>e.getBoundingClientRect().right>innerWidth).slice(0,8).map(e=>[e.tagName,e.className,e.getBoundingClientRect().width])")
            assert not errors, errors
            (OUTPUT / 'report.json').write_text(json.dumps({'passed': True,
                'scope': 'real form, intercepted synthetic submission, not business backend',
                'submitted': requests[0], 'page_errors': errors}, ensure_ascii=False, indent=2))
        finally:
            browser.close()


if __name__ == '__main__':
    main()
