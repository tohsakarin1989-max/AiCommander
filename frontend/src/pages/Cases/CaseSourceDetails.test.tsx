import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CaseSourceDetails, { CaseSourceVersionCard } from './CaseSourceDetails'
import type { CaseSourceRevisionDetail } from '../../types'

const state = vi.hoisted(() => ({ failed: false, more: false }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1 }, sessionEpoch: 3 }) }))
vi.mock('@tanstack/react-query', () => ({ useQuery: ({ queryKey }: { queryKey: unknown[] }) => ({ isError: state.failed, isPending: false,
  data: queryKey[0] === 'case-sources' ? { current_revision_id: 25, revisions: [{ id: 25, revision: 1, source_hash: 'hash-abc', created_at: '2026-09-27T04:00:00Z' }], references: [], boundary: '原始提交版本', next_before_revision: state.more ? 4 : null }
    : queryKey[0] === 'case-measurements' ? [{ id: 1, value: 0, unit: 'unknown', stage: 'seized' }] : [],
}) }))

describe('来源详情只展示当前可读记录', () => {
  beforeEach(() => { state.failed = false; state.more = false })
  it('有历史游标时提供更早版本；切换案件或修订会重置详情和分页状态', () => {
    state.more = true
    const html = renderToStaticMarkup(<CaseSourceDetails caseId={7} />)
    expect(html).toContain('来源版本分页'); expect(html).toContain('>更早版本</button>')
    expect(CaseSourceDetails({ caseId: 7 }).key).not.toBe(CaseSourceDetails({ caseId: 8 }).key)
    expect(CaseSourceDetails({ caseId: 7, revision: 'a' }).key).not.toBe(CaseSourceDetails({ caseId: 7, revision: 'b' }).key)
  })
  it('版本序号不是主键；未知量纲与无地点明确显示', () => {
    const html = renderToStaticMarkup(<CaseSourceDetails caseId={7} />)
    expect(html).toContain('当前来源：第 1 版')
    expect(html).not.toContain('当前来源：25')
    expect(html).toContain('2026-09-27 12:00')
    expect(html).toContain('0 单位未知')
    expect(html).toContain('尚未补录独立地点角色')
  })
  it('撤权或失败不展示缓存版本，也不声称没有来源或零数量', () => {
    state.failed = true
    const html = renderToStaticMarkup(<CaseSourceDetails caseId={7} />)
    expect(html).toContain('来源暂不可读')
    expect(html).toContain('测量明细暂不可读')
    expect(html).not.toContain('hash-abc'); expect(html).not.toContain('0 单位未知')
  })
  it('版本卡首先展示冻结原文，内部编号、null 和校验摘要仅在关闭的技术详情内', () => {
    const source: CaseSourceRevisionDetail = { id: 25, revision: 1, source_hash: 'internal-hash', created_at: '2026-09-27T04:00:00Z', payload: {
      case: { time_precision: 'unknown', time_expression: '昨晚附近', occurred_time: null, location: '厂区东侧', description: '原始案情第一行\n第二行', oil_volume: 8, oil_volume_unit: 'unknown' },
    } }
    const html = renderToStaticMarkup(<CaseSourceVersionCard source={source} />)
    const readable = html.split('<details>')[0]
    expect(readable).toContain('第 1 版原文记录')
    expect(readable).toContain('保存于 2026-09-27 12:00（北京时间）')
    expect(readable).toContain('昨晚附近（时间未明确）')
    expect(readable).toContain('厂区东侧'); expect(readable).toContain('原始案情第一行\n第二行'); expect(readable).toContain('8 单位未知')
    expect(readable).not.toContain('internal-hash'); expect(readable).not.toContain('null'); expect(readable).not.toContain('occurred_time')
    expect(html).toContain('<details><summary>技术详情（完整来源数据）</summary>')
    expect(html).not.toContain('<details open'); expect(html).toContain('internal-hash')
  })
  it('版本中的地点与不同测量分别呈现，缺少原文不使用其他版本补齐', () => {
    const source: CaseSourceRevisionDetail = { id: 26, revision: 2, source_hash: 'hash', created_at: '2026-09-27T04:00:00Z', payload: {
      case: { time_precision: 'interval', occurred_from: '2026-09-01T00:00:00Z', occurred_to: '2026-09-02T00:00:00Z' },
      locations: [{ role: 'discovery', description: '路口', precision: 'area' }],
      measurements: [{ value: 10, unit: 'liter', stage: 'seized' }, { value: 5, unit: 'kg', stage: 'recovered' }],
    } }
    const readable = renderToStaticMarkup(<CaseSourceVersionCard source={source} />).split('<details>')[0]
    expect(readable).toContain('时间区间'); expect(readable).toContain('该次保存未填写案情原文')
    expect(readable).toContain('路口（仅知区域）'); expect(readable).toContain('查获：10 升'); expect(readable).toContain('回收：5 千克')
    expect(readable).not.toContain('15'); expect(readable).not.toContain('吨')
  })
})
