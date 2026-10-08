import { describe, expect, it, vi } from 'vitest'
import { displayMapValue, mapBatchError, mapBatchPreviewCanCommit, mapImportError, mapPreviewCanCommit, mapReceivedTime, mapRowLabels, normalizeMapNumericFormat, prepareMapBatchRetry, prepareMapRetry } from './mapLedgerPresentation'
import { ledgerTemplatePayload } from './MapLedgerTemplateForm'
import type { MapLedgerClaim, MapLedgerPreview } from '../../services/mapLedgerImports'
import { ledgerBatchRun, ledgerBatchClaim, ledgerBatchPreview } from './mapLedgerBatch.fixtures'

describe('生产台账的模板与提交边界', () => {
  it('保留完整生产字段、明确单位、工作表表头，不按值推断坐标系', () => {
    const result = ledgerTemplatePayload(7, { name: ' 月台账 ', sheet_name: ' 生产 ', header_row: 3,
      coordinate_system: 'cgcs2000_geographic', coordinate_unit: 'degree', axis_order: 'lat_lon',
      field_mapping: { name: ' 井名 ', water_cut_min: '最低含水', production_output: ' 月产量 ', production_state: '产量处理', oil_type: '' },
      field_units: { production_output_unit: ' 吨 ', water_cut_unit: ' % ' }, expected_headers: '井名\n最低含水\n月产量\n产量处理\n' })
    expect(result).toEqual({ source_id: 7, name: '月台账', sheet_name: '生产', header_row: 3,
      coordinate_system: 'cgcs2000_geographic', coordinate_unit: 'degree', axis_order: 'lat_lon',
      field_mapping: { name: '井名', water_cut_min: '最低含水', production_output: '月产量', production_state: '产量处理' },
      field_units: { production_output_unit: '吨', water_cut_unit: '%' },
      expected_structure: { headers: ['井名', '最低含水', '月产量', '产量处理'], sheet_name: '生产', header_row: 3 } })
  })
  it('没有完整预览凭证、有漂移或不可写预览都不能提交', () => {
    const preview = { plan_token: 'frozen-plan', publishable: true, drift: [] } as unknown as MapLedgerPreview
    expect(mapPreviewCanCommit(preview)).toBe(true)
    expect(mapPreviewCanCommit(null)).toBe(false)
    expect(mapPreviewCanCommit({ ...preview, plan_token: '' })).toBe(false)
    expect(mapPreviewCanCommit({ ...preview, publishable: false })).toBe(false)
    expect(mapPreviewCanCommit({ ...preview, drift: [{ field: 'headers', code: 'changed', message: '表头变了' }] })).toBe(false)
  })
  it('异常续做冻结完整原列和身份凭证，不把空白改成数值零', () => {
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('12345678-1234-1234-1234-123456789012')
    const values = { 井号: 'A', 产量: 0, 油品: null, 含水: '' }
    const request = prepareMapRetry(55, values, 12)
    values.井号 = 'B'
    expect(request).toEqual({ request_id: '12345678-1234-1234-1234-123456789012', template_id: 12,
      rows: [{ claim_id: 55, values: { 井号: 'A', 产量: 0, 油品: null, 含水: '' } }] })
    vi.restoreAllMocks()
  })
  it('六分类完整、未知不转风险，结构化错误可区分过期计划', () => {
    expect(Object.values(mapRowLabels)).toEqual(['新增', '更新', '未变', '身份待对应', '冲突', '失败'])
    expect(displayMapValue(0)).toBe('0'); expect(displayMapValue(false)).toBe('否'); expect(displayMapValue(null)).toBe('未提供')
    expect(mapImportError({ detail: { detail: { code: 'plan_stale', message: '请重新预览' } } })).toEqual({ code: 'plan_stale', message: '请重新预览' })
    expect(mapImportError(new Error('网络断开'))).toEqual({ code: undefined, message: '网络断开' })
  })
  it('接收时间明确按业务时区，旧无时区值不自动解释成本机时间', () => {
    expect(mapReceivedTime('2026-10-05T08:30:00Z')).toBe('2026-10-05 16:30（北京时间）')
    expect(mapReceivedTime('2026-10-05T08:30:00')).toContain('历史记录未标明时区')
    expect(mapReceivedTime(null)).toBe('接收时间未记录')
  })
})

const batchRun = ledgerBatchRun()
const batchClaim = ledgerBatchClaim

describe('台账同因批量修正边界', () => {
  it('保留不同原行数值与完整列，只整理所选数字列，并固定原模板', () => {
    const rows = [batchClaim(), batchClaim(2)]
    const payload = prepareMapBatchRetry(batchRun, rows, { kind: 'numeric_format', column: '产量' }, 9)
    expect(payload.template_id).toBe(4)
    expect(payload.rows.map(row => row.values.产量)).toEqual(['1.5', '2.5'])
    expect(payload.rows.map(row => row.values.编号)).toEqual(['F1', 'F2'])
    expect(payload.rows[0].values.空白).toBeNull()
    expect(rows[0].raw_payload?.产量).toBe('　1．５　')
    rows[0].raw_payload!.编号 = 'changed'
    expect(payload.rows[0].values.编号).toBe('F1')
    expect(() => prepareMapBatchRetry(batchRun, rows, { kind: 'numeric_format', column: '编号' })).toThrow('异常数字列')
  })
  it.each(['', '  ', null, 0, '1,000', '1吨', '5%', '1 2', '未知', '１，０００'])('格式整理不换算或推断 %s', value => {
    expect(normalizeMapNumericFormat(value)).toBe(value)
  })
  it('新模板只重新解释原行，禁止未选择或沿用原模板的空操作', () => {
    const row = batchClaim()
    expect(prepareMapBatchRetry(batchRun, [row], { kind: 'template' }, 9).rows[0].values).toEqual(row.raw_payload)
    expect(() => prepareMapBatchRetry(batchRun, [row], { kind: 'template' }, 4)).toThrow('新模板')
    expect(() => prepareMapBatchRetry(batchRun, [row], { kind: 'template' })).toThrow('新模板')
  })
  it('成功、后继、身份、不同字段、事实冲突及无后继检查的旧回执不能混入', () => {
    const first = batchClaim()
    const second = batchClaim(2)
    const invalidRows: MapLedgerClaim[] = [
      { ...second, retry_superseded: true }, { ...second, retry_superseded: undefined },
      { ...second, status: 'published' }, { ...second, run_id: 'other-batch' },
      { ...second, plan: { ...second.plan!, classification: 'new' } },
      { ...second, plan: { ...second.plan!, classification: 'identity_pending' } },
      { ...second, plan: { ...second.plan!, errors: [{ code: 'invalid_production_output', field: 'other', message: '不是有效数字' }] } },
      { ...second, plan: { ...second.plan!, errors: [{ code: 'duplicate_source_identity', field: 'external_id', message: '重复编号' }] } },
      { ...second, plan: { ...second.plan!, groups: [{ group: 'production', state: 'set', status: 'conflict', reason: 'equal_priority', old: {}, new: {} }] } },
    ]
    for (const row of invalidRows) expect(() => prepareMapBatchRetry(batchRun, [first, row], { kind: 'template' }, 9)).toThrow('同批次')
    expect(mapBatchError({ ...first, retry_superseded: true })).toBeNull()
    expect(() => prepareMapBatchRetry(batchRun, [first, first], { kind: 'template' }, 9)).toThrow('不重复')
    expect(() => prepareMapBatchRetry(batchRun, Array.from({ length: 201 }, (_, index) => batchClaim(index)), { kind: 'template' }, 9)).toThrow('200')
  })
  it('逐行完整预览且全部可处理，才允许共同确认；通用publishable不足以批准部分异常', () => {
    const claims = [batchClaim(), batchClaim(2)]
    const preview = ledgerBatchPreview(claims)
    expect(mapBatchPreviewCanCommit(preview, claims)).toBe(true)
    expect(mapBatchPreviewCanCommit({ ...preview, rows_complete: false }, claims)).toBe(false)
    expect(mapBatchPreviewCanCommit({ ...preview, rows: preview.rows.slice(0, 1) }, claims)).toBe(false)
    for (const classification of ['conflict', 'failed', 'identity_pending'] as const) {
      expect(mapBatchPreviewCanCommit({ ...preview, rows: [preview.rows[0], { ...preview.rows[1], classification }] }, claims)).toBe(false)
    }
  })
})
