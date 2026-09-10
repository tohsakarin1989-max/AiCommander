import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Form, Input, List, Select, Skeleton, Space, Table, Typography, Upload } from 'antd'
import { useQuery } from '@tanstack/react-query'
import type { MapSource } from '../../services/mapFoundation'
import { internalRoadsApi, type RoadFeature, type RoadImport, type RoadPreview, type RoadReview } from '../../services/internalRoads'

const labels = { verified: '资料已核验', rejected: '已驳回', pending_verification: '待核验' }

export default function InternalRoadManager({ sources }: { sources: MapSource[] }) {
  const [source, setSource] = useState<number>()
  const eligible = sources.filter(item => item.status === 'active' && item.source_type !== 'public_map')
  const selected = eligible.find(item => item.id === source)
  return <Card title="内部道路与入口" className="jurisdiction-card">
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Alert type="info" showIcon message="保存来源资料，不直接发布可通行道路"
        description="首次准备带稳定来源编号的 GeoJSON，明确 EPSG:4326。保留完整道路和入口；公共地图来源不能接收内部资料。" />
      <Select aria-label="内部道路来源" placeholder="选择已登记的内部来源" value={selected?.id}
        style={{ width: '100%' }} onChange={setSource}
        options={eligible.map(item => ({ value: item.id, label: `${item.name} · ${item.operational_area.name}` }))} />
      {!eligible.length && <Typography.Text>请先在生产地图数据治理中登记内部资料来源。</Typography.Text>}
      {selected && <RoadSourceWorkspace key={selected.id} source={selected.id} />}
    </Space>
  </Card>
}

function RoadSourceWorkspace({ source }: { source: number }) {
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const [payload, setPayload] = useState<unknown>()
  const [preview, setPreview] = useState<RoadPreview>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [before, setBefore] = useState<number>()
  const [selected, setSelected] = useState<number>()
  const list = useQuery({ queryKey: ['internal-road-imports', source, before],
    queryFn: ({ signal }) => internalRoadsApi.list(source, before, signal), retry: false })
  const record = useQuery({ queryKey: ['internal-road-import', source, selected],
    queryFn: ({ signal }) => internalRoadsApi.read(source, selected!, signal), enabled: selected != null, retry: false })

  async function chooseFile(file?: File) {
    setPreview(undefined); setPayload(undefined); setNotice(''); setError('')
    if (!file) return
    setBusy(true)
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error('too-large')
      const data: unknown = JSON.parse(await file.text())
      const result = await internalRoadsApi.preview(source, data)
      if (alive.current) { setPayload(data); setPreview(result) }
    } catch { if (alive.current) setError('预检失败。请选择不超过 2MiB 的有效 GeoJSON，并检查来源权限和坐标声明。') }
    finally { if (alive.current) setBusy(false) }
  }

  async function save() {
    if (!preview || preview.valid !== preview.total || busy) return
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await internalRoadsApi.ingest(source, payload)
      if (alive.current) {
        setSelected(result.id); setBefore(undefined); setPreview(undefined); setPayload(undefined)
        setNotice(`来源批次 ${result.id} 已保存或复用，请核对资料。尚未发布路网。`)
        void list.refetch()
      }
    } catch { if (alive.current) setError('保存未确认成功，请查看来源批次；相同资料重新提交会复用已有批次。') }
    finally { if (alive.current) setBusy(false) }
  }

  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    <Upload accept=".json,.geojson,application/geo+json" showUploadList={false} disabled={busy}
      beforeUpload={file => { void chooseFile(file); return false }}>
      <Button disabled={busy}>选择道路 GeoJSON 文件</Button>
    </Upload>
    {busy && <Typography.Text role="status">正在处理，请稍候。切换来源只停止页面等待，不撤销已发出的保存。</Typography.Text>}
    {error && <Alert type="error" showIcon message={error} />}
    {notice && <Alert type="success" showIcon message={notice} />}
    {preview && <>
      <Typography.Text>共 {preview.total} 项，有效 {preview.valid} 项；所有错误修正后才可保存。</Typography.Text>
      <List size="small" pagination={{ pageSize: 10 }} dataSource={preview.rows}
        renderItem={row => <List.Item>第 {row.row} 项 · {row.source_feature_id ?? '缺少编号'}：{[...row.errors, ...row.warnings].join('；')}</List.Item>} />
      <Button type="primary" disabled={busy || preview.valid !== preview.total} onClick={() => void save()}>保存待核资料</Button>
    </>}
    <Typography.Title level={5}>来源批次</Typography.Title>
    {list.isError ? <Alert type="error" message="批次读取失败，不显示旧列表。" action={<Button onClick={() => void list.refetch()}>重试</Button>} />
      : list.isFetching ? <Skeleton active paragraph={{ rows: 2 }} /> : <List dataSource={list.data?.items}
        locale={{ emptyText: '尚无道路批次，先选择文件预检。' }} renderItem={item => <List.Item
          actions={[<Button key="open" onClick={() => setSelected(item.id)}>查看与核验</Button>]}>
          批次 {item.id} · {item.feature_count} 项 · {item.created_at}
        </List.Item>} />}
    <Space><Button disabled={before == null || list.isFetching} onClick={() => setBefore(undefined)}>回到最新</Button>
      <Button disabled={!list.data?.next_before_id || list.isFetching || list.isError}
        onClick={() => setBefore(list.data!.next_before_id!)}>更早批次</Button></Space>
    {selected != null && <Button disabled={record.isFetching} onClick={() => void record.refetch()}>刷新所选批次</Button>}
    {selected != null && (record.isError ? <Alert type="error" message="该批次不可读取，请检查当前权限或重试。"
      action={<Button onClick={() => void record.refetch()}>重试</Button>} /> : record.isFetching ? <Skeleton active />
      : record.data && <RoadRecord key={`${source}:${record.data.id}:${record.data.input_sha256}`} source={source}
          record={record.data} refresh={() => void record.refetch()} />)}
  </Space>
}

function RoadRecord({ source, record, refresh }: { source: number; record: RoadImport; refresh: () => void }) {
  const [feature, setFeature] = useState<RoadFeature>()
  return <>
    <Typography.Title level={5}>批次 {record.id} 的来源资料</Typography.Title>
    <Typography.Paragraph>核验只确认资料，不代表入口已连接、获得通行许可或已有参考路径。</Typography.Paragraph>
    <Table rowKey="id" dataSource={record.features} size="small" scroll={{ x: 600 }} pagination={{ pageSize: 10 }}
      columns={[
        { title: '来源编号', dataIndex: 'id' },
        { title: '名称', render: (_, item) => item.properties.name },
        { title: '类型', render: (_, item) => item.properties.kind === 'road' ? '道路' : '入口' },
        { title: '资料状态', render: (_, item) => labels[record.feature_reviews?.[item.id]?.decision ?? 'pending_verification'] },
        { title: '操作', render: (_, item) => <Button onClick={() => setFeature(item)}>核对资料</Button> },
      ]} />
    {feature && <RoadReviewForm key={feature.id} source={source} record={record} feature={feature} refresh={refresh} />}
  </>
}

function RoadReviewForm({ source, record, feature, refresh }: {
  source: number; record: RoadImport; feature: RoadFeature; refresh: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const review = record.feature_reviews?.[feature.id]
  return <section aria-label={`核验 ${feature.properties.name}`}>
    <Typography.Title level={5}>{feature.properties.name} · {feature.id}</Typography.Title>
    <details><summary>完整线形与来源属性</summary><pre style={{ maxHeight: 260, overflow: 'auto' }}>{JSON.stringify(feature, null, 2)}</pre></details>
    {record.warnings.filter(item => item.source_feature_id === feature.id).flatMap(item => item.warnings)
      .map(warning => <Typography.Paragraph key={warning}>{warning}</Typography.Paragraph>)}
    {review && <Typography.Paragraph>最近核验：{labels[review.decision]}；{review.note}；依据：{review.evidence_reference}</Typography.Paragraph>}
    {error && <Alert type="error" message={error} />}
    <Form layout="vertical" disabled={busy} onFinish={async (values: { decision: RoadReview['decision']; note: string; evidence: string }) => {
      setBusy(true); setError('')
      try { await internalRoadsApi.review(source, record, feature, values.decision, values.note, values.evidence); refresh() }
      catch { setError('核验未确认成功。请刷新批次后查看当前决定，再提交；不覆盖他人的核验。') }
      finally { setBusy(false) }
    }}>
      <Form.Item label="核验决定" name="decision" rules={[{ required: true }]}><Select options={Object.entries(labels).map(([value, label]) => ({ value, label }))} /></Form.Item>
      <Form.Item label="核验依据（台账、核查记录等）" name="evidence" rules={[{ required: true, whitespace: true }]}><Input maxLength={500} /></Form.Item>
      <Form.Item label="核验说明" name="note" rules={[{ required: true, whitespace: true }]}><Input.TextArea maxLength={2000} rows={3} /></Form.Item>
      <Button htmlType="submit" type="primary" loading={busy}>记录核验决定</Button>
    </Form>
  </section>
}
