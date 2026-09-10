/* Real authenticated API; fixed synthetic cases only, no API mocks. */
const assert = require('node:assert/strict')
const { mkdirSync } = require('node:fs')
const { chromium } = require(process.env.AIC_PLAYWRIGHT_MODULE || 'playwright')
const mapMode = process.env.AIC_SHOWCASE_MAP_CHECK === '1'
const base = mapMode ? 'http://127.0.0.1:13042' : 'http://127.0.0.1:13043'

async function main() {
  const browser = await chromium.launch({ headless: true, channel: 'chrome', args: ['--enable-unsafe-swiftshader'] })
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const external = [], errors = []
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== base) { external.push(route.request().url()); return route.abort() }
      return route.continue()
    })
    assert.equal((await context.request.get(base + '/api/showcase/runs')).status(), 401)
    const login = await context.request.post(base + '/api/auth/login', { headers: { Origin: base },
      data: mapMode ? { username: 'queue-map-test', password: 'Isolated-queue-map-test-123!' }
        : { username: 'showcase-check', password: 'Disposable-showcase-0910!' } })
    assert.equal(login.status(), 200)
    const page = await context.newPage()
    const responses = []
    page.on('response', response => responses.push({ path: new URL(response.url()).pathname, status: response.status() }))
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(base + '/showcase')
    const records = []
    for (const title of ['一次录入，形成证据', '证据不足，明确停止', '模型故障，业务继续']) {
      const responsePromise = page.waitForResponse(r => r.url().endsWith('/api/showcase/runs') && r.request().method() === 'POST')
      await page.getByRole('button', { name: title, exact: false }).first().click()
      const response = await responsePromise
      assert.equal(response.status(), 201)
      const record = await response.json()
      assert.equal(record.status, 'completed')
      records.push(record)
      await page.getByRole('heading', { name: '本次运行结果' }).waitFor()
      await page.getByRole('heading', { name: '真实调用轨迹' }).waitFor()
      await page.getByRole('heading', { name: '00 / 真实 CSV 导入' }).waitFor()
      assert.equal(record.result.import.rows, 1)
      if (mapMode) {
        await page.locator('.showcase-map .maplibregl-canvas').waitFor()
        await page.locator('.showcase-map').scrollIntoViewIfNeeded()
        await page.waitForFunction(() => !document.querySelector('.showcase-map-host').textContent.includes('正在加载'))
        await page.waitForLoadState('networkidle')
        assert.equal(await page.getByRole('button', { name: '重试当前地图' }).count(), 0)
      }
    }
    assert.ok(records[0].result.analysis.hypotheses.length > 0)
    assert.equal(records[1].result.analysis.hypotheses.length, 0)
    assert.equal(records[2].result.fault.status, 'degraded')
    await page.locator('.showcase-history').last().click()
    await page.getByRole('heading', { name: '历史轨迹回放' }).waitFor()
    await page.reload()
    await page.locator('.showcase-history').first().waitFor()
    const saved = (await (await context.request.get(base + '/api/showcase/runs')).json()).items
    assert.ok(records.every(record => saved.some(item => item.id === record.id)))
    await page.locator('.showcase-history').first().click()
    await page.getByRole('heading', { name: '历史轨迹回放' }).waitFor()
    if (mapMode) {
      await page.locator('.showcase-map .maplibregl-canvas').waitFor()
      await page.locator('.showcase-map').scrollIntoViewIfNeeded()
      await page.waitForFunction(() => !document.querySelector('.showcase-map-host').textContent.includes('正在加载'))
      await page.waitForLoadState('networkidle')
      assert.equal(await page.getByRole('button', { name: '重试当前地图' }).count(), 0)
    }
    mkdirSync('output/playwright/showcase', { recursive: true })
    await page.screenshot({ path: 'output/playwright/showcase/desktop.png', fullPage: true })
    await page.setViewportSize({ width: 768, height: 1024 })
    await page.waitForLoadState('networkidle')
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
    await page.screenshot({ path: 'output/playwright/showcase/narrow.png', fullPage: true })
    // Separate UI authorization fault injection; the three executions above
    // used the real API without substituted responses.
    await page.route('**/api/showcase/runs/*', route => route.fulfill({ status: 403,
      contentType: 'application/json', body: JSON.stringify({ detail: '权限已撤销' }) }))
    await page.locator('.showcase-history').first().click()
    await page.getByText('展示服务未启用、无访问权限或暂不可用。', { exact: false }).waitFor()
    assert.equal(await page.locator('.showcase-candidate').count(), 0)
    assert.equal(await page.locator('.showcase-history').count(), 0)
    assert.deepEqual(errors, [])
    assert.deepEqual(external, [])
    if (mapMode) {
      assert.ok(responses.some(r => r.path.includes('/tiles/') && r.status === 200))
      assert.ok(responses.some(r => r.path.includes('/glyphs/') && r.status === 200))
      assert.ok(!responses.some(r => /production|\/api\/cases|\/api\/jurisdiction/.test(r.path)))
    }
    console.log(JSON.stringify({ status: 'passed', liveScenarios: 3, historicalReplay: true,
      reloadPreserved: 3, liveScenarioApiMocking: false, authorizationFaultInjected: true,
      deniedContentCleared: true, realPublicMap: mapMode, productionLayerRequested: false,
      publicRequests: 0, pageErrors: 0 }))
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
