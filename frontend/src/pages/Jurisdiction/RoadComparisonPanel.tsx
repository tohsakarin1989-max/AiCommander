import { Alert, Button, Skeleton, Table, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { internalRoadsApi, type RoadComparison } from '../../services/internalRoads'

const changeLabels = { added: '新增', changed: '变化', unchanged: '不变', not_provided: '本批未提供' }
const fieldLabels: Record<string, string> = {
  geometry: '完整线形/坐标', 'properties.name': '名称', 'properties.kind': '要素类型',
  'properties.conditions': '通行条件', 'properties.road_id': '入口关联道路',
}

export function RoadComparisonView({ data }: { data: RoadComparison }) {
  return <section aria-label="道路版本比较结果">
    <Typography.Title level={5}>基准批次 {data.before_id} → 对比批次 {data.after_id}</Typography.Title>
    <Typography.Paragraph>新增 {data.summary.added} 项，变化 {data.summary.changed} 项，不变 {data.summary.unchanged} 项，本批未提供 {data.summary.not_provided} 项。</Typography.Paragraph>
    <Alert type="info" showIcon message="比较不会覆盖资料；本批未提供不代表删除，已核验状态不自动继承。" />
    <Table rowKey="source_feature_id" dataSource={data.items} size="small" scroll={{ x: 680 }} pagination={{ pageSize: 10 }}
      columns={[
        { title: '来源编号', dataIndex: 'source_feature_id' },
        { title: '名称', render: (_, item) => item.after?.properties.name ?? item.before?.properties.name },
        { title: '变化', render: (_, item) => changeLabels[item.change] },
        { title: '变化字段', render: (_, item) => item.changed_fields.map(key => fieldLabels[key] ?? key).join('、') || '无' },
        { title: '核验影响', render: (_, item) => item.affects_verified_source ? '涉及已核验资料，请核对' : '未标记影响' },
      ]}
      expandable={{ expandedRowRender: item => <>
        <Typography.Text strong>基准资料</Typography.Text>
        <pre style={{ maxHeight: 220, overflow: 'auto' }}>{item.before ? JSON.stringify(item.before, null, 2) : '基准批次未提供'}</pre>
        <Typography.Text strong>对比资料</Typography.Text>
        <pre style={{ maxHeight: 220, overflow: 'auto' }}>{item.after ? JSON.stringify(item.after, null, 2) : '对比批次未提供，不代表删除'}</pre>
      </> }} />
    <Typography.Paragraph type="secondary" style={{ overflowWrap: 'anywhere' }}>
      基准摘要：{data.before_sha256}<br />对比摘要：{data.after_sha256}
    </Typography.Paragraph>
  </section>
}

export default function RoadComparisonPanel({ source, before, after }: { source: number; before: number; after: number }) {
  const query = useQuery({ queryKey: ['internal-road-compare', source, before, after],
    queryFn: ({ signal }) => internalRoadsApi.compare(source, before, after, signal), retry: false })
  if (query.isError) return <Alert type="error" message="比较读取失败，不展示缓存结果。请确认两个批次的当前权限。"
    action={<Button onClick={() => void query.refetch()}>重试比较</Button>} />
  if (query.isFetching || !query.data) return <Skeleton active />
  if (query.data.source_id !== source || query.data.before_id !== before || query.data.after_id !== after)
    return <Alert type="error" message="比较版本不匹配，请重新选择批次。" />
  return <RoadComparisonView data={query.data} />
}
