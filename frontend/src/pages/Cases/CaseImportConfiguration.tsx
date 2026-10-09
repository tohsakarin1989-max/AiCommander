import { useEffect, useState } from 'react'
import { Alert, Button, Input, Select } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import type { CaseImportOptions } from '../../services/cases'
import { caseImportsApi, type ImportHeaders } from '../../services/caseImports'
import { importFieldLabels, importTimeZoneLabel } from './importCorrection'

interface Props {
  file: File | null
  areaId?: number
  settings: CaseImportOptions
  disabled: boolean
  onChange: (settings: CaseImportOptions) => void
  onBusyChange: (busy: boolean) => void
}

export default function CaseImportConfiguration({ file, areaId, settings, disabled, onChange, onBusyChange }: Props) {
  const { user, sessionEpoch } = useAuth()
  const client = useQueryClient()
  const [headers, setHeaders] = useState<ImportHeaders | null>(null)
  const [name, setName] = useState('')
  const [notice, setNotice] = useState('')
  const key = ['case-import-templates', user?.id, sessionEpoch]
  const templates = useQuery({ queryKey: key, queryFn: ({ signal }) => caseImportsApi.templates(signal), retry: false })
  const inspect = useMutation({
    mutationFn: () => caseImportsApi.inspect(file!, areaId, settings),
    onSuccess: setHeaders,
  })
  const save = useMutation({
    mutationFn: () => caseImportsApi.saveTemplate(name.trim(), areaId, settings),
    onSuccess: () => { setNotice('模板已保存，可用于后续同类台账'); void client.invalidateQueries({ queryKey: key }) },
  })
  useEffect(() => { setHeaders(null); inspect.reset(); setNotice('') }, [file, areaId, settings.worksheet, settings.header_row, settings.import_preset])
  useEffect(() => {
    onBusyChange(inspect.isPending || save.isPending)
    return () => onBusyChange(false)
  }, [inspect.isPending, save.isPending, onBusyChange])
  const busy = disabled || inspect.isPending || save.isPending
  return <details style={{ marginBottom: 14 }}>
    <summary>字段映射与导入模板</summary>
    <div style={{ padding: '12px 0' }}>
      <p>模板只保存列名和解析设置，不保存案件内容。使用后仍须预览。</p>
      {settings.import_preset === 'security_ledger' ? <p>本预设保留行号作为出处，不把年度序号当作跨表稳定编号；暂按首次新增导入，相同文件与设置重传不会重复建案。</p> : <fieldset style={{ marginBottom: 12 }}><legend>持续更新来源（可选）</legend>
        <label>已确认的来源标识<Input aria-label="案件台账来源标识" value={settings.source_key || ''} maxLength={80} disabled={busy}
          placeholder="例如：本单位案件月台账；同一来源后续保持不变"
          onChange={event => onChange({ ...settings, source_key: event.target.value })} /></label>
        <label>来源表版本<Input aria-label="案件台账来源表版本" value={settings.source_revision || ''} maxLength={80} disabled={busy || !settings.source_key?.trim()}
          placeholder="可选，例如：2026-10修订1；不是文件名"
          onChange={event => onChange({ ...settings, source_revision: event.target.value })} /></label>
        <p>使用持续更新时，必须把来源中的稳定编号列映射为“外部稳定记录键”。不以文件名、行号、相似文本或系统案件编号猜测身份。</p>
        <p>不填来源则按普通首次新增处理；相同文件幂等不等于不同文件能自动识别同一案件。来源冲突、人工已修改和空白清值不自动覆盖。</p>
      </fieldset>}
      {templates.isError && <Alert type="error" message="模板读取失败或无权访问" />}
      <Select aria-label="套用导入模板" placeholder="选择本厂区已有模板" style={{ width: '100%' }}
        disabled={busy || !templates.isSuccess} value={null}
        options={(templates.isSuccess ? templates.data : []).filter(item => item.operational_area_id === areaId)
          .map(item => ({ value: item.id, label: `${item.name} · ${importTimeZoneLabel(item.settings.time_zone)}` }))}
        onChange={id => {
          const template = templates.data?.find(item => item.id === id)
          if (template) { onChange(template.settings); setNotice(`已套用“${template.name}”。无时区时间按${importTimeZoneLabel(template.settings.time_zone)}解释，请重新预览。`) }
        }} />
      <Button disabled={!file || busy} onClick={() => { inspect.reset(); setHeaders(null); inspect.mutate() }} style={{ margin: '12px 0' }}>
        读取文件列名
      </Button>
      <Button disabled={busy} onClick={() => onChange({ ...settings, field_mapping: {} })}>清除自定义映射</Button>
      {inspect.isError && <Alert type="error" message="列名读取失败，请核对工作表、表头行与文件格式" />}
      {headers && <>
        {!!headers.warnings?.length && <Alert type="info" message="台账字段保留规则"
          description={<ul>{headers.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>} />}
        {!!headers.worksheets.length && <Select aria-label="选择导入工作表" style={{ width: '100%', marginBottom: 12 }}
          disabled={busy} value={headers.worksheet} options={headers.worksheets.map(value => ({ value, label: value }))}
          onChange={worksheet => onChange({ ...settings, worksheet, field_mapping: {} })} />}
        <div style={{ maxHeight: 260, overflowY: 'auto' }}>
          {headers.headers.map(header => <label key={header} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
            <span style={{ overflowWrap: 'anywhere' }}>{header}</span>
            <select aria-label={`列${header}对应字段`} disabled={busy || (settings.import_preset === 'security_ledger' && !headers.suggested_mapping[header])}
              style={{ width: '100%', minWidth: 0, padding: 6, color: 'var(--ink-0)', background: 'var(--bg-2)', border: '1px solid var(--line)' }}
              value={Object.prototype.hasOwnProperty.call(settings.field_mapping ?? {}, header)
                ? settings.field_mapping![header] ?? '' : headers.suggested_mapping[header] ?? ''}
              onChange={event => onChange({ ...settings, field_mapping: { ...settings.field_mapping, [header]: event.target.value || null } })}>
              <option value="">{settings.import_preset === 'security_ledger' ? '仅保留来源原值' : '不映射业务字段'}</option>
              {Object.entries(importFieldLabels).filter(([value]) => settings.import_preset !== 'security_ledger' || value === headers.suggested_mapping[header])
                .map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>)}
        </div>
      </>}
      <Input aria-label="导入模板名称" placeholder="模板名称，例如：生产案件月台账" maxLength={80} disabled={busy}
        value={name} onChange={event => { setName(event.target.value); setNotice(''); save.reset() }} />
      <Button disabled={busy || !name.trim() || areaId == null} onClick={() => save.mutate()} style={{ marginTop: 8 }}>保存当前导入模板</Button>
      {save.isError && <Alert type="error" message="模板保存失败，请检查映射冲突、设置和权限" />}
      {notice && <Alert type="info" message={notice} />}
    </div>
  </details>
}
