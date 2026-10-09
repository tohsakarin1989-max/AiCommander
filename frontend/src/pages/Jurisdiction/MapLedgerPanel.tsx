import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, InputNumber, Select, Space, Upload } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { mapFoundationApi, type MapTemplateCreate, type MapLedgerDeclaration } from '../../services/mapFoundation'
import { mapLedgerImportsApi, type MapLedgerPreview, type MapTableInspection } from '../../services/mapLedgerImports'
import MapLedgerJobs from './MapLedgerJobs'
import MapLedgerTemplateForm from './MapLedgerTemplateForm'
import MapImportPlan from './MapImportPlan'
import MapIngestHistory from './MapIngestHistory'
import MapLedgerDeclarationForm, { emptyLedgerDeclaration, ledgerDeclarationPayload, type LedgerDeclarationDraft } from './MapLedgerDeclaration'
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
  const [inspection, setInspection] = useState<MapTableInspection | null>(null)
  const [pastedText, setPastedText] = useState(''), [inputKind, setInputKind] = useState<'file' | 'clipboard'>('file')
  const [sheetName, setSheetName] = useState<string>(), [headerRow, setHeaderRow] = useState(1)
  const [declaration, setDeclaration] = useState<LedgerDeclarationDraft>(emptyLedgerDeclaration)
  const mounted = useRef(true), busyRef = useRef(false)
  const attempt = useRef<{ file: File; templateId: number; revision: string; planToken: string; declaration?: MapLedgerDeclaration } | null>(null)
  const queuedAttempt = useRef<{ file: File; templateId: number; revision: string; declaration?: MapLedgerDeclaration; inputKind: 'file' | 'clipboard' } | null>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { onDirtyChange(!!file || !!pastedText || historyDirty || templateDirty || pendingWrite || declaration.mode !== 'unknown'); return () => onDirtyChange(false) }, [file, pastedText, historyDirty, templateDirty, pendingWrite, declaration.mode, onDirtyChange])
  const historyDirtyChanged = useCallback((dirty: boolean) => setHistoryDirty(dirty), [])
  const contract = useQuery({ queryKey: ['map-import-fields', user?.id, sessionEpoch], queryFn: ({ signal }) => mapLedgerImportsApi.fields(signal), gcTime: 0 })
  const templates = useQuery({ queryKey: ['map-foundation-templates', user?.id, sessionEpoch, sourceId], queryFn: () => mapFoundationApi.listTemplates(sourceId), gcTime: 0 })
  const selected = templates.isSuccess ? templates.data.find(item => item.id === templateId) : undefined
  const sheetMatches = !!inspection && inspection.structure.header_row === headerRow
    && (inspection.structure.sheet_name || undefined) === sheetName && !!selected
    && selected.header_row === headerRow
    && (selected.sheet_name || inspection.structure.available_sheets?.[0] || undefined) === sheetName
    && Object.values(selected.field_mapping || {}).filter(value => typeof value === 'string').every(value => inspection.structure.headers.includes(value as string))
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
    const scope = ledgerDeclarationPayload(declaration)
    const result = await (scope ? mapLedgerImportsApi.preview(sourceId, selectedFile, templateId, undefined, scope)
      : mapLedgerImportsApi.preview(sourceId, selectedFile, templateId))
    if (mounted.current) setPreview(result)
  })
  const inspectHeaders = (selectedFile = file, sheet = sheetName, header = headerRow) => act(async () => {
    if (!selectedFile) return
    setInspection(null); setPreview(null)
    const result = await mapLedgerImportsApi.inspect(sourceId, selectedFile, sheet, header)
    if (!mounted.current) return
    setInspection(result); setSheetName(result.structure.sheet_name || undefined); setHeaderRow(result.structure.header_row)
    if (!templateId && result.recommended_template_id) {
      setTemplateId(result.recommended_template_id)
      setNotice('已带出该来源唯一匹配的已确认模板。坐标和单位沿用模板，完整行核对在后台进行。')
    }
  })
  const queue = () => act(async () => {
    if (!queuedAttempt.current) {
      if (!file || !templateId || !selected || !sheetMatches || templateDirty) return
      queuedAttempt.current = { file, templateId, revision, declaration: ledgerDeclarationPayload(declaration), inputKind }
    }
    setPendingWrite(true)
    const frozen = queuedAttempt.current
    const result = frozen.inputKind === 'clipboard'
      ? await mapLedgerImportsApi.enqueue(sourceId, frozen.file, frozen.templateId, frozen.revision, frozen.declaration, 'clipboard')
      : await mapLedgerImportsApi.enqueue(sourceId, frozen.file, frozen.templateId, frozen.revision, frozen.declaration)
    if (!mounted.current) return
    queuedAttempt.current = null; setPendingWrite(false)
    setNotice(`原件与批次 ${result.id} 已保存，后台继续整理；现在可以离页。正式设施在整批采用前保持不变。`)
    setFile(null); setPastedText(''); setInspection(null); setPreview(null); setDeclaration(emptyLedgerDeclaration)
    void queryClient.invalidateQueries({ queryKey: ['map-ingest-runs'] })
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
      attempt.current = { file, templateId, revision, planToken: preview.plan_token, declaration: ledgerDeclarationPayload(declaration) }
    }
    setPendingWrite(true)
    const frozen = attempt.current
    try {
      const run = await (frozen.declaration ? mapFoundationApi.ingest(sourceId, frozen.templateId, frozen.file, frozen.revision, frozen.planToken, frozen.declaration)
        : mapFoundationApi.ingest(sourceId, frozen.templateId, frozen.file, frozen.revision, frozen.planToken))
      if (!mounted.current) return
      attempt.current = null; setPendingWrite(false); setFile(null); setPreview(null); setDeclaration(emptyLedgerDeclaration)
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
      <MapLedgerTemplateForm sourceId={sourceId} contract={contract.data} selected={selected} structure={inspection?.structure || preview?.structure}
        busy={busy || pendingWrite || historyDirty} onSave={payload => void saveTemplate(payload)} onDirtyChange={() => setTemplateDirty(true)} />
    </details>}
    <h4>选择文件并核对差异</h4>
    <MapLedgerDeclarationForm sourceId={sourceId} value={declaration} disabled={busy || pendingWrite || historyDirty}
      onChange={value => { setDeclaration(value); setPreview(null); setFailure('') }} />
    <Input aria-label="台账来源修订" placeholder="来源修订，例如：2026-10 月度台账；不填则由文件摘要辨识" value={revision}
      disabled={busy || pendingWrite} onChange={event => { setRevision(event.target.value); setPreview(null) }} />
    <Upload accept=".csv,.tsv,.xlsx,.xlsm,.xltx,.xltm" showUploadList={false} disabled={busy || pendingWrite || !contract.isSuccess}
      beforeUpload={item => {
        if (busyRef.current || attempt.current || queuedAttempt.current) return false
        setFile(item); setInputKind('file'); setPreview(null); setInspection(null); void inspectHeaders(item); return false
      }}>
      <Button disabled={busy || pendingWrite || !contract.isSuccess}>选择台账并读取表头</Button>
    </Upload>
    <details><summary>从 Excel 选区粘贴（含表头）</summary>
      <p>按原样保存粘贴的制表符文本，标为人工粘贴来源；不声称保留完整工作簿。坐标和单位仍须明确模板。</p>
      <textarea aria-label="生产台账粘贴原文" value={pastedText} disabled={busy || pendingWrite} rows={5} style={{ width: '100%' }}
        onChange={event => setPastedText(event.target.value)} />
      <Button disabled={busy || pendingWrite || !pastedText.trim() || !contract.isSuccess} onClick={() => {
        if (busyRef.current || attempt.current || queuedAttempt.current) return
        const item = new File([pastedText], '人工粘贴.tsv', { type: 'text/tab-separated-values' })
        setFile(item); setInputKind('clipboard'); setPreview(null); setInspection(null); setSheetName(undefined); setHeaderRow(1)
        void inspectHeaders(item, undefined, 1)
      }}>读取粘贴表头</Button>
    </details>
    {file && <><p>当前文件：{file.name}</p><Space wrap>
      {!!inspection?.structure.available_sheets?.length && <Select aria-label="实际工作表" value={sheetName} disabled={busy || pendingWrite}
        options={inspection.structure.available_sheets.map(value => ({ value, label: value }))} onChange={value => { setSheetName(value); setPreview(null) }} />}
      <label>表头行 <InputNumber aria-label="实际表头行" value={headerRow} min={1} max={100} disabled={busy || pendingWrite}
        onChange={value => { setHeaderRow(value || 1); setPreview(null) }} /></label>
      <Button disabled={busy || pendingWrite} onClick={() => void inspectHeaders()}>读取所选表头</Button>
    </Space>{inspection && <p>实际列：{inspection.structure.headers.filter(Boolean).join('、')}。{inspection.boundary}</p>}
    {!sheetMatches && selected && inspection && <Alert type="warning" message="所选工作表、表头或映射与模板不一致；请读取当前表头并保存匹配模板后再处理。" />}
    {templateDirty && <Alert type="warning" message="模板有尚未保存的修改；保存后才会用于后台整理。" />}
    <Button type="primary" disabled={busy || (pendingWrite && !queuedAttempt.current) || !selected || historyDirty || templateDirty || (!queuedAttempt.current && !sheetMatches)}
      onClick={() => void queue()}>{queuedAttempt.current ? '按原请求核对后台接收结果' : '后台整理并按来源规则采用'}</Button>
    <details><summary>少量资料同步预览（兼容入口）</summary><Button disabled={busy || pendingWrite || inputKind === 'clipboard' || file.size > 256 * 1024} onClick={() => void inspect()}>重新预览</Button>
      <p>较大文件使用上面的后台整理，避免页面长时间等待。</p></details></>}
    {!templateId && <p>无模板预览只用于读取表头，不能写入。请先明确工作表、坐标系、单位和原列映射，再保存模板。</p>}
    {notice && <Alert type="info" showIcon message={notice} />}
    {failure && <Alert type="warning" showIcon role="alert" message={failure} />}
    {preview && contract.isSuccess && <MapImportPlan preview={preview} fields={contract.data.fields} />}
    <Button type="primary" loading={busy} disabled={busy || !!queuedAttempt.current || !selected || (!pendingWrite && !mapPreviewCanCommit(preview)) || historyDirty}
      onClick={() => void ingest()}>{pendingWrite && !queuedAttempt.current ? '用原文件与凭证核对并重试' : '按预览写入合格记录'}</Button>
    {pendingWrite && <Alert type="warning" message={queuedAttempt.current ? '后台接收结果尚待确认；原文件、模板和来源修订已冻结。按原请求核对，不能另换文件重复导入。' : '提交结果尚待确认；原文件、模板、来源修订和预览凭证已冻结。请使用原请求重试或核对最近批次，不换文件另导。'} />}
    <p>台账写入不是底图发布。正常行按已确认规则处理，异常行保留回执，不因同名自动合并设施。</p>
    {contract.isSuccess && <MapLedgerJobs sourceId={sourceId} contract={contract.data} onChanged={onChanged} />}
    {contract.isSuccess && <details><summary>最近批次、逐行来源与异常续做</summary>
      <MapIngestHistory sourceId={sourceId} contract={contract.data} templateId={templateId} onChanged={onChanged} onDirtyChange={historyDirtyChanged} />
    </details>}
  </section>
}
