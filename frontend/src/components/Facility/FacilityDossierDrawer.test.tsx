import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import FacilityDossierDrawer, { FacilitySectionContent, sectionLabels } from './FacilityDossierDrawer'
import type { FacilityDossier } from '../../services/facilityAnalysis'

const state = vi.hoisted(() => ({ search: 'assetId=7', epoch: 1, error: false, data: undefined as FacilityDossier | undefined, keys: [] as unknown[][] }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 3 }, sessionEpoch: state.epoch }) }))
vi.mock('react-router-dom', () => ({ useSearchParams: () => [new URLSearchParams(state.search), vi.fn()], Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a> }))
vi.mock('antd', () => ({ Drawer: ({ children }: { children: ReactNode }) => <div>{children}</div>, Spin: () => <p>读取中</p>, Alert: ({ message }: { message: ReactNode }) => <p>{message}</p> }))
vi.mock('@tanstack/react-query', () => ({ useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
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
    expect(state.keys[1]).toEqual(['facility-dossier', 3, 2, 8, '2026-09-01', undefined])
    expect(html).not.toContain('同名井')
  })
  it('撤权/读取失败时不展示仍在缓存中的内容', () => {
    state.error = true
    const html = renderToStaticMarkup(<FacilityDossierDrawer />)
    expect(html).not.toContain('同名井')
    expect(html).toContain('未展示旧缓存')
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
})
