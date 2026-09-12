import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Home from './Home'

const state = vi.hoisted(() => ({ role: 'admin', bonusEnabled: false }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { role: state.role } }) }))
vi.mock('../../config/useRuntimeFeatures', () => ({ useRuntimeFeatures: () => ({ bonusAccountingEnabled: state.bonusEnabled }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('@tanstack/react-query', () => ({
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: ({ queryKey }: { queryKey: string[] }) => ({
    data: queryKey[0] === 'cases' ? Array.from({ length: 7 }, (_, index) => ({
      id: 7 - index, case_number: `RECENT-${7 - index}`, status: 'pending',
      occurred_time: `2026-09-${String(12 - index).padStart(2, '0')}T00:00:00`,
    })) : queryKey[0] === 'home-case-statistics' ? { total_cases: 180, pending_cases: 18, cases_with_geo: 150 }
      : queryKey[0] === 'conclusions' ? [] : { suggestions: [] },
  }),
}))

describe('首页入口与案件顺序', () => {
  beforeEach(() => { state.role = 'admin'; state.bonusEnabled = false })

  it('关闭奖金功能时不显示不可用入口，开启时保留入口', () => {
    expect(renderToStaticMarkup(<Home />)).not.toContain('奖金核算内业')
    state.bonusEnabled = true
    expect(renderToStaticMarkup(<Home />)).toContain('奖金核算内业')
  })

  it('沿用案件接口的最新优先顺序，显示最新五件', () => {
    const html = renderToStaticMarkup(<Home />)
    expect(html).toContain('RECENT-7')
    expect(html).toContain('RECENT-3')
    expect(html).not.toContain('RECENT-1')
    expect(html.indexOf('RECENT-7')).toBeLessThan(html.indexOf('RECENT-6'))
  })

  it('普通角色进入案件研判，不显示管理员专用分析按钮', () => {
    for (const role of ['analyst', 'viewer']) {
      state.role = role
      const html = renderToStaticMarkup(<Home />)
      expect(html).not.toContain('一键智能研判')
      expect(html).toContain('进入案件研判')
    }
  })

  it('案件总数使用统计接口，不把本页条数当全库总数', () => {
    expect(renderToStaticMarkup(<Home />)).toContain('<div class="val">180</div>')
  })
})
