import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MapIngestHistory from './MapIngestHistory'
import type { MapLedgerClaim } from '../../services/mapLedgerImports'
import { ledgerBatchClaim } from './mapLedgerBatch.fixtures'

const state = vi.hoisted(() => ({ cursor: 0, hooks: [] as unknown[], failed: false, epoch: 1,
  buttons: [] as Array<{ label: string; disabled?: boolean; onClick: () => void }>,
  inputs: {} as Record<string, { value: string; disabled?: boolean; onChange: (event: { target: { value: string } }) => void }>,
  pages: [] as Array<(page: number) => void>, queries: [] as unknown[][], retryPreview: vi.fn(), retry: vi.fn(),
  claimItems: null as null | MapLedgerClaim[], batchClaims: [] as MapLedgerClaim[],
  rowSelection: null as null | { selectedRowKeys: number[]; onChange: (keys: number[]) => void; getCheckboxProps: (row: MapLedgerClaim) => { disabled: boolean } },
}))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(), useEffect: vi.fn(),
  useState: (initial: unknown) => { const index = state.cursor++; if (!(index in state.hooks)) state.hooks[index] = initial
    return [state.hooks[index], (next: unknown) => { state.hooks[index] = typeof next === 'function' ? (next as (previous: unknown) => unknown)(state.hooks[index]) : next }] },
  useRef: (initial: unknown) => { const index = state.cursor++; if (!(index in state.hooks)) state.hooks[index] = { current: initial }; return state.hooks[index] },
}))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 8 }, sessionEpoch: state.epoch }) }))
vi.mock('../../services/mapLedgerImports', () => ({ mapLedgerImportsApi: { retryPreview: state.retryPreview, retry: state.retry } }))
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }), useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
  state.queries.push(queryKey)
  const items = queryKey[0] === 'map-ingest-runs' ? [{ id: 'parent-run', filename: '合成原表.csv', source_revision: '原修订', counts: {}, table_metadata: { sheet_name: '生产', header_row: 2 } }]
    : state.claimItems || [{ id: 12, row_number: 7, status: 'quarantined', raw_payload: { 井号: 'A', 产量: '错误值', 单位: '吨' }, plan: { classification: 'failed', groups: [] } },
      { id: 13, row_number: 8, status: 'published', raw_payload: { 井号: 'B' }, plan: { classification: 'new', groups: [] } }]
  return { isSuccess: !state.failed, isError: state.failed, data: { items, total: 55 }, refetch: vi.fn() }
} }))
vi.mock('./MapImportPlan', () => ({ default: () => <p>修正预览已读</p>, MapPlanDetails: () => null }))
vi.mock('./MapFieldDecision', () => ({ default: () => null }))
vi.mock('./MapBatchCorrection', () => ({ default: ({ claims }: { claims: MapLedgerClaim[] }) => {
  state.batchClaims = claims; return <p>批量待核 {claims.length} 行</p>
} }))
vi.mock('antd', () => ({
  Alert: ({ message }: { message: string }) => <p>{message}</p>, Space: ({ children }: { children: ReactNode }) => <div>{children}</div>, Select: () => null,
  Input: (props: { 'aria-label': string; value: string; disabled?: boolean; onChange: (event: { target: { value: string } }) => void }) => {
    state.inputs[props['aria-label']] = props; return <input value={props.value} readOnly />
  },
  Button: ({ children, disabled, onClick }: { children: ReactNode; disabled?: boolean; onClick: () => void }) => {
    state.buttons.push({ label: String(children), disabled, onClick }); return <button disabled={disabled}>{children}</button>
  },
  Pagination: ({ onChange }: { onChange: (page: number) => void }) => { state.pages.push(onChange); return null },
  Table: ({ dataSource, columns, rowSelection }: { dataSource: Record<string, unknown>[]; rowSelection?: typeof state.rowSelection; columns: Array<{ dataIndex?: string; render?: (value: unknown, item: Record<string, unknown>) => ReactNode }> }) => {
    if (rowSelection) state.rowSelection = rowSelection
    return <div>{dataSource.map((item, index) => <div key={index}>{columns.map((column, col) => <span key={col}>{column.render ? column.render(item[column.dataIndex || ''], item) : String(item[column.dataIndex || ''])}</span>)}</div>)}</div>
  },
}))
const flush = () => new Promise(resolve => setTimeout(resolve, 0))
function render() { state.cursor = 0; state.buttons = []; state.pages = []
  return renderToStaticMarkup(<MapIngestHistory sourceId={3} templateId={9} contract={{ schema_version: 'test', fields: [], groups: {}, value_states: [] }} onChanged={vi.fn()} onDirtyChange={vi.fn()} />) }
function button(label: string, index = 0) { return state.buttons.filter(item => item.label === label)[index] }
function chooseRow() { render(); button('查看逐行回执').onClick(); render(); button('修正这一行').onClick(); render() }
describe('台账最近批次的异常续做行为', () => {
  beforeEach(() => { state.cursor = 0; state.hooks = []; state.failed = false; state.epoch = 1; state.queries = []; vi.clearAllMocks()
    state.claimItems = null; state.rowSelection = null; state.batchClaims = []
    state.retryPreview.mockResolvedValue({ plan_token: 'row-plan', publishable: true, drift: [] })
    state.retry.mockResolvedValue({ id: 'child-run' }) })
  it('失败预览保留完整原列；提交失联后保留同一凭证重试，不重新导成功行', async () => {
    chooseRow(); expect(button('修正这一行', 1).disabled).toBe(true)
    state.inputs['修正台账列 产量'].onChange({ target: { value: '28' } }); render()
    state.retryPreview.mockRejectedValueOnce(new Error('预览暂不可用'))
    button('预览此行修正').onClick(); await flush(); let html = render()
    expect(html).toContain('预览暂不可用'); expect(state.inputs['修正台账列 产量'].value).toBe('28')
    button('预览此行修正').onClick(); await flush(); render()
    expect(state.inputs['修正台账列 产量'].disabled).toBe(true)
    state.retry.mockRejectedValueOnce(new Error('写入响应丢失'))
    button('按原请求提交此行修正').onClick(); await flush(); html = render()
    expect(html).toContain('写入响应丢失'); expect(button('核对后返回修改').disabled).toBe(true); expect(button('放弃本页修正').disabled).toBe(true)
    button('按原请求提交此行修正').onClick(); await flush(); html = render()
    const first = state.retry.mock.calls[0]
    expect(first[0]).toBe('parent-run'); expect(first[1].rows).toEqual([{ claim_id: 12, values: { 井号: 'A', 产量: '28', 单位: '吨' } }])
    expect(first[1].plan_token).toBe('row-plan'); expect(state.retry.mock.calls[1]).toEqual(first)
    expect(html).toContain('child-run'); expect(html).not.toContain('第 7 行修正')
  })
  it.each(['plan_stale', 'retry_identifier_taken', 'retry_parent_stale', 'retry_row_superseded'])('明确 %s 拒绝保输入但取消旧预览，重新比较后才可继续', async code => {
    chooseRow(); button('预览此行修正').onClick(); await flush(); render()
    state.retry.mockRejectedValueOnce({ detail: { detail: { code, message: '数据已变化' } } })
    button('按原请求提交此行修正').onClick(); await flush(); const html = render()
    expect(html).toContain('数据已变化'); expect(html).not.toContain('修正预览已读')
    expect(state.inputs['修正台账列 产量'].disabled).toBe(false); expect(button('按原请求提交此行修正').disabled).toBe(true)
  })
  it('两级分页保留厂区来源与账号代次，读取失败不把旧回执当当前值', () => {
    chooseRow(); state.pages[0](3); state.pages[1](3); render()
    expect(state.queries).toContainEqual(['map-ingest-runs', 8, 1, 3, 20])
    expect(state.queries).toContainEqual(['map-ingest-claims', 8, 1, 'parent-run', 40, undefined])
    state.failed = true; state.epoch = 2; const html = render()
    expect(html).toContain('批次读取失败'); expect(html).not.toContain('查看逐行回执')
    expect(state.queries).toContainEqual(['map-ingest-runs', 8, 2, 3, 20])
  })
  it('跨页保留同因选择，成功、已修订及不同错误不可混选，逐行入口不并行改同批', () => {
    const first = ledgerBatchClaim(1, 'parent-run')
    const second = ledgerBatchClaim(2, 'parent-run')
    const consumed = { ...ledgerBatchClaim(3, 'parent-run'), retry_superseded: true }
    const otherError = { ...ledgerBatchClaim(4, 'parent-run'), plan: { ...first.plan!, errors: [{ code: 'invalid_coordinate', field: 'geometry', message: '坐标不是数字' }] } }
    state.claimItems = [first, consumed]
    render(); button('查看逐行回执').onClick(); render()
    expect(state.rowSelection!.getCheckboxProps(consumed).disabled).toBe(true)
    state.rowSelection!.onChange([1]); render()
    expect(state.batchClaims.map(row => row.id)).toEqual([1]); expect(button('修正这一行').disabled).toBe(true)
    state.pages[1](2); state.claimItems = [second, otherError]; render()
    expect(state.rowSelection!.getCheckboxProps(otherError).disabled).toBe(true)
    button('选中本页同因异常').onClick(); render()
    expect(state.batchClaims.map(row => row.id)).toEqual([1, 2])
    state.rowSelection!.onChange([1, 2, 4]); const html = render()
    expect(state.batchClaims.map(row => row.id)).toEqual([1, 2]); expect(html).toContain('同一字段和错误')
  })
})
