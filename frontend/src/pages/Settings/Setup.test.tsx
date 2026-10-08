import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Setup, { setupDestination } from './Setup'

type QueryState = { data?: unknown; isPending: boolean; isError: boolean; refetch: () => void }
const state = vi.hoisted(() => ({
  queries: {} as Record<string, QueryState>, selected: undefined as number | undefined,
  useStateIndex: 0, requests: [] as Array<{ queryKey: unknown[]; enabled?: boolean }>,
}))
vi.mock('react', async importOriginal => {
  const react = await importOriginal<typeof import('react')>()
  return { ...react, useState: (initial: unknown) => {
    const index = state.useStateIndex++
    return [index === 0 ? state.selected : initial, vi.fn()]
  } }
})
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1, role: 'admin' }, sessionEpoch: 8 }) }))
vi.mock('../../services/mapFoundation', () => ({ mapFoundationApi: { listAreas: vi.fn(), listSources: vi.fn(), listSnapshots: vi.fn() } }))
vi.mock('react-router-dom', () => ({ Link: ({ to, children }: { to: string; children: ReactNode }) => <a href={to}>{children}</a> }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: (options: { queryKey: unknown[]; enabled?: boolean }) => { state.requests.push(options); return state.queries[String(options.queryKey[0])] },
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
}))
vi.mock('antd', () => {
  const Wrapper = ({ children }: { children?: ReactNode }) => <div>{children}</div>
  return {
    Alert: ({ message, description }: { message: ReactNode; description?: ReactNode }) => <aside>{message}{description}</aside>,
    Button: ({ children }: { children: ReactNode }) => <button>{children}</button>,
    Form: Object.assign(Wrapper, { useForm: () => [{ resetFields: vi.fn(), setFieldsValue: vi.fn() }], Item: Wrapper }),
    Input: () => <input />, Select: () => <select />, Space: Wrapper, Tag: Wrapper,
    Table: ({ dataSource }: { dataSource: Array<{ id: number; name: string }> }) => <div>{dataSource.map(row => <p key={row.id}>{row.name}</p>)}</div>,
    Modal: () => null, message: { success: vi.fn(), error: vi.fn() },
  }
})
const render = () => { state.useStateIndex = 0; return renderToStaticMarkup(<Setup />) }

describe('首次启用读取实际配置并贯通所选厂区', () => {
  beforeEach(() => {
    state.selected = undefined; state.useStateIndex = 0; state.requests = []
    const ready = (data: unknown): QueryState => ({ data, isError: false, isPending: false, refetch: vi.fn() })
    state.queries = {
      'setup-areas': ready([{ id: 1, name: '默认厂区', is_default: true, status: 'active' }, { id: 2, name: '第二厂区', is_default: false, status: 'active' }]),
      'setup-sources': ready([{ name: '一厂台账', operational_area: { id: 1 } }, { name: '二厂台账', operational_area: { id: 2 } }]),
      'setup-snapshots': ready([{ version: '合成地图版本', status: 'current' }]),
    }
  })

  it('选择非默认厂区后，三个业务跳转与地图读取都保留该厂区', () => {
    state.selected = 2
    const html = render()
    expect(html).toContain('href="/jurisdiction?operational_area_id=2#offline-map-management"')
    expect(html).toContain('href="/jurisdiction?operational_area_id=2#map-source-management"')
    expect(html).toContain('href="/cases/map?operational_area_id=2"')
    expect(html).toContain('已登记来源：二厂台账'); expect(html).not.toContain('一厂台账')
    const snapshotKey = state.requests.find(row => row.queryKey[0] === 'setup-snapshots')!.queryKey
    expect(snapshotKey[snapshotKey.length - 1]).toBe(2)
  })

  it('地图或来源读取失败时不展示缓存版本，也不报告为空', () => {
    state.queries['setup-snapshots'].isError = true
    state.queries['setup-sources'].isError = true
    const html = render()
    expect(html).toContain('地图版本读取失败，不能确认是否可用')
    expect(html).toContain('台账来源读取失败，不能当成没有资料')
    expect(html).not.toContain('合成地图版本'); expect(html).not.toContain('一厂台账')
    expect(html).not.toContain('尚无已发布地图'); expect(html).not.toContain('尚未登记台账来源')
  })

  it('厂区读取失败不沿用旧缓存选区，也不请求全范围地图', () => {
    state.selected = 2; state.queries['setup-areas'].isError = true
    const html = render()
    expect(html).toContain('厂区读取失败')
    expect(html).not.toContain('第二厂区')
    expect(html).not.toContain('operational_area_id=2')
    expect(state.requests.find(row => row.queryKey[0] === 'setup-snapshots')?.enabled).toBe(false)
  })

  it('空库不捏造地图状态，默认厂区链接保留锚点', () => {
    state.queries['setup-areas'].data = []
    const html = render()
    expect(html).toContain('暂无可检查的厂区')
    expect(html).not.toContain('当前地图：')
    expect(setupDestination('/jurisdiction', 2, '#map-source-management')).toBe('/jurisdiction?operational_area_id=2#map-source-management')
    expect(setupDestination('/cases/map')).toBe('/cases/map')
  })
})
