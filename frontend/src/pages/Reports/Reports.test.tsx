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
  presentation: { template: 'full', label: '完整资料', schema_version: 'material-presentation-7.4-1', options: [{ id: 'full', label: '完整资料' }], boundary: '通用整理格式，不是单位正式样表' },
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
  it('打开材料和来源返回链接保留目录条件与页码', () => {
    state.params = 'kind=meeting&resultId=9&subject=case&subjectId=42&catalogQ=管线&catalogKind=meeting&catalogOffset=40&fromKind=topic&fromId=original'
    state.data!.sources = [{ kind: 'case', id: 'source-result', content_sha256: 'b'.repeat(64) }]
    const html = renderToStaticMarkup(<Reports />)
    expect(state.requested[0].queryKey).toContain('管线'); expect(state.requested[0].queryKey).toContain(40)
    expect(html).toContain('返回原目录条件'); expect(html).toContain('返回引用此资料的材料'); expect(html).toContain('第 3 页')
    expect(html).toContain('catalogOffset=40'); expect(html).toContain('fromKind=meeting&amp;fromId=9')
    expect(html).toContain('kind=topic&amp;resultId=original&amp;subject=case')
  })
  it('从全局导航带入caseId时限定本案材料并保留案件筛选回跳', () => {
    state.params = 'caseId=42&case_view=materials&keyword=管线&statuses=pending&statuses=processing'
    const html = renderToStaticMarkup(<Reports />)
    expect(state.requested[0].queryKey.slice(-2)).toEqual(['case', '42'])
    expect(html).toContain('当前限定来源：案件 #42')
    expect(html).toContain('返回来源案件'); expect(html).toContain('statuses=pending&amp;statuses=processing')
    expect(html).toContain('kind=meeting&amp;resultId=9&amp;keyword=')
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
  it.each(['bogus', '__proto__', '', 'case_summary', 'full&template=case_summary'])('无效或不适用格式 %s 拒绝显示已有缓存', template => {
    state.params = `kind=meeting&resultId=9&template=${template}`
    const html = renderToStaticMarkup(<Reports />)
    expect(html).toContain('材料格式无效或不适用于此类材料')
    expect(html).not.toContain('原文未发现车辆'); expect(html).not.toContain('导出本版 Word')
    expect(state.requested.find(item => item.queryKey[0] === 'material-reader')?.enabled).toBe(false)
  })
  it('格式和预期内容版本进入独立缓存，错误返回的完整正文不可显示', () => {
    state.data = { ...materialFixture(), kind: 'case' }
    state.params = `kind=case&resultId=9&template=case_summary&expected_content_sha256=${'a'.repeat(64)}`
    let html = renderToStaticMarkup(<Reports />)
    expect(state.requested.find(item => item.queryKey[0] === 'material-reader')?.queryKey).toEqual(['material-reader', '4:2', 'case', '9', 'case_summary', 'a'.repeat(64)])
    expect(html).toContain('返回的材料格式或内容版本不匹配'); expect(html).not.toContain('原文未发现车辆')
    state.data.presentation = { ...state.data.presentation, template: 'case_summary', label: '案件资料摘要', options: [{ id: 'full', label: '完整资料' }, { id: 'case_summary', label: '案件资料摘要' }] }
    html = renderToStaticMarkup(<Reports />)
    expect(html).toContain('原文未发现车辆'); expect(html).toContain('value="case_summary" selected=""')
    expect(html).toContain('不是单位正式样表'); expect(html).toContain('按需记录判断')
    state.data.content_sha256 = 'b'.repeat(64)
    expect(renderToStaticMarkup(<Reports />)).not.toContain('原文未发现车辆')
  })
  it('预期内容摘要不合法时不读取且不使用缓存', () => {
    state.params = 'kind=meeting&resultId=9&expected_content_sha256=wrong'
    const html = renderToStaticMarkup(<Reports />)
    expect(html).toContain('内容版本参数无效'); expect(html).not.toContain('原文未发现车辆')
    expect(state.requested.find(item => item.queryKey[0] === 'material-reader')?.enabled).toBe(false)
  })
})
