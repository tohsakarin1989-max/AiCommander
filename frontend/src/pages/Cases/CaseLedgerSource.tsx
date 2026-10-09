function record(value: unknown): Record<string, unknown> | undefined {
  return value != null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined
}

/** Render already-authorized source rows; do not interpret counts as case facts. */
export default function CaseLedgerSource({ reference }: { reference: Record<string, unknown> }) {
  const locator = record(reference.locator)
  const source = record(locator?.import_source)
  if (reference.availability !== 'available' || source?.import_preset !== 'security_ledger') return null
  const columns = Array.isArray(source.columns) ? source.columns.flatMap(value => {
    const item = record(value)
    return item && typeof item.column === 'string' ? [item] : []
  }) : []
  const warnings = Array.isArray(source.warnings) ? source.warnings.filter((value): value is string => typeof value === 'string') : []
  return <details>
    <summary>保卫台账原始行 · 第 {typeof source.row === 'number' ? source.row : '未知'} 行</summary>
    <p>以下是收到的台账原值，不是系统推断。空白未改成零；年月日角色、数量单位、处置口径以原来源为准。</p>
    {warnings.length > 0 && <ul>{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
    <div style={{ overflowX: 'auto' }}><table>
      <thead><tr><th scope="col">原列</th><th scope="col">原表头</th><th scope="col">原值</th></tr></thead>
      <tbody>{columns.map((item, index) => <tr key={index}>
        <td>{String(item.column)}</td><td>{typeof item.header === 'string' && item.header ? item.header : '无表头补充'}</td>
        <td style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxWidth: '70ch' }}>{item.value == null ? '原表为空'
          : typeof item.value === 'boolean' ? String(item.value) : typeof item.value === 'object' ? JSON.stringify(item.value) : String(item.value)}</td>
      </tr>)}</tbody>
    </table></div>
  </details>
}
