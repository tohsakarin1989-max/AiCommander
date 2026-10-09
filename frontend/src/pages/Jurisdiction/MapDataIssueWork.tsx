import { useState } from 'react'
import { Alert, Button, Form, Input, InputNumber, Pagination, Select, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { mapDataIssuesApi, type MapDataIssue } from '../../services/mapDataIssues'
import { issueGroupLabels, issueStateLabels } from '../../components/Facility/FacilityDataIssues'
import { openFacilityDossier } from '../../services/regionalContext'

export default function MapDataIssueWork({ sourceId }: { sourceId?: number }) {
  const { user, sessionEpoch } = useAuth()
  const [page, setPage] = useState(1), [selected, setSelected] = useState<MapDataIssue | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [form] = Form.useForm<{ state: string; note: string; claimId?: number; versionId?: number }>()
  const state = Form.useWatch('state', form)
  const query = useQuery({ queryKey: ['map-data-issue-work', user?.id, sessionEpoch, sourceId, page], gcTime: 0,
    queryFn: ({ signal }) => mapDataIssuesApi.work(sourceId, page, signal) })
  const submit = async (values: { state: string; note: string; claimId?: number; versionId?: number }) => {
    if (!selected) return
    setBusy(true); setError('')
    try {
      await mapDataIssuesApi.resolve(selected.id, { state: values.state, note: values.note,
        expected_state: selected.state, request_id: crypto.randomUUID(),
        ...(values.claimId || values.versionId ? { source_reference: { field_group: selected.source_reference.field_group,
          source_claim_id: values.claimId, asset_version_id: values.versionId } } : {}) })
      setSelected(null); form.resetFields(); void query.refetch()
    } catch { setError('处理未确认；请保留说明并刷新核对当前状态、来源和权限。') }
    finally { setBusy(false) }
  }
  return <section aria-label="资料问题核对"><h3>资料问题核对</h3>
    <p>汇总员工标注，核实后写明依据。需要改资料时先修改来源或明确采用新修订，本回执不替代资料修改。</p>
    {query.isError ? <Alert type="warning" message="资料问题暂不可读，不能据此视为问题清零。" /> : query.isSuccess && <>
      {!query.data.items.length && <p>当前可访问来源中没有问题标注。</p>}
      {query.data.items.map(item => <div key={item.id}><strong>{item.asset_name || `设施 ${item.asset_id}`}</strong> · {issueGroupLabels[item.source_reference.field_group]} · {issueStateLabels[item.state]}
        <p>{item.notes}</p>{item.resolution && <p>上次核对：{item.resolution.note}</p>}
        <Space><Button onClick={() => openFacilityDossier(item.asset_id)}>查看设施与来源版本</Button>
          <Button disabled={busy} onClick={() => { setSelected(item); form.resetFields(); setError('') }}>记录核对结果</Button></Space>
      </div>)}<Pagination current={page} pageSize={10} total={query.data.total} onChange={setPage} showSizeChanger={false} />
    </>}
    {selected && <Form form={form} layout="vertical" onFinish={submit} disabled={busy} initialValues={{ state: 'needs_information' }}>
      <h4>问题 #{selected.id}</h4>
      <Form.Item name="state" label="核对结果" rules={[{ required: true }]}><Select options={Object.entries(issueStateLabels).filter(([key]) => key !== 'reported').map(([value, label]) => ({ value, label }))} /></Form.Item>
      <Form.Item name="note" label="核实依据或待补内容" rules={[{ required: true, whitespace: true }, { max: 2000 }]}><Input.TextArea rows={3} /></Form.Item>
      {state === 'corrected' && <><p>从设施档案复制新的来源行或版本编号；服务器会核验仍可访问且属于同一设施，不能引用原问题版本冒充修正。</p>
        <Form.Item name="claimId" label="新来源行编号"><InputNumber min={1} /></Form.Item>
        <Form.Item name="versionId" label="或新设施版本编号"><InputNumber min={1} /></Form.Item></>}
      <Space><Button htmlType="submit" loading={busy}>保存核对回执</Button><Button onClick={() => setSelected(null)}>取消</Button></Space>
    </Form>}{error && <Alert type="warning" message={error} />}
  </section>
}
