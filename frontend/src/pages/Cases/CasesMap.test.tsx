import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CasesMap from './CasesMap'

type Query = { queryKey: unknown[]; enabled?: boolean; queryFn: (context: { signal: AbortSignal }) => unknown }
const state = vi.hoisted(() => ({
  search: '?caseId=2401', epoch: 1, failed: false, listFailed: false,
  queries: [] as Query[], map: {} as Record<string, unknown>,
  getCase: vi.fn(), getCases: vi.fn(), navigate: vi.fn(),
}))

// Query and rendering contracts only: SSR does not execute area-selection effects.
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 9, role: 'analyst' }, sessionEpoch: state.epoch }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => state.navigate, useSearchParams: () => [new URLSearchParams(state.search), vi.fn()] }))
vi.mock('../../services/cases', () => ({ caseApi: {
  getCase: state.getCase, getCases: state.getCases, getHotspots: vi.fn(), getSerialCases: vi.fn(), getChainMapData: vi.fn(),
} }))
vi.mock('../../services/auth', () => ({ authApi: { myAreaScopes: vi.fn() } }))
vi.mock('../../components/Map/LeafletMap', () => ({ default: (props: Record<string, unknown>) => {
  state.map = props
  return <div data-testid="map-boundary" />
} }))
vi.mock('@ant-design/icons', () => ({ FireOutlined: () => null, LinkOutlined: () => null, FieldTimeOutlined: () => null,
  EnvironmentOutlined: () => null, AppstoreOutlined: () => null }))
vi.mock('antd', () => ({
  Alert: ({ message }: { message: ReactNode }) => <div>{message}</div>,
  Button: ({ children }: { children: ReactNode }) => <button>{children}</button>,
  Select: () => null, Spin: () => null, Switch: () => null,
  List: Object.assign(() => null, { Item: ({ children }: { children: ReactNode }) => <div>{children}</div> }),
}))
vi.mock('@tanstack/react-query', () => ({ useQuery: (query: Query) => {
  state.queries.push(query)
  const [name, kind] = query.queryKey
  const focusId = Number(new URLSearchParams(state.search).get('caseId'))
  const focus = { id: focusId, case_number: `独立指定案件-${focusId}`, operational_area_id: focusId === 2402 ? 1 : 2,
    latitude: 46.6, longitude: 125.1, occurred_time: '2026-09-01', facility_type: '管线' }
  const isDetail = name === 'cases' && kind === 'detail'
  const isMap = name === 'cases' && kind === 'map'
  const failed = (isDetail && state.failed) || (isMap && state.listFailed)
  const data = isDetail ? focus : isMap ? [{ id: 1, case_number: '区域普通案件', operational_area_id: query.queryKey[2],
    latitude: 46.5, longitude: 125 }] : name === 'my-area-scopes'
    ? [{ operational_area_id: 1, operational_area_name: '默认厂区', is_default: true },
      { operational_area_id: 2, operational_area_name: '指定案厂区' }]
    : name === 'chain-map-data' ? { links: [] } : []
  return { data, isLoading: false, isFetching: false, isSuccess: !failed, isError: failed }
} }))

const renderPage = () => { state.queries = []; return renderToStaticMarkup(<CasesMap />) }

describe('案件地图接续（组件契约，非 DOM）', () => {
  beforeEach(() => {
    state.search = '?caseId=2401'; state.epoch = 1; state.failed = false; state.listFailed = false
    state.map = {}; vi.clearAllMocks()
  })
  it('深链超出区域列表限制时仍独立请求精确案件，且传递取消信号', async () => {
    renderPage()
    const exact = state.queries.find(query => query.queryKey[1] === 'detail')!
    expect(exact.enabled).toBe(true)
    expect(exact.queryKey).toEqual(['cases', 'detail', 9, 1, 2401])
    const signal = new AbortController().signal
    await exact.queryFn({ signal })
    expect(state.getCase).toHaveBeenCalledWith(2401, signal)
    expect(state.getCases).not.toHaveBeenCalled()
    expect(state.queries.find(query => query.queryKey[1] === 'map')?.enabled).toBe(false)
  })
  it('新的 URL 快照请求新案件，并按当前用户和授权代次隔离查询', async () => {
    renderPage()
    state.search = '?caseId=2402'; state.epoch++
    renderPage()
    const exact = state.queries.find(query => query.queryKey[1] === 'detail')!
    expect(exact.queryKey).toEqual(['cases', 'detail', 9, 2, 2402])
    const signal = new AbortController().signal
    await exact.queryFn({ signal })
    expect(state.getCase).toHaveBeenLastCalledWith(2402, signal)
  })
  it('精确读取撤权失败即使保留旧缓存，也不将缓存或其他案当作指定案件', () => {
    renderPage()
    state.failed = true; state.listFailed = true; state.epoch++
    const html = renderPage()
    expect(html).toContain('指定案件不存在、参数无效或当前不可访问')
    expect(html).not.toContain('独立指定案件-2401')
    expect(html).not.toContain('选中案件')
    expect(state.map.center).toBeUndefined()
    expect(state.map.markers).toEqual([])
    expect(state.queries.find(query => query.queryKey[0] === 'chain-map-data')?.enabled).toBe(false)
  })
  it('无效深链不发起精确案件请求，也不默认选中列表第一案', () => {
    state.search = '?caseId=1bad'
    const html = renderPage()
    expect(state.queries.find(query => query.queryKey[1] === 'detail')?.enabled).toBe(false)
    expect(html).toContain('未替换为其他案件')
    expect(html).not.toContain('选中案件')
  })
})
