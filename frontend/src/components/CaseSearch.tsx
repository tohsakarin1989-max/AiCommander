import { useState } from 'react'
import { Alert, Button, Input, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { caseApi } from '../services/cases'
import type { Case } from '../types'

interface Props { areaId?: number; disabled?: boolean; onChoose: (item: Case) => void; selectedIds?: number[] }
export default function CaseSearch(props: Props) {
  const { user, sessionEpoch } = useAuth()
  return <CaseSearchSession key={`${user?.id}:${sessionEpoch}:${props.areaId}`} {...props} />
}
function CaseSearchSession({ areaId, disabled, onChoose, selectedIds = [] }: Props) {
  const { user, sessionEpoch } = useAuth()
  const [input, setInput] = useState('')
  const [term, setTerm] = useState('')
  const [page, setPage] = useState(1)
  const query = useQuery({ queryKey: ['case-search-picker', user?.id, sessionEpoch, areaId, term, page],
    queryFn: ({ signal }) => caseApi.getCasePage({ keyword: term, page, page_size: 10, operational_area_id: areaId }, signal),
    enabled: Boolean(user && term && !disabled), gcTime: 0, retry: false })
  const result = query.isError ? undefined : query.data
  return <div>
    <Input.Search aria-label="查找案件" placeholder="案件编号、地点或案情关键词" value={input} maxLength={200} disabled={disabled}
      onChange={event => setInput(event.target.value)} onSearch={value => { setTerm(value.trim()); setPage(1) }} enterButton="查找案件" />
    {!term ? <p>按关键词查找全部授权案件，不限最近 50 案。</p> : query.isError ? <Alert type="error" message="案件查询失败，未使用旧结果" action={<Button onClick={() => void query.refetch()}>重试</Button>} /> : query.isFetching ? <p role="status">正在查找案件…</p> : result && <>
      {result.items.length ? <ul style={{ paddingLeft: 20 }}>{result.items.map(item => <li key={item.id} style={{ marginBlock: 8 }}><Space wrap><span>{item.case_number} · {item.case_type || '未填写类型'} · {item.location || '未填写地点'}</span><Button size="small" disabled={disabled || selectedIds.includes(item.id)} onClick={() => onChoose(item)}>{selectedIds.includes(item.id) ? '已选择' : '选择此案'}</Button></Space></li>)}</ul> : <p>当前授权范围及条件下没有匹配案件。</p>}
      <Space wrap><Button disabled={page === 1 || disabled} onClick={() => setPage(value => value - 1)}>上一页案件</Button><span>第 {page} 页 · 共 {result.total} 案</span><Button disabled={page * result.page_size >= result.total || disabled} onClick={() => setPage(value => value + 1)}>下一页案件</Button></Space>
    </>}
  </div>
}
