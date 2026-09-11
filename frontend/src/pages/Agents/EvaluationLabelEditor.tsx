import { useDeferredValue, useState } from 'react'
import { Alert, Button, Input, Select, Space, Spin } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { governanceApi, type EvaluationLabel } from '../../services/governance'
import { existingLabel, labelPayload, type LabelDraft } from './evaluationLabels'

const TYPES = [{ value: 'possible_source', label: '盗取来源' }, { value: 'storage_area', label: '囤储区域' },
  { value: 'activity_area', label: '活动区域' }, { value: 'transfer_route', label: '转运方向或路径' }]

export default function EvaluationLabelEditor({ datasetId }: { datasetId: number }) {
  const cache = useQueryClient()
  const [caseId, setCaseId] = useState<number>()
  const [drafts, setDrafts] = useState<Record<number, LabelDraft>>({})
  const [version, setVersion] = useState('')
  const [reason, setReason] = useState('')
  const [search, setSearch] = useState('')
  const term = useDeferredValue(search)
  const source = useQuery({ queryKey: ['evaluation-labels', datasetId], queryFn: () => governanceApi.getLabels(datasetId), retry: false })
  const activeId = caseId ?? source.data?.case_ids[0]
  const assets = useQuery({ queryKey: ['evaluation-label-assets', datasetId, activeId, term],
    queryFn: () => governanceApi.searchLabelAssets(datasetId, activeId!, term), enabled: !!activeId && !source.isError, retry: false })
  let payload: ReturnType<typeof labelPayload> | undefined
  try { if (source.data) payload = labelPayload(source.data, drafts) } catch { /* Incomplete edits cannot be saved. */ }
  const save = useMutation({ mutationFn: () => {
    if (!payload || source.isError) throw new Error('labels_unavailable')
    return governanceApi.reviseLabels(datasetId, { ...payload, version: version.trim(), reason: reason.trim() })
  }, retry: false, onSuccess: () => { void cache.invalidateQueries({ queryKey: ['fixed-datasets'] }) } })
  if (source.isError) return <Alert type="warning" message="标签或来源不可读取，已隐藏旧内容。" />
  if (!source.data || activeId === undefined) return <Spin />
  const data = source.data
  const draft = drafts[activeId] || existingLabel(data, activeId)
  const locked = save.isPending || save.isSuccess || source.isFetching
  const change = (value: LabelDraft) => setDrafts(previous => ({ ...previous, [activeId]: value }))
  const editLabel = (index: number, patch: Partial<EvaluationLabel>) => change({ ...draft,
    labels: draft.labels.map((label, at) => at === index ? { ...label, ...patch } : label) })
  const options = [...new Map([...data.label_assets, ...(assets.isError ? [] : assets.data?.items || [])]
    .map(item => [item.id, { value: item.id, label: item.name }])).values()]
  return <div className="evaluation-label-editor">
    <p>仅按人工核验资料填写，不把系统候选直接当作答案。保存生成新版本；没有修改的其他样本保持原标签。</p>
    <label>评测样本<Select aria-label="评测样本" value={activeId} disabled={locked}
      options={data.cases.map(row => ({ value: row.id, label: row.case_number }))}
      onChange={id => { setCaseId(id); setSearch('') }} /></label>
    <label>核验状态<Select aria-label="核验状态" value={draft.state} disabled={locked}
      options={[{ value: 'unlabeled', label: '尚未标注，不计正确率' }, { value: 'negative', label: '人工确认无候选（阴性）' }, { value: 'positive', label: '有人工确认目标（阳性）' }]}
      onChange={state => change({ state, labels: state === 'positive' ? [{ hypothesis_type: 'possible_source', expected_asset_ids: [] }] : [] })} /></label>
    {draft.state === 'positive' && <>
      {draft.labels.map((label, index) => <div className="evaluation-label-editor__target" key={index}>
        <label>目标类型<Select aria-label={`目标类型${index + 1}`} value={label.hypothesis_type} options={TYPES} disabled={locked}
          onChange={hypothesis_type => editLabel(index, { hypothesis_type })} /></label>
        <label>核验设施<Select mode="multiple" aria-label={`核验设施${index + 1}`} value={label.expected_asset_ids} options={options}
          filterOption={false} showSearch onSearch={setSearch} loading={assets.isFetching} disabled={locked || assets.isError}
          placeholder="按名称查找，仅列该样本辖区设施" onChange={expected_asset_ids => editLabel(index, { expected_asset_ids })} maxCount={20} /></label>
        <label>核验网格（没有对应设施时填写）<Input aria-label={`核验网格${index + 1}`} value={label.expected_region_grid || ''}
          maxLength={32} disabled={locked} placeholder="纬度:经度，例如 47.00:125.00"
          onChange={event => editLabel(index, { expected_region_grid: event.target.value || null })} /></label>
        <Button size="small" disabled={locked} onClick={() => change({ ...draft, labels: draft.labels.filter((_, at) => at !== index) })}>移除此目标</Button>
      </div>)}
      {assets.isError && <Alert type="warning" message="设施查询失败，请重试；不使用未授权或缓存中的查找结果。" />}
      {assets.data?.has_more && <p>还有更多设施，请输入更完整的名称缩小范围。</p>}
      <Button disabled={locked || draft.labels.length >= 20} onClick={() => change({ ...draft, labels: [...draft.labels, { hypothesis_type: 'possible_source', expected_asset_ids: [] }] })}>增加核验目标</Button>
    </>}
    <label>新标签版本<Input aria-label="新标签版本" maxLength={80} value={version} disabled={locked} placeholder={`不能覆盖 ${data.version}`}
      onChange={event => setVersion(event.target.value)} /></label>
    <label>修订原因与核验依据<Input.TextArea aria-label="修订原因与核验依据" rows={2} maxLength={500} value={reason} disabled={locked}
      onChange={event => setReason(event.target.value)} /></label>
    <Space wrap><Button type="primary" loading={save.isPending} disabled={locked || !payload || !version.trim() || version.trim() === data.version || !reason.trim()}
      onClick={() => save.mutate()}>另存标签版本</Button><span>未标注不等于阴性；未完成的阳性目标不能保存。</span></Space>
    {save.isError && <Alert type="error" message="未能保存，请核对版本、目标、网格格式和当前权限。旧标签未修改。" />}
    {save.isSuccess && <Alert type="success" message="新标签版本已保存，请在数据集列表选择新版本后运行评测。" />}
  </div>
}
