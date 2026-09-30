import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import FacilityCaseLinkForm, { materialReferenceOptions } from './FacilityCaseLinkForm'
import type { CaseSources } from '../../types'

const state = vi.hoisted(() => ({ queries: [] as Array<{ enabled: boolean; queryKey: unknown[] }>, writes: vi.fn() }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 3, role: 'analyst' }, sessionEpoch: 4 }) }))
vi.mock('antd', () => ({ Popconfirm: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: (options: { enabled: boolean; queryKey: unknown[] }) => { state.queries.push(options); return { data: undefined, isError: false, isFetching: false } },
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, isError: false, isSuccess: false, mutate: state.writes, reset: vi.fn() }),
}))

describe('设施人工材料关联', () => {
  beforeEach(() => { state.queries = []; state.writes.mockReset() })
  it('只选当前修订的原文和证据，不把旧案情片段或未知引用种类当当前材料', () => {
    const sources: CaseSources = { case_id: 1, current_revision_id: 9, revisions: [], references: [
      { id: 1, kind: 'text', source_revision_id: 9, locator: { field: 'description' } },
      { id: 2, kind: 'text', source_revision_id: 8, locator: { title: '过期原文' } },
      { id: 3, kind: 'evidence', locator: { title: '现场记录' } },
      { id: 4, kind: 'inference' }, { id: '5', kind: 'evidence' },
    ] }
    expect(materialReferenceOptions(sources)).toEqual([{ id: 1, label: '原文引用（案情原文） · 引用 1' }, { id: 3, label: '现场记录 · 引用 3' }])
    expect(materialReferenceOptions()).toEqual([])
  })
  it('日常读取折叠表单不自动查案或写入，仅继承明确案件编号作为待核输入', () => {
    const html = renderToStaticMarkup(<FacilityCaseLinkForm assetId={7} initialCaseId={8} />)
    expect(html).toContain('按材料登记明确关联（按需）'); expect(html).toContain('核对案件与材料'); expect(html).toContain('value="8"')
    expect(html).toContain('不认定实际盗取来源'); expect(html).toContain('disabled=""')
    expect(state.queries.every(item => !item.enabled)).toBe(true)
    expect(state.queries[0].queryKey).toEqual(['facility-case-link-source', 3, 4, 7, null])
    expect(state.writes).not.toHaveBeenCalled()
  })
})
