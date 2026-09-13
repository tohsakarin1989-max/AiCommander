import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CaseGraph from './Graphs/CaseGraph'
import GangAnalysis from './Gangs/GangAnalysis'
import Jurisdiction from './Jurisdiction/Jurisdiction'
import { PatrolRouteMap } from './Patrols/Patrols'
import { visibleNavigation } from '../config/navigation'

const state = vi.hoisted(() => ({ role: 'viewer', path: '/agents',
  queries: [] as Array<{ queryKey: unknown[]; enabled?: boolean }> }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { role: state.role, display_name: '测试' }, logout: vi.fn() }) }))
vi.mock('../config/useRuntimeFeatures', () => ({ useRuntimeFeatures: () => ({
  bonusAccountingEnabled: false, agentLabEnabled: false,
  availability: { bonus_accounting: 'disabled', legacy_operations: 'disabled', showcase: 'disabled' },
  query: { data: { active_model_count: 0 }, isSuccess: true },
}) }))
vi.mock('react-router-dom', () => ({ Link: ({ children, to, ...props }: { children: React.ReactNode; to: string }) => <a href={to} {...props}>{children}</a>, useNavigate: () => vi.fn(), useLocation: () => ({ pathname: state.path }), useSearchParams: () => [new URLSearchParams()] }))
vi.mock('../components/ActiveWorkSessionBar', () => ({ default: () => null }))
vi.mock('./Jurisdiction/JurisdictionAssetMap', () => ({ default: () => null }))
vi.mock('./Jurisdiction/MapDataGovernance', () => ({ default: () => null }))
vi.mock('echarts-for-react', () => ({ default: () => null }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: (options: typeof state.queries[number]) => {
    state.queries.push(options)
    const key = options.queryKey[0]
    const data = key === 'gangStatistics' ? { top_gangs: [], total_gangs: 0 } :
      key === 'cases' || key === 'my-area-scopes' || key === 'jurisdiction-assets' ? [] : undefined
    return { data, isLoading: false, isError: false }
  },
}))

describe('历史页面与 v3 运行中心边界', () => {
  beforeEach(() => { state.role = 'viewer'; state.path = '/agents'; state.queries = [] })

  it('关系图谱只读账号不给出可执行生成入口', () => {
    const html = renderToStaticMarkup(<CaseGraph />)
    expect(html).toContain('只读账号不触发关系图谱生成')
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>[\s\S]*?生成图谱/)
  })

  it('条件组画像没有档案创建假按钮且只读账号不发自动 POST 查询', () => {
    const html = renderToStaticMarkup(<GangAnalysis />)
    expect(html).toContain('查看当前画像')
    expect(html).not.toContain('新建条件组档案')
    for (const name of ['gangHeatmap', 'crossGangPersons', 'gangTimeline']) {
      expect(state.queries.find(q => q.queryKey[0] === name)?.enabled).toBe(false)
    }
  })

  it('辖区只读账号明确资产维护权限且不触发部署参考 POST', () => {
    const html = renderToStaticMarkup(<Jurisdiction />)
    expect(html).toContain('地图资产由管理员维护')
    expect(state.queries.find(q => q.queryKey[0] === 'jurisdiction-patrol-plan')?.enabled).toBe(false)
  })

  it('没有数据时巡逻固定路线始终明确标记示意与待配置', () => {
    const html = renderToStaticMarkup(<PatrolRouteMap areaRisks={[]} hotspots={[]} keyLocations={[]} />)
    expect(html).toContain('路线待配置')
    expect(html).toContain('4 条示意路径')
    expect(html).not.toContain('基于风险分析自动规划')
    expect(html).not.toContain('4 条路线')
  })

  it('管理员的 v3 运行中心不依赖已关闭的旧 Agent Lab', () => {
    state.role = 'admin'
    expect(visibleNavigation('admin', () => false).flatMap(group => group.pages).map(page => page.path)).toContain('/agents')
  })

  it('普通账号不显示管理员运行入口', () => {
    expect(visibleNavigation('viewer', () => true).flatMap(group => group.pages).map(page => page.path)).not.toContain('/agents')
  })
  it('旧 Lab 兼容入口仅向明确启用的管理员开放', () => {
    const paths = (role: string, enabled: boolean) => visibleNavigation(role, () => enabled).flatMap(group => group.pages).map(page => page.path)
    expect(paths('admin', true)).toContain('/agent-lab')
    expect(paths('admin', false)).not.toContain('/agent-lab')
    expect(paths('analyst', true)).not.toContain('/agent-lab')
  })
})
