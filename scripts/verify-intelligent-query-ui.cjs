/* Real browser + isolated API responses. Not a model/backend integration test. */
const assert = require('node:assert/strict')
const { mkdirSync } = require('node:fs')
const { chromium } = require(process.env.AIC_PLAYWRIGHT_MODULE || 'playwright')
const base = 'http://127.0.0.1:13041'
const output = 'output/playwright/intelligent-query'
const id = '11111111-1111-4111-8111-111111111111'
const childId = '22222222-2222-4222-8222-222222222222'

async function main() {
  mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, channel: 'chrome' })
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } })
  const page = await context.newPage()
  let status = 'queued', denied = false, disabled = false
  let activeId = id
  const submissions = []
  let delayedCancel, holdCancel = false, holdRead = false, delayedRead
  let markCancelRequested, markReadRequested
  const cancelRequested = new Promise(resolve => { markCancelRequested = resolve })
  const readRequested = new Promise(resolve => { markReadRequested = resolve })
  const crashes = [], external = [], calls = []
  page.on('pageerror', error => crashes.push(error.message))
  await context.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.origin !== base) { external.push(url.href); return route.abort() }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    calls.push(url.pathname)
    if (url.pathname === '/api/auth/me') return route.fulfill({ json: {
      id: 1, username: 'fixture', display_name: '隔离测试', role: 'analyst', is_active: true, created_at: '2026-09-10',
    } })
    if (url.pathname === '/api/auth/me/area-scopes') return route.fulfill({ json: [] })
    if (url.pathname === '/api/intelligent-queries' && route.request().method() === 'POST') {
      if (disabled) return route.fulfill({ status: 404, json: { detail: 'disabled' } })
      status = 'queued'
      const body = route.request().postDataJSON()
      submissions.push(body)
      activeId = body.parent_query_id ? childId : id
      return route.fulfill({ status: 201, json: { id: activeId, status, query: '统计案件', result: {} } })
    }
    if (url.pathname.endsWith('/cancel')) {
      if (holdCancel) return new Promise(resolve => { delayedCancel = async () => {
        status = 'cancelled'
        await route.fulfill({ json: { id, status } }); resolve()
      }; markCancelRequested() })
      status = 'cancelled'
      return route.fulfill({ json: { id, status } })
    }
    if ([`/api/intelligent-queries/${id}`, `/api/intelligent-queries/${childId}`].includes(url.pathname)) {
      if (holdRead) return new Promise(resolve => { delayedRead = async () => {
        await route.fulfill({ status: 403, json: { detail: 'revoked' } }); resolve()
      }; markReadRequested() })
      if (denied) return route.fulfill({ status: 403, json: { detail: 'revoked' } })
      return route.fulfill({ json: { id: activeId, status, query: '统计案件', result_kind: 'historical_query_snapshot',
        followup_context: activeId === childId ? { parent_query_id: id, previous_question: '统计案件',
          parent_result_hash: 'a'.repeat(64), conditions: { case_filters: { operational_area_id: 1 }, area: 1, tool_defaults: {} } } : null,
        result: status === 'completed' ? { query_conditions: { case_filters: { operational_area_id: 1 }, area: 1, tool_defaults: {} }, cards: [{ tool: 'count_cases', state: 'empty', data: { count: 0 },
          information_gaps: ['无匹配数据不代表其他范围不存在数据。'],
          evidence: { source: 'cases', queried_at: '2026-09-10T10:00:00Z', filters: { operational_area_id: 1 } },
          boundary: '只读查询。' }, {
            tool: 'summarize_results', state: 'ready', data: { total: 1, items: [{
              run_id: 'isolated-content', content_state: 'ready', summary: '隔离成果摘要',
              case_profile_id: 'profile-fixture', map_snapshot_id: 'snapshot-fixture', algorithm_version: 'fixture-1',
              information_gaps: ['缺少现场核验'], hypotheses: [{ id: 'candidate-fixture', title: '区域候选',
                claim: '隔离候选解释', rule_support: 60, supporting_evidence: ['同类案件条件'],
                counter_evidence: ['可能只是设施集中'], information_gaps: ['缺少现场核验'],
                evidence_refs: ['case:1'], boundary: '不是正式事实' }],
            }] }, information_gaps: ['历史候选不转为正式事实。'],
          }, { tool: 'find_case_profiles', state: 'ready', data: { total: 1,
            items: [{ case_id: 1, case_number: '合成案件', profile_version: 1, content_state: 'ready',
              assertions: [{ value: '罐车', kind: 'negated', reference: { field: 'description',
                quote: '未发现罐车', start: 0, end: 5, source_sha256: 'synthetic-source-hash' } }] }],
            batch_patterns: [{ value: '罐车', kind: 'negated', case_count: 1 }] },
            information_gaps: ['本批统计不代表全库规律。']
          }], trace: [{ step: 1, tool: 'count_cases', duration_ms: 5 }] } : {} } })
    }
    return route.fulfill({ json: {} })
  })
  try {
    await page.goto(`${base}/assistant`)
    await page.getByLabel('查询问题').fill('统计案件')
    await page.getByRole('button', { name: '提交查询', exact: true }).click()
    await page.getByText('排队中', { exact: true }).waitFor()
    assert.ok(page.url().includes(id))
    await page.reload()
    await page.getByText('排队中', { exact: true }).waitFor()
    await page.getByRole('button', { name: '取消本次查询', exact: true }).click()
    await page.getByText('已取消', { exact: true }).waitFor()
    status = 'completed'
    await page.getByRole('button', { name: '刷新状态', exact: true }).click()
    await page.getByText('查询完成', { exact: true }).waitFor()
    assert.match(await page.locator('.query-result').first().innerText(), /匹配案件：0 起/)
    const content = await page.locator('.query-insight-content').first().innerText()
    for (const text of ['隔离成果摘要', '隔离候选解释', '支持证据', '反向证据', '可能只是设施集中', '不是准确概率']) {
      assert.ok(content.includes(text))
    }
    await page.getByRole('button', { name: '导出 Word', exact: true }).waitFor()
    await page.getByRole('button', { name: '导出 PDF', exact: true }).waitFor()
    const semantics = await page.getByRole('region', { name: '案件语义画像' }).innerText()
    for (const text of ['原文否定', '未发现罐车', 'synthetic-source-hash', '非全库统计']) assert.ok(semantics.includes(text))
    await page.getByLabel('继续追问', { exact: true }).fill('这些案件有多少？')
    await page.getByRole('button', { name: '继续追问', exact: true }).click()
    await page.getByText('排队中', { exact: true }).waitFor()
    assert.equal(submissions.at(-1).parent_query_id, id)
    assert.ok(page.url().includes(childId))
    await page.getByRole('button', { name: '查看上一轮', exact: true }).waitFor()
    status = 'completed'
    await page.getByRole('button', { name: '刷新状态', exact: true }).click()
    await page.getByText('查询完成', { exact: true }).waitFor()
    assert.ok((await page.getByRole('region', { name: '当前查询条件' }).innerText()).includes('辖区编号：1'))
    for (const width of [1366, 768, 390]) {
      await page.setViewportSize({ width, height: 900 })
      await page.screenshot({ path: `${output}/result-${width}.png`, fullPage: true })
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    }
    denied = true
    await page.getByRole('button', { name: '刷新状态', exact: true }).click()
    await page.getByText('账号或数据范围已变化，不能继续显示旧查询结果。').waitFor()
    assert.equal(await page.locator('.query-result').count(), 0)
    assert.equal(await page.locator('.query-original').count(), 0)
    // A late cancellation must not resurrect cached content after a read denial.
    denied = false; status = 'queued'; holdCancel = true
    await page.getByRole('button', { name: '重新读取', exact: true }).click()
    await page.getByText('排队中', { exact: true }).waitFor()
    await page.getByRole('button', { name: '取消本次查询', exact: true }).click()
    await cancelRequested
    denied = true
    await page.getByRole('button', { name: '刷新状态', exact: true }).click()
    await page.getByText('账号或数据范围已变化，不能继续显示旧查询结果。').waitFor()
    holdRead = true
    await delayedCancel()
    await readRequested
    // Keep the post-cancel read in flight so an optimistic cache update cannot hide.
    assert.equal(await page.locator('.query-original').count(), 0)
    assert.equal(await page.locator('.query-result').count(), 0)
    await delayedRead()
    await page.getByText('账号或数据范围已变化，不能继续显示旧查询结果。').waitFor()
    assert.equal(await page.locator('.query-original').count(), 0)
    holdRead = false; holdCancel = false
    await page.getByRole('button', { name: '新查询', exact: true }).click()
    disabled = true
    await page.getByLabel('查询问题').fill('统计')
    await page.getByRole('button', { name: '提交查询', exact: true }).click()
    await page.getByText('智能查询尚未启用，请联系管理员。').waitFor()
    assert.equal(calls.some(path => path.startsWith('/api/assistant/')), false)
    assert.deepEqual(crashes, [])
    assert.deepEqual(external, [])
    console.log(JSON.stringify({ passed: true, checks: ['submit', 'followup-parent-reference', 'inherited-condition-display', 'reload', 'cancel', 'zero', 'responsive', 'revoked', 'late-cancel-after-revocation', 'disabled'], backendIntegration: false }))
  } finally { await context.close(); await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
