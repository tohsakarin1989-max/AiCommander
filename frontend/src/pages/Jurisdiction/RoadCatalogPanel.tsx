import { useState } from 'react'
import { Alert, Button, Skeleton, Space, Table, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { internalRoadsApi } from '../../services/internalRoads'

export default function RoadCatalogPanel({ source, onOpen }: { source: number; onOpen: (id: number) => void }) {
  const [after, setAfter] = useState<string>()
  const query = useQuery({ queryKey: ['internal-road-catalog', source, after],
    queryFn: ({ signal }) => internalRoadsApi.catalog(source, after, signal), retry: false })
  return <section aria-label="跨批次道路目录">
    <Typography.Title level={5}>跨批次道路目录</Typography.Title>
    <Typography.Paragraph>按稳定来源编号汇总全部历史批次。最新资料不等于已核验资料；此目录不代表道路可通行。</Typography.Paragraph>
    {query.isError ? <Alert type="error" message="目录读取失败，未展示旧结果。请检查来源权限。" />
      : query.isFetching || !query.data ? <Skeleton active />
      : query.data.source_id !== source ? <Alert type="error" message="来源不匹配，已停止展示。" />
      : <Table rowKey="source_feature_id" dataSource={query.data.items} pagination={false} scroll={{ x: 650 }} size="small"
          columns={[
            { title: '编号', dataIndex: 'source_feature_id' }, { title: '最新名称', dataIndex: 'name' },
            { title: '资料状态', render: (_, item) => item.pending_update ? '有待核更新，历史核验未覆盖'
              : item.latest_review?.decision === 'verified' ? '最新资料已核验'
                : item.latest_review?.decision === 'rejected' ? '最新资料已驳回' : '待核验' },
            { title: '查看版本', render: (_, item) => <Space wrap>
              <Button onClick={() => onOpen(item.latest_import_id)}>最新批次 {item.latest_import_id}</Button>
              {item.last_verified_import_id != null && item.last_verified_import_id !== item.latest_import_id
                && <Button onClick={() => onOpen(item.last_verified_import_id!)}>历史核验批次 {item.last_verified_import_id}</Button>}
            </Space> },
          ]} />}
    <Space wrap style={{ marginTop: 12 }}>
      <Button disabled={query.isFetching} onClick={() => void query.refetch()}>刷新道路目录</Button>
      <Button disabled={after == null || query.isFetching} onClick={() => setAfter(undefined)}>回到目录首页</Button>
      <Button disabled={query.isFetching || query.isError || !query.data?.next_after_feature}
        onClick={() => setAfter(query.data!.next_after_feature!)}>下一页道路</Button>
    </Space>
  </section>
}
