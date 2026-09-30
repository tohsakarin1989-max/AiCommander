import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IntelliInspect from './IntelliInspect'
import api from '../../services/api'
import type { AutomationAlert } from '../../services/automationAlerts'

const state = vi.hoisted(() => ({
  data: [] as AutomationAlert[], error: false,
  queries: [] as Array<{ queryKey: string[]; queryFn: () => Promise<unknown> }>,
  invalidate: vi.fn(), navigate: vi.fn(),
}))
vi.mock('../../services/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('react-router-dom', () => ({ useNavigate: () => state.navigate }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: state.invalidate }),
  useQuery: (options: typeof state.queries[number]) => {
    state.queries.push(options)
    return { data: state.data, isError: state.error, isLoading: false, isFetching: false }
  },
  useMutation: (options: { mutationFn: (value: AutomationAlert) => Promise<unknown> }) => ({
    isPending: false, mutate: (value: AutomationAlert) => options.mutationFn(value),
  }),
}))

function button(node: ReactNode, label: string): ReactElement<Record<string, any>> | undefined {
  if (Array.isArray(node)) return node.map(child => button(child, label)).find(Boolean)
  if (!isValidElement<Record<string, any>>(node)) return undefined
  if (node.type === 'button' && node.props.children === label) return node
  return button(node.props.children, label)
}

function render() {
  let tree: ReactNode
  function Capture() { tree = IntelliInspect({}); return tree }
  const html = renderToStaticMarkup(<Capture />)
  return { html, click: (label: string) => button(tree, label)!.props.onClick() }
}

const alert: AutomationAlert = {
  id: 7, alert_number: 'AUTO-7', source_system: 'manual', alert_type: 'parameter_anomaly',
  title: '既有人工告警', level: 'medium', risk_level: 'medium',
  occurred_time: '2026-09-25T00:00:00Z', status: 'pending_review', is_simulated: false,
}

describe('历史告警页读取与显式操作', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    state.data = []; state.error = false; state.queries = []
    vi.mocked(api.get).mockResolvedValue({ data: [] })
    vi.mocked(api.post).mockResolvedValue({ data: { event_id: 12 } })
  })

  it('首次读取和刷新仅查询已有记录，不调用任何 POST', async () => {
    const page = render()
    await state.queries[0].queryFn()
    expect(api.get).toHaveBeenCalledWith('/automation-alerts/', { params: { limit: 100 } })
    expect(api.post).not.toHaveBeenCalled()
    page.click('刷新已有告警')
    expect(state.invalidate).toHaveBeenCalledWith({ queryKey: ['automation-alerts', 'history'] })
    await state.queries[0].queryFn()
    expect(api.get).toHaveBeenCalledTimes(2)
    expect(api.post).not.toHaveBeenCalled()
    expect(page.html).toContain('暂无已有告警，不会自动生成演示记录')
    expect(page.html).toContain('前往隔离展示')
    expect(page.html).not.toContain('基础就绪')
  })

  it('列表读取失败不会退回造数，也不把缓存或空态当作当前清单', async () => {
    state.data = [alert]; state.error = true
    vi.mocked(api.get).mockRejectedValueOnce(new Error('offline'))
    const page = render()
    await expect(state.queries[0].queryFn()).rejects.toThrow('offline')
    expect(api.post).not.toHaveBeenCalled()
    expect(page.html).toContain('告警列表读取失败')
    expect(page.html).not.toContain('既有人工告警')
    expect(page.html).not.toContain('暂无已有告警')
  })

  it('区分旧模拟记录，保留已有告警的人工操作且不自动触发', async () => {
    state.data = [alert, { ...alert, id: 8, title: '旧实验记录', is_simulated: true }]
    const page = render()
    expect(page.html).toContain('既有人工告警')
    expect(page.html).toContain('历史模拟记录')
    expect(page.html).toContain('旧实验记录')
    expect(page.html).toContain('研判包')
    expect(page.html).toContain('标记误报')
    expect(page.html).toContain('转案件')
    expect(api.post).not.toHaveBeenCalled()
    await page.click('生成事件')
    expect(api.post).toHaveBeenCalledExactlyOnceWith('/automation-alerts/7/event')
    expect(page.html).not.toContain('自动调阅附近雷达')
  })

  it('未知登记等级保留未知，不当成低风险', () => {
    state.data = [{ ...alert, risk_level: 'unknown' }]
    const page = render()
    expect(page.html).toContain('登记等级：未标注')
    expect(page.html).not.toContain('登记等级：低')
  })
})
