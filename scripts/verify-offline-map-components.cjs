/* Public artifacts only. Requires a local Vite server; does not change current maps. */
const assert = require('node:assert/strict')
const { readFileSync, mkdirSync } = require('node:fs')
const { resolve } = require('node:path')
const { createHash } = require('node:crypto')
const { gunzipSync } = require('node:zlib')
const { DatabaseSync } = require('node:sqlite')
const { chromium } = require(process.env.AIC_PLAYWRIGHT_MODULE || 'playwright')
const base = 'http://127.0.0.1:13041'
const id = '11111111-1111-4111-8111-111111111111'
const root = resolve('backups/map-foundation/v4-source/20260908')
const output = process.env.AIC_BROWSER_OUTPUT || '/tmp/aic-v4-vector-browser'
const candidate = process.env.AIC_MAP_CANDIDATE
assert.ok(candidate === undefined || candidate === 'composite-v2', 'unknown public candidate')

function compositeAssets() {
  const directory = `${root}/complete-candidate-v2`
  const raw = readFileSync(`${directory}/transport/manifest.json`)
  const hash = bytes => createHash('sha256').update(bytes).digest('hex')
  assert.equal(hash(raw), 'd4ab1cf9b73f4352b437f81939aed2a86f2afd313fc12185690bb3af772ede48')
  const manifest = JSON.parse(raw)
  const assembly = `${directory}/map-assembly-muyp0orr`
  function asset(name) {
    const index = manifest.assets.findIndex(item => item.name === name)
    assert.ok(index >= 0, 'asset must be present in the pinned candidate')
    const entry = manifest.assets[index]
    const filename = `${assembly}/asset-${String(index).padStart(4, '0')}.bin`
    const bytes = readFileSync(filename)
    assert.equal(bytes.length, entry.size_bytes)
    assert.equal(hash(bytes), entry.sha256)
    return { filename, bytes }
  }
  const style = JSON.parse(asset('style.json').bytes)
  style.glyphs = `/api/maps/${id}/glyphs/{fontstack}/{range}.pbf`
  style.sources.public.tiles = [`/api/maps/tiles/${id}/{z}/{x}/{y}`]
  return { manifest, asset, style, vector: asset('two-city.mbtiles').filename }
}

async function main() {
  mkdirSync(output, { recursive: true })
  const bundle = candidate ? compositeAssets() : null
  const db = new DatabaseSync(bundle?.vector || `${root}/vector-candidate-v1/two-city.mbtiles`, { readOnly: true })
  const tile = db.prepare('SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?')
  const browser = await chromium.launch({ headless: true, channel: 'chrome', args: ['--enable-unsafe-swiftshader'] })
  const context = await browser.newContext({ viewport: { width: 1200, height: 900 } })
  const page = await context.newPage()
  const external = [], crashes = [], requests = [], workers = []
  let style = bundle?.style, failStyle = false
  page.on('pageerror', e => crashes.push(e.stack || e.message))
  await context.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.origin !== base) { external.push(url.href); return route.abort() }
    if (url.pathname.includes('maplibre-gl-worker')) workers.push(url.pathname)
    if (!url.pathname.startsWith('/api/')) return route.continue()
    requests.push(url.pathname)
    if (url.pathname.endsWith('/manifest')) return route.fulfill({ json: {
      schema_version: '2.0', renderer: 'maplibre', snapshot_id: id,
      tile_url: `/api/maps/tiles/${id}/{z}/{x}/{y}`, style_url: `/api/maps/${id}/style.json`,
      min_zoom: 6, max_zoom: 16, display_max_zoom: 19, bounds: bundle?.manifest.bounds || [122, 45.2, 127, 49.1],
    } })
    if (url.pathname.endsWith('/style.json')) return failStyle
      ? route.fulfill({ status: 503, body: 'fixture failure' }) : route.fulfill({ json: style })
    const match = url.pathname.match(/\/tiles\/[^/]+\/(\d+)\/(\d+)\/(\d+)$/)
    if (match) {
      const [z, x, y] = match.slice(1).map(Number)
      const row = tile.get(z, x, 2 ** z - 1 - y)
      // Empty PBF outside coverage is test-only; not a production availability claim.
      return route.fulfill({ contentType: 'application/x-protobuf',
        body: row ? gunzipSync(Buffer.from(row.tile_data)) : Buffer.alloc(0) })
    }
    const glyph = url.pathname.match(/\/glyphs\/([^/]+)\/(\d+-\d+)\.pbf$/)
    if (glyph) {
      if (bundle) assert.equal(decodeURIComponent(glyph[1]),
        'Noto Sans CJK SC Regular,Noto Sans Mongolian Regular,Noto Emoji Regular')
      return route.fulfill({ contentType: 'application/x-protobuf',
        body: bundle ? bundle.asset(`glyphs-${glyph[2]}.pbf`).bytes
          : readFileSync(`${root}/glyphs-cjk-v1/Noto Sans CJK SC Regular/${glyph[2]}.pbf`) })
    }
    return route.fulfill({ status: 404, body: 'fixture route absent' })
  })
  try {
    await page.goto(`${base}/tests/fixtures/offline-map.html`)
    await page.waitForLoadState('networkidle')
    if (!bundle) style = await page.evaluate(() => window.fixtureStyle)
    for (const view of ['cases', 'picker', 'heat', 'assets']) {
      await page.getByRole('button', { name: view, exact: true }).click()
      await page.locator('.maplibregl-canvas').waitFor()
      await page.waitForFunction(() => !document.body.textContent.includes('正在加载'))
      assert.equal(await page.getByRole('button', { name: '重试当前地图' }).count(), 0)
      assert.ok(await page.locator('.maplibregl-canvas').evaluate(c => c.width > 0 && c.height > 0))
      const mapBox = await page.locator('.leaflet-container').boundingBox()
      const canvasBox = await page.locator('.maplibregl-canvas').boundingBox()
      assert.ok(canvasBox.width >= mapBox.width * 0.9 && canvasBox.height >= mapBox.height * 0.9,
        'vector canvas must cover the map, not remain a miniature after zoom')
      await page.screenshot({ path: `${output}/${view}.png` })
      if (view === 'picker') {
        await page.locator('.leaflet-container').click({ position: { x: 550, y: 325 } })
        assert.notEqual(await page.getByTestId('selection').innerText(), '尚未选点')
      }
      await page.getByRole('button', { name: 'none', exact: true }).click()
      assert.equal(await page.locator('.maplibregl-canvas').count(), 0)
    }
    failStyle = true
    await page.getByRole('button', { name: 'picker', exact: true }).click()
    await page.getByRole('button', { name: '重试当前地图' }).waitFor()
    assert.equal(await page.locator('[aria-disabled="true"]').count(), 1)
    const manifests = requests.filter(path => path.endsWith('/manifest')).length
    failStyle = false
    await page.getByRole('button', { name: '重试当前地图' }).click()
    await page.getByText('点击地图选点，或拖动标记调整位置').waitFor()
    assert.equal(requests.filter(path => path.endsWith('/manifest')).length, manifests)
    await page.getByRole('button', { name: 'none', exact: true }).click()
    // Inject missing WebGL at the browser API boundary, exercising the real constructor.
    await page.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext
      HTMLCanvasElement.prototype.getContext = function (kind, ...args) {
        if (String(kind).includes('webgl')) return null
        return original.call(this, kind, ...args)
      }
    })
    await page.reload()
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: 'cases', exact: true }).click()
    await page.getByRole('button', { name: '重试当前地图' }).waitFor()
    assert.equal(await page.locator('.maplibregl-canvas').count(), 0)
    await page.getByRole('button', { name: 'Zoom in' }).click()
    const box = await page.locator('.leaflet-container').boundingBox()
    await page.mouse.move(box.x + 300, box.y + 300)
    await page.mouse.down(); await page.mouse.move(box.x + 350, box.y + 340); await page.mouse.up()
    await page.getByRole('button', { name: 'none', exact: true }).click()
    assert.ok(requests.some(path => path.includes('/glyphs/')))
    assert.ok(requests.some(path => path.includes('/tiles/')))
    assert.ok(workers.length > 0, 'must load the locally bundled rendering worker')
    assert.deepEqual(external, [])
    assert.deepEqual(crashes, [])
    console.log(JSON.stringify({ result: 'passed', candidate: candidate || 'legacy',
      backendPublicationVerified: false, components: 4, explicitRetry: true, missingWebGLCleanup: true,
      tileRequests: requests.filter(p => p.includes('/tiles/')).length,
      glyphRequests: requests.filter(p => p.includes('/glyphs/')).length,
      externalRequests: external.length, workers, screenshots: output }))
  } finally { await browser.close(); db.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
