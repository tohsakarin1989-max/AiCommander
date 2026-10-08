import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CaseEvidenceFiles from './CaseEvidenceFiles'
const state = vi.hoisted(() => ({ failed: false, requested: [] as unknown[][] }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1, role: 'viewer' }, sessionEpoch: 3 }) }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }), useMutation: () => ({ mutate: vi.fn() }),
  useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
    state.requested.push(queryKey)
    return { isError: state.failed, isPending: false, data: queryKey[0] === 'case-file-references'
      ? { references: Array.from({ length: 21 }, (_, i) => ({ kind: 'evidence', id: i + 1 })), next_before_reference: 1 }
      : { locator: { title: `合成原件${queryKey[2]}` }, availability: 'available' } }
  },
}))
describe('佐证列表完整查阅与案件隔离', () => {
  beforeEach(() => { state.failed = false; state.requested = [] })
  it('展示后端本页所有原件并提供后续页，不在客户端静默截掉第21条', () => {
    const html = renderToStaticMarkup(<CaseEvidenceFiles caseId={7} />)
    expect(html).toContain('合成原件21'); expect(html).toContain('佐证原件分页'); expect(html).toContain('下一页')
    expect(state.requested.every(key => key[1] === 7)).toBe(true)
    expect(CaseEvidenceFiles({ caseId: 7 }).key).not.toBe(CaseEvidenceFiles({ caseId: 8 }).key)
  })
  it('列表失败隐藏缓存原件，不把失败解释为空列表', () => {
    state.failed = true
    const html = renderToStaticMarkup(<CaseEvidenceFiles caseId={7} />)
    expect(html).toContain('材料引用列表暂不可读'); expect(html).not.toContain('合成原件'); expect(html).not.toContain('本页无原件引用')
  })
})
