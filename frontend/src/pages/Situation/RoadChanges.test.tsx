import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import RoadChanges from './RoadChanges'

describe('road source changes', () => {
  it('distinguishes incomplete comparison from no change', () => {
    const html = renderToStaticMarkup(<RoadChanges data={{ state: 'unavailable', items: [],
      boundary: '登记变化', information_gaps: ['资料缺失'] }} />)
    expect(html).toContain('不代表道路没有变化')
    expect(html).not.toContain('未发现差异')
  })
  it('renders conditions, review state and evidence without asserting passage', () => {
    const html = renderToStaticMarkup(<RoadChanges data={{ state: 'compared', boundary: '不是通行结论',
      information_gaps: [], items: [{ source_id: 1, feature_id: 'r1', name: '<道路甲>', kind: 'road',
        change: 'updated_source', changed_fields: ['condition_validity', 'source_review'],
        before_import_id: 1, after_import_id: 1,
        previous_conditions: { gate: 'open' }, current_conditions: { gate: 'open' },
        previous_status: { validity: 'within_recorded_interval', review_state: 'verified' },
        current_status: { validity: 'expired', review_state: 'pending_verification' },
        evidence_refs: ['internal_road_import:1', 'internal_road_review:2'] }] }} />)
    expect(html).toContain('已到期')
    expect(html).toContain('待重新核验')
    expect(html).toContain('internal_road_review:2')
    expect(html).toContain('&lt;道路甲&gt;')
    expect(html).not.toContain('确定可达')
  })
})
