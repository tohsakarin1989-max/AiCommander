import { useState } from 'react'
import { Alert, Button, Pagination } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { caseDraftsApi } from '../../services/caseDrafts'
import { formatStoredTime } from '../../utils/caseValues'

export default function CaseDraftLibrary({ disabled, onRestore }: { disabled: boolean; onRestore: (id: string) => void }) {
  const { user, sessionEpoch } = useAuth()
  const [page, setPage] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const query = useQuery({ queryKey: ['case-private-drafts', user?.id, sessionEpoch, page], retry: false,
    queryFn: ({ signal }) => caseDraftsApi.list(page, signal) })
  return <section aria-label="我的私有草稿">
    <p>只有本人在当前可写范围内可找回。草稿不进入正式案件、统计或研判；到期后不可恢复。已转正式的草稿只保留结果入口。</p>
    {(query.isError || error) && <Alert type="error" message={error || '草稿读取失败或当前无权访问，请重试'} />}
    {query.isFetching && <p role="status">正在读取草稿…</p>}
    {query.isSuccess && !query.data.items.length && <p>没有可找回的草稿。在录入窗口点击“保存私有草稿”后可跨页面继续。</p>}
    {query.isSuccess && query.data.items.map(draft => {
      const values = draft.form_snapshot.values as Record<string, unknown> | undefined
      return <div key={draft.id} className="case-facility-choice"><div>
        <strong>{draft.status === 'submitted' ? `已转正式案件 #${draft.submitted_case_id}` : `${draft.target_case_id ? `编辑案件 #${draft.target_case_id}` : '新建案件'}草稿`}</strong>
        {draft.status !== 'submitted' && <p>{String(values?.location || values?.description || '尚未填写地点或案情').slice(0, 90)}</p>}
        <p>厂区 #{draft.operational_area_id} · 保存于 {formatStoredTime(draft.updated_at)} · 到期 {formatStoredTime(draft.expires_at)} · 版本 {draft.revision}</p>
      </div><Button disabled={disabled || busy} onClick={() => onRestore(draft.id)}>{draft.status === 'submitted' ? '查看正式案件' : '继续填写'}</Button>
        {draft.status !== 'submitted' && <Button danger disabled={disabled || busy} onClick={async () => {
          if (!window.confirm('删除这份私有草稿？未转正式的输入将无法找回。')) return
          setBusy(true); setError('')
          try { await caseDraftsApi.remove(draft.id, draft.revision); await query.refetch() }
          catch { setError('草稿删除未确认或版本已变化，请刷新核对；没有自动删除其他版本。') }
          finally { setBusy(false) }
        }}>删除草稿</Button>}
      </div>
    })}
    <div className="case-entry-actions"><Button disabled={busy || query.isFetching} onClick={() => void query.refetch()}>刷新草稿</Button>
      {query.isSuccess && <Pagination current={page} pageSize={query.data.page_size} total={query.data.total} showSizeChanger={false} onChange={setPage} />}</div>
  </section>
}
