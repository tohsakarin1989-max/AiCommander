/* Actual authenticated HTTP + published public MBTiles + synthetic business data. */
const assert = require('node:assert/strict')
const { mkdirSync, writeFileSync } = require('node:fs')
const { chromium } = require(process.env.AIC_PLAYWRIGHT_MODULE || 'playwright')
const base = 'http://127.0.0.1:13042'
const output = 'output/playwright/dashboard-map-integration'

async function main() {
  mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, channel: 'chrome', args: ['--enable-unsafe-swiftshader'] })
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
  const external = [], errors = [], responses = []
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin !== base) {
      external.push(route.request().url()); return route.abort()
    }
    return route.continue()
  })
  try {
    const login = await context.request.post(`${base}/api/auth/login`, {
      headers: { Origin: base }, data: { username: 'queue-map-test', password: 'Isolated-queue-map-test-123!' },
    })
    assert.equal(login.status(), 200)
    const reply = await context.request.get(`${base}/api/cases/dashboard-summary?operational_area_id=1&days=7`)
    assert.equal(reply.status(), 200)
    const summary = await reply.json()
    assert.equal(summary.metrics.cases, 1)
    const insight = summary.attention.find(item => item.kind === 'existing_insight')
    assert.ok(insight && insight.counter_evidence.length && insight.evidence_refs.length)
    assert.equal(insight.evidence[0].case_number, 'SYNTHETIC-DASHBOARD-001')
    const manifestReply = await context.request.get(`${base}/api/maps/current/manifest?operational_area_id=1`)
    assert.equal(manifestReply.status(), 200)
    const manifest = await manifestReply.json()
    assert.equal(insight.map_snapshot_id, manifest.snapshot_id)
    assert.equal(manifest.network_required, false)
    assert.equal(manifest.capabilities.motor_vehicle_routing, false)
    const page = await context.newPage()
    page.on('pageerror', error => errors.push(error.message))
    page.on('response', response => {
      const path = new URL(response.url()).pathname
      if (path.startsWith('/api/')) responses.push({ path, status: response.status() })
    })
    const cdp = await context.newCDPSession(page)
    await cdp.send('Network.clearBrowserCache')
    const started = Date.now()
    await page.goto(`${base}/dashboard`)
    await page.locator('.maplibregl-canvas').waitFor()
    await page.waitForFunction(() => !document.body.textContent.includes('正在加载'))
    await page.waitForLoadState('networkidle')
    const coldOpenMs = Date.now() - started
    assert.ok(responses.some(item => item.path.includes('/tiles/') && item.status === 200))
    assert.ok(responses.some(item => item.path.includes('/glyphs/') && item.status === 200))
    const panel = page.locator('.daily-attention')
    await panel.locator('summary').first().click()
    assert.ok((await panel.innerText()).includes(insight.claim))
    await panel.getByRole('button', { name: '地图定位', exact: true }).first().click()
    await page.waitForLoadState('networkidle')
    await page.screenshot({ path: `${output}/dashboard-evidence-map.png`, fullPage: true })
    await page.getByRole('button', { name: '登记井', exact: true }).click()
    assert.match(await page.locator('.daily-map-caption').innerText(), /有有效坐标登记井 1 口/)
    const link = panel.getByRole('link', { name: 'SYNTHETIC-DASHBOARD-001', exact: true }).first()
    assert.equal(await link.getAttribute('href'), '/cases?caseId=1')
    const detailResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/cases/1')
    await link.click()
    await page.waitForURL('**/cases?caseId=1')
    assert.equal((await detailResponse).status(), 200)
    await page.locator('.maplibregl-canvas').waitFor()
    await page.locator('.maplibregl-canvas').scrollIntoViewIfNeeded()
    await page.waitForFunction(() => !document.body.textContent.includes('正在加载内网地图'))
    await page.waitForLoadState('networkidle')
    assert.ok(responses.some(item => item.path === '/api/cases/1' && item.status === 200))
    await page.screenshot({ path: `${output}/case-detail.png`, fullPage: true })
    assert.deepEqual(external, [])
    assert.deepEqual(errors, [])
    assert.ok(!responses.some(item => item.status >= 500))
    const report = { passed: true, apiMocking: false, syntheticBusinessData: true,
      snapshot: manifest.snapshot_id, caseId: 1, coldOpenMs, coldOpenTargetMs: 5000,
      coldOpenTargetMet: coldOpenMs <= 5000, publicRequests: external.length,
      responses, errors, targetServerVerified: false }
    writeFileSync(`${output}/report.json`, JSON.stringify(report, null, 2))
    console.log(JSON.stringify(report))
  } catch (error) {
    writeFileSync(`${output}/failure.json`, JSON.stringify({ errors, responses, message: String(error) }, null, 2))
    throw error
  } finally {
    await context.close()
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
