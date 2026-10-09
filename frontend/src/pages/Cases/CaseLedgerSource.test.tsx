import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import CaseLedgerSource from './CaseLedgerSource'

const reference = { availability: 'available', locator: { import_source: {
  import_preset: 'security_ledger', row: 4, warnings: ['回收量单位待核'], columns: [
    { column: 'AC', header: '备注', value: '合成原文' },
    { column: 'AM', header: '备注', value: '补充处置' },
    { column: 'AQ', header: null, value: '<script>不执行</script>' },
    { column: 'AF', header: '回收原油', value: 0 },
  ],
} } }

describe('保卫台账原始行', () => {
  it('shows duplicate headers by original column, preserving zero and unknown labels', () => {
    const html = renderToStaticMarkup(<CaseLedgerSource reference={reference} />)
    expect(html).toContain('第 4 行')
    expect(html).toContain('AC'); expect(html).toContain('AM')
    expect(html).toContain('无表头补充'); expect(html).toContain('>0</td>')
    expect(html).toContain('回收量单位待核')
    expect(html).toContain('&lt;script&gt;不执行&lt;/script&gt;')
    expect(html).not.toContain('<script>')
  })
  it('does not display copied content on revoked, unknown or unavailable references', () => {
    for (const availability of ['revoked', 'unavailable', undefined]) {
      expect(renderToStaticMarkup(<CaseLedgerSource reference={{ ...reference, availability }} />)).toBe('')
    }
    expect(renderToStaticMarkup(<CaseLedgerSource reference={{ locator: 'legacy' }} />)).toBe('')
  })
})
