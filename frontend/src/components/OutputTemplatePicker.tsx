import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { authApi } from '../services/auth'
import { outputTemplatesApi } from '../services/outputTemplates'
import type { OutputConfiguration, OutputTemplateKind } from '../services/outputTemplates'

/** Only names, field selections and headings; never case text or browser persistence. */
export default function OutputTemplatePicker({ kind, configuration, onApply }: {
  kind: OutputTemplateKind; configuration: OutputConfiguration; onApply: (value: OutputConfiguration) => void
}) {
  const { user, sessionEpoch } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'analyst'
  const [name, setName] = useState('')
  const [area, setArea] = useState<number>()
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const identity = `${user?.id}:${sessionEpoch}`
  const saved = useQuery({ queryKey: ['output-templates', identity, kind],
    queryFn: ({ signal }) => outputTemplatesApi.list(kind, signal), retry: false, gcTime: 0 })
  const scopes = useQuery({ queryKey: ['output-template-areas', identity], queryFn: authApi.myAreaScopes,
    enabled: canWrite, retry: false, gcTime: 0 })
  const writable = (scopes.data || []).filter(scope => scope.access_level === 'write' || scope.access_level === 'manage')
  const chosenArea = writable.some(scope => scope.operational_area_id === area) ? area
    : (writable.find(scope => scope.is_default) || writable[0])?.operational_area_id
  async function save() {
    if (!canWrite || !chosenArea || !name.trim() || busy) return
    setBusy(true); setNotice('')
    try {
      await outputTemplatesApi.save(kind, name.trim(), configuration, chosenArea)
      setNotice('已保存新的用户配置；不代表单位官方表样已确认。')
      setName(''); await saved.refetch()
    } catch { setNotice('保存未确认。请先刷新配置列表核对，避免重复保存。') }
    finally { setBusy(false) }
  }
  return <div className="output-template-picker">
    <label>已保存的用户配置 <select value="" disabled={busy || !!saved.error} onChange={event => {
      const item = saved.data?.find(row => row.id === event.target.value)
      if (item) onApply(item.configuration)
    }}><option value="">选择配置，不改变当前业务范围</option>{saved.data?.map(row =>
      <option key={row.id} value={row.id}>{row.name} · 范围 {row.operational_area_id} · v{row.version}</option>)}</select></label>
    {saved.error && <p role="alert">配置列表暂不可读，不影响本次选择与导出。<button type="button" onClick={() => void saved.refetch()}>重读配置</button></p>}
    {canWrite && <details><summary>保存为可复用配置</summary>
      <p>保存在所选范围，范围内用户可复用；只保存列名或章节选择，不保存案件内容。修改后另存，不覆盖已存配置。</p>
      <label>配置名称 <input value={name} maxLength={80} onChange={event => setName(event.target.value)} /></label>
      <label>保存范围 <select value={chosenArea || ''} onChange={event => setArea(Number(event.target.value))}>
        {!writable.length && <option value="">无可写范围或范围读取未完成</option>}
        {writable.map(scope => <option key={scope.operational_area_id} value={scope.operational_area_id}>{scope.area_name}</option>)}</select></label>
      <button type="button" className="btn-ghost" disabled={busy || !chosenArea || !name.trim()} onClick={() => void save()}>{busy ? '正在保存…' : '保存当前配置'}</button>
    </details>}
    <small>用户配置，未经过单位官方表样确认。必要来源、时间口径、单位及适用边界仍保留。</small>
    {notice && <p role="status">{notice}</p>}
  </div>
}
