/* Isolated browser regression: requires browser_fixture_app and a local frontend. */
const assert = require('node:assert/strict')
const { mkdirSync } = require('node:fs')
const { chromium } = require(process.env.AIC_PLAYWRIGHT_MODULE || 'playwright')
const base = 'http://127.0.0.1:13040'
const output = process.env.AIC_BROWSER_OUTPUT || '/tmp/aic-v4-browser-artifacts'

async function main() {
  mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, channel: 'chrome' })
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
  const page = await context.newPage()
  const external = []
  const crashes = []
  page.on('pageerror', error => crashes.push(error.stack || error.message))
  await context.route('**/*', route => {
    if (new URL(route.request().url()).hostname !== '127.0.0.1') {
      external.push(route.request().url()); return route.abort()
    }
    return route.continue()
  })
  try {
    await page.goto(`${base}/dashboard`)
    await page.waitForLoadState('networkidle')
    console.log('Initial headings:', await page.locator('h1,h2').allTextContents())
    await page.getByRole('heading', { name: '初始化系统管理员' }).waitFor()
    await page.getByLabel('用户名', { exact: true }).fill('browseradmin')
    await page.getByLabel('密码', { exact: true }).fill('FixturePassword!2026')
    await page.getByLabel('确认密码', { exact: true }).fill('FixturePassword!2026')
    await page.getByRole('button', { name: '创建管理员并进入系统' }).click()
    await page.locator('.daily-metrics').waitFor()
    assert.match(await page.locator('.daily-metrics article').first().innerText(), /125/)
    assert.equal(await page.locator('.daily-metrics article').count(), 4)
    await page.screenshot({ path: `${output}/dashboard-1920.png`, fullPage: true })
    for (const width of [3840, 1366, 768]) {
      await page.setViewportSize({ width, height: width === 3840 ? 2160 : 1080 })
      await page.screenshot({ path: `${output}/dashboard-${width}.png`, fullPage: true })
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    }
    await page.setViewportSize({ width: 1920, height: 1080 })
    await page.locator('.daily-attention summary').first().click()
    await page.getByRole('button', { name: '地图定位', exact: true }).first().click()
    await page.getByText('所选样例案件位置', { exact: true }).waitFor()
    await page.getByTitle('放大', { exact: true }).click()
    await page.waitForFunction(() => !document.querySelector('.leaflet-zoom-anim'))
    const mapBounds = await page.locator('.daily-map-frame').boundingBox()
    await page.mouse.move(mapBounds.x + 250, mapBounds.y + 160)
    await page.mouse.down()
    await page.mouse.move(mapBounds.x + 370, mapBounds.y + 200, { steps: 8 })
    await page.mouse.up()
    const mapPane = page.locator('.daily-map-frame .leaflet-map-pane')
    // Leaflet 惯性平移继续运行；连续12帧稳定后再记录基线，避免把惯性误判成刷新。
    await mapPane.evaluate(element => new Promise((resolve, reject) => {
      let previous = '', stableFrames = 0
      const deadline = performance.now() + 4000
      function inspect() {
        const current = element.getAttribute('style')
        stableFrames = current === previous ? stableFrames + 1 : 0
        previous = current
        if (stableFrames >= 12) return resolve()
        if (performance.now() > deadline) return reject(new Error('map movement did not settle'))
        requestAnimationFrame(inspect)
      }
      inspect()
    }))
    const before = await mapPane.getAttribute('style')
    await page.route('**/api/cases/dashboard-summary?**', route => route.fulfill({ status: 503, json: { detail: 'fixture outage' } }))
    await page.getByRole('button', { name: '刷新', exact: true }).click()
    await page.getByText('数据已过期，请刷新', { exact: true }).waitFor()
    assert.equal(await page.locator('.daily-map-frame .leaflet-container').count(), 1)
    await page.unroute('**/api/cases/dashboard-summary?**')
    await page.getByRole('button', { name: '刷新', exact: true }).click()
    await page.getByText('每 30 秒自动更新', { exact: true }).waitFor()
    assert.equal(await mapPane.getAttribute('style'), before)

    await page.goto(`${base}/cases?caseId=125`)
    await page.waitForLoadState('networkidle')
    await page.locator('.cno-big').filter({ hasText: 'DEMO-124' }).waitFor()
    await page.getByPlaceholder('搜索案件编号、地点、描述...').fill('DEMO-124')
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/cases/page') && response.url().includes('DEMO-124')),
      page.getByPlaceholder('搜索案件编号、地点、描述...').press('Enter'),
    ])
    assert.equal(await page.locator('tbody tr').filter({ hasText: 'DEMO-124' }).count(), 1)
    await page.screenshot({ path: `${output}/case-full-search.png`, fullPage: true })

    await page.getByRole('button', { name: '导入 ▾', exact: true }).click()
    const importDialog = page.getByRole('dialog')
    await page.getByRole('spinbutton', { name: '导入表头行' }).fill('2')
    const importContent = Buffer.from('回归台账\n案发时间,案情描述,经度,纬度\n2026-09-10T10:00:00+08:00,中文导入有效样本,124,47\n'
      + Array.from({ length: 6 }, (_, index) => `2026-09-10T10:00:00+08:00,中文导入错误样本${index},不是坐标,47\n`).join(''))
    await importDialog.locator('input[type="file"]').setInputFiles({
      name: '中文回归.csv', mimeType: 'text/csv',
      buffer: importContent,
    })
    await importDialog.getByText('第 4 行：经度坐标必须为有限数', { exact: true }).waitFor()
    assert.equal(await importDialog.getByText('第 9 行：经度坐标必须为有限数', { exact: true }).count(), 1)
    await importDialog.getByTitle('UTC（兼容旧版）', { exact: true }).click()
    await page.getByText('北京时间（UTC+8）', { exact: true }).click()
    assert.equal(await importDialog.locator('button').filter({ hasText: '确认导入' }).isDisabled(), true)
    await importDialog.getByRole('button', { name: '重新预览', exact: true }).click()
    await importDialog.getByText('第 4 行：经度坐标必须为有限数', { exact: true }).waitFor()
    await importDialog.getByRole('button', { name: '确认导入', exact: true }).click()
    await importDialog.getByText('本批已写入 1 条案件', { exact: true }).waitFor()
    assert.equal(await importDialog.locator('button').filter({ hasText: '确认导入' }).isDisabled(), true)
    await importDialog.getByText('第 4 行：经度坐标必须为有限数', { exact: true }).waitFor()
    await page.screenshot({ path: `${output}/case-import-receipt.png`, fullPage: true })
    await importDialog.getByText('直接修正失败行', { exact: true }).click()
    await importDialog.getByRole('combobox', { name: '选择失败行' }).click()
    await page.getByTitle('第 4 行：经度坐标必须为有限数', { exact: true }).click()
    await importDialog.getByRole('textbox', { name: '修正经度', exact: true }).fill('125')
    await importDialog.getByRole('button', { name: '仅重试此失败行', exact: true }).click()
    await importDialog.getByText('本批已写入 2 条案件', { exact: true }).waitFor()
    await importDialog.getByText('已修正并新增 1 条案件', { exact: true }).waitFor()
    assert.equal(await importDialog.locator('.cases-import-errors').getByText('第 4 行：经度坐标必须为有限数', { exact: true }).count(), 0)
    await page.screenshot({ path: `${output}/case-import-corrected.png`, fullPage: true })
    await importDialog.getByRole('combobox', { name: '选择失败行' }).click()
    await page.getByTitle('第 5 行：经度坐标必须为有限数', { exact: true }).click()
    await importDialog.getByRole('textbox', { name: '修正经度', exact: true }).fill('126')
    // Commit on the real fixture backend, then lose only the browser response.
    await page.route('**/api/case-imports/batches/*/retry', async route => {
      const response = await route.fetch()
      assert.equal(response.status(), 200)
      await route.abort('failed')
    })
    await importDialog.getByRole('button', { name: '仅重试此失败行', exact: true }).click()
    await importDialog.getByText('提交未确认或记录已变化，请刷新回执后核对。不要重新上传整批文件。', { exact: true }).waitFor()
    await page.unroute('**/api/case-imports/batches/*/retry')
    await importDialog.getByRole('button', { name: '刷新失败行', exact: true }).click()
    await importDialog.getByText('本批已写入 3 条案件', { exact: true }).waitFor()
    assert.equal(await importDialog.locator('.cases-import-errors').getByText('第 5 行：经度坐标必须为有限数', { exact: true }).count(), 0)
    await importDialog.getByRole('button', { name: /关\s*闭/ }).click()
    const repeated = await context.request.post(`${base}/api/cases/import`, {
      params: { header_row: 2 },
      multipart: { file: { name: '中文回归.csv', mimeType: 'text/csv', buffer: importContent } },
    })
    assert.equal(repeated.status(), 200)
    const replay = await repeated.json()
    assert.equal(replay.replayed, true)
    assert.equal(replay.created, 0)
    assert.equal(replay.original_created, 3)
    assert.equal(replay.table.time_zone, 'Asia/Shanghai')
    const retried = await context.request.post(`${base}/api/case-imports/batches/${replay.batch_id}/retry`, {
      data: { rows: [{ row: 4, revision: 0, changes: { longitude: '125' } }] },
    })
    assert.equal(retried.status(), 200)
    assert.equal((await retried.json()).created, 0)
    const importedCases = await context.request.get(`${base}/api/cases/page`, { params: { keyword: '中文导入有效样本' } })
    assert.equal((await importedCases.json()).total, 1)

    await page.getByRole('button', { name: '导入 ▾', exact: true }).click()
    const mappedContent = Buffer.from('日期,内容\n2026-10-01,模板映射合成样本\n')
    await importDialog.locator('input[type="file"]').setInputFiles({ name: '待映射.csv', mimeType: 'text/csv', buffer: mappedContent })
    await page.getByText(/预览失败/).waitFor()
    await importDialog.getByText('字段映射与导入模板', { exact: true }).click()
    await importDialog.getByRole('button', { name: '读取文件列名', exact: true }).click()
    await importDialog.getByRole('combobox', { name: '列日期对应字段' }).selectOption('occurred_time')
    await importDialog.getByRole('combobox', { name: '列内容对应字段' }).selectOption('description')
    await importDialog.getByRole('textbox', { name: '导入模板名称' }).fill('浏览器回归模板')
    await importDialog.getByRole('button', { name: '保存当前导入模板', exact: true }).click()
    await importDialog.getByText('模板已保存，可用于后续同类台账', { exact: true }).waitFor()
    const templateResponse = await context.request.get(`${base}/api/case-imports/templates`)
    const template = (await templateResponse.json()).find(item => item.name === '浏览器回归模板')
    assert.equal(template.settings.field_mapping['日期'], 'occurred_time')
    assert.equal(template.settings.field_mapping['内容'], 'description')
    assert.doesNotMatch(JSON.stringify(template), /模板映射合成样本/)
    await importDialog.getByRole('button', { name: /关\s*闭/ }).click()
    await page.reload()
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: '导入 ▾', exact: true }).click()
    await importDialog.getByText('字段映射与导入模板', { exact: true }).click()
    await importDialog.getByRole('combobox', { name: '套用导入模板' }).press('ArrowDown')
    await page.getByTitle(`浏览器回归模板 · ${template.id.slice(0, 8)}`, { exact: true }).click()
    await importDialog.locator('input[type="file"]').setInputFiles({ name: '待映射.csv', mimeType: 'text/csv', buffer: mappedContent })
    await importDialog.getByRole('button', { name: '确认导入', exact: true }).click()
    await importDialog.getByText('本批已写入 1 条案件', { exact: true }).waitFor()
    await importDialog.getByRole('button', { name: /关\s*闭/ }).click()
    const mappedCases = await context.request.get(`${base}/api/cases/page`, { params: { keyword: '模板映射合成样本' } })
    assert.equal((await mappedCases.json()).total, 1)

    const createdUser = await context.request.post(`${base}/api/auth/users`, { data: {
      username: 'areatwo', password: 'FixturePassword!2026', role: 'analyst', display_name: '二区测试员',
    } })
    assert.equal(createdUser.status(), 201)
    const userId = (await createdUser.json()).id
    assert.equal((await context.request.put(`${base}/api/auth/users/${userId}/area-scopes`, {
      data: { scopes: [{ operational_area_id: 2, access_level: 'write' }] },
    })).status(), 200)
    let releaseLogout
    const delayLogout = new Promise(resolve => { releaseLogout = resolve })
    await page.route('**/api/auth/logout', async route => { await delayLogout; await route.continue() })
    await page.getByRole('button', { name: '退出登录', exact: true }).click()
    await page.getByText('正在校验系统状态', { exact: true }).waitFor()
    assert.equal(await page.getByLabel('用户名', { exact: true }).count(), 0)
    releaseLogout()
    await page.getByLabel('用户名', { exact: true }).waitFor()
    await page.getByLabel('用户名', { exact: true }).fill('areatwo')
    await page.getByLabel('密码', { exact: true }).fill('FixturePassword!2026')
    await page.getByRole('button', { name: '登录系统', exact: true }).click()
    await page.getByText('链接中的案件不存在或当前无权访问。', { exact: true }).waitFor()
    assert.equal(await page.locator('.cno-big').count(), 0)
    assert.equal(await page.getByText('合成回归样本 124', { exact: false }).count(), 0)
    assert.match(await page.locator('tbody').innerText(), /AREA-TWO-ONLY/)
    assert.doesNotMatch(await page.locator('tbody').innerText(), /DEMO-/)
    assert.equal((await context.request.get(`${base}/api/cases/125`)).status(), 404)
    assert.equal((await context.request.get(`${base}/api/case-imports/batches/${replay.batch_id}`)).status(), 404)
    assert.deepEqual(await (await context.request.get(`${base}/api/case-imports/templates`)).json(), [])
    assert.equal((await context.request.post(`${base}/api/case-imports/batches/${replay.batch_id}/retry`, {
      data: { rows: [{ row: 6, revision: 0, changes: { longitude: '124' } }] },
    })).status(), 404)
    assert.deepEqual(crashes, [])
    assert.deepEqual(external, [])
    console.log(JSON.stringify({ passed: ['bootstrap', 'dashboard_full_counts', 'responsive_layout', 'map_network_recovery', 'full_search', 'deep_link', 'chinese_import_receipt', 'import_timezone', 'failed_row_correction', 'lost_response_recovery', 'import_template_mapping', 'logout_wait', 'cross_user_isolation'], artifacts: output }))
  } catch (error) {
    await page.screenshot({ path: `${output}/failure.png`, fullPage: true })
    console.log('Failure URL:', page.url(), 'Dialogs:', await page.getByRole('dialog').allTextContents())
    throw error
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
