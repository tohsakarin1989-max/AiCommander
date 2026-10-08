import { useState } from 'react'
import { Alert, Button, Input, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { jurisdictionApi } from '../../services/jurisdiction'
import { openFacilityDossier } from '../../services/regionalContext'
import { useAuth } from '../../auth/AuthContext'

const PAGE_SIZE = 20

export default function FacilityLookup({ areaId }: { areaId: number | null }) {
  const { user, sessionEpoch } = useAuth()
  const [input, setInput] = useState('')
  const [term, setTerm] = useState('')
  const [offset, setOffset] = useState(0)
  const query = useQuery({ queryKey: ['facility-lookup', user?.id, sessionEpoch, areaId, term, offset],
    queryFn: () => jurisdictionApi.listAssets({ keyword: term, operational_area_id: areaId!, skip: offset, limit: PAGE_SIZE + 1 }),
    enabled: areaId != null && Boolean(term), gcTime: 0, retry: false })
  const rows = query.isError ? [] : query.data || []
  return <section id="facility-lookup" className="card" aria-label="查井场与设施">
    <div className="card-head"><h2 className="ti">查井场与设施</h2></div><div className="card-body">
      <p>按名称或台账编号查询当前授权辖区，先查全部匹配记录再分页。这里只查登记资料，不推断涉案关系。</p>
      <Input.Search aria-label="设施名称或台账编号" placeholder="输入井场名称或台账编号" maxLength={200} value={input} disabled={areaId == null}
        onChange={event => setInput(event.target.value)} onSearch={value => { setTerm(value.trim()); setOffset(0) }} enterButton="查找" style={{ maxWidth: 480 }} />
      {areaId == null ? <p>请先选择已授权辖区。</p> : !term ? <p>输入名称即可查找，不需要知道系统编号。</p> : query.isError ? <Alert type="error" message="设施查询失败，不能视为没有记录" action={<Button onClick={() => void query.refetch()}>重试</Button>} /> : query.isFetching ? <p role="status">正在查询…</p> : <>
        {rows.length ? <ul>{rows.slice(0, PAGE_SIZE).map(item => <li key={item.id}><Space wrap><span>{item.name} · {item.external_id || `系统编号 ${item.id}`}</span><Button size="small" onClick={() => openFacilityDossier(item.id)}>打开档案</Button></Space></li>)}</ul> : <p>当前名称及授权辖区下没有匹配记录。</p>}
        <Space><Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</Button><span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页</span><Button disabled={rows.length <= PAGE_SIZE} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</Button></Space>
      </>}
    </div>
  </section>
}
