import { useEffect, useState } from 'react'
import { Alert, Button, Input, Select } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import type { CaseImportOptions } from '../../services/cases'
import { caseImportsApi, type ImportHeaders } from '../../services/caseImports'
import { importFieldLabels } from './importCorrection'

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
  useEffect(() => { setHeaders(null); inspect.reset(); setNotice('') }, [file, areaId, settings.worksheet, settings.header_row])
  useEffect(() => {
    onBusyChange(inspect.isPending || save.isPending)
    return () => onBusyChange(false)
  }, [inspect.isPending, save.isPending, onBusyChange])
  const busy = disabled || inspect.isPending || save.isPending
  return <details style={{ marginBottom: 14 }}>
    <summary>字段映射与导入模板</summary>
    <div style={{ padding: '12px 0' }}>
      <p>模板只保存列名和解析设置，不保存案件内容。使用后仍须预览。</p>
      {templates.isError && <Alert type="error" message="模板读取失败或无权访问" />}
      <Select aria-label="套用导入模板" placeholder="选择本厂区已有模板" style={{ width: '100%' }}
        disabled={busy || !templates.isSuccess} value={null}
        options={(templates.isSuccess ? templates.data : []).filter(item => item.operational_area_id === areaId)
          .map(item => ({ value: item.id, label: `${item.name} · ${item.id.slice(0, 8)}` }))}
        onChange={id => {
          const template = templates.data?.find(item => item.id === id)
          if (template) { onChange(template.settings); setNotice(`已套用“${template.name}”，请重新预览`) }
        }} />
      <Button disabled={!file || busy} onClick={() => { inspect.reset(); setHeaders(null); inspect.mutate() }} style={{ margin: '12px 0' }}>
        读取文件列名
      </Button>
      <Button disabled={busy} onClick={() => onChange({ ...settings, field_mapping: {} })}>清除自定义映射</Button>
      {inspect.isError && <Alert type="error" message="列名读取失败，请核对工作表、表头行与文件格式" />}
      {headers && <>
        {!!headers.worksheets.length && <Select aria-label="选择导入工作表" style={{ width: '100%', marginBottom: 12 }}
          disabled={busy} value={headers.worksheet} options={headers.worksheets.map(value => ({ value, label: value }))}
          onChange={worksheet => onChange({ ...settings, worksheet, field_mapping: {} })} />}
        <div style={{ maxHeight: 260, overflowY: 'auto' }}>
          {headers.headers.map(header => <label key={header} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
            <span style={{ overflowWrap: 'anywhere' }}>{header}</span>
            <select aria-label={`列${header}对应字段`} disabled={busy}
              style={{ width: '100%', minWidth: 0, padding: 6, color: 'var(--ink-0)', background: 'var(--bg-2)', border: '1px solid var(--line)' }}
              value={Object.prototype.hasOwnProperty.call(settings.field_mapping ?? {}, header)
                ? settings.field_mapping![header] ?? '' : headers.suggested_mapping[header] ?? ''}
              onChange={event => onChange({ ...settings, field_mapping: { ...settings.field_mapping, [header]: event.target.value || null } })}>
              <option value="">不导入</option>
              {Object.entries(importFieldLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
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
