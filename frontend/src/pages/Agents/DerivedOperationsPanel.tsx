import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Space, Table } from 'antd'
import { useQuery } from '@tanstack/react-query'

import { useAuth } from '../../auth/AuthContext'
import { derivedOperations, type DerivedTask } from '../../services/derivedOperations'

const STATES: Record<string, string> = { pending: '排队中', retry: '等待重试', processing: '处理中',
  waiting_dependency: '等待运行条件', failed: '已失败' }

export default function DerivedOperationsPanel() {
  // Office administrators need a compact failure list, not another dashboard.
  const { user, sessionEpoch } = useAuth()
  const identity = `${user?.id ?? 'none'}:${sessionEpoch}:${user?.role ?? 'none'}`
  const currentIdentity = useRef(identity)
  currentIdentity.current = identity
  const [page, setPage] = useState(1)
  const [failedOnly, setFailedOnly] = useState(true)
  const [pending, setPending] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ type: 'error' | 'success'; text: string; identity: string } | null>(null)
  const pendingIdentity = useRef(identity)
  const requestIds = useRef(new Map<string, string>())
  const controller = useRef<AbortController | null>(null)
  const generation = useRef(0)
  useEffect(() => {
    generation.current += 1
    setPending(null); setNotice(null); requestIds.current.clear()
    return () => { generation.current += 1; controller.current?.abort() }
  }, [identity])
  const query = useQuery({ queryKey: ['derived-operations', user?.id, sessionEpoch, page, failedOnly],
    queryFn: ({ signal }) => derivedOperations.list(page, failedOnly, signal),
    enabled: user?.role === 'admin', refetchInterval: 60_000 })
  const data = !query.error && user?.role === 'admin' ? query.data : undefined
  const activePending = pendingIdentity.current === identity ? pending : null

  async function retry(row: DerivedTask) {
    const epoch = generation.current
    const key = `${row.id}:${row.attempts}`
    const requestId = requestIds.current.get(key) || crypto.randomUUID()
    requestIds.current.set(key, requestId) // A lost response reuses the exact request.
    controller.current?.abort()
    const abort = new AbortController()
    controller.current = abort
    pendingIdentity.current = identity
    setPending(row.id); setNotice(null)
    try {
      await derivedOperations.retry(row, requestId, abort.signal)
      if (generation.current !== epoch || currentIdentity.current !== identity || abort.signal.aborted) return
      setNotice({ type: 'success', text: '已安排这次重试，由后台处理；尚不代表分析成功。', identity })
      await query.refetch()
    } catch {
      if (generation.current === epoch && currentIdentity.current === identity && !abort.signal.aborted)
        setNotice({ type: 'error', text: '本次未能确认重试结果。可再次点击重试，或刷新核对状态；重复请求不会重复排队。', identity })
    } finally {
      if (generation.current === epoch && currentIdentity.current === identity) setPending(null)
    }
  }
  if (user?.role !== 'admin') return null
  return <section aria-labelledby="derived-operations-heading">
    <h2 id="derived-operations-heading">后台积压与失败恢复</h2>
    <p>这里只重试已确定失败的画像、检索索引、道路分析。不会修改原始案件，不恢复已取消任务，也不重放人工批准操作。</p>
    <Space wrap>
      <Checkbox checked={failedOnly} onChange={e => { setFailedOnly(e.target.checked); setPage(1) }}>只看已失败</Checkbox>
      <Button onClick={() => query.refetch()} loading={query.isFetching}>刷新状态</Button>
    </Space>
    {query.error && <Alert type="error" showIcon message="任务状态暂不可读，已隐藏旧列表和数量。" />}
    {notice?.identity === identity && <Alert showIcon type={notice.type} message={notice.text} />}
    {data && <p>{Object.entries(data.counts).map(([state, count]) => `${STATES[state] || state} ${count}`).join('；')}。
      {data.oldest_wait_seconds !== null && <> 最早待处理任务已保留 {Math.floor(data.oldest_wait_seconds / 60)} 分钟。</>}
      并发容量需按部署配置核实，这里未进行现场测量。</p>}
    <Table<DerivedTask> rowKey="id" dataSource={data?.items || []} loading={query.isPending}
      locale={{ emptyText: query.error ? '无法读取，不表示没有失败' : '当前授权范围没有符合筛选条件的派生任务' }}
      pagination={{ current: page, pageSize: 10, total: data?.total || 0, onChange: setPage, showSizeChanger: false }}
      columns={[
        { title: '任务', dataIndex: 'label' },
        { title: '状态', dataIndex: 'status', render: (value: string) => STATES[value] || '状态待核' },
        { title: '累计尝试', dataIndex: 'attempts' },
        { title: '来源', dataIndex: 'source_state', render: (value: string) => value === 'current' ? '当前版本' : '已变化或不可用' },
        { title: '操作', render: (_: unknown, row: DerivedTask) => row.retryable
          ? <Button onClick={() => retry(row)} disabled={activePending !== null && activePending !== row.id} loading={activePending === row.id}>重试这项派生任务</Button>
          : <span>不开放手动重试</span> },
      ]} />
    {data && <p>{data.boundary}</p>}
  </section>
}
