import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, Select, Space, Upload } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { mapFoundationApi, type MapTemplateCreate } from '../../services/mapFoundation'
import { mapLedgerImportsApi, type MapLedgerPreview } from '../../services/mapLedgerImports'
import MapLedgerTemplateForm from './MapLedgerTemplateForm'
import MapImportPlan from './MapImportPlan'
import MapIngestHistory from './MapIngestHistory'
import { downloadMapFile, mapImportError, mapPreviewCanCommit } from './mapLedgerPresentation'

export default function MapLedgerPanel({ sourceId, onChanged, onDirtyChange }: {
  sourceId: number; onChanged: () => void; onDirtyChange: (dirty: boolean) => void
}) {
  const { user, sessionEpoch } = useAuth(), queryClient = useQueryClient()
  const [templateId, setTemplateId] = useState<number>(), [file, setFile] = useState<File | null>(null)
  const [revision, setRevision] = useState(''), [preview, setPreview] = useState<MapLedgerPreview | null>(null)
  const [busy, setBusy] = useState(false), [failure, setFailure] = useState(''), [notice, setNotice] = useState('')
  const [historyDirty, setHistoryDirty] = useState(false), [templateDirty, setTemplateDirty] = useState(false)
  const [pendingWrite, setPendingWrite] = useState(false)
  const mounted = useRef(true), busyRef = useRef(false)
  const attempt = useRef<{ file: File; templateId: number; revision: string; planToken: string } | null>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { onDirtyChange(!!file || historyDirty || templateDirty || pendingWrite); return () => onDirtyChange(false) }, [file, historyDirty, templateDirty, pendingWrite, onDirtyChange])
  const historyDirtyChanged = useCallback((dirty: boolean) => setHistoryDirty(dirty), [])
  const contract = useQuery({ queryKey: ['map-import-fields', user?.id, sessionEpoch], queryFn: ({ signal }) => mapLedgerImportsApi.fields(signal), gcTime: 0 })
  const templates = useQuery({ queryKey: ['map-foundation-templates', user?.id, sessionEpoch, sourceId], queryFn: () => mapFoundationApi.listTemplates(sourceId), gcTime: 0 })
  const selected = templates.isSuccess ? templates.data.find(item => item.id === templateId) : undefined
  const act = async (work: () => Promise<void>) => {
    if (busyRef.current) return
    busyRef.current = true; setBusy(true); setFailure(''); setNotice('')
    try { await work() } catch (error) {
      if (mounted.current) setFailure(`${mapImportError(error).message}。文件选择和当前输入仍保留。`)
    } finally { busyRef.current = false; if (mounted.current) setBusy(false) }
  }
  const inspect = (selectedFile = file) => act(async () => {
    if (!selectedFile) return
    setPreview(null)
    const result = await mapLedgerImportsApi.preview(sourceId, selectedFile, templateId)
    if (mounted.current) setPreview(result)
  })
  const saveTemplate = (payload: MapTemplateCreate) => act(async () => {
    const result = await mapFoundationApi.createTemplate(payload)
    if (!mounted.current) return
    void queryClient.invalidateQueries({ queryKey: ['map-foundation-templates'] })
    setTemplateId(result.id); setPreview(null); setTemplateDirty(false)
    setNotice(`模板 v${result.version} 已保存。请用所选文件重新预览，新模板不改写旧批次。`)
  })
  const ingest = () => act(async () => {
    if (!attempt.current) {
      if (!file || !templateId || !preview || !mapPreviewCanCommit(preview)) return
      attempt.current = { file, templateId, revision, planToken: preview.plan_token }
    }
    setPendingWrite(true)
    const frozen = attempt.current
    try {
      const run = await mapFoundationApi.ingest(sourceId, frozen.templateId, frozen.file, frozen.revision, frozen.planToken)
      if (!mounted.current) return
      attempt.current = null; setPendingWrite(false); setFile(null); setPreview(null)
      setNotice(`批次 ${run.id} 已确认：新增 ${run.created_assets}，更新 ${run.updated_assets}。完整逐行结果见最近批次；身份待对应和异常可继续处理。`)
      void queryClient.invalidateQueries({ queryKey: ['map-ingest-runs'] }); onChanged()
    } catch (error) {
      if (!mounted.current) return
      const { code } = mapImportError(error)
      if (code === 'plan_stale' || code === 'template_drift') { attempt.current = null; setPendingWrite(false); setPreview(null) }
      throw error
    }
  })
  return <section aria-label="生产台账模板预览与导入">
    <Space wrap>
      <Button onClick={() => void act(async () => {
        const blob = await mapLedgerImportsApi.example()
        if (!mounted.current) return
        downloadMapFile(blob, '生产台账-中文字段示例.csv')
      })}>下载中文示例 CSV</Button>
      <Button disabled={busy} onClick={() => { void contract.refetch(); void templates.refetch() }}>刷新字段与模板</Button>
    </Space>
    {contract.isError && <Alert type="error" showIcon message="字段说明读取失败，不能按猜测的字段导入。请重试。" />}
    {templates.isError && <Alert type="error" showIcon message="模板读取失败，未使用旧缓存。" />}
    <h4>复用来源模板</h4>
    <Select aria-label="生产台账导入模板" style={{ width: '100%' }} allowClear placeholder="选择模板；首次可先上传查看表头"
      value={templateId} disabled={busy || pendingWrite || historyDirty} options={templates.isSuccess ? templates.data.map(item => ({ value: item.id, label: `${item.name} · v${item.version}` })) : []}
      onChange={value => { setTemplateId(value); setPreview(null); setFailure('') }} />
    {selected && <p>工作表 {selected.sheet_name || '由文件解析器选择'} · 表头第 {selected.header_row} 行 · {selected.coordinate_system} / {selected.coordinate_unit} · {selected.axis_order === 'lon_lat' ? '经度、纬度' : '纬度、经度'}</p>}
    {contract.isSuccess && <details><summary>配置或复制为新模板，查看全部生产字段说明</summary>
      <MapLedgerTemplateForm sourceId={sourceId} contract={contract.data} selected={selected} structure={preview?.structure}
        busy={busy || pendingWrite || historyDirty} onSave={payload => void saveTemplate(payload)} onDirtyChange={() => setTemplateDirty(true)} />
    </details>}
    <h4>选择文件并核对差异</h4>
    <Input aria-label="台账来源修订" placeholder="来源修订，例如：2026-10 月度台账；不填则由文件摘要辨识" value={revision}
      disabled={busy || pendingWrite} onChange={event => { setRevision(event.target.value); setPreview(null) }} />
    <Upload accept=".csv,.xlsx,.xlsm,.xltx,.xltm" showUploadList={false} disabled={busy || pendingWrite || !contract.isSuccess}
      beforeUpload={item => {
        if (busyRef.current || attempt.current) return false
        setFile(item); setPreview(null); void inspect(item); return false
      }}>
      <Button disabled={busy || pendingWrite || !contract.isSuccess}>选择台账并预览</Button>
    </Upload>
    {file && <p>当前文件：{file.name} <Button disabled={busy || pendingWrite} onClick={() => void inspect()}>重新预览</Button></p>}
    {!templateId && <p>无模板预览只用于读取表头，不能写入。请先明确工作表、坐标系、单位和原列映射，再保存模板。</p>}
    {notice && <Alert type="info" showIcon message={notice} />}
    {failure && <Alert type="warning" showIcon role="alert" message={failure} />}
    {preview && contract.isSuccess && <MapImportPlan preview={preview} fields={contract.data.fields} />}
    <Button type="primary" loading={busy} disabled={busy || !selected || (!pendingWrite && !mapPreviewCanCommit(preview)) || historyDirty}
      onClick={() => void ingest()}>{pendingWrite ? '用原文件与凭证核对并重试' : '按预览写入合格记录'}</Button>
    {pendingWrite && <Alert type="warning" message="提交结果尚待确认；原文件、模板、来源修订和预览凭证已冻结。请使用原请求重试或核对最近批次，不换文件另导。" />}
    <p>台账写入不是底图发布。正常行按已确认规则处理，异常行保留回执，不因同名自动合并设施。</p>
    {contract.isSuccess && <details><summary>最近批次、逐行来源与异常续做</summary>
      <MapIngestHistory sourceId={sourceId} contract={contract.data} templateId={templateId} onChanged={onChanged} onDirtyChange={historyDirtyChanged} />
    </details>}
  </section>
}
