import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Reports from './Reports'
import type { ResultMaterial } from '../../services/results'
vi.mock('../../components/CaseResult/CaseResultMap', () => ({ default: () => <p>同版案件地图</p> }))

const state = vi.hoisted(() => ({ params: '', role: 'analyst', listError: false, readError: false,
  requested: [] as Array<{ queryKey: unknown[]; enabled?: boolean }>, data: undefined as ResultMaterial | undefined }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 4, role: state.role }, sessionEpoch: 2 }) }))
vi.mock('react-router-dom', () => ({
  useSearchParams: () => [new URLSearchParams(state.params), vi.fn()],
  Link: ({ to, children }: { to: string; children: React.ReactNode }) => <a href={to}>{children}</a>,
}))
vi.mock('@tanstack/react-query', () => ({
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: (options: typeof state.requested[number]) => {
    state.requested.push(options)
    const key = options.queryKey[0]
    return { data: key === 'material-catalog' ? { items: state.data ? [state.data] : [], has_more: false }
      : key === 'material-reader' ? state.data : undefined,
    error: key === 'material-catalog' && state.listError || key === 'material-reader' && state.readError ? new Error('unavailable') : null,
    isPending: false, isFetching: false, refetch: vi.fn() }
  },
}))
export const materialFixture = (): ResultMaterial => ({ kind: 'meeting', id: '9', title: '合成会议材料', content_sha256: 'a'.repeat(64),
  schema_version: 'meeting-material-6.5-1', subject: { kind: 'meeting', id: 'history-meeting' }, created_at: '2026-09-30', availability: 'available',
  body: {}, sources: [], boundary: ['讨论参考不是案件事实'], judgments: [],
  document: { schema_version: 'business-result-document-6.5-1', blocks: [
    { kind: 'paragraph', text: '原文未发现车辆，未知不等于零', rows: [] }, { kind: 'table', text: '确定性统计', rows: [['已登记', '0']] },
  ] } })
describe('统一材料入口与历史边界', () => {
  beforeEach(() => { state.params = ''; state.role = 'analyst'; state.listError = false; state.readError = false; state.requested = []; state.data = materialFixture() })
  it('旧会议深链接直接限定会议来源，不依赖默认列表包含该会议', () => {
    state.params = 'meetingId=history-meeting'
    const html = renderToStaticMarkup(<Reports />)
    expect(state.requested[0].queryKey).toContain('history-meeting')
    expect(state.requested[0].queryKey).toContain('meeting')
    expect(html).toContain('当前限定来源')
    expect(html).toContain('kind=meeting&amp;resultId=9')
  })
  it('目录失败隐藏缓存，不冒充空结果或零总数', () => {
    state.listError = true
    const html = renderToStaticMarkup(<Reports />)
    expect(html).toContain('目录暂不可读'); expect(html).not.toContain('合成会议材料')
    expect(html).not.toContain('当前范围尚无可读材料')
  })
  it('正文失败隐藏缓存的原文、地图与人工判断', () => {
    state.params = 'kind=meeting&resultId=9'; state.readError = true
    const html = renderToStaticMarkup(<Reports />)
    expect(html).toContain('已隐藏旧正文与地图'); expect(html).not.toContain('原文未发现车辆')
    expect(html).not.toContain('按需记录判断')
  })
  it('只读账号能读固定材料但没有审稿和记录判断按钮', () => {
    state.params = 'kind=meeting&resultId=9'; state.role = 'viewer'
    const html = renderToStaticMarkup(<Reports />)
    expect(html).toContain('原文未发现车辆'); expect(html).toContain('导出本版 Word')
    expect(html).not.toContain('检查本报告表达'); expect(html).not.toContain('按需记录判断')
  })
  it('保留可选会议审稿和版本判断，不重新生成案件结论', () => {
    state.params = 'kind=meeting&resultId=9'
    const html = renderToStaticMarkup(<Reports />)
    expect(html).toContain('检查本报告表达'); expect(html).toContain('按需记录判断')
    expect(html).toContain('不是必经流程'); expect(html).not.toContain('生成结论')
    expect(html).toContain('<td>0</td>'); expect(html).not.toContain('0%')
  })
  it('正文转义不可信文本，无效类型不发起读取', () => {
    state.data!.document.blocks[0].text = '<img src=x onerror=alert(1)>'
    state.params = 'kind=meeting&resultId=9'
    expect(renderToStaticMarkup(<Reports />)).toContain('&lt;img')
    state.params = 'kind=__proto__&resultId=9'; state.requested = []
    expect(renderToStaticMarkup(<Reports />)).toContain('材料类型或编号无效')
    expect(state.requested.find(item => item.queryKey[0] === 'material-reader')?.enabled).toBe(false)
  })
  it('历史结论以typed reader显示原判断，不再调用旧结论工厂', () => {
    state.data = { ...materialFixture(), kind: 'conclusion', title: '历史结论', judgments: [{ id: 'human-1', decision: 'retain_reference', note: '只对本版保留参考', created_by: 1, created_at: '2026-09-30', content_sha256: 'a'.repeat(64), additional_sources: [] }] }
    state.params = 'kind=conclusion&resultId=9'
    const html = renderToStaticMarkup(<Reports />)
    expect(html).toContain('只对本版保留参考'); expect(html).toContain('不自动变成案件事实')
    expect(state.requested.every(item => !String(item.queryKey[0]).includes('conclusion'))).toBe(true)
  })
})
