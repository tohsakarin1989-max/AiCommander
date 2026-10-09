import { useEffect, useRef, useState } from 'react'
import { Button, Checkbox, Dropdown, Input, Modal, Space, message } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import api from '../../services/api'
import type { CasePageParams } from '../../services/cases'
import { useAuth } from '../../auth/AuthContext'
import { outputTemplatesApi } from '../../services/outputTemplates'
import type { OutputColumn } from '../../services/outputTemplates'
import OutputTemplatePicker from '../../components/OutputTemplatePicker'

export default function CaseExportMenu({ params }: { params: CasePageParams }) {
  const { user, sessionEpoch } = useAuth()
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  const [custom, setCustom] = useState<OutputColumn[]>()
  const controller = useRef<AbortController | null>(null)
  const active = useRef(true)
  const selection = JSON.stringify([user?.id, sessionEpoch, params, custom])
  const currentSelection = useRef(selection)
  currentSelection.current = selection
  useEffect(() => {
    active.current = true; setBusy(false)
    const cancel = () => { active.current = false; controller.current?.abort() }
    window.addEventListener('aic:auth-expired', cancel)
    return () => { cancel(); window.removeEventListener('aic:auth-expired', cancel) }
  }, [selection])
  const columns = useQuery({ queryKey: ['case-output-columns', user?.id, sessionEpoch],
    queryFn: ({ signal }) => outputTemplatesApi.columns(signal), enabled: open, retry: false, gcTime: 0 })
  const selected = custom || columns.data || []
  const validation = selected.length === 0 ? '请选择至少一个有效列'
    : !selected.some(column => column.key === 'case_number') ? '必须保留记录编号'
      : selected.some(column => column.key === 'oil_volume') && !selected.some(column => column.key === 'oil_volume_unit') ? '数量必须与单位同时导出'
        : selected.some(column => !column.label.trim()) ? '表头不能为空' : ''
  const download = async (format: 'csv' | 'xlsx') => {
    if (busy) return
    if (custom && validation) { message.error(validation); return }
    const abort = new AbortController(); controller.current = abort
    setBusy(true)
    try {
      const { page: _page, page_size: _size, ...filters } = params
      const response = await api.get(`/case-exports/ledger.${format}`, {
        params: { ...filters, time_basis: filters.time_basis || 'discovery',
          ...(custom ? { output_configuration: JSON.stringify({ columns: custom }) } : {}) },
        paramsSerializer: { indexes: null }, responseType: 'blob',
        signal: abort.signal,
      })
      if (!active.current || abort.signal.aborted || currentSelection.current !== selection) return
      const url = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = `案件明细.${format}`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      message.success('已导出当前筛选的全部授权记录，请按内部资料保管')
    } catch {
      if (active.current && !abort.signal.aborted && currentSelection.current === selection) message.error('导出未完成，请检查权限、服务状态或缩小筛选范围后重试')
    } finally {
      if (active.current && currentSelection.current === selection) setBusy(false)
    }
  }
  return <><Dropdown disabled={busy} menu={{ items: [
    { key: 'xlsx', label: 'Excel 明细（含口径说明）' }, { key: 'csv', label: 'CSV 明细（含口径说明）' },
    { key: 'configure', label: '选择列与中文表头…' },
  ], onClick: ({ key }) => key === 'configure' ? setOpen(true) : void download(key as 'csv' | 'xlsx') }}>
    <Button loading={busy} icon={<DownloadOutlined />}>导出筛选明细</Button>
  </Dropdown><Modal title="通用台账列与中文表头" open={open} onCancel={() => !busy && setOpen(false)} width={720} footer={
    <Space><Button onClick={() => setCustom(undefined)} disabled={busy}>恢复默认列</Button>
      <Button disabled={busy || !!columns.error || !!validation} onClick={() => void download('csv')}>导出 CSV</Button>
      <Button type="primary" disabled={busy || !!columns.error || !!validation} loading={busy} onClick={() => void download('xlsx')}>导出 Excel</Button></Space>}>
    <p>沿用当前筛选，导出全部授权匹配记录，不受当前页大小影响。用户配置未经过单位官方表样确认；来源编号、时间口径与边界不可隐藏。</p>
    {columns.isPending ? <p role="status">正在读取可选列…</p> : columns.error ? <p role="alert">可选列暂不可读，请稍后重试。</p> : <div style={{ display: 'grid', gap: 8 }}>
      {columns.data?.map(column => {
        const value = selected.find(item => item.key === column.key)
        return <Space key={column.key} style={{ display: 'flex' }}><Checkbox checked={!!value} disabled={busy || column.key === 'case_number'} onChange={event =>
          setCustom(event.target.checked ? [...selected, column] : selected.filter(item => item.key !== column.key))}>{column.label}</Checkbox>
          {value && <Input aria-label={`${column.label}导出表头`} value={value.label} maxLength={60} disabled={busy} onChange={event =>
            setCustom(selected.map(item => item.key === column.key ? { ...item, label: event.target.value } : item))} />}</Space>
      })}
    </div>}
    {validation && <p role="alert">{validation}</p>}
    {columns.data && <OutputTemplatePicker key={`${user?.id}:${sessionEpoch}`} kind="case_ledger" configuration={{ columns: selected }} onApply={configuration => {
      if ('columns' in configuration) setCustom(configuration.columns)
    }} />}
    <small>配置仅保存在服务器；不会把案情写入浏览器本地存储。未知值留空，数量不跨单位汇总。</small>
  </Modal></>
}
