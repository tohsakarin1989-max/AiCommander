import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { caseResultsApi } from '../../services/caseResults'
import CaseResultPanel from '../../components/CaseResult/CaseResultPanel'
import CaseResultMap from '../../components/CaseResult/CaseResultMap'
import './CaseResultsBrowser.css'
import { resultCreatedTime } from './caseResultCatalogPresentation'

export default function CaseResultsBrowser() {
  const [params, setParams] = useSearchParams()
  const resultId = params.get('resultId') || ''
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const pageSize = 10
  const catalog = useQuery({
    queryKey: ['case-result-catalog', query, offset],
    queryFn: () => caseResultsApi.list({ q: query, offset, limit: pageSize }),
    retry: false, gcTime: 0, refetchInterval: 30000,
  })
  const selected = useQuery({
    queryKey: ['case-result-version', resultId],
    queryFn: () => caseResultsApi.get(resultId), enabled: !!resultId,
    retry: false, gcTime: 0, refetchInterval: 30000,
  })
  const items = catalog.isError ? [] : catalog.data?.items || []
  return <section className="case-results-browser" aria-label="案件成果版本">
    <h2>案件成果</h2>
    <p>系统自动形成的画像与研判版本。查看固定版本不会重新分析案件，也不改变正式记录。</p>
    <div className={`results-workspace ${resultId ? 'is-reading' : ''}`}><div className="results-directory">
    <form className="case-results-browser__search" onSubmit={event => {
      event.preventDefault(); setQuery(draft.trim()); setOffset(0)
    }}>
      <label htmlFor="case-result-search">案件编号或地点</label>
      <input id="case-result-search" maxLength={100} value={draft} onChange={event => setDraft(event.target.value)} placeholder="检索授权范围内的成果" />
      <button type="submit" className="btn-ghost" disabled={catalog.isFetching}>查询</button>
    </form>
    {catalog.isError ? <p role="status">成果目录暂时无法读取，已隐藏上次列表。</p>
      : catalog.isPending ? <p role="status">正在读取成果目录…</p>
        : !items.length ? <p role="status">当前检索范围暂无成果。后台生成后会自动出现，不需要启动智能体。</p>
          : resultId ? <div className="results-directory-list">{items.map(item => <button key={item.id} type="button" aria-current={item.id === resultId ? 'true' : undefined}
            disabled={item.availability !== 'available'} onClick={() => setParams(previous => { const next = new URLSearchParams(previous); next.set('resultId', item.id); return next })}>
            <strong>{item.case_number}</strong><span>{resultCreatedTime(item.created_at)}</span>
            <small>{item.availability !== 'available' ? '引用失效或权限受限' : `画像第 ${item.versions?.profile_version} 版`}</small>
          </button>)}</div>
          : <div className="case-results-browser__table"><table>
            <caption>已授权案件的成果版本，按生成时间排列</caption>
            <thead><tr><th scope="col">案件</th><th scope="col">生成时间（北京时间）</th><th scope="col">内容</th><th scope="col">操作</th></tr></thead>
            <tbody>{items.map(item => <tr key={item.id} aria-selected={item.id === resultId}>
              <td>{item.case_number}</td><td title={item.created_at}>{resultCreatedTime(item.created_at)}</td>
              <td>{item.availability !== 'available' ? '引用失效或权限受限'
                : item.versions?.analysis_run_id ? `融合成果 · 画像第${item.versions.profile_version}版` : `基础画像 · 第${item.versions?.profile_version}版`}</td>
              <td><button className="btn-ghost" type="button" disabled={item.availability !== 'available'}
                onClick={() => setParams(previous => { const next = new URLSearchParams(previous); next.set('resultId', item.id); return next })}
                aria-label={`查看案件 ${item.case_number} 的成果 ${item.id}`}>查看</button></td>
            </tr>)}</tbody>
          </table></div>}
    <nav className="case-results-browser__pages" aria-label="成果目录分页">
      <button className="btn-ghost" disabled={offset === 0 || catalog.isFetching} onClick={() => setOffset(value => Math.max(0, value - pageSize))}>上一页</button>
      <span>第 {Math.floor(offset / pageSize) + 1} 页</span>
      <button className="btn-ghost" disabled={catalog.isError || !catalog.data?.has_more || catalog.isFetching} onClick={() => setOffset(value => value + pageSize)}>下一页</button>
    </nav>
    </div>
    {resultId && <div className="case-results-browser__selected">
      <p>正在查看固定历史版本。原始案件后续更新不会覆盖此内容。</p>
      <CaseResultPanel key={resultId} caseId={selected.data?.content.case_id ?? -1}
        result={selected.data} loading={selected.isPending} error={selected.isError}
        errorStatus={(selected.error as { status?: number } | null)?.status}
        map={selected.data && <CaseResultMap result={selected.data} />} />
    </div>}
    </div>
  </section>
}
