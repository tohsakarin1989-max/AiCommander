import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FacilitySearch from './Facility/FacilitySearch'
import CaseSearch from './CaseSearch'

type Query = { queryKey: unknown[]; enabled: boolean; gcTime: number; queryFn: (context: { signal: AbortSignal }) => unknown }
const state = vi.hoisted(() => ({ cursor: 0, hooks: [] as unknown[], failed: false, fetching: false, epoch: 2,
  queries: [] as Query[], buttons: {} as Record<string, { disabled?: boolean; onClick: () => void }>,
  search: null as null | { onSearch: (value: string) => void }, assets: vi.fn(), cases: vi.fn(), choose: vi.fn(),
}))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(), useState: (initial: unknown) => {
  const index = state.cursor++; if (!(index in state.hooks)) state.hooks[index] = initial
  return [state.hooks[index], (value: unknown) => { state.hooks[index] = typeof value === 'function' ? value(state.hooks[index]) : value }]
} }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 7 }, sessionEpoch: state.epoch }) }))
vi.mock('../services/jurisdiction', () => ({ jurisdictionApi: { listAssets: state.assets } }))
vi.mock('../services/cases', () => ({ caseApi: { getCasePage: state.cases } }))
vi.mock('@tanstack/react-query', () => ({ useQuery: (query: Query) => {
  state.queries.push(query)
  const assets = Array.from({ length: 21 }, (_, index) => ({ id: 100 + index, name: `当前井场${index}`, asset_type: 'well', search_match: { kind: 'historical_name', value: '旧登记名称' } }))
  return { isError: state.failed, isFetching: state.fetching, refetch: vi.fn(), data: query.queryKey[0] === 'facility-search' ? assets : {
    items: [{ id: 2401, case_number: '历史案2401', location: '合成地点' }], total: 31, page_size: 10,
  } }
} }))
vi.mock('antd', () => ({
  Input: { Search: (props: { onSearch: (value: string) => void }) => { state.search = props; return <input /> } },
  Alert: ({ message }: { message: string }) => <div role="alert">{message}</div>,
  Space: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Button: (props: { children: ReactNode; disabled?: boolean; onClick: () => void }) => { state.buttons[String(props.children)] = props; return <button disabled={props.disabled}>{props.children}</button> },
}))
function render(kind: 'facility' | 'case') {
  state.cursor = 0; state.queries = []; state.buttons = {}
  return renderToStaticMarkup(kind === 'facility' ? <FacilitySearch areaId={3} onChoose={state.choose} /> : <CaseSearch areaId={3} onChoose={state.choose} />)
}
describe('完整目录查找控件（受控事件及查询契约）', () => {
  beforeEach(() => { state.cursor = 0; state.hooks = []; state.failed = false; state.fetching = false; state.epoch = 2; vi.clearAllMocks() })
  it('设施先全文检索再分页，显示旧名线索；新关键词回到第一页', async () => {
    render('facility'); expect(state.queries[0].enabled).toBe(false)
    state.search!.onSearch(' 旧井名 '); let html = render('facility')
    expect(html).toContain('历史名称匹配（不是当前名称）'); expect(html).toContain('当前井场0')
    state.buttons['下一页设施'].onClick(); render('facility')
    const signal = new AbortController().signal
    await state.queries[0].queryFn({ signal })
    expect(state.assets).toHaveBeenCalledWith({ keyword: '旧井名', operational_area_id: 3, status: 'active', skip: 20, limit: 21 }, signal)
    state.search!.onSearch('其他井场'); render('facility'); expect(state.queries[0].queryKey[5]).toBe(0)
    state.failed = true; html = render('facility')
    expect(html).toContain('查询失败'); expect(html).not.toContain('当前井场0'); expect(html).not.toContain('选择此设施')
  })
  it('案件使用总数分页并携带授权代次与取消信号，不依赖最近50案', async () => {
    render('case'); state.search!.onSearch('历史案'); render('case')
    state.buttons['下一页案件'].onClick(); const html = render('case')
    expect(html).toContain('共 31 案'); expect(html).toContain('历史案2401')
    const query = state.queries[0], signal = new AbortController().signal
    expect(query.queryKey).toEqual(['case-search-picker', 7, 2, 3, '历史案', 2]); expect(query.gcTime).toBe(0)
    await query.queryFn({ signal }); expect(state.cases).toHaveBeenCalledWith({ keyword: '历史案', page: 2, page_size: 10, operational_area_id: 3 }, signal)
    state.buttons['选择此案'].onClick(); expect(state.choose.mock.calls[0][0].id).toBe(2401)
    state.failed = true; expect(render('case')).not.toContain('历史案2401')
    state.epoch++; render('case'); expect(state.queries[0].queryKey[2]).toBe(3)
  })
})
