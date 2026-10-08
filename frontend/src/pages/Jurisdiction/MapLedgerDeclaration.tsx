import { Input, Select } from 'antd'
import type { MapLedgerDeclaration } from '../../services/mapFoundation'

export interface LedgerDeclarationDraft {
  mode: 'unknown' | 'full' | 'incremental'; scopeKey: string; scopeDescription: string; validFrom: string; validTo: string
}
export const emptyLedgerDeclaration: LedgerDeclarationDraft = { mode: 'unknown', scopeKey: '', scopeDescription: '', validFrom: '', validTo: '' }
export function ledgerDeclarationPayload(draft: LedgerDeclarationDraft): MapLedgerDeclaration | undefined {
  if (draft.mode === 'unknown') return undefined
  const from = draft.validFrom.trim(), to = draft.validTo.trim()
  const explicit = (value: string) => /(Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value))
  if (!draft.scopeKey.trim() || !draft.scopeDescription.trim() || !explicit(from) || !explicit(to) || Date.parse(to) <= Date.parse(from)) {
    throw new Error('请明确稳定范围编号、范围说明和带时区的有效起止时间；不清楚时保留“未声明”，不以接收日期代替')
  }
  return { mode: draft.mode, scope_key: draft.scopeKey.trim(), scope_description: draft.scopeDescription.trim(), valid_from: from, valid_to: to }
}

export default function MapLedgerDeclarationForm({ sourceId, value, disabled, onChange }: {
  sourceId: number; value: LedgerDeclarationDraft; disabled: boolean; onChange: (value: LedgerDeclarationDraft) => void
}) {
  const patch = (values: Partial<LedgerDeclarationDraft>) => onChange({ ...value, ...values })
  return <details><summary>台账完整度与业务期间（可选，由管理员明确声明）</summary>
    <p>只对应当前来源 #{sourceId} 及其授权厂区，不要求覆盖全厂。未知时不声明，正常导入仍可继续。</p>
    <Select aria-label="台账完整度声明" value={value.mode} disabled={disabled} style={{ minWidth: 220 }}
      options={[{ value: 'unknown', label: '未声明，不比较缺席' }, { value: 'full', label: '声明范围内完整台账' }, { value: 'incremental', label: '增量资料，不比较缺席' }]}
      onChange={mode => patch({ mode })} />
    {value.mode !== 'unknown' && <>
      <label>稳定范围编号<Input aria-label="台账覆盖范围编号" maxLength={100} value={value.scopeKey} disabled={disabled}
        placeholder="例如 north-area-wells；同一范围后续沿用，范围变动应换编号" onChange={event => patch({ scopeKey: event.target.value })} /></label>
      <label>覆盖范围说明<Input aria-label="台账覆盖范围说明" maxLength={300} value={value.scopeDescription} disabled={disabled}
        placeholder="例如某作业区全部登记井，不以文件名称推断" onChange={event => patch({ scopeDescription: event.target.value })} /></label>
      <label>业务有效起点<Input aria-label="台账业务有效起点" value={value.validFrom} disabled={disabled}
        placeholder="2026-10-01T00:00:00+08:00" onChange={event => patch({ validFrom: event.target.value })} /></label>
      <label>业务有效终点（不含）<Input aria-label="台账业务有效终点" value={value.validTo} disabled={disabled}
        placeholder="2026-11-01T00:00:00+08:00" onChange={event => patch({ validTo: event.target.value })} /></label>
      <p>使用左闭右开期间：[起点，终点)。相邻台账须本期起点等于上期终点；时间必须带时区，不采用文件接收时间。声明作为管理员说明留存，不标成原表单元格事实。</p>
    </>}
  </details>
}
