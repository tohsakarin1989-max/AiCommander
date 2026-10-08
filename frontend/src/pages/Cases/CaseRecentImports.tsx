import { useState } from 'react'
import { Alert, Button, Pagination } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { caseImportsApi, type RecentImportBatch } from '../../services/caseImports'
import { formatStoredTime } from '../../utils/caseValues'
import { importTimeZoneLabel } from './importCorrection'

export default function CaseRecentImports({ disabled, onOpen }: { disabled: boolean; onOpen: (batch: RecentImportBatch) => void }) {
  const { user, sessionEpoch } = useAuth()
  const [page, setPage] = useState(1)
  const result = useQuery({ queryKey: ['case-recent-imports', user?.id, sessionEpoch, page], retry: false,
    queryFn: ({ signal }) => caseImportsApi.batches(page, undefined, signal) })
  return <section aria-label="最近导入批次">
    <p>按当前权限找回已有批次，无需重新上传。成功行不重复写入，只续做失败行。</p>
    {result.isFetching && <p role="status">正在读取导入批次…</p>}
    {result.isError && <Alert type="error" showIcon message="批次读取失败或当前无权访问，请刷新重试。" />}
    {result.isSuccess && !result.data.items.length && <p>尚无可见导入批次，可从下方上传首份表格。</p>}
    {result.isSuccess && result.data.items.map(batch => <div className="case-facility-choice" key={batch.batch_id}>
      <div><strong>{formatStoredTime(batch.created_at)} · {batch.worksheet || '未记录工作表'} · {batch.batch_id.slice(0, 8)}</strong>
        <p>厂区 #{batch.operational_area_id ?? '未记录'} · 总行数 {batch.total ?? '未记录'} · 成功 {batch.success ?? '未记录'} · 失败 {batch.failed ?? '未记录'}</p>
        <p>{batch.time_zone ? importTimeZoneLabel(batch.time_zone) : '历史回执未记录时区'}{!batch.retry_available ? '；未保存逐行来源，不能在此续做，请核对原始文件。' : ''}</p>
      </div><Button disabled={disabled || !batch.retry_available} onClick={() => onOpen(batch)}>{batch.failed ? '找回并续做失败行' : '查看批次回执'}</Button>
    </div>)}
    <div className="case-entry-actions"><Button disabled={disabled || result.isFetching} onClick={() => void result.refetch()}>刷新导入批次</Button>
      {result.isSuccess && <Pagination current={page} pageSize={result.data.page_size} total={result.data.total} showSizeChanger={false} onChange={setPage} />}</div>
  </section>
}
