import { describe, expect, it, vi } from 'vitest'
import { displayMapValue, mapImportError, mapPreviewCanCommit, mapReceivedTime, mapRowLabels, prepareMapRetry } from './mapLedgerPresentation'
import { ledgerTemplatePayload } from './MapLedgerTemplateForm'
import type { MapLedgerPreview } from '../../services/mapLedgerImports'

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
