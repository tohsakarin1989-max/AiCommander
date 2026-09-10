/* Real HTTP API, isolated public dataset only. No mocked API responses. */
const assert = require('node:assert/strict')
const { mkdirSync } = require('node:fs')
const { chromium } = require(process.env.AIC_PLAYWRIGHT_MODULE || 'playwright')
const base = 'http://127.0.0.1:13042'
const output = 'output/playwright/real-map-http'
const containerMode = process.env.AIC_CONTAINER_MAP_CHECK === '1'

async function main() {
  mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, channel: 'chrome',
    args: ['--enable-unsafe-swiftshader'] })
  try {
    const context = await browser.newContext({ viewport: { width: 1200, height: 900 } })
    const external = [], errors = [], responses = []
    await context.route('**/*', route => {
      const url = new URL(route.request().url())
      if (url.origin !== base) { external.push(url.href); return route.abort() }
      return route.continue()
    })
    const login = await context.request.post(`${base}/api/auth/login`, {
      headers: { Origin: base },
      data: containerMode
        ? { username: 'queue-map-test', password: 'Isolated-queue-map-test-123!' }
        : { username: 'map-check', password: 'Disposable-map-check-0910!' },
    })
    assert.equal(login.status(), 200, 'real isolated login required')
    const page = await context.newPage()
    page.on('pageerror', error => errors.push(error.stack || error.message))
    page.on('response', response => {
      const url = new URL(response.url())
      if (url.pathname.startsWith('/api/')) responses.push({ path: url.pathname, status: response.status() })
    })
    const cdp = await context.newCDPSession(page)
    await cdp.send('Network.clearBrowserCache')
    await page.goto(`${base}/tests/fixtures/offline-map.html`)
    for (const view of ['cases', 'picker', 'heat', 'assets']) {
      const firstResponse = responses.length
      await page.getByRole('button', { name: view, exact: true }).click()
      await page.locator('.maplibregl-canvas').waitFor()
      await page.waitForFunction(() => !document.body.textContent.includes('正在加载'))
      await page.waitForLoadState('networkidle')
      assert.equal(await page.getByRole('button', { name: '重试当前地图' }).count(), 0)
      assert.ok(responses.slice(firstResponse).some(item => item.path.endsWith('/style.json') && item.status === 200),
        `${view}: real style must load`)
      assert.ok(responses.slice(firstResponse).some(item => item.path.includes('/tiles/') && item.status === 200),
        `${view}: real tiles must load`)
      await page.screenshot({ path: `${output}/${view}.png` })
      if (view === 'picker') {
        await page.locator('.leaflet-container').click({ position: { x: 550, y: 325 } })
        assert.notEqual(await page.getByTestId('selection').innerText(), '尚未选点')
      }
      await page.getByRole('button', { name: 'none', exact: true }).click()
      await page.locator('.maplibregl-canvas').waitFor({ state: 'detached' })
    }
    const manifestReply = await context.request.get(`${base}/api/maps/current/manifest?operational_area_id=1`)
    assert.equal(manifestReply.status(), 200)
    const manifest = await manifestReply.json()
    assert.equal(manifest.network_required, false)
    assert.equal(manifest.capabilities.motor_vehicle_routing, false)
    const places = await context.request.get(`${base}/api/maps/${manifest.snapshot_id}/places?q=${encodeURIComponent('大庆')}&operational_area_id=1`)
    assert.equal(places.status(), 200)
    assert.ok((await places.json()).items.length > 0)
    assert.deepEqual(external, [])
    assert.deepEqual(errors, [])
    assert.ok(responses.some(item => item.path.endsWith('/style.json') && item.status === 200))
    assert.ok(responses.some(item => item.path.includes('/glyphs/') && item.status === 200))
    assert.ok(responses.some(item => item.path.includes('/tiles/') && item.status === 200))
    assert.ok(!responses.some(item => item.status >= 500))
    const productionPages = []
    if (containerMode) {
      for (const path of ['/cases/map', '/jurisdiction', '/cases/spacetime', '/dashboard']) {
        const start = responses.length
        await page.goto(base + path)
        await page.locator('.maplibregl-canvas').waitFor()
        await page.locator('.maplibregl-canvas').scrollIntoViewIfNeeded()
        await page.waitForFunction(() => !document.body.textContent.includes('正在加载'))
        await page.waitForLoadState('networkidle')
        assert.equal(await page.getByRole('button', { name: '重试当前地图' }).count(), 0)
        assert.ok(responses.slice(start).some(item => item.path.endsWith('/style.json') && item.status === 200))
        assert.ok(responses.slice(start).some(item => item.path.includes('/tiles/') && item.status === 200),
          `${path}: no successful tile response`)
        assert.ok(!responses.slice(start).some(item => item.status >= 500))
        await page.screenshot({ path: `${output}/page-${path.replaceAll('/', '-')}.png`, fullPage: true })
        productionPages.push(path)
      }
      // SPA navigation (not document reload) must dispose queued map callbacks.
      await page.getByTitle('放大', { exact: true }).click()
      await page.getByTitle('全屏', { exact: true }).click()
      await page.evaluate(() => {
        const map = document.querySelector('.db-dashboard-leaflet')
        if (!map) throw new Error('dashboard map missing')
        window.history.pushState({}, '', '/cases')
        window.dispatchEvent(new PopStateEvent('popstate'))
      })
      await page.locator('.db-dashboard-leaflet').waitFor({ state: 'detached' })
      await page.waitForLoadState('networkidle')
    }
    assert.deepEqual(external, [])
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ status: 'real_http_offline_components_passed', components: 4,
      authenticated: true, apiMocking: false, publicRequests: external.length,
      successfulTiles: responses.filter(item => item.path.includes('/tiles/') && item.status === 200).length,
      successfulGlyphs: responses.filter(item => item.path.includes('/glyphs/') && item.status === 200).length,
      snapshot: manifest.snapshot_id, productionPagesOpened: productionPages,
      productionPageFlowsVerified: false }))
  } finally { await browser.close() }
}
main().catch(error => { console.error(error.message); process.exitCode = 1 })
