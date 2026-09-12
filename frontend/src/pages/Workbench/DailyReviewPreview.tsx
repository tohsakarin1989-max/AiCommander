import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { suggestionsApi } from '../../services/suggestions'
import { getSuggestionRoute } from '../Suggestions/suggestionPresentation'

const PREVIEW_LIMIT = 3

const DailyReviewPreview: React.FC = () => {
  const { user, sessionEpoch } = useAuth()
  const query = useQuery({
    queryKey: ['suggestions', 'daily-review-preview', user?.id, user?.role, sessionEpoch],
    queryFn: () => suggestionsApi.list({ workflow: 'conclusion_review', status: 'open', limit: PREVIEW_LIMIT, offset: 0 }),
    enabled: Boolean(user),
    refetchInterval: 60_000,
  })
  const data = query.isError || query.isPending ? undefined : query.data
  const total = data?.summary ? data.summary.workflow.conclusion_review ?? 0 : data?.total
  const suggestions = data?.suggestions.slice(0, PREVIEW_LIMIT) ?? []

  return <section className="daily-review" aria-labelledby="daily-review-title" aria-busy={query.isPending}>
    <div className="daily-section-heading">
      <h2 id="daily-review-title">待人工判断的结论</h2>
      <span>{total == null ? '数量待确认' : `当前分类共 ${total} 项 · 最多预览 ${PREVIEW_LIMIT} 项`}</span>
    </div>
    {query.isPending ? <p className="daily-review-message" role="status">正在读取待判断结论，不影响案件查看。</p>
      : query.isError || !data ? <div className="daily-review-message" role="alert">
        <p>待判断结论暂不可读，不能据此判断是否存在待确认记录。</p>
        <button className="btn-ghost" onClick={() => void query.refetch()}>重新读取结论</button>
      </div> : suggestions.length === 0 ? <p className="daily-review-message">当前没有待人工判断的结论；其他事项仍可按需查看。</p>
        : <ul className="daily-review-list">{suggestions.map(item => {
          const target = getSuggestionRoute(item)
          return <li key={item.id}>
            <div>
              <h3>{item.title}</h3>
              <p>{item.description || '该记录尚未提供摘要，请查看原结论及依据。'}</p>
            </div>
            {target ? <Link className="daily-case-link" to={target}>查看依据并判断</Link>
              : <span className="daily-muted">暂未提供可用入口</span>}
          </li>
        })}</ul>}
    <div className="daily-review-footer">
      <span>这里只读预览已有结论，不自动确认；数量仅代表本分类。</span>
      <Link to="/suggestions">全部待判断事项</Link>
    </div>
  </section>
}

export default DailyReviewPreview
