/* Real browser, isolated API fixture: not backend or offline-map integration. */
const assert = require('node:assert/strict')
const { mkdirSync } = require('node:fs')
const { chromium } = require(process.env.AIC_PLAYWRIGHT_MODULE || 'playwright')
const base = 'http://127.0.0.1:13041'
const output = 'output/playwright/dashboard-insights'

async function main() {
  mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, channel: 'chrome' })
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await context.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.origin !== base) return route.abort()
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (url.pathname === '/api/auth/me') return route.fulfill({ json: {
      id: 1, username: 'fixture', display_name: '隔离测试', role: 'analyst', is_active: true,
      created_at: '2026-09-10T00:00:00Z',
    } })
    if (url.pathname === '/api/auth/me/area-scopes') return route.fulfill({ json: [
      { operational_area_id: 1, area_name: '合成一区', is_default: true },
    ] })
    if (url.pathname === '/api/cases/dashboard-summary') return route.fulfill({ json: {
      schema_version: 1, operational_area_id: 1, as_of: new Date().toISOString(), state: 'ready',
      period: { start: '2026-09-03T00:00:00Z', end: '2026-09-10T00:00:00Z', days: 7,
        previous_start: '2026-08-27T00:00:00Z', previous_end: '2026-09-03T00:00:00Z', timezone: 'Asia/Shanghai' },
      metrics: { cases: 1, previous_cases: 0, change: 1, registered_wells: 0, analysis_results: 1 },
      definitions: { cases: '合成案件', registered_wells: '合成登记', analysis_results: '生成时间口径', trend: '北京时间' },
      trend: [{ date: '2026-09-09', count: 1 }],
      attention_scan: { limit: 50, truncated: true },
      attention: [{ id: 'h1', kind: 'existing_insight', title: '合成区域待核验候选',
        claim: '已有候选解释，不是确认结论', rule_support: 60,
        supporting_evidence: ['条件相近'], counter_evidence: ['不能证明实际来源'],
        information_gaps: ['缺少现场证据'], evidence_refs: ['case:1'],
        case_profile_id: 'profile-v1', map_snapshot_id: 'snapshot-v1', algorithm_version: 'algorithm-v1',
        evidence: [{ case_id: 1, case_number: 'SYNTHETIC-001', latitude: 46.6, longitude: 125.1 }],
        boundary: '仅供人工核验，不是正式事实' }],
      map: { cases: [], wells: [], coordinate_cases: 0, missing_coordinate_cases: 1, coordinate_wells: 0 },
    } })
    if (url.pathname.startsWith('/api/maps/')) return route.fulfill({ status: 404, json: { detail: 'fixture_no_map' } })
    return route.fulfill({ json: {} })
  })
  try {
    await page.goto(`${base}/dashboard`)
    await page.getByRole('heading', { name: '本期关注重点' }).waitFor()
    await page.locator('.daily-attention summary').click()
    for (const width of [1920, 768, 390]) {
      await page.setViewportSize({ width, height: 1080 })
      const panel = page.locator('.daily-attention')
      const text = await panel.innerText()
      for (const required of ['支持证据', '反向证据', '不能证明实际来源', '缺少现场证据', '不是准确概率', '最近 50 份']) {
        assert.ok(text.includes(required), required)
      }
      assert.equal(await panel.getByRole('link', { name: 'SYNTHETIC-001' }).getAttribute('href'), '/cases?caseId=1')
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      await panel.screenshot({ path: `${output}/attention-${width}.png` })
    }
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ passed: true, apiFixture: true, backendIntegration: false, widths: [1920, 768, 390] }))
  } catch (error) {
    console.error({ pageErrors: errors, pageText: await page.locator('body').innerText() })
    throw error
  } finally {
    await context.close()
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
