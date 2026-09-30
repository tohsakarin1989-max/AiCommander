import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MapReadinessPanel, { visibleReadiness } from './MapReadinessPanel'
import type { MapReadiness } from '../../services/facilityAnalysis'

const state = vi.hoisted(() => ({ role: 'admin', error: false, data: undefined as MapReadiness | undefined, keys: [] as unknown[][] }))
vi.mock('../../services/useRegionalContext', () => ({ useRegionalContext: () => ({ user: { id: 1, role: state.role }, sessionEpoch: 2, areaId: 3,
  ready: true, error: undefined, scopes: [{ operational_area_id: 3, area_name: '厂区' }], update: vi.fn() }) }))
vi.mock('@tanstack/react-query', () => ({ useQuery: ({ queryKey }: { queryKey: unknown[] }) => { state.keys.push(queryKey); return { data: state.data, isError: state.error, isPending: false, isFetching: false, refetch: vi.fn() } } }))
const fixture = (): MapReadiness => ({ context: { operational_area_id: 3 }, page: 1, page_size: 10, total: 21, boundary: '资料就绪不是路线结果',
  items: [{ asset_id: 8, name: '测试井', asset_type: 'well', state: 'missing', checks: [{ key: 'entry', label: '可信入口', state: 'missing', detail: '未登记可信入口' }] }] })

describe('管理员地图计算准备清单', () => {
  beforeEach(() => { state.role = 'admin'; state.error = false; state.data = fixture(); state.keys = [] })
  it('分页总数由后端提供，并能打开档案及原维护入口，不新建地图', () => {
    const html = renderToStaticMarkup(<MapReadinessPanel />)
    expect(html).toContain('共 21 个设施'); expect(html).toContain('测试井'); expect(html).toContain('打开设施档案')
    for (const id of ['map-source-management', 'internal-road-management', 'offline-map-management']) expect(html).toContain(`href="#${id}"`)
    expect(html).toContain('下一页'); expect(state.keys[0]).toEqual(['map-readiness', 1, 2, 3, 1])
  })
  it('失败和范围不匹配不暴露旧缓存，不冒充零条或资料就绪', () => {
    state.error = true
    const html = renderToStaticMarkup(<MapReadinessPanel />)
    expect(html).toContain('未展示旧缓存'); expect(html).not.toContain('测试井'); expect(html).not.toContain('共 0')
    expect(visibleReadiness({ data: fixture(), isError: false }, 9, 1)).toBeUndefined()
    expect(visibleReadiness({ data: fixture(), isError: false }, 3, 2)).toBeUndefined()
  })
  it('非管理员不渲染维护清单，也不发起其查询', () => {
    state.role = 'analyst'
    expect(renderToStaticMarkup(<MapReadinessPanel />)).toBe('')
    expect(state.keys).toEqual([])
  })
})
