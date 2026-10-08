import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CaseDraftLibrary from './CaseDraftLibrary'
import CaseRecentImports from './CaseRecentImports'
import CaseEditConflict from './CaseEditConflict'

const state = vi.hoisted(() => ({ data: {} as unknown, failed: false, epoch: 1, queries: [] as Array<{ queryKey: unknown[]; queryFn: (ctx: { signal: AbortSignal }) => unknown }>,
  choices: {} as Record<string, string>, buttons: {} as Record<string, { disabled?: boolean; onClick: () => void }>,
  list: vi.fn(), batches: vi.fn(), radios: {} as Record<string, (event: { target: { value: string } }) => void>,
}))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(), useState: (initial: unknown) => typeof initial === 'object' && initial !== null
  ? [state.choices, (update: (previous: typeof state.choices) => typeof state.choices) => { state.choices = update(state.choices) }]
  : [initial, vi.fn()] }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 8 }, sessionEpoch: state.epoch }) }))
vi.mock('../../services/caseDrafts', () => ({ caseDraftsApi: { list: state.list } }))
vi.mock('../../services/caseImports', () => ({ caseImportsApi: { batches: state.batches } }))
vi.mock('@tanstack/react-query', () => ({ useQuery: (query: (typeof state.queries)[number]) => {
  state.queries.push(query)
  return { data: state.data, isSuccess: !state.failed, isError: state.failed, refetch: vi.fn() }
} }))
vi.mock('antd', () => ({
  Alert: ({ message, description }: { message: string; description?: string }) => <p>{message}{description}</p>, Pagination: () => null,
  Button: ({ children, disabled, onClick }: { children: ReactNode; disabled?: boolean; onClick: () => void }) => {
    state.buttons[String(children)] = { disabled, onClick }; return <button disabled={disabled}>{children}</button>
  },
  Radio: Object.assign(({ children }: { children: ReactNode }) => <span>{children}</span>, { Group: ({ children, onChange, 'aria-label': label }: { children: ReactNode; onChange: (event: { target: { value: string } }) => void; 'aria-label': string }) => {
    state.radios[label] = onChange; return <div>{children}</div>
  } }),
}))

describe('录入恢复入口与明确冲突比较', () => {
  beforeEach(() => { state.failed = false; state.epoch = 1; state.queries = []; state.buttons = {}; state.choices = {}; state.radios = {}; vi.clearAllMocks() })
  it('草稿按当前账号代次读取，失败不显示缓存中的敏感草稿', async () => {
    state.data = { total: 1, page: 1, page_size: 20, items: [{ id: 'draft', status: 'active', operational_area_id: 1, revision: 2,
      form_snapshot: { values: { description: '合成私有输入' } }, updated_at: '2026-10-01T00:00:00Z', expires_at: '2026-10-08T00:00:00Z' }] }
    expect(renderToStaticMarkup(<CaseDraftLibrary disabled={false} onRestore={vi.fn()} />)).toContain('合成私有输入')
    expect(state.queries[0].queryKey).toEqual(['case-private-drafts', 8, 1, 1])
    const signal = new AbortController().signal; await state.queries[0].queryFn({ signal })
    expect(state.list).toHaveBeenCalledWith(1, signal)
    state.failed = true; state.epoch = 2
    expect(renderToStaticMarkup(<CaseDraftLibrary disabled={false} onRestore={vi.fn()} />)).not.toContain('合成私有输入')
    expect(state.queries[1].queryKey).toEqual(['case-private-drafts', 8, 2, 1])
  })
  it('最近批次缺失总数不显示零，旧无逐行来源不能续做', () => {
    state.data = { total: 1, page: 1, page_size: 20, items: [{ batch_id: 'old-batch', created_at: '2026-10-01T00:00:00Z',
      total: null, success: null, failed: null, duplicate: null, state: 'legacy_receipt', retry_available: false }] }
    const html = renderToStaticMarkup(<CaseRecentImports disabled={false} onOpen={vi.fn()} />)
    expect(html).toContain('总行数 未记录'); expect(html).toContain('未保存逐行来源')
    expect(state.buttons['查看批次回执'].disabled).toBe(true)
    expect(html).not.toContain('重复 0')
  })
  it('我的输入与最新记录都可见，逐项选择完成前不能返回可提交表单', () => {
    const onResolve = vi.fn(), mine = { location: '我的地点', description: '同文' }, latest = { location: '服务器地点', description: '同文' }
    const render = () => renderToStaticMarkup(<CaseEditConflict mine={mine} latest={latest} revision={7} onResolve={onResolve} />)
    const html = render()
    expect(html).toContain('我的地点'); expect(html).toContain('服务器地点')
    expect(state.buttons['采用比较结果，返回表单'].disabled).toBe(true)
    Object.values(state.radios)[0]({ target: { value: 'mine' } }); render()
    expect(state.buttons['采用比较结果，返回表单'].disabled).toBe(false)
    state.buttons['采用比较结果，返回表单'].onClick()
    expect(onResolve).toHaveBeenCalledWith(mine)
  })
})
