"""Real React form check with synthetic data, no business server or login."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:13051'
OUTPUT = Path('output/playwright/vehicle-entry-v42')
HTML = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div>
<script type="module">
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>t=>t;
window.__vite_plugin_react_preamble_installed__=true;
const {default:React}=await import('/node_modules/.vite/deps/react.js');
const {default:ReactDOM}=await import('/node_modules/.vite/deps/react-dom_client.js');
const componentSource=await (await fetch('/src/pages/Cases/Cases.tsx')).text();
const antdUrl=componentSource.match(/from\s*["']([^"']*\/antd\.js[^"']*)["']/)[1];
const {Form,ConfigProvider,theme}=await import(antdUrl);
const {CaseEntryPrecheck}=await import('/src/pages/Cases/Cases.tsx');
const {getThemeTokens}=await import('/src/theme/themeMode.ts');
const {buildCaseEntrySubmitPayload}=await import('/src/pages/Cases/caseEntrySubmitPayload.ts');
await import('/src/styles/design-system.css');
function App(){const [form]=Form.useForm();return React.createElement(Form,{form,layout:'vertical',
initialValues:{bonus_has_vehicle:true,initial_vehicles:[{id:1,vehicle_type:'重型挂车'}]},
onFinish:values=>{window.saved=buildCaseEntrySubmitPayload(values,{mode:'edit'});}},
React.createElement(CaseEntryPrecheck,{form,onBonusVehicleScopeChange:()=>{},onBonusPersonScopeChange:()=>{}}),
React.createElement('button',{type:'submit'},'验证保存'));}
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(ConfigProvider,
{theme:{algorithm:theme.darkAlgorithm,token:{...getThemeTokens('dark').tokens,borderRadius:0,fontSize:13}}},React.createElement(App)));
</script></html>'''


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = OUTPUT / 'report.json'
    report.write_text(json.dumps({'passed': False, 'status': 'started'}))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1100, 'height': 950})
            errors, blocked = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def intercept(route):
                url = route.request.url
                if not url.startswith(BASE + '/') or '/api/' in url:
                    blocked.append(url)
                    route.abort()
                elif url == BASE + '/vehicle-entry-check':
                    route.fulfill(status=200, content_type='text/html', body=HTML)
                else:
                    route.continue_()
            page.route('**/*', intercept)
            page.goto(BASE + '/vehicle-entry-check')
            page.wait_for_load_state('networkidle')
            expect(page.get_by_text('道路通行条件（选填）', exact=True)).to_be_visible()
            page.get_by_role('button', name='验证保存').click()
            page.wait_for_function('window.saved !== undefined')
            assert 'height_m' not in page.evaluate('window.saved.initial_vehicles[0]')
            page.get_by_text('道路通行条件（选填）', exact=True).click()
            page.get_by_label('道路计算车型').click()
            page.get_by_text('货车', exact=True).click()
            page.get_by_label('车高（米）').fill('3.2')
            page.get_by_label('车辆总重（吨）').fill('12.5')
            page.get_by_role('button', name='验证保存').click()
            page.wait_for_function('window.saved.initial_vehicles[0].gross_weight_t === 12.5')
            assert page.evaluate('window.saved.initial_vehicles[0].road_vehicle_kind') == 'truck'
            page.keyboard.press('Escape')
            page.get_by_text('道路通行条件（选填）', exact=True).focus()
            expect(page.locator('.ant-select-dropdown:visible')).to_have_count(0)
            for width in (1100, 420):
                page.set_viewport_size({'width': width, 'height': 950})
                expect(page.get_by_label('车高（米）')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(OUTPUT / f'form-{width}.png'), full_page=True)
            assert not errors and not blocked, (errors, blocked)
            report.write_text(json.dumps({'passed': True, 'scope': 'synthetic React form, no production login',
                'optional_save': True, 'truck_fields_submitted': True, 'widths': [1100, 420],
                'page_errors': errors, 'blocked_requests': blocked}, ensure_ascii=False, indent=2))
        finally:
            browser.close()


if __name__ == '__main__':
    main()
