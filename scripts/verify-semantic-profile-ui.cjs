/* Real local API + synthetic-only fixture from serve-isolated-showcase.py. */
const assert = require('node:assert/strict')
const { mkdirSync, writeFileSync } = require('node:fs')
const { chromium } = require(process.env.AIC_PLAYWRIGHT_MODULE || 'playwright')
const base = 'http://127.0.0.1:13043'
const output = 'output/playwright/semantic-profile'

async function main() {
  mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, channel: 'chrome' })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const external = [], errors = [], checks = []
  try {
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== base) {
        external.push(route.request().url()); return route.abort()
      }
      return route.continue()
    })
    assert.equal((await context.request.get(base + '/api/cases/1/analysis-profile/latest')).status(), 401)
    const login = await context.request.post(base + '/api/auth/login', {
      headers: { Origin: base }, data: { username: 'showcase-check', password: 'Disposable-showcase-0910!' },
    })
    assert.equal(login.status(), 200)
    const caseResponse = await context.request.get(base + '/api/cases/1')
    const caseData = await caseResponse.json()
    assert.equal(caseData.case_number, 'SYNTHETIC-SEMANTIC-001')
    const profileResponse = await context.request.get(base + '/api/cases/1/analysis-profile/latest')
    assert.equal(profileResponse.status(), 200)
    const profile = await profileResponse.json()
    assert.equal(profile.payload.semantics.time_intervals.length, 1)
    assert.equal(profile.payload.semantics.structured_sources.entries.length, 4)
    const resultResponse = await context.request.get(base + '/api/cases/1/results/latest')
    assert.equal(resultResponse.status(), 200)
    const result = await resultResponse.json()
    assert.equal(result.content.versions.case_profile_id, profile.id)
    assert.equal(result.freshness, 'current')
    const page = await context.newPage()
    const businessReads = []
    page.on('request', request => {
      const url = new URL(request.url())
      if (url.pathname.startsWith('/api/cases/1/')) businessReads.push(url.pathname)
    })
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(base + '/cases?caseId=1')
    const unified = page.getByRole('region', { name: '统一研判成果', exact: true })
    await unified.getByRole('heading', { name: '统一研判成果', exact: true }).waitFor()
    const panel = page.getByRole('region', { name: '案情语义画像' })
    await panel.getByRole('heading', { name: '案情语义画像' }).waitFor()
    await page.waitForLoadState('networkidle')
    assert.match(await panel.innerText(), /原文否定/)
    await panel.getByText('查看原文出处', { exact: true }).first().click()
    assert.ok(await panel.getByText('未发现罐车', { exact: true }).isVisible())
    await panel.getByText('时间表达 1 项', { exact: true }).click()
    await panel.getByText('结构化资料 4 项', { exact: true }).click()
    assert.match(await panel.innerText(), /2026-09-10 22时/)
    assert.match(await panel.innerText(), /套牌.*否/)
    await unified.getByText('原始记录摘要与关联条件', { exact: true }).click()
    assert.match(await unified.innerText(), /原始记录摘要，非新增核实结论/)
    assert.match(await unified.innerText(), /尚无可展示候选/)
    for (const width of [1440, 420]) {
      await page.setViewportSize({ width, height: 1000 })
      await panel.scrollIntoViewIfNeeded()
      const box = await panel.boundingBox()
      const layout = await panel.evaluate(el => {
        const result = []
        for (let node = el; node; node = node.parentElement) {
          const rect = node.getBoundingClientRect()
          result.push({ name: node.className, width: rect.width, x: rect.x })
        }
        return result
      })
      await panel.screenshot({ path: `${output}/observed-${width}.png` })
      assert.ok(box && box.width <= width && box.x >= 0 && box.x + box.width <= width + 1, JSON.stringify({ width, box, layout }))
      assert.equal(await panel.evaluate(el => el.scrollWidth <= el.clientWidth + 1), true)
      await panel.screenshot({ path: `${output}/semantic-${width}.png` })
      await panel.getByRole('heading', { name: '案情语义画像' }).evaluate(el => el.scrollIntoView({ block: 'center' }))
      await page.screenshot({ path: `${output}/viewport-${width}.png` })
      await unified.getByRole('heading', { name: '统一研判成果', exact: true }).evaluate(el => el.scrollIntoView({ block: 'center' }))
      await page.screenshot({ path: `${output}/unified-${width}.png` })
      assert.equal(await unified.evaluate(el => el.scrollWidth <= el.clientWidth + 1), true)
      checks.push({ width, panelWidth: box.width, horizontalOverflow: false })
    }
    const after = await (await context.request.get(base + '/api/cases/1')).json()
    assert.equal(after.description, caseData.description)
    assert.deepEqual(after.vehicle_info, caseData.vehicle_info)
    assert.deepEqual(external, [])
    assert.deepEqual(errors, [])
    assert.ok(businessReads.includes('/api/cases/1/results/latest'))
    assert.ok(!businessReads.includes('/api/cases/1/analysis-profile/latest'))
    assert.ok(!businessReads.includes('/api/cases/1/insights/latest'))
    // Inject only a transport failure after real content is loaded, never a fake success response.
    await page.route('**/api/cases/1/results/latest', route => route.abort())
    await unified.getByText('成果暂时无法读取，已隐藏上次内容。案件保存不受影响。', { exact: true }).waitFor({ timeout: 15000 })
    assert.ok(!(await unified.innerText()).includes('未发现罐车'))
    assert.equal(await unified.getByRole('region', { name: '案情语义画像' }).count(), 0)
    await page.unroute('**/api/cases/1/results/latest')
    await page.reload()
    await page.getByRole('region', { name: '案情语义画像' }).getByText('原文否定', { exact: true }).first().waitFor()
    writeFileSync(`${output}/report.json`, JSON.stringify({ passed: true, apiMocking: false,
      syntheticData: true, profileId: profile.id, ruleVersion: profile.payload.semantics.rule_version,
      resultId: result.id, unifiedResult: true, businessReads, transportFailureHidesCachedContent: true,
      checks, errors, external, targetServerVerified: false }, null, 2))
    console.log('semantic_profile_ui_passed')
  } catch (error) {
    writeFileSync(`${output}/failure.json`, JSON.stringify({ message: String(error), checks, errors }, null, 2))
    throw error
  } finally { await context.close(); await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
