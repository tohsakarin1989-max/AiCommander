import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DataIssueForm } from './FacilityDataIssues'

const state = vi.hoisted(() => ({ failed: false, create: vi.fn(), reset: vi.fn(), refetch: vi.fn(),
  finish: undefined as undefined | ((values: { reference: string; field_group: 'production'; notes: string }) => Promise<void>),
  query: {} as { queryKey: unknown[]; enabled: boolean },
}))
vi.mock('../../services/mapDataIssues', () => ({ mapDataIssuesApi: { create: state.create, list: vi.fn() } }))
vi.mock('@tanstack/react-query', () => ({ useQuery: (query: typeof state.query) => {
  state.query = query
  return { isError: state.failed, isPending: false, refetch: state.refetch,
    data: { items: [{ id: 1, notes: '旧缓存敏感标注', source_reference: { field_group: 'production' } }], total: 1 } }
} }))
vi.mock('antd', () => ({
  Form: Object.assign(({ children, onFinish }: { children: ReactNode; onFinish: typeof state.finish }) => {
    state.finish = onFinish; return <form>{children}</form>
  }, { useForm: () => [{ resetFields: state.reset }], Item: ({ children, label }: { children: ReactNode; label: string }) => <label>{label}{children}</label> }),
  Input: { TextArea: () => <textarea /> }, Select: () => <select />,
  Alert: ({ message }: { message: string }) => <p>{message}</p>, Pagination: () => null,
  Button: ({ children }: { children: ReactNode }) => <button>{children}</button>,
}))

const production = { state: 'ready' as const, items: [{ id: 'claim:9', label: '台账来源', row_number: 2, source_revision: 'v2' }] }
function render() { return renderToStaticMarkup(<DataIssueForm assetId={7} production={production} userId={3} sessionEpoch={5} />) }

describe('来源问题标注不变成设施修改流程', () => {
  beforeEach(() => { vi.clearAllMocks(); state.failed = false; state.create.mockResolvedValue({ id: 1 }) })
  it('默认不加载折叠内容，缓存按账号代次隔离，读取失败不展示旧标注', () => {
    render()
    expect(state.query.queryKey).toEqual(['map-data-issues', 3, 5, 7, 1])
    expect(state.query.enabled).toBe(false)
    state.failed = true
    const html = render()
    expect(html).toContain('暂不可读'); expect(html).not.toContain('旧缓存敏感标注')
  })
  it('失败保留说明，不清空输入；成功只清说明、不改写设施字段', async () => {
    render()
    state.create.mockRejectedValueOnce(new Error('offline'))
    await state.finish!({ reference: 'claim:9', field_group: 'production', notes: '核对单位' })
    expect(state.reset).not.toHaveBeenCalled()
    expect(state.create).toHaveBeenCalledWith(7, '核对单位', { field_group: 'production', source_claim_id: 9 })
    await state.finish!({ reference: 'claim:9', field_group: 'production', notes: '核对单位' })
    expect(state.reset).toHaveBeenCalledWith(['notes'])
  })
  it('来源已变时不提交，缺来源不能编造', async () => {
    render()
    await state.finish!({ reference: 'claim:999', field_group: 'production', notes: '保留' })
    expect(state.create).not.toHaveBeenCalled()
    const html = renderToStaticMarkup(<DataIssueForm assetId={7} production={{ state: 'empty', items: [] }} userId={3} sessionEpoch={5} />)
    expect(html).toContain('不能补造来源'); expect(html).not.toContain('保存问题标注')
  })
})
