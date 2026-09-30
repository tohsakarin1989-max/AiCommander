import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import FacilityDossierDrawer, { FacilitySectionContent, sectionLabels } from './FacilityDossierDrawer'
import type { FacilityDossier } from '../../services/facilityAnalysis'

const state = vi.hoisted(() => ({ search: 'assetId=7', epoch: 1, error: false, data: undefined as FacilityDossier | undefined, keys: [] as unknown[][] }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 3 }, sessionEpoch: state.epoch }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn(), useSearchParams: () => [new URLSearchParams(state.search), vi.fn()], Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a> }))
vi.mock('antd', () => ({ Drawer: ({ children }: { children: ReactNode }) => <div>{children}</div>, Spin: () => <p>读取中</p>, Alert: ({ message }: { message: ReactNode }) => <p>{message}</p> }))
vi.mock('./FacilityCaseLinkForm', () => ({ default: () => <p>按材料登记明确关联</p>, FacilityCaseLinkRevoke: ({ associationId }: { associationId: number }) => <p>撤销人工关联 {associationId}</p> }))
vi.mock('@tanstack/react-query', () => ({ useMutation: () => ({ isPending: false, mutate: vi.fn() }), useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
  state.keys.push(queryKey); return { data: state.data, isError: state.error, isFetching: false, refetch: vi.fn() }
} }))

const dossier = (id: number): FacilityDossier => ({ schema_version: 'facility-dossier-5.4-1', facility: { id, name: '同名井' }, filters: {},
  sections: Object.fromEntries(Object.keys(sectionLabels)
    .map(key => [key, { state: 'empty', items: [], total: 0, gaps: [], boundary: '各类关联分别展示' }])) as unknown as FacilityDossier['sections'],
  versions: {}, gaps: [], boundary: '附近不等于涉案', summary: { state: 'pending', revision: null, changes: [] } })

describe('设施档案读取与资料分类', () => {
  beforeEach(() => { state.search = 'assetId=7'; state.epoch = 1; state.error = false; state.data = dossier(7); state.keys = [] })
  it('按用户、授权代次、设施与时间隔离同名设施', () => {
    renderToStaticMarkup(<FacilityDossierDrawer />)
    state.search = 'assetId=8&start_date=2026-09-01'; state.epoch = 2
    const html = renderToStaticMarkup(<FacilityDossierDrawer />)
    expect(state.keys[1]).toEqual(['facility-dossier', 3, 2, 8, '2026-09-01', undefined, undefined, undefined])
    expect(html).not.toContain('同名井')
  })
  it('撤权/读取失败时不展示仍在缓存中的内容', () => {
    state.error = true
    const html = renderToStaticMarkup(<FacilityDossierDrawer />)
    expect(html).not.toContain('同名井')
    expect(html).toContain('未展示旧缓存')
  })
  it('双时间进入独立缓存，历史查看不冒充当前其他分区的历史还原', () => {
    state.search = 'assetId=7&valid_at=2026-08-01T00%3A00%3A00Z&known_at=2026-09-01T00%3A00%3A00Z&resultRef=result-1&mapSnapshot=snapshot-1'
    const html = renderToStaticMarkup(<FacilityDossierDrawer />)
    expect(state.keys[0].slice(-2)).toEqual(['2026-08-01T00:00:00.000Z', '2026-09-01T00:00:00.000Z'])
    expect(html).toContain('指定时点的生产资料'); expect(html).toContain('不是上述历史时点的完整还原')
    expect(html).toContain('按所选时点与当前权限核对计算资料')
    expect(html).toContain('当前读取 · 空间邻近案件'); expect(html).toContain('原成果引用：result-1')
    expect(html).toContain('清空，查看当下')
  })
  it('非法历史时刻不改查当前资料，也不显示已缓存设施', () => {
    state.search = 'assetId=7&known_at=wrong'
    const html = renderToStaticMarkup(<FacilityDossierDrawer />)
    expect(html).toContain('未回退为当前资料'); expect(html).not.toContain('同名井')
  })
  it('受限分区即使带误传数据也不暴露标题、内容或数量', () => {
    const html = renderToStaticMarkup(<FacilitySectionContent params={new URLSearchParams()} section={{ state: 'restricted', total: 123456,
      items: [{ id: 1, label: '不应泄漏', detail: '受限详情' }], boundary: '受限来源细节' }} />)
    expect(html).toContain('资料受限')
    expect(html).not.toContain('123456'); expect(html).not.toContain('不应泄漏'); expect(html).not.toContain('受限来源细节')
  })
  it('明确关联、邻近、候选分开且摘要待形成不等于案件未办结', () => {
    const html = renderToStaticMarkup(<FacilityDossierDrawer />)
    expect(html).toContain('有明确记录的案件关联'); expect(html).toContain('空间邻近案件'); expect(html).toContain('待核验候选关联')
    expect(html).toContain('不代表案件未办结')
    expect(html).not.toContain('风险分')
  })
  it('摘要受限时不展示误传的历史版本数量', () => {
    state.data!.summary = { state: 'restricted', revision: 654321, changes: [] }
    const html = renderToStaticMarkup(<FacilityDossierDrawer />)
    expect(html).toContain('生产资料摘要受限'); expect(html).not.toContain('654321'); expect(html).not.toContain('生产资料摘要待更新')
  })
  it('来源钻取关闭档案且保留时间条件，展示原始核验与台账行', () => {
    const html = renderToStaticMarkup(<FacilitySectionContent params={new URLSearchParams('assetId=7&start_date=2026-09-01')} section={{ state: 'ready', items: [{
      id: 1, label: '原始来源', case_id: 8, review_status: 'pending_review', case_in_window: false, row_number: 25,
      source_revision: 'ledger-v2', connection_status: 'unknown', facility_link_verified: false,
    }] }} />)
    expect(html).toContain('caseId=8'); expect(html).not.toContain('assetId=7'); expect(html).toContain('start_date=2026-09-01')
    expect(html).toContain('待复核'); expect(html).toContain('位于时间窗外'); expect(html).toContain('原始台账行'); expect(html).toContain('ledger-v2')
  })
  it('只允许撤销明确人工材料关联，不把事件或系统候选当作人工关系', () => {
    const section = { state: 'ready' as const, items: [
      { id: 'case_material:17', association_id: 17, relation_kind: 'recorded_material_link', status: 'recorded', label: '材料记载', source_state: 'stale', evidence_state: 'metadata_only', relation_type: 'mentioned' },
      { id: 18, association_id: 18, relation_kind: 'system_candidate', status: 'recorded', label: '系统候选' },
      { id: 'case_material:19', association_id: 19, relation_kind: 'recorded_material_link', status: 'revoked', label: '历史材料' },
    ] }
    const html = renderToStaticMarkup(<FacilitySectionContent section={section} params={new URLSearchParams()} allowRecord />)
    expect(html).toContain('撤销人工关联 17'); expect(html).not.toContain('撤销人工关联 18'); expect(html).not.toContain('撤销人工关联 19')
    expect(html).toContain('来源已变化'); expect(html).toContain('仅有目录'); expect(html).toContain('原文明确提及')
    expect(renderToStaticMarkup(<FacilitySectionContent section={section} params={new URLSearchParams()} />)).not.toContain('撤销人工关联')
  })
})
