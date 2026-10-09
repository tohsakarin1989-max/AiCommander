import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import dayjs from 'dayjs'
import { useAuth } from '../../auth/AuthContext'
import { workbenchApi, type DailyWorkbenchCase } from '../../services/workbench'
import DailyReviewPreview from './DailyReviewPreview'
import TopicChangeCard from './TopicChangeCard'
import { formatStoredTime } from '../../utils/caseValues'
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
export function formatDailyCaseTime(item: DailyWorkbenchCase): string {
  if (item.occurred_time) return formatDailyOccurredTime(item.occurred_time)
  if (item.occurred_from && item.occurred_to && dayjs(item.occurred_from).isValid()
      && dayjs(item.occurred_to).isValid() && dayjs(item.occurred_from).valueOf() <= dayjs(item.occurred_to).valueOf()) {
    return `${formatDailyOccurredTime(item.occurred_from)} 至 ${formatDailyOccurredTime(item.occurred_to)}（时间区间）`
  }
  return item.time_expression ? `${item.time_expression}（具体时间未知）` : '未记录'
}

const Workbench: React.FC = () => {
  const { user, sessionEpoch } = useAuth()
  const canEdit = user?.role === 'admin' || user?.role === 'analyst'
  const [offset, setOffset] = useState(0)
  const query = useQuery({
    queryKey: ['workbench-daily', user?.id, user?.role, sessionEpoch, offset],
    queryFn: () => workbenchApi.daily({ limit: PAGE_SIZE, offset }),
    refetchInterval: 60_000,
  })
  const quickActions = <nav className="daily-actions" aria-label="常用工作">
    {canEdit && <Link className="btn-primary" to="/cases?create=1">录案件</Link>}
    {canEdit && <Link className="btn-ghost" to="/cases?drafts=1">继续草稿</Link>}
    {canEdit && <Link className="btn-ghost" to="/cases?imports=1">导入续做</Link>}
    <Link className="btn-ghost" to="/cases">查案件</Link>
    <Link className="btn-ghost" to="/jurisdiction#facility-lookup">查井场</Link>
    <Link className="btn-ghost" to="/reports">取材料</Link>
    {user?.role === 'admin' && <Link className="btn-ghost" to="/settings/setup">首次启用检查</Link>}
  </nav>

  if (query.isPending) {
    return <div className="page-scrollable daily-workbench" aria-busy="true">
      <h1>日常工作</h1>
      {quickActions}
      <div className="daily-loading" role="status">正在读取日常工作</div>
      <div className="daily-placeholder" aria-hidden="true" />
      <DailyReviewPreview />
    </div>
  }

  const data = query.isError ? undefined : query.data
  if (!data) {
    return <div className="page-scrollable daily-workbench">
      <h1>日常工作</h1>
      {quickActions}
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
        <p>继续自己的录入与导入，查看近期登记、重要变化和已有材料。</p>
      </div>
      <div className="daily-actions">
        <Link className="btn-primary" to="/cases">进入案件</Link>
        <Link className="btn-ghost" to="/suggestions">待判断事项</Link>
        <button className="btn-ghost" disabled={query.isFetching} onClick={() => void query.refetch()}>
          {query.isFetching ? '正在刷新' : '刷新'}
        </button>
      </div>
    </header>
    {quickActions}

    <section aria-label="日常工作概览" className="daily-summary">
      <dl>
        <div><dt>授权案件</dt><dd>{summary.total_cases}</dd></div>
        {canEdit && <div><dt>我的私有草稿</dt><dd>{data.resume?.state === 'ready' ? data.resume.drafts?.total : '未读取'}</dd></div>}
        {canEdit && <div><dt>我的导入待续做</dt><dd>{data.resume?.state === 'ready' ? data.resume.imports?.total : '未读取'}</dd></div>}
        <div><dt>业务材料</dt><dd><Link to="/reports">按需取用</Link></dd></div>
      </dl>
      <p>案件为授权范围内全部案件；草稿和导入续做只计本人当前可写范围。不以未出报告、未生成经验卡或未知公安反馈判断案件未完成。</p>
    </section>
    {user?.role === 'admin' && <details><summary>后台运维状态（管理员）</summary><p>画像可查看 {summary.analysis_ready}；尚未形成 {summary.analysis_pending}。后台状态不等于案件处置状态。</p><Link to="/settings/setup">检查实际启用能力</Link></details>}

    <DailyReviewPreview />

    {data.changes && <section className="daily-cases" aria-label="持续关注的重要变化">
      <h2>持续关注的重要变化</h2>
      {data.changes.length ? <ul>{data.changes.slice(0, 3).map(change => <TopicChangeCard
        key={`${user?.id}:${user?.role}:${sessionEpoch}:${change.group_key || change.topic_id}`}
        change={change} onDismissed={() => { void query.refetch() }} />)}</ul>
        : <p>目前没有需要提示的实质变化。后台刷新或重试不会单独生成事项。</p>}
    </section>}

    <section className="daily-cases" aria-labelledby="daily-cases-title">
      <div className="daily-section-heading">
        <h2 id="daily-cases-title">近期登记</h2>
        <span>统计时刻：{formatTime(data.generated_at)}</span>
      </div>
      {data.cases.length === 0 ? <div className="daily-message">
        <h3>当前没有可展示的案件</h3>
        <p>可进入案件列表查看授权数据，或正常录入案件。这里不会生成示例记录。</p>
      </div> : <div className="daily-table-scroll">
        <table>
          <thead><tr><th scope="col">记录与时间</th><th scope="col">地点原文</th><th scope="col">可补充资料</th>{user?.role === 'admin' && <th scope="col">后台状态</th>}<th scope="col">操作</th></tr></thead>
          <tbody>{data.cases.map(item => <tr key={item.id}>
            <th scope="row"><Link to={`/cases?caseId=${item.id}`}>{item.case_number}</Link>
              <small>发现／查获：{item.discovered_at ? formatStoredTime(item.discovered_at) : '未掌握'}</small>
              <small>实际案发：{formatDailyCaseTime(item)}</small>
              <small>登记：{item.registered_at ? formatStoredTime(item.registered_at) : '未记录'}</small></th>
            <td>{item.location || '地点未记录'}</td>
            <td>{item.information_gaps.length > 0
              ? <ul>{item.information_gaps.slice(0, 3).map((gap, index) => <li key={`${index}:${gap}`}>{gap}</li>)}</ul>
              : <span className="daily-muted">按已掌握情况使用，不催补未知侦查信息</span>}</td>
            {user?.role === 'admin' && <td><span className={`daily-state ${item.profile_ready ? 'ready' : ''}`}>{dailyProfileStatus(item)}</span></td>}
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
