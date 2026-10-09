import { useQuery } from '@tanstack/react-query'
import { Alert, Button, List, Tag } from 'antd'
import { Link } from 'react-router-dom'
import api from '../../services/api'

const labels: Record<string, string> = {
  enabled: '已启用', ready: '资源校验通过', ok: '连接在线', disabled: '未启用',
  degraded: '资源不完整', not_configured: '尚未配置', unavailable: '暂不可用',
  configured_unverified: '已配置，效果未核验',
}
interface Capabilities {
  checked_at: string
  capabilities: Array<{ key: string; label: string; state: string; basis: string }>
  model_registered_count: number
}
export default function RuntimeCapabilities() {
  const query = useQuery({ queryKey: ['runtime-capabilities'],
    queryFn: async () => (await api.get<Capabilities>('/runtime/capabilities')).data })
  return <section aria-label="实际启用能力">
    <Alert type="info" showIcon message="先开放登记、查找和离线资料；增强能力按需启用"
      description="发布版本、登记模型或地图版本不等于已完成现场验收。此页只读取状态，不导入、不重建、不调用模型。" />
    <p><Link to="/settings/setup">首次启用检查</Link> · <Link to="/jurisdiction">离线地图与生产资料</Link></p>
    {query.isError ? <Alert type="error" message="能力状态读取失败，未推定全部可用" /> :
      <List loading={query.isPending} dataSource={query.data?.capabilities || []}
        renderItem={item => <List.Item><List.Item.Meta title={<>{item.label} <Tag>{labels[item.state] || item.state}</Tag></>}
          description={item.basis} /></List.Item>} />}
    {query.data && <p>核对时间：{new Date(query.data.checked_at).toLocaleString()}；已登记且启用的模型配置 {query.data.model_registered_count} 项（不是可用模型数）。</p>}
    <Button loading={query.isFetching} onClick={() => void query.refetch()}>重新读取</Button>
  </section>
}
