import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AreaAnalysis, { regionalViewPath } from './AreaAnalysis'

const state = vi.hoisted(() => ({ search: '', hash: '#history', conditions: 0, time: 0 }))
vi.mock('react-router-dom', () => ({
  useLocation: () => ({ search: state.search, hash: state.hash }),
  Link: ({ to, children, ...props }: { to: string; children: ReactNode }) => <a href={to} {...props}>{children}</a>,
}))
vi.mock('../../components/Facility/RegionalAnalysisView', () => ({ default: () => {
  state.conditions++; return <div>设施条件对照内容</div>
} }))
vi.mock('../Cases/SpaceTimeAnalysis', () => ({ default: ({ embedded }: { embedded: boolean }) => {
  state.time++; return <div>{embedded ? '内嵌时间规律内容' : '独立时间页'}</div>
} }))

describe('区域综合研判的单视图挂载', () => {
  beforeEach(() => { state.search = ''; state.hash = '#history'; state.conditions = 0; state.time = 0 })
  it('默认仅挂载条件对照，不为隐藏时间视图重复请求', () => {
    const html = renderToStaticMarkup(<AreaAnalysis />)
    expect(state.conditions).toBe(1); expect(state.time).toBe(0)
    expect(html).toContain('设施条件对照内容'); expect(html).not.toContain('内嵌时间规律内容')
    expect(html).toContain('区域研判视图')
  })
  it('URL切换后仅挂载时间规律，并保留返回同范围条件视图的链接', () => {
    state.search = '?regional_view=time&operational_area_id=2&assetId=8&statuses=pending&statuses=resolved'
    const html = renderToStaticMarkup(<AreaAnalysis />)
    expect(state.conditions).toBe(0); expect(state.time).toBe(1)
    expect(html).toContain('内嵌时间规律内容'); expect(html).not.toContain('设施条件对照内容')
    expect(html).toContain('regional_view=conditions'); expect(html).toContain('assetId=8')
    expect(html).toContain('statuses=pending&amp;statuses=resolved#history')
  })
  it('切换只替换视图标识，合法条件、重复参数与错误参数交由既有验证处理', () => {
    const search = '?regional_view=time&regional_view=conditions&operational_area_id=2&assetId=8&caseId=6&eventId=9&has_geo=false&case_types=盗油&case_types=盗设施&assetId=11'
    const destination = new URL(regionalViewPath(search, '#evidence', 'conditions'), 'http://localhost')
    expect(destination.pathname).toBe('/area-analysis'); expect(destination.hash).toBe('#evidence')
    expect(destination.searchParams.getAll('regional_view')).toEqual(['conditions'])
    for (const key of new Set(new URLSearchParams(search).keys())) {
      if (key !== 'regional_view') expect(destination.searchParams.getAll(key)).toEqual(new URLSearchParams(search).getAll(key))
    }
  })
})
