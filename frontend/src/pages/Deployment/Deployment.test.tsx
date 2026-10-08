import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Deployment from './Deployment'

const state = vi.hoisted(() => ({ keys: [] as unknown[][] }))
vi.mock('react-router-dom', () => ({ Link: ({ to, children }: { to: string; children: ReactNode }) => <a href={to}>{children}</a> }))
vi.mock('antd', () => ({ Table: () => <div>原统计表</div>, Tabs: ({ items }: { items: { key: string; label: ReactNode; children: ReactNode }[] }) => <div>{items.map(item => <section key={item.key}>{item.label}{item.children}</section>)}</div> }))
vi.mock('@tanstack/react-query', () => ({ useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
  state.keys.push(queryKey)
  const data = queryKey[0] === 'deploymentReport' ? { summary: { key_findings: ['来自原服务的发现'], priority_actions: ['保留原服务建议'] },
    modules: { hotspots: { cluster_count: 0 }, gangs: { gang_count: 3 } } }
    : queryKey[0] === 'patrolRoutes' ? { routes: [{ route_name: '原中心点', center_latitude: 46.6, center_longitude: 125.1,
      coverage_radius_km: 4, case_count: 12, priority: '高', recommended_patrol_times: ['凌晨'], suggestions: [] }] }
      : queryKey[0] === 'temporalPatterns' ? { high_risk_hours: [], high_risk_weekdays: [] } : undefined
  return { data, refetch: vi.fn(), isFetching: false }
} }))

describe('旧部署页保留独有查询且明确结果边界', () => {
  beforeEach(() => { state.keys = [] })
  it('保留六类原查询与报告统计，候选条件组不冒充已确认团伙', () => {
    const html = renderToStaticMarkup(<Deployment />)
    expect(state.keys.map(key => key[0])).toEqual(['deploymentReport', 'temporalPatterns', 'targetPatterns', 'patrolRoutes', 'resourceAllocation', 'preventionMeasures'])
    expect(html).toContain('来自原服务的发现'); expect(html).toContain('保留原服务建议'); expect(html).toContain('原统计表')
    expect(html).toContain('候选条件组'); expect(html).toContain('3</b> 组'); expect(html).toContain('0</b> 处')
    expect(html).not.toContain('识别团伙'); expect(html).not.toContain('0.82'); expect(html).not.toContain('79%'); expect(html).not.toContain('15%'); expect(html).not.toContain('6%')
  })
  it('明确旧窗口和空间示意边界，旧报告出口指向当前态势和统一目录', () => {
    const html = renderToStaticMarkup(<Deployment />)
    expect(html).toContain('旧口径 · 评分未校准'); expect(html).toContain('圆和连线并非真实路由或实际覆盖')
    expect(html).toContain('不代表真实道路、导航路线、可达性或实际覆盖')
    expect(html).toContain('href="/situation"'); expect(html).toContain('href="/reports"'); expect(html).not.toContain('导出报告</button>')
    expect(html).toContain('原中心点'); expect(html).toContain('参考半径')
  })
})
