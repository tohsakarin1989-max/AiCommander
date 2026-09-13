import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Drawer } from 'antd'
import { FullscreenOutlined, FullscreenExitOutlined, ReloadOutlined } from '@ant-design/icons'
import { useAuth } from '../../auth/AuthContext'
import { authApi } from '../../services/auth'
import { getDashboardSummary } from '../../services/dashboard'
import DashboardRiskMap, { type DashboardMapLayer } from './DashboardRiskMap'
import type { DashboardMapPoint, DashboardWellPoint } from './dashboardCommandModel'
import { trendHeights, validMapCoordinate, mayShowCachedDashboard } from './dailyDashboardModel'
import './Dashboard.css'
import './DailyDashboard.css'
import DashboardActivityList from './DashboardActivityList'

const EMPTY: [] = []
const formatTime = (value: string) => new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
}).format(new Date(value))

export default function DailyDashboard() {
  const { user, sessionEpoch } = useAuth()
  const [areaId, setAreaId] = useState<number | null>(null)
  const [days, setDays] = useState(7)
  const [layer, setLayer] = useState<DashboardMapLayer>('cases')
  const [focus, setFocus] = useState<[number, number] | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [fullscreenError, setFullscreenError] = useState(false)
  const [moreActivity, setMoreActivity] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const scopes = useQuery({ queryKey: ['my-area-scopes', user?.id, sessionEpoch], queryFn: authApi.myAreaScopes, refetchInterval: 30_000 })
  useEffect(() => {
    const available = scopes.data ?? []
    if (!available.some(item => item.operational_area_id === areaId)) {
      setAreaId((available.find(item => item.is_default) ?? available[0])?.operational_area_id ?? null)
    }
  }, [areaId, scopes.data])
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 10_000)
    const onFullscreen = () => setFullscreen(document.fullscreenElement === root.current)
    document.addEventListener('fullscreenchange', onFullscreen)
    return () => { window.clearInterval(timer); document.removeEventListener('fullscreenchange', onFullscreen) }
  }, [])
  const summary = useQuery({
    queryKey: ['cases', 'dashboard', user?.id, sessionEpoch, areaId, days],
    queryFn: ({ signal }) => getDashboardSummary(areaId!, days, signal),
    enabled: areaId != null, refetchInterval: 30_000, retry: 1,
  })
  const authorizedSummary = mayShowCachedDashboard(summary.error) && mayShowCachedDashboard(scopes.error) ? summary.data : undefined
  const allActivity = useQuery({
    queryKey: ['cases', 'dashboard-activities', user?.id, sessionEpoch, areaId, days],
    queryFn: ({ signal }) => getDashboardSummary(areaId!, days, signal, 100),
    enabled: moreActivity && areaId != null && !!authorizedSummary, refetchInterval: moreActivity ? 30_000 : false,
    retry: 1,
  })
  const data = mayShowCachedDashboard(allActivity.error) ? authorizedSummary : undefined
  const cases = useMemo<DashboardMapPoint[]>(() => (data?.map.cases ?? []).map(item => ({
    id: item.id, caseNumber: item.case_number, latitude: item.latitude, longitude: item.longitude,
    x: 0, y: 0, chainPosition: 'unknown', label: item.case_type ?? '未分类', color: '#c63845', shape: 'circle',
  })), [data?.map.cases])
  const wells = useMemo<DashboardWellPoint[]>(() => (data?.map.wells ?? []).map(item => ({
    assetId: item.id, name: item.name, latitude: item.latitude, longitude: item.longitude, x: 0, y: 0,
    attentionScore: 0, attentionLevel: 'watch', signalCount: 0, isHighProduction: false, region: '',
  })), [data?.map.wells])
  const heights = trendHeights(data?.trend.map(item => item.count) ?? [])
  const stale = !!data && (summary.isError || scopes.isError || now - new Date(data.as_of).getTime() > 90_000)
  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen()
      else await root.current?.requestFullscreen()
      setFullscreenError(false)
    } catch { setFullscreenError(true) }
  }

  return <div ref={root} className="daily-dashboard">
    <header className="daily-heading">
      <div><h1>涉油案件态势总览</h1></div>
      <div className="daily-controls">
        <label>辖区<select aria-label="大屏辖区" value={areaId ?? ''} onChange={event => {
          setAreaId(Number(event.target.value)); setFocus(null)
        }}>
          {!scopes.data?.length && <option value="">暂无授权辖区</option>}
          {scopes.data?.map(item => <option key={item.operational_area_id} value={item.operational_area_id}>{item.area_name}</option>)}
        </select></label>
        <label>周期<select aria-label="大屏周期" value={days} onChange={event => { setDays(Number(event.target.value)); setFocus(null) }}>
          <option value={7}>最近 7 天</option><option value={30}>最近 30 天</option>
        </select></label>
        <button aria-label="刷新" title="刷新" onClick={() => void summary.refetch()} disabled={areaId == null || summary.isFetching}><ReloadOutlined /></button>
        <button className="daily-fullscreen" onClick={() => void toggleFullscreen()}>{fullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}{fullscreen ? '退出全屏' : '全屏投屏'}</button>
      </div>
    </header>
    <div className="daily-status" role="status">
      {data ? <><span>北京时间 {formatTime(data.period.start)} — {formatTime(data.as_of)}</span>
        <span className={stale ? 'daily-warning' : ''}>{stale ? '数据已过期，请刷新' : summary.isFetching ? '正在更新' : '每 30 秒自动更新'}</span></>
        : <span>{scopes.isError || summary.isError ? '数据读取失败，不能视为无案件。' : scopes.isPending || summary.isFetching ? '正在读取完整授权数据…' : '当前没有可查看的辖区。'}</span>}
      {fullscreenError && <span className="daily-warning">浏览器不支持全屏，可继续在当前窗口使用。</span>}
    </div>
    {(scopes.isError || summary.isError) && <div className="daily-message" role="alert">
      无法取得最新授权数据，请检查连接或权限后重试。
      <button onClick={() => { void scopes.refetch(); if (areaId) void summary.refetch() }}>重试</button>
    </div>}
    {data && <>
      <section className="daily-metrics" aria-label="统一口径态势指标">
        {[
          { label: '本期案件', value: data.metrics.cases, unit: '起', note: '按案发时间统计，包含无坐标案件', detail: data.definitions.cases },
          { label: '较上一同长度周期', value: `${data.metrics.change > 0 ? '+' : ''}${data.metrics.change}`, unit: '起', note: `上期 ${data.metrics.previous_cases} 起，同样 ${days} 天`, detail: '数量增减不直接代表风险变化' },
          { label: '范围内登记井', value: data.metrics.registered_wells, unit: '口', note: '当前有效登记井，非历史井数', detail: data.definitions.registered_wells },
          { label: '完成研判次数', value: data.metrics.analysis_results, unit: '次', note: '按完成时间，含降级完成和重算', detail: data.definitions.analysis_results },
        ].map(item => <article key={item.label} title={item.detail}><h2>{item.label}</h2><div className="daily-value">{item.value}<small>{item.unit}</small></div><p>{item.note}</p></article>)}
      </section>
      <div className="daily-main-grid">
        <section className="daily-activity-panel"><h2>最新动态</h2>
          <DashboardActivityList key={`${areaId}:${days}`} items={data.activities ?? EMPTY} onLocate={point => { setLayer('cases'); setFocus(point) }} />
          <button className="activity-more" onClick={() => setMoreActivity(true)}>查看更多动态</button>
          {data.processing && <div className="daily-processing">排队 {data.processing.pending} · 处理 {data.processing.processing}<br />重试 {data.processing.retry} · 失败 {data.processing.failed}</div>}
        </section>
        <section className="daily-map-panel">
          <div className="daily-panel-heading"><h2>案件与登记井分布</h2><div className="daily-layer-buttons">
            <button aria-pressed={layer === 'cases'} onClick={() => setLayer('cases')}>本期案件</button>
            <button aria-pressed={layer === 'attention'} onClick={() => setLayer('attention')}>登记井</button>
          </div></div>
          <div className="daily-map-frame">
            <DashboardRiskMap key={areaId} operationalAreaId={areaId!} layer={layer} cases={cases} wells={wells}
              signals={EMPTY} chainLines={EMPTY} hotspots={EMPTY} neutralWells focus={focus}
              isFullscreen={fullscreen} onToggleFullscreen={() => void toggleFullscreen()} />
          </div>
          <p className="daily-map-caption">
            {layer === 'cases'
              ? `有有效坐标 ${data.map.coordinate_cases} 起，当前展示 ${cases.length} 起；缺失或异常坐标 ${data.map.missing_coordinate_cases} 起仍计入案件总数。`
              : `有有效坐标登记井 ${data.map.coordinate_wells} 口，当前展示 ${wells.length} 口；井点分布不代表风险等级。`}
            {(layer === 'cases' ? data.map.cases_truncated : data.map.wells_truncated) && ' 点位展示已限额，统计未截断。'}
          </p>
        </section>
        <aside className="daily-attention"><h2>本期变化关注</h2><p>近期已有候选与类型数量变化，不代表风险排名</p>
          {data.attention_scan?.truncated && <p>候选仅检索最近 {data.attention_scan.limit} 份当前成果，未展示内容不代表不存在；总量统计未截断。</p>}
          {!data.attention.length && <div className="daily-message">暂无可展示候选或类型数量上升，不强行生成关注建议。</div>}
          {data.attention.map((item, index) => <article key={item.id ?? item.case_type ?? 'unknown'}>
            <details><summary><span className="daily-order">0{index + 1}</span><h3>{item.title}</h3>
            <p>{item.kind === 'existing_insight' ? '已有待核验候选 · 查看证据'
              : `本期 ${item.current_count} 起 / 上期 ${item.previous_count} 起 · 查看依据`}</p></summary>
            {item.kind === 'existing_insight' && <>
              <p>{item.claim}</p>
              <p>规则支持度 {item.rule_support}，不是准确概率。</p>
              <dl>
                <dt>支持证据</dt><dd>{item.supporting_evidence?.join('；') || '未提供'}</dd>
                <dt>反向证据</dt><dd>{item.counter_evidence?.join('；') || '未提供'}</dd>
                <dt>信息缺口</dt><dd>{item.information_gaps?.join('；') || '未列出，不代表证据完整'}</dd>
                <dt>引用</dt><dd>{item.evidence_refs?.join('；')}</dd>
              </dl>
              <p>画像 {item.case_profile_id} · 地图 {item.map_snapshot_id} · 算法 {item.algorithm_version}</p>
            </>}
            <ul>{item.evidence.map(evidence => <li key={evidence.case_id}>
              <Link to={`/cases?caseId=${evidence.case_id}`}>{evidence.case_number}</Link>
              {validMapCoordinate(evidence.latitude, evidence.longitude) && <button onClick={() => {
                setLayer('cases'); setFocus([evidence.latitude!, evidence.longitude!])
              }}>地图定位</button>}
            </li>)}</ul><p className="daily-boundary">{item.boundary}</p></details>
          </article>)}
          <section className="daily-results"><h2>最新研判成果</h2><DashboardActivityList items={data.recent_results ?? EMPTY} auto={false} onLocate={point => { setLayer('cases'); setFocus(point) }} /></section>
        </aside>
      </div>
      <div className="daily-bottom-grid">
      <section className="daily-trend"><div className="daily-panel-heading"><h2>案件发生趋势</h2><p>{data.definitions.trend}</p></div>
        <div className="daily-trend-columns">{data.trend.map((item, index) => <div key={item.date} className="daily-trend-column" title={`${item.date}：${item.count} 起`}>
          <span>{item.count}</span><div className="daily-trend-track"><div style={{ height: `${heights[index]}%` }} /></div><span>{item.date.slice(5)}</span>
        </div>)}</div>
      </section>
      <section className="daily-completion"><h2>研判完成状态</h2>{data.completion ? [
        { name: '正常完成', count: data.completion.completed }, { name: '降级完成', count: data.completion.degraded },
      ].map(item => <div key={item.name}><span>{item.name}</span><meter aria-label={item.name} min={0} max={Math.max(data.metrics.analysis_results, 1)} value={item.count} /><strong>{item.count}</strong></div>) : <p>暂无状态统计</p>}<p>按研判运行完成时间统计</p></section>
      </div>
    </>}
    <Drawer title="本期最新动态（最多 100 条）" open={moreActivity} onClose={() => setMoreActivity(false)} getContainer={() => root.current!} width={480}>
      {data && mayShowCachedDashboard(allActivity.error) ? <><p role="status">{allActivity.isError ? '刷新失败，以下为缓存记录' : allActivity.isFetching ? '正在更新' : ''}</p><DashboardActivityList key={`${areaId}:${days}`} items={allActivity.data?.activities ?? EMPTY} auto={false} onLocate={point => { setLayer('cases'); setFocus(point); setMoreActivity(false) }} /></> : <p>数据不可访问，请重新确认权限。</p>}
    </Drawer>
  </div>
}
