import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { RoadComparisonView } from './RoadComparisonPanel'
import type { RoadComparison } from '../../services/internalRoads'

describe('道路版本比较', () => {
  it('显示变化与核验影响，不把缺失资料当作删除或通行许可', () => {
    const data: RoadComparison = { source_id: 1, before_id: 2, after_id: 3,
      before_sha256: 'old-hash', after_sha256: 'new-hash',
      summary: { added: 0, changed: 1, unchanged: 0, not_provided: 1 },
      items: [{ source_feature_id: 'road-1', change: 'changed', changed_fields: ['geometry', 'properties.conditions'],
        before: null, after: { type: 'Feature', id: 'road-1', geometry: { type: 'LineString', coordinates: [] },
          properties: { name: '<script>测试</script>', kind: 'road' } }, affects_verified_source: true },
      { source_feature_id: 'road-2', change: 'not_provided', changed_fields: [], before: null, after: null, affects_verified_source: false }] }
    const html = renderToStaticMarkup(<RoadComparisonView data={data} />)
    for (const text of ['本批未提供不代表删除', '涉及已核验资料，请核对', '完整线形/坐标', '通行条件', 'old-hash', 'new-hash'])
      expect(html).toContain(text)
    expect(html).toContain('&lt;script&gt;')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('允许通行')
  })
})
