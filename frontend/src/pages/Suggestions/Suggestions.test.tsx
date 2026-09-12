import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Suggestions from './Suggestions'
import { suggestionsApi } from '../../services/suggestions'

const state = vi.hoisted(() => ({ failed: false, queries: [] as Array<{ queryKey: unknown[]; queryFn: () => unknown }> }))
vi.mock('../../services/suggestions', () => ({ suggestionsApi: { list: vi.fn() } }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 7, role: 'analyst' }, sessionEpoch: 1 }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: (options: typeof state.queries[number]) => { state.queries.push(options); return { isError: state.failed, data: {
    offset: 0, limit: 20, has_more: true,
    summary: { total: 21, priority: { high: 9, medium: 10, low: 2 }, type: { analysis: 21 }, workflow: { data_quality: 21 } },
    total: 21, generated_at: '2026-09-12T00:00:00', suggestions: [{
      id: 'case-1', type: 'analysis', action: 'open_case', status: 'open', priority: 'medium',
      target_type: 'case', target_id: 1, title: '资料待核', description: '需要补充',
      created_at: '2026-09-12T00:00:00',
    }],
  } } },
}))

describe('待办统计事实口径', () => {
  beforeEach(() => { state.failed = false; state.queries = []; vi.clearAllMocks() })

  it('不把优先级、未载队列数表达为完成量或今日复核进度', () => {
    const html = renderToStaticMarkup(<Suggestions />)
    expect(html).toContain('全队列</span><b>21</b>')
    expect(html).toContain('中优先级</span><b>10</b>')
    expect(html).not.toContain('今日已审')
    expect(html).not.toContain('已完成</span>')
    expect(html).not.toContain('规则引擎 <b>正常')
    expect(html).not.toContain('经验卡生成')
    expect(html).not.toContain('AI0001')
    expect(html).toContain('不以经验卡或报告是否生成为每案必办条件')
  })

  it('接口失败隐藏缓存待办并说明未知，不误报无待办', () => {
    state.failed = true
    const html = renderToStaticMarkup(<Suggestions />)
    expect(html).toContain('待办读取失败')
    expect(html).not.toContain('当前没有待处理待办')
    expect(html).not.toContain('资料待核')
  })

  it('仅呈现已有分类和重置控件，待办计数不伪装成筛选按钮', () => {
    const html = renderToStaticMarkup(<Suggestions />)
    const buttons = Array.from(html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g), match => match[1])
    expect(html).not.toContain('按最新')
    expect(html).not.toContain('<select')
    expect(html).not.toContain('全部来源')
    expect(html).not.toContain('全部风险区域')
    expect(buttons.some(button => button.includes('全部待办'))).toBe(true)
    expect(buttons.some(button => button.includes('坐标缺口'))).toBe(true)
    expect(buttons.some(button => button.includes('重置筛选'))).toBe(true)
    expect(buttons.some(button => /全队列|当前筛选/.test(button))).toBe(false)
    const summary = html.split('class="sg-status-tabs"')[1]?.split('class="sg-table-head"')[0]
    expect(summary).toContain('高优先级')
    expect(summary).not.toContain('<button')
  })

  it('将分类与页码传入后端，不依据当前一页推算全队列', async () => {
    renderToStaticMarkup(<Suggestions />)
    expect(state.queries[0].queryKey).toEqual(['suggestions', 7, 1, 'all', 0])
    await state.queries[0].queryFn()
    expect(suggestionsApi.list).toHaveBeenCalledWith({ limit: 20, offset: 0, status: 'open', workflow: 'all' })
  })
})
