import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { caseImportsApi } from './caseImports'
import { caseApi } from './cases'

vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

describe('same ledger settings across inspection, preview and import', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.post).mockResolvedValue({ data: {} }) })
  const file = new File(['synthetic workbook placeholder'], '合成台账.xlsx')
  const settings = { import_preset: 'security_ledger' as const, header_row: 3, time_zone: 'Asia/Shanghai' as const }

  it('does not drop the explicit preset between requests', async () => {
    await caseImportsApi.inspect(file, 1, settings)
    await caseApi.previewImportCases(file, 1, settings)
    await caseApi.importCases(file, false, 1, settings)
    const calls = vi.mocked(api.post).mock.calls
    for (const [, , options] of calls) {
      expect(options?.params).toMatchObject({ import_preset: 'security_ledger', header_row: 3, operational_area_id: 1 })
    }
    expect(calls[1][2]?.params).toHaveProperty('dry_run', true)
    expect(calls[2][2]?.params).toHaveProperty('dry_run', false)
  })

  it('persists preset in reusable settings, without case contents', async () => {
    await caseImportsApi.saveTemplate('年度台账模板', 1, settings)
    expect(vi.mocked(api.post).mock.calls[0][1]).toEqual({ name: '年度台账模板', operational_area_id: 1, settings })
  })

  it('leaves ordinary tables in the strict general path', async () => {
    await caseApi.previewImportCases(file, 1)
    expect(vi.mocked(api.post).mock.calls[0][2]?.params).toHaveProperty('import_preset', undefined)
  })
})
