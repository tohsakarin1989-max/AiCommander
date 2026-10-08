import { useState } from 'react'
import { Alert, Button, Input, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { jurisdictionApi, type JurisdictionAsset } from '../../services/jurisdiction'
import { facilityMatchText } from './facilitySearchPresentation'

interface Props {
  areaId?: number | null
  requireArea?: boolean
  disabled?: boolean
  onChoose: (asset: JurisdictionAsset) => void
  actionLabel?: string
  extraAction?: (asset: JurisdictionAsset) => React.ReactNode
}
const PAGE_SIZE = 20

export default function FacilitySearch(props: Props) {
  const { user, sessionEpoch } = useAuth()
  return <FacilitySearchSession key={`${user?.id}:${sessionEpoch}:${props.areaId}`} {...props} />
}
function FacilitySearchSession({ areaId, requireArea, disabled, onChoose, actionLabel = '选择此设施', extraAction }: Props) {
  const { user, sessionEpoch } = useAuth()
  const [input, setInput] = useState('')
  const [term, setTerm] = useState('')
  const [offset, setOffset] = useState(0)
  const blocked = disabled || (requireArea && areaId == null)
  const query = useQuery({ queryKey: ['facility-search', user?.id, sessionEpoch, areaId, term, offset],
    queryFn: ({ signal }) => jurisdictionApi.listAssets({ keyword: term, operational_area_id: areaId ?? undefined, status: 'active', skip: offset, limit: PAGE_SIZE + 1 }, signal),
    enabled: Boolean(user && !blocked && term), gcTime: 0, retry: false })
  const rows = query.isError ? [] : query.data || []
  return <div>
    <Input.Search aria-label="设施名称、编号、地址或历史名" placeholder="名称、编号、地址或历史名" maxLength={200} value={input} disabled={blocked}
      onChange={event => setInput(event.target.value)} onSearch={value => { setTerm(value.trim()); setOffset(0) }} enterButton="查找设施" />
    {requireArea && areaId == null ? <p>请先选择已授权辖区。</p> : !term ? <p>查询完整授权设施目录，不限于地图当前显示的设施。</p> : query.isError ? <Alert type="error" message="设施查询失败，不能视为没有记录" action={<Button onClick={() => void query.refetch()}>重试</Button>} /> : query.isFetching ? <p role="status">正在查询…</p> : <>
      {rows.length ? <ul style={{ paddingLeft: 20 }}>{rows.slice(0, PAGE_SIZE).map(item => <li key={item.id} style={{ marginBlock: 10 }}>
        <strong>{item.name}</strong><div>{item.external_id || `系统编号 ${item.id}`}{item.address ? ` · ${item.address}` : ''}</div>
        {facilityMatchText(item) && <div>{facilityMatchText(item)}</div>}
        <Space wrap><Button size="small" disabled={disabled} onClick={() => onChoose(item)}>{actionLabel}</Button>{extraAction?.(item)}</Space>
      </li>)}</ul> : <p>当前授权范围及条件下没有匹配设施。</p>}
      <Space wrap><Button disabled={!offset || disabled} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))}>上一页设施</Button><span>第 {offset / PAGE_SIZE + 1} 页</span><Button disabled={rows.length <= PAGE_SIZE || disabled} onClick={() => setOffset(value => value + PAGE_SIZE)}>下一页设施</Button></Space>
    </>}
  </div>
}
