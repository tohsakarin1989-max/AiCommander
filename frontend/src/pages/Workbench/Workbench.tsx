import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import dayjs from 'dayjs'
import { useAuth } from '../../auth/AuthContext'
import { workbenchApi, type DailyWorkbenchCase } from '../../services/workbench'
import DailyReviewPreview from './DailyReviewPreview'
import './Workbench.css'

const PAGE_SIZE = 20

export function dailyProfileStatus(item: DailyWorkbenchCase): string {
  if (item.profile_ready) return '画像可查看'
  switch (item.pipeline_status) {
    case 'queued': case 'pending': return '等待后台处理'
    case 'running': case 'processing': return '后台处理中'
    case 'failed': return '处理异常，案件记录已保留'
    case 'disabled': case 'off': return '自动分析未启用'
    case 'degraded': return '分析降级，画像待形成'
    case 'cancelled': return '处理已取消，案件记录已保留'
    default: return '画像尚未形成'
  }
}

const formatTime = (value: string | null) => value && dayjs(value).isValid()
  ? dayjs(value).format('YYYY-MM-DD HH:mm') : '未记录'

export function formatDailyOccurredTime(value: string | null): string {
  if (!value || !dayjs(value).isValid()) return '未记录'
  const formatted = formatTime(value)
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value.trim())
    ? formatted : `${formatted}（存储时刻，未注明时区）`
}

const Workbench: React.FC = () => {
  const { user, sessionEpoch } = useAuth()
  const [offset, setOffset] = useState(0)
  const query = useQuery({
    queryKey: ['workbench-daily', user?.id, user?.role, sessionEpoch, offset],
    queryFn: () => workbenchApi.daily({ limit: PAGE_SIZE, offset }),
    refetchInterval: 60_000,
  })

  if (query.isPending) {
    return <div className="page-scrollable daily-workbench" aria-busy="true">
      <h1>日常工作</h1>
      <div className="daily-loading" role="status">正在读取日常工作</div>
      <div className="daily-placeholder" aria-hidden="true" />
      <DailyReviewPreview />
    </div>
  }

  const data = query.isError ? undefined : query.data
  if (!data) {
    return <div className="page-scrollable daily-workbench">
      <h1>日常工作</h1>
      <section className="daily-message" role="alert">
        <h2>工作台暂不可用</h2>
        <p>当前无法确认案件数量和分析状态，可以直接进入案件页面。</p>
        <div className="daily-actions">
          <button className="btn-ghost" onClick={() => void query.refetch()}>重新读取</button>
          <Link className="btn-primary" to="/cases">进入案件</Link>
          <Link className="btn-ghost" to="/suggestions">待判断事项</Link>
        </div>
      </section>
      <DailyReviewPreview />
    </div>
  }

  const { summary, pagination } = data
  const page = Math.floor(pagination.offset / pagination.limit) + 1
  const pages = Math.max(1, Math.ceil(pagination.total / pagination.limit))

  return <div className="page-scrollable daily-workbench">
    <header className="daily-heading">
      <div>
        <h1>日常工作</h1>
        <p>查看近期案件、关键补充与已有分析；经验沉淀和报告按需使用。</p>
      </div>
      <div className="daily-actions">
        <Link className="btn-primary" to="/cases">进入案件</Link>
        <Link className="btn-ghost" to="/suggestions">待判断事项</Link>
        <button className="btn-ghost" disabled={query.isFetching} onClick={() => void query.refetch()}>
          {query.isFetching ? '正在刷新' : '刷新'}
        </button>
      </div>
    </header>

    <section aria-label="案件与分析状态" className="daily-summary">
      <dl>
        <div><dt>授权案件</dt><dd>{summary.total_cases}</dd></div>
        <div><dt>关键资料待补充</dt><dd>{summary.needs_information}</dd></div>
        <div><dt>画像待形成</dt><dd>{summary.analysis_pending}</dd></div>
        <div><dt>画像可查看</dt><dd>{summary.analysis_ready}</dd></div>
      </dl>
      <p>口径：授权范围内全部案件。资料缺项与画像待形成可以重叠，画像可查看不代表案件办结。</p>
    </section>

    <DailyReviewPreview />

    <section className="daily-cases" aria-labelledby="daily-cases-title">
      <div className="daily-section-heading">
        <h2 id="daily-cases-title">近期案件</h2>
        <span>统计时刻：{formatTime(data.generated_at)}</span>
      </div>
      {data.cases.length === 0 ? <div className="daily-message">
        <h3>当前没有可展示的案件</h3>
        <p>可进入案件列表查看授权数据，或正常录入案件。这里不会生成示例记录。</p>
      </div> : <div className="daily-table-scroll">
        <table>
          <thead><tr><th scope="col">案件与时间</th><th scope="col">地点</th><th scope="col">关键补充</th><th scope="col">自动画像</th><th scope="col">操作</th></tr></thead>
          <tbody>{data.cases.map(item => <tr key={item.id}>
            <th scope="row"><Link to={`/cases?caseId=${item.id}`}>{item.case_number}</Link><small>发生时间：{formatDailyOccurredTime(item.occurred_time)}</small></th>
            <td>{item.location || '地点未记录'}</td>
            <td>{item.information_gaps.length > 0
              ? <ul>{item.information_gaps.slice(0, 3).map((gap, index) => <li key={`${index}:${gap}`}>{gap}</li>)}</ul>
              : <span className="daily-muted">当前未提示关键缺项</span>}</td>
            <td><span className={`daily-state ${item.profile_ready ? 'ready' : ''}`}>{dailyProfileStatus(item)}</span></td>
            <td><Link className="daily-case-link" to={`/cases?caseId=${item.id}`} aria-label={`查看案件 ${item.case_number}`}>查看案件</Link></td>
          </tr>)}</tbody>
        </table>
      </div>}
      <div className="daily-pagination">
        <span>本页 {pagination.returned} 起 / 共 {pagination.total} 起</span>
        <div className="daily-actions">
          <button className="btn-ghost" disabled={pagination.offset === 0 || query.isFetching} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</button>
          <span>第 {page} / {pages} 页</span>
          <button className="btn-ghost" disabled={pagination.offset + pagination.limit >= pagination.total || query.isFetching} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</button>
        </div>
      </div>
    </section>
    <p className="daily-boundary">自动画像在后台形成；原始记录与人工判断分开保存。无需先生成经验卡或报告才能继续使用案件。</p>
  </div>
}

export default Workbench
