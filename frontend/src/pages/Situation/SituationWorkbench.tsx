import { useEffect, useMemo, useState } from 'react'
import { App as AntdApp, Input, Select } from 'antd'
import {
  AimOutlined,
  DownloadOutlined,
  EnvironmentOutlined,
  RadarChartOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import SituationChart from './SituationChart'

import {
  situationApi,
  type SituationPriority,
  type SituationQuery,
} from '../../services/situation'
import { intelligenceFlowApi } from '../../services/intelligenceFlow'
import {
  buildBriefMarkdown,
  buildSituationMapOption,
  buildTrendOption,
  getChangePresentation,
  getPriorityPresentation,
} from './situationPresentation'
import './SituationWorkbench.css'
import SpatialCoveragePanel from './SpatialCoveragePanel'
import RoadChanges from './RoadChanges'
import AutomaticBriefStatus from './AutomaticBriefStatus'


const WINDOW_OPTIONS = [7, 14, 30, 90].map(value => ({
  value,
  label: value === 7 ? '近7天' : value === 14 ? '近14天' : value === 30 ? '近30天' : '近90天',
}))

const RADIUS_OPTIONS = [1, 3, 5, 10, 20].map(value => ({
  value,
  label: `${value}公里`,
}))

function downloadText(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function PriorityCard({
  item,
  active,
  onClick,
}: {
  item: SituationPriority
  active: boolean
  onClick: () => void
}) {
  const presentation = getPriorityPresentation(item)
  return (
    <button
      type="button"
      className={`sw-priority sw-priority--${presentation.tone}${active ? ' is-active' : ''}`}
      onClick={onClick}
    >
      <span className="sw-priority-rank">{String(item.rank).padStart(2, '0')}</span>
      <span className="sw-priority-body">
        <span className="sw-priority-meta">{presentation.levelLabel} · {presentation.actionLabel}</span>
        <strong>{item.title}</strong>
        <small>{item.finding}</small>
      </span>
      <span className="sw-priority-arrow">→</span>
    </button>
  )
}

const SituationWorkbench: React.FC = () => {
  const { message } = AntdApp.useApp()
  const [draft, setDraft] = useState<SituationQuery>({
    windowDays: 30,
    hotspotRadiusKm: 1.5,
    wellRadiusKm: 5,
    minCases: 2,
    areaKeyword: '',
  })
  const [applied, setApplied] = useState<SituationQuery>({ ...draft })
  const [selectedPriorityId, setSelectedPriorityId] = useState<string | null>(null)
  const [legacyOpen, setLegacyOpen] = useState(false)

  const overviewQuery = useQuery({
    queryKey: ['situation-overview', applied],
    queryFn: () => situationApi.getOverview(applied),
    staleTime: 60_000,
    enabled: legacyOpen,
  })
  const overview = overviewQuery.data
  const automaticBriefQuery = useQuery({
    queryKey: ['automatic-situation-brief'],
    queryFn: intelligenceFlowApi.getLatestSituationBrief,
    retry: false,
    refetchInterval: 60_000,
  })
  const feedbackMutation = useMutation({
    mutationFn: ({ id, decision, score }: { id: string; decision: 'adopt_reference' | 'not_adopted' | 'insufficient_information'; score?: number }) => (
      intelligenceFlowApi.submitRecommendationFeedback(id, decision, score)
    ),
    onSuccess: result => message.success(result.execution_task_created ? '反馈已记录' : '反馈已记录，未生成执行任务'),
    onError: () => message.error('反馈记录失败，请稍后重试'),
  })
  const automaticBrief = automaticBriefQuery.isError ? undefined : automaticBriefQuery.data

  useEffect(() => {
    setSelectedPriorityId(overview?.priorities[0]?.id ?? null)
  }, [overview?.source_snapshot.data_version])

  const selectedPriority = overview?.priorities.find(item => item.id === selectedPriorityId)
    ?? overview?.priorities[0]
    ?? null
  const trendOption = useMemo(
    () => buildTrendOption(overview?.timeline ?? []),
    [overview?.timeline],
  )
  const mapOption = useMemo(
    () => overview ? buildSituationMapOption(overview) : null,
    [overview],
  )
  const change = overview ? getChangePresentation(overview.summary) : null

  const runAnalysis = () => {
    const next = { ...draft, areaKeyword: draft.areaKeyword?.trim() }
    const unchanged = JSON.stringify(next) === JSON.stringify(applied)
    setApplied(next)
    if (unchanged) void overviewQuery.refetch()
    message.info('正在按当前范围重新组织双域态势')
  }

  const exportBrief = () => {
    if (!overview) return
    downloadText(
      `双域态势研判简报-${overview.as_of.slice(0, 10)}.md`,
      buildBriefMarkdown(overview),
    )
  }

  return (
    <div className="page-scrollable situation-workbench" data-testid="situation-workbench">
      <section className="sw-hero">
        <div className="sw-hero-copy">
          <span className="sw-kicker">同期变化 · 自动部署参考</span>
          <h1>自动态势与部署参谋</h1>
          <p>系统自动汇总案件画像、地图版本和技防摘要，每期只给出最多三项有证据的部署参考。</p>
          <div className="sw-hero-boundary">
            <span>只读分析</span><span>内网计算</span><span>不做犯罪预测</span><span>不自动调度</span>
          </div>
        </div>
        <AutomaticBriefStatus loading={automaticBriefQuery.isPending} failed={automaticBriefQuery.isError}
          errorStatus={(automaticBriefQuery.error as { response?: { status?: number }; status?: number } | null)?.response?.status
            ?? (automaticBriefQuery.error as { status?: number } | null)?.status}
          count={automaticBrief?.recommendations.length} summary={automaticBrief?.summary}
          unavailable={automaticBrief?.status === 'unavailable'} version={automaticBrief?.algorithm_version}
          retry={() => void automaticBriefQuery.refetch()} />
      </section>

      {!automaticBriefQuery.isError && automaticBriefQuery.data?.comparison_snapshot && <section aria-label="完整周期比较">
        <h2>完整周期比较</h2>
        <p>业务时区：{automaticBriefQuery.data.comparison_snapshot.timezone}；区间左闭右开，下面时间使用 UTC 标识。</p>
        <p>本期：{automaticBriefQuery.data.comparison_snapshot.current.start} — {automaticBriefQuery.data.comparison_snapshot.current.end}，
          案发 {automaticBriefQuery.data.comparison_snapshot.current.case_count} 起。</p>
        <p>对照期：{automaticBriefQuery.data.comparison_snapshot.previous.start} — {automaticBriefQuery.data.comparison_snapshot.previous.end}，
          案发 {automaticBriefQuery.data.comparison_snapshot.previous.case_count} 起。</p>
        <p>本期生成画像版本 {automaticBriefQuery.data.comparison_snapshot.current.profile_versions_generated} 份，仅代表处理进度。</p>
        {automaticBriefQuery.data.comparison_snapshot.semantic_changes && <details className="sw-semantic-changes">
          <summary>手法、地点与时段表述变化</summary>
          <p>{automaticBriefQuery.data.comparison_snapshot.semantic_changes.boundary}</p>
          <p>可用画像：上期 {automaticBriefQuery.data.comparison_snapshot.semantic_changes.previous.readable_case_count}/{automaticBriefQuery.data.comparison_snapshot.semantic_changes.previous.case_count} 案，
            本期 {automaticBriefQuery.data.comparison_snapshot.semantic_changes.current.readable_case_count}/{automaticBriefQuery.data.comparison_snapshot.semantic_changes.current.case_count} 案。</p>
          {automaticBriefQuery.data.comparison_snapshot.semantic_changes.state === 'comparable'
            ? <div className="sw-coverage-table"><table><caption>涉及案件数量，非词语出现次数或已确认事实</caption>
              <thead><tr><th>表述</th><th>性质</th><th>上期</th><th>本期</th><th>变化</th></tr></thead>
              <tbody>{automaticBriefQuery.data.comparison_snapshot.semantic_changes.changes.map(item => <tr key={`${item.category}:${item.value}:${item.kind}`}>
                <th>{item.value}</th><td>{{ stated: '明确表述', negated: '否定表述', uncertain: '不确定表述', inferred: '推断表述' }[item.kind] || '待核'}</td>
                <td>{item.previous_count}</td><td>{item.current_count}</td><td>{item.case_count_change}</td>
              </tr>)}</tbody></table></div>
            : <p>两期画像条件不同，暂不计算语义变化。</p>}
          <p>{automaticBriefQuery.data.comparison_snapshot.semantic_changes.information_gaps.join('；')}</p>
        </details>}
        {automaticBriefQuery.data.comparison_snapshot.roads && <RoadChanges data={automaticBriefQuery.data.comparison_snapshot.roads} />}
        {automaticBriefQuery.data.comparison_snapshot.tech_defense && <details><summary>技防同期变化与缺口</summary>
          <p>{automaticBriefQuery.data.comparison_snapshot.tech_defense.boundary}</p>
          {automaticBriefQuery.data.comparison_snapshot.tech_defense.items.map(item => <div key={`${item.source_id}-${item.device_type}`}>
            <strong>来源 {item.source_id} · {item.device_type}</strong>
            <p>{item.state === 'comparable'
              ? `离线报告数：${item.previous?.reported_offline} → ${item.current?.reported_offline}；报警数量变化：${item.alert_change}`
              : '摘要不满足同口径条件，不计算变化率。'}</p>
            <p>{item.information_gaps.join('；')}</p>
          </div>)}
          <p>{automaticBriefQuery.data.comparison_snapshot.tech_defense.information_gaps.join('；')}</p>
        </details>}
      </section>}

      {automaticBrief && automaticBriefQuery.data && (
        <section className="sw-auto-recommendations" aria-label="自动部署建议">
          {automaticBriefQuery.data.recommendations.map(item => (
            <article key={item.id}>
              <header><b>{String(item.rank).padStart(2, '0')}</b><strong>{item.title}</strong><em>规则参考 · 非概率</em></header>
              <p>{item.suggested_action}</p>
              <small>依据：{item.supporting_evidence[0] || item.evidence_refs[0]}</small>
              <small className="gap">缺口：{item.information_gaps[0] || '仍需人工结合现场条件判断'}</small>
              <footer>
                <button onClick={() => feedbackMutation.mutate({ id: item.id, decision: 'adopt_reference', score: 5 })}>可作为参考</button>
                <button onClick={() => feedbackMutation.mutate({ id: item.id, decision: 'insufficient_information' })}>信息不足</button>
              </footer>
            </article>
          ))}
          {!automaticBriefQuery.data.recommendations.length && (
            <div className="empty-state"><span className="icon">◇</span>{automaticBriefQuery.data.status === 'unavailable'
              ? '来源访问条件已变化，历史建议不可展示。' : '本期未达到关注规则，系统未生成泛化建议。'}</div>
          )}
        </section>
      )}

      <SpatialCoveragePanel />

      <details className="sw-history-controls" open={legacyOpen}>
        <summary onClick={event => {
          // Native toggle hides canvases before the deferred toggle event.
          // Keep visibility and chart unmount in the same React update instead.
          event.preventDefault()
          setLegacyOpen(value => !value)
        }}>旧版手动窗口分析（兼容入口，默认不运行）</summary>
        <p>以下采用手动窗口与直线半径，仅供历史对照；不是上方完整周期自动简报，也不代表道路可达性。</p>
        <div className="sw-scope" aria-label="历史态势研判范围">
          <label>
            <span>时间窗口</span>
            <Select value={draft.windowDays} options={WINDOW_OPTIONS} onChange={value => setDraft(current => ({ ...current, windowDays: value }))} />
          </label>
          <label>
            <span>井点参考半径</span>
            <Select value={draft.wellRadiusKm} options={RADIUS_OPTIONS} onChange={value => setDraft(current => ({ ...current, wellRadiusKm: value }))} />
          </label>
          <label className="sw-scope-area">
            <span>区域关键词（可选）</span>
            <Input value={draft.areaKeyword} maxLength={50} allowClear placeholder="如：北区、采油三厂" onChange={event => setDraft(current => ({ ...current, areaKeyword: event.target.value }))} onPressEnter={runAnalysis} />
          </label>
          <button className="btn-primary sw-run" onClick={runAnalysis} disabled={overviewQuery.isFetching}>
            <ThunderboltOutlined />{overviewQuery.isFetching ? '正在研判…' : '重新对比'}
          </button>
        </div>
      {legacyOpen && (overviewQuery.isError ? (
        <section className="empty-state sw-state-panel">
          <span className="icon">!</span>
          <strong>态势研判暂不可用</strong>
          <span>案件、地图和报告主流程不受影响。</span>
          <button className="btn-ghost" onClick={() => void overviewQuery.refetch()}>重新读取</button>
        </section>
      ) : !overview ? (
        <section className="empty-state sw-state-panel"><span className="icon">⌛</span>正在读取增量数据</section>
      ) : (
        <>
          <section className="sw-window-line">
            <span>上一窗口 {overview.window.previous_start.slice(0, 10)}—{overview.window.previous_end.slice(0, 10)}</span>
            <i>对比</i>
            <span>当前窗口 {overview.window.current_start.slice(0, 10)}—{overview.window.current_end.slice(0, 10)}</span>
            <code>SNAP {overview.source_snapshot.data_version.slice(0, 12)}</code>
          </section>

          <section className="sw-kpis" aria-label="态势摘要">
            <article className="sw-kpi sw-kpi--primary">
              <span>本期新增案件</span>
              <strong>{overview.summary.current_case_count}</strong>
              <small className={`sw-change sw-change--${change?.tone}`}>{change?.label}</small>
            </article>
            <article className="sw-kpi">
              <span>历史聚集热点</span><strong>{overview.summary.hotspot_count}</strong><small>限定窗口内形成</small>
            </article>
            <article className="sw-kpi">
              <span>井点空间参考</span><strong>{overview.summary.well_attention_count}</strong><small>按关注度排序</small>
            </article>
            <article className="sw-kpi">
              <span>坐标就绪率</span><strong>{overview.summary.data_readiness_percent}%</strong><small>{overview.summary.geocoded_case_count} 起可做空间分析</small>
            </article>
            <article className="sw-kpi sw-kpi--accent">
              <span>优先核查事项</span><strong>{overview.priorities.length}</strong><small>最多突出三项</small>
            </article>
          </section>

          <section className="sw-pipeline" aria-label="确定性研判步骤">
            {overview.pipeline.map((item, index) => (
              <div key={item.step}>
                <i>{String(index + 1).padStart(2, '0')}</i>
                <span><strong>{item.label}</strong><small>{item.result}</small></span>
                <b>完成</b>
              </div>
            ))}
          </section>

          {overview.summary.analysis_status === 'no_current_data' ? (
            <section className="empty-state sw-state-panel sw-no-data">
              <span className="icon">◇</span>
              <strong>当前范围没有新增案件</strong>
              <span>系统没有生成热点、井点排序或泛化建议。可以扩大时间窗口或清除区域关键词。</span>
            </section>
          ) : (
            <>
              <section className="sw-priority-grid">
                <div className="card sw-priorities">
                  <div className="card-head">
                    <AimOutlined className="ico" /><span className="ti">今日优先核查</span>
                    <span className="spacer" /><span className="chip accent">最多 3 项</span>
                  </div>
                  <div className="sw-priority-list">
                    {overview.priorities.map(item => (
                      <PriorityCard
                        key={item.id}
                        item={item}
                        active={item.id === selectedPriority?.id}
                        onClick={() => setSelectedPriorityId(item.id)}
                      />
                    ))}
                  </div>
                </div>

                <div className="card sw-priority-detail">
                  <div className="card-head"><span className="ico">▤</span><span className="ti">核查依据与边界</span></div>
                  {selectedPriority && (
                    <div className="sw-priority-detail-body">
                      <span className={`sw-level sw-level--${selectedPriority.level}`}>
                        {getPriorityPresentation(selectedPriority).levelLabel}
                      </span>
                      <h2>{selectedPriority.title}</h2>
                      <p>{selectedPriority.finding}</p>
                      <div className="sw-action"><b>建议核查</b><span>{selectedPriority.action}</span></div>
                      <div className="sw-evidence-refs">
                        <b>数据依据</b>
                        <div>{selectedPriority.evidence_refs.map(ref => <code key={ref}>{ref}</code>)}</div>
                      </div>
                      <small className="sw-detail-boundary">{selectedPriority.boundary}</small>
                    </div>
                  )}
                </div>
              </section>

              <section className="sw-analysis-grid">
                <div className="card sw-map-card">
                  <div className="card-head">
                    <RadarChartOutlined className="ico" /><span className="ti">双域时空态势沙盘</span>
                    <span className="spacer" /><span className="sw-map-legend"><i className="case" />案件<i className="hot" />聚集<i className="well" />井点</span>
                  </div>
                  {mapOption && <SituationChart option={mapOption} height={520} />}
                  <div className="sw-map-note">空间坐标窗仅用于态势对比，不是导航地图；虚线只表示限定半径内的空间参考。</div>
                </div>

                <div className="sw-side-stack">
                  <div className="card sw-trend-card">
                    <div className="card-head"><span className="ico">⌁</span><span className="ti">相邻窗口案件走势</span></div>
                    <SituationChart option={trendOption} height={235} />
                  </div>
                  <div className="card sw-pattern-card">
                    <div className="card-head"><span className="ico">≋</span><span className="ti">作案手法变化</span></div>
                    <div className="sw-pattern-list">
                      {overview.pattern_shifts.modus_operandi.slice(0, 5).map(item => (
                        <div key={item.name}>
                          <span><strong>{item.name}</strong><small>上期 {item.previous_count} · 本期 {item.current_count}</small></span>
                          <b className={item.delta > 0 ? 'up' : item.delta < 0 ? 'down' : ''}>
                            {item.delta > 0 ? '+' : ''}{item.delta}
                          </b>
                        </div>
                      ))}
                    </div>
                    <div className="sw-peak-hours">
                      <span>相对集中时点</span>
                      {overview.pattern_shifts.peak_hours.map(item => <code key={item.hour}>{item.hour}:00 · {item.count}起</code>)}
                    </div>
                  </div>
                </div>
              </section>

              <section className="sw-bottom-grid">
                <div className="card sw-wells">
                  <div className="card-head">
                    <EnvironmentOutlined className="ico" /><span className="ti">重点井关注顺序</span>
                    <span className="spacer" /><small>空间参考，不是事实关联</small>
                  </div>
                  <div className="sw-well-list">
                    {overview.well_attention.slice(0, 8).map((item, index) => (
                      <article key={item.asset_id}>
                        <span className="sw-well-rank">{String(index + 1).padStart(2, '0')}</span>
                        <span className="sw-well-main">
                          <strong>{item.name}{item.is_high_production && <em>高产井</em>}</strong>
                          <small>{item.region} · 最近 {item.minimum_distance_km.toFixed(2)}km · 本期 {item.nearby_case_count} 起</small>
                        </span>
                        <span className={`sw-well-score sw-well-score--${item.attention_level}`}>{item.attention_score}</span>
                        <span className={item.verified ? 'sw-verified' : 'sw-unverified'}>{item.verified ? '坐标已核验' : '待核验'}</span>
                      </article>
                    ))}
                    {!overview.well_attention.length && <div className="empty-state"><span className="icon">◇</span>当前半径没有井点空间参考</div>}
                  </div>
                </div>

                <div className="card sw-brief">
                  <div className="card-head">
                    <span className="ico">▧</span><span className="ti">一页研判简报</span>
                    <span className="spacer" />
                    <button className="btn-ghost-sm" onClick={exportBrief}><DownloadOutlined /> 导出 Markdown</button>
                  </div>
                  <div className="sw-brief-body">
                    <h2>{overview.brief.headline}</h2>
                    <div>
                      <strong>事实摘要</strong>
                      {overview.brief.facts.map(item => <p key={item}>{item}</p>)}
                    </div>
                    <div>
                      <strong>研判发现</strong>
                      {(overview.brief.findings.length ? overview.brief.findings : ['当前数据未形成可报告的聚集或井点空间参考。']).map(item => <p key={item}>{item}</p>)}
                    </div>
                    <div>
                      <strong>建议核查</strong>
                      {(overview.brief.suggestions.length ? overview.brief.suggestions : ['当前窗口无新增核查建议。']).map(item => <p key={item}>{item}</p>)}
                    </div>
                  </div>
                </div>
              </section>
            </>
          )}

          <section className="sw-boundary">
            <strong>使用边界</strong>
            {overview.boundary.statements.map(item => <span key={item}>{item}</span>)}
          </section>
        </>
      ))}
      </details>
    </div>
  )
}

export default SituationWorkbench
