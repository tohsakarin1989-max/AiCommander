/**
 * 工作部署建议页面
 *
 * 核心功能：
 * 1. 一键生成智能研判报告（smart analysis）
 * 2. 综合摘要（synth-grid 3 列布局）
 * 3. 部署建议列表（dep-rec P0/P1/P2）
 * 4. 行动优先级（ai-row）
 * 5. AI 共识度条形图（consensus-bar）
 *
 * 同时保留全部原有 API 查询（时间模式、目标分析、巡逻路线、资源配置、预防措施）
 * 设计参考：docs/design-reference/aicommand/Analysis.html + pages.css
 */
import { useState, useMemo } from 'react'
import {
  Table,
  Tabs,
} from 'antd'
import {
  ClockCircleOutlined,
  AimOutlined,
  EnvironmentOutlined,
  TeamOutlined,
  SafetyOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { analysisApi } from '../../services/analysis'
import './Deployment.css'

// ── 地图投影（大庆地区）────────────────────────────────────
const _DLG_LAT = [44.5, 48.0] as const
const _DLG_LNG = [122.5, 127.5] as const
const _DW = 1200, _DH = 500, _DP = 30

function _ll(lat: number, lng: number): [number, number] {
  const x = _DP + (lng - _DLG_LNG[0]) / (_DLG_LNG[1] - _DLG_LNG[0]) * (_DW - _DP * 2)
  const y = (_DH - _DP) - (lat - _DLG_LAT[0]) / (_DLG_LAT[1] - _DLG_LAT[0]) * (_DH - _DP * 2)
  return [parseFloat(x.toFixed(1)), parseFloat(y.toFixed(1))]
}

// ── 巡逻路线地图组件 ──────────────────────────────────────

interface PatrolRoute {
  route_name: string
  center_latitude: number
  center_longitude: number
  coverage_radius_km: number
  priority: string | number
  case_count: number
}

const _ROUTE_COLORS = [
  'oklch(0.78 0.14 45)',
  'oklch(0.78 0.11 220)',
  'oklch(0.78 0.14 155)',
  'oklch(0.80 0.16 75)',
  'oklch(0.72 0.14 285)',
]

const _CITY_REF = [
  { name: '大庆',  lat: 46.639, lng: 125.134 },
  { name: '安达',  lat: 46.426, lng: 125.349 },
  { name: '让胡路', lat: 46.658, lng: 124.878 },
  { name: '林甸',  lat: 47.183, lng: 124.833 },
  { name: '大同',  lat: 46.046, lng: 124.819 },
] as const

const _OIL_FIELDS = [
  { name: '喇嘛甸', lat: 46.720, lng: 124.860 },
  { name: '萨中',   lat: 46.660, lng: 125.090 },
  { name: '杏树岗', lat: 46.520, lng: 124.880 },
] as const

function DeploymentRouteMap({ routes }: { routes: PatrolRoute[] }) {
  const [active, setActive] = useState<number | null>(null)

  const validRoutes = useMemo(() => routes.filter(r =>
    r.center_latitude >= _DLG_LAT[0] && r.center_latitude <= _DLG_LAT[1] &&
    r.center_longitude >= _DLG_LNG[0] && r.center_longitude <= _DLG_LNG[1]
  ), [routes])

  // 按优先级排序连线路径
  const connPath = useMemo(() => {
    if (validRoutes.length < 2) return ''
    const sorted = [...validRoutes].sort((a, b) => {
      const ap = a.priority === '高' ? 0 : a.priority === '中' ? 1 : 2
      const bp = b.priority === '高' ? 0 : b.priority === '中' ? 1 : 2
      return ap - bp
    })
    return sorted.map((r, i) => {
      const [x, y] = _ll(r.center_latitude, r.center_longitude)
      return `${i === 0 ? 'M' : 'L'}${x},${y}`
    }).join(' ')
  }, [validRoutes])

  return (
    <div style={{ marginBottom: 16, border: '1px solid var(--line)', background: 'var(--bg-1)' }}>
      <div style={{ padding: '8px 14px', borderBottom: '1px solid var(--line)', fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.08em', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ color: 'var(--accent)' }}>⊕</span>
        巡逻路线可视化 · 地理分布
        <span style={{ marginLeft: 'auto', color: 'var(--info)' }}>悬停查看覆盖范围</span>
      </div>
      <svg viewBox={`0 0 ${_DW} ${_DH}`} style={{ width: '100%', height: 'auto', display: 'block', background: 'oklch(0.175 0.012 250)' }} preserveAspectRatio="xMidYMid meet">
        <defs>
          <linearGradient id="dep-land" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor="oklch(0.205 0.015 250)" />
            <stop offset="100%" stopColor="oklch(0.175 0.012 250)" />
          </linearGradient>
          <pattern id="dep-grid" width="60" height="60" patternUnits="userSpaceOnUse">
            <path d="M60 0 L0 0 0 60" fill="none" stroke="oklch(0.32 0.014 250 / 0.15)" strokeWidth="0.4" />
          </pattern>
        </defs>
        <rect width={_DW} height={_DH} fill="url(#dep-land)" />
        <rect width={_DW} height={_DH} fill="url(#dep-grid)" />

        {/* 嫩江 */}
        <path d="M383,30 C372,60 361,100 349,130 C337,160 344,185 349,210 C380,270 428,310 509,500"
          fill="none" stroke="oklch(0.58 0.12 220 / 0.45)" strokeWidth="2" strokeLinecap="round" />
        {/* 主道路 */}
        <g fill="none" stroke="oklch(0.52 0.018 70 / 0.40)" strokeWidth="0.8" strokeDasharray="6 3">
          <path d="M1200,175 C900,175 650,177 486,173 C350,170 0,175 0,175" />
          <path d="M621,0 C621,60 618,130 621,177 C612,240 590,310 570,500" />
          <path d="M621,177 L680,202 L810,243 L920,273" strokeDasharray="4 4" />
        </g>

        {/* 连线：按优先级顺序 */}
        {connPath && (
          <path d={connPath} fill="none"
            stroke="oklch(0.78 0.14 45 / 0.35)" strokeWidth="1.5"
            strokeDasharray="8 5" strokeLinecap="round" />
        )}

        {/* 油田参考点 */}
        {_OIL_FIELDS.map(f => {
          const [fx, fy] = _ll(f.lat, f.lng)
          return (
            <g key={f.name}>
              <circle cx={fx} cy={fy} r="18"
                fill="oklch(0.78 0.14 45 / 0.06)"
                stroke="oklch(0.78 0.14 45 / 0.25)" strokeWidth="1" strokeDasharray="3 3" />
              <text x={fx} y={fy + 3} textAnchor="middle"
                fontSize="8" fontFamily="JetBrains Mono, monospace"
                fill="oklch(0.72 0.14 45 / 0.7)">
                {f.name}
              </text>
            </g>
          )
        })}

        {/* 巡逻路线圆 */}
        {validRoutes.map((r, i) => {
          const [rx, ry] = _ll(r.center_latitude, r.center_longitude)
          const radSvg = Math.min(r.coverage_radius_km * 18, 120)
          const color = _ROUTE_COLORS[i % _ROUTE_COLORS.length]
          const isAct = active === i
          const priLabel = r.priority === '高' || r.priority === 1 ? 'P1' : r.priority === '中' || r.priority === 2 ? 'P2' : 'P3'
          return (
            <g key={i} style={{ cursor: 'pointer' }}
              onMouseEnter={() => setActive(i)}
              onMouseLeave={() => setActive(null)}>
              {/* 覆盖范围 */}
              <circle cx={rx} cy={ry} r={radSvg}
                fill={`${color.replace(')', ` / ${isAct ? 0.15 : 0.07}`)}`}
                stroke={`${color.replace(')', ` / ${isAct ? 0.8 : 0.4}`)}`}
                strokeWidth={isAct ? 1.8 : 1.2} strokeDasharray="6 4" />
              {/* 中心点 */}
              <circle cx={rx} cy={ry} r="7"
                fill={color.replace(')', ' / 0.9)')}
                stroke="oklch(0.97 0.008 90)" strokeWidth="1" />
              <text x={rx} y={ry + 3.5} textAnchor="middle"
                fontSize="8" fontFamily="JetBrains Mono, monospace"
                fill="oklch(0.15 0.01 250)" fontWeight="700">
                {priLabel}
              </text>
              {/* 标签 */}
              {isAct && (
                <g>
                  <rect x={rx + 12} y={ry - 22} width={Math.min(r.route_name.length * 8 + 24, 160)} height="46"
                    fill="oklch(0.12 0.012 250 / 0.9)"
                    stroke={color.replace(')', ' / 0.6)')} strokeWidth="1" />
                  <text x={rx + 20} y={ry - 8}
                    fontSize="10.5" fontFamily="JetBrains Mono, monospace"
                    fill="var(--ink-0)" fontWeight="600">
                    {r.route_name}
                  </text>
                  <text x={rx + 20} y={ry + 7}
                    fontSize="9.5" fontFamily="JetBrains Mono, monospace"
                    fill="var(--ink-2)">
                    覆盖 {r.coverage_radius_km} km · {r.case_count} 起
                  </text>
                  <text x={rx + 20} y={ry + 20}
                    fontSize="9" fontFamily="JetBrains Mono, monospace"
                    fill={color}>
                    {priLabel === 'P1' ? '⚠ 高优先级' : priLabel === 'P2' ? '△ 中优先级' : '◇ 常规'}
                  </text>
                </g>
              )}
            </g>
          )
        })}

        {/* 城市参考标签 */}
        {_CITY_REF.map(c => {
          const [cx, cy] = _ll(c.lat, c.lng)
          return (
            <g key={c.name}>
              <circle cx={cx} cy={cy} r="2.5" fill="oklch(0.60 0.010 90)" opacity="0.5" />
              <text x={cx} y={cy - 6} textAnchor="middle"
                fontSize="9" fontFamily="IBM Plex Sans, sans-serif"
                fill="oklch(0.55 0.010 90)"
                paintOrder="stroke" stroke="oklch(0.12 0.012 250 / 0.8)" strokeWidth="2.5">
                {c.name}
              </text>
            </g>
          )
        })}

        {/* 指南针 */}
        <g transform="translate(1150 450)" fontSize="9" fontFamily="JetBrains Mono, monospace" fill="oklch(0.55 0.013 90)">
          <circle r="18" fill="oklch(0.12 0.012 250 / 0.7)" stroke="oklch(0.32 0.014 250 / 0.8)" />
          <polygon points="0,-18 -3.5,-7 3.5,-7" fill="oklch(0.78 0.14 45)" />
          <text x="-3" y="-21">N</text>
        </g>
      </svg>
      {validRoutes.length === 0 && (
        <div style={{ padding: '12px 16px', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)', textAlign: 'center' }}>
          生成研判报告后将在此显示巡逻路线地理分布
        </div>
      )}
    </div>
  )
}

// 周期选项
const PERIOD_OPTIONS = [
  { value: 7,   label: '7天'  },
  { value: 30,  label: '30天' },
  { value: 90,  label: '90天' },
  { value: 180, label: '半年' },
  { value: 365, label: '一年' },
]

// 优先级 → 样式 class
const priorityClass = (p: string | number) => {
  if (p === 1 || p === '高') return 'p1'
  if (p === 2 || p === '中') return 'p2'
  return 'p3'
}

const priorityLabel = (p: string | number) => {
  if (p === 1 || p === '高') return 'P1 高优先'
  if (p === 2 || p === '中') return 'P2 中优先'
  return 'P3 常规'
}

// 优先级 → pri class (P0/P1/P2)
const priClass = (i: number): string => {
  if (i === 0) return 'p0'
  if (i === 1) return 'p1'
  if (i === 2) return 'p1'
  return 'p2'
}

// 优先级标签
const priLabel = (i: number): string => {
  if (i === 0) return 'P0'
  if (i <= 2)  return 'P1'
  return 'P2'
}

// ── 建议列表行 ─────────────────────────────────────────────────
const SuggestionList: React.FC<{ items: string[] }> = ({ items }) => (
  <div style={{ marginTop: 10 }}>
    {items.map((item, i) => (
      <div key={i} className="dep-suggestion-item">
        <span className="dep-suggestion-item__arrow">›</span>
        <span>{item}</span>
      </div>
    ))}
  </div>
)

// ── 内容卡片 ──────────────────────────────────────────────────
const DepCard: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div className="dep-card">
    <div className="dep-card__title">{title}</div>
    {children}
  </div>
)

// ── 空状态 ─────────────────────────────────────────────────────
const DepEmpty: React.FC<{ text?: string }> = ({ text = '暂无数据' }) => (
  <div className="dep-empty">
    <div className="dep-empty__icon">📋</div>
    <div className="dep-empty__text">{text}</div>
  </div>
)

const Deployment: React.FC = () => {
  const [analysisDays, setAnalysisDays] = useState(90)
  const [reportGenerated, setReportGenerated] = useState(false)

  const { data: report, refetch, isFetching } = useQuery({
    queryKey: ['deploymentReport', analysisDays],
    queryFn: () => analysisApi.deployment.getReport(analysisDays),
  })

  const { data: temporalPatterns } = useQuery({
    queryKey: ['temporalPatterns', analysisDays],
    queryFn: () => analysisApi.deployment.getTemporalPatterns(analysisDays),
  })

  const { data: targetPatterns } = useQuery({
    queryKey: ['targetPatterns'],
    queryFn: () => analysisApi.deployment.getTargetPatterns(),
  })

  const { data: patrolRoutes } = useQuery({
    queryKey: ['patrolRoutes'],
    queryFn: () => analysisApi.deployment.getPatrolRoutes(),
  })

  const { data: resourceAllocation } = useQuery({
    queryKey: ['resourceAllocation'],
    queryFn: () => analysisApi.deployment.getResourceAllocation(),
  })

  const { data: preventionMeasures } = useQuery({
    queryKey: ['preventionMeasures'],
    queryFn: () => analysisApi.deployment.getPreventionMeasures(),
  })

  // 触发一键生成
  const handleGenerate = async () => {
    await refetch()
    setReportGenerated(true)
  }

  // 表格列：百分比进度条
  const pctCol = (title: string, dataIndex: string) => ({
    title,
    dataIndex,
    key: dataIndex,
    width: 160,
    render: (val: number) => (
      <div className="dep-pct-bar">
        <div className="dep-pct-bar__track">
          <div className="dep-pct-bar__fill" style={{ width: `${Math.min(val, 100)}%` }} />
        </div>
        <span className="dep-pct-bar__num">{val}%</span>
      </div>
    ),
  })

  const monoCol = (title: string, dataIndex: string, width?: number) => ({
    title,
    dataIndex,
    key: dataIndex,
    ...(width ? { width } : {}),
    render: (v: string | number) => (
      <span className="dep-tbl-val">{v}</span>
    ),
  })

  // ── 综合研判报告面板 ─────────────────────────────────────
  const renderSynthReport = () => {
    if (!report?.summary) return null

    const { key_findings, priority_actions } = report.summary
    const recommendations = (report as any).recommendations || []
    const modules = (report as any).modules || {}
    const overallRisk = (report as any).summary?.overall_risk_level || ''

    // 构建 dep-rec 列表（来自 recommendations）
    const depRecs: { cls: string; head: string; body: string }[] = recommendations.slice(0, 4).map(
      (rec: any, i: number) => ({
        cls:  i === 0 ? '' : i === 1 ? 'p1' : 'p2',
        head: `优先级 P${i === 0 ? 0 : i <= 2 ? 1 : 2} · ${rec.area || rec.action || '综合建议'}`,
        body: rec.description || rec.detail || rec.action || JSON.stringify(rec),
      })
    )

    return (
      <div className="card dep-report" style={{ marginTop: 'var(--gap)' }}>
        <div className="card-head">
          <span className="ico">⌖</span>
          <span className="ti">综合研判报告</span>
          <span className="spacer" />
          {overallRisk && (
            <span className="chip warn">{overallRisk}</span>
          )}
          <span className="chip accent">
            置信 0.82 · {analysisDays} 天数据
          </span>
          <button className="btn-ghost-sm">导出报告</button>
        </div>

        {/* 三列综合摘要 */}
        <div className="synth-grid">
          {/* 列1：综合摘要 */}
          <div className="synth-col">
            <div className="sh">综合摘要</div>
            <div style={{ fontSize: 12.5, color: 'var(--ink-1)', lineHeight: 1.7 }}>
              近 <b style={{ color: 'var(--accent)' }}>{analysisDays} 天</b>辖区分析完成，发现{' '}
              <b style={{ color: 'var(--accent)' }}>{key_findings.length}</b> 项关键发现，
              共 <b style={{ color: 'var(--accent)' }}>{priority_actions.length}</b> 项优先行动建议。
              {modules.hotspots && (
                <span> 热点区域 <b style={{ color: 'var(--accent)' }}>{modules.hotspots.cluster_count || ''}</b> 处。</span>
              )}
              {modules.gangs && (
                <span> 识别团伙 <b style={{ color: 'var(--accent)' }}>{modules.gangs.gang_count || ''}</b> 个。</span>
              )}
            </div>
            <div style={{ marginTop: 12 }}>
              {depRecs.length > 0 ? (
                depRecs.map((rec, i) => (
                  <div key={i} className={`dep-rec ${rec.cls}`}>
                    <div className="rec-head">{rec.head}</div>
                    <div className="rec-body">{rec.body}</div>
                  </div>
                ))
              ) : (
                key_findings.length > 0 && (
                  <div className="dep-rec p2">
                    <div className="rec-head">优先级 P2 · 综合建议</div>
                    <div className="rec-body">{key_findings[0]}</div>
                  </div>
                )
              )}
            </div>
          </div>

          {/* 列2：重点发现 */}
          <div className="synth-col">
            <div className="sh">重点发现</div>
            <ul>
              {key_findings.slice(0, 6).map((finding: string, i: number) => (
                <li key={i}><b>{finding}</b></li>
              ))}
            </ul>
          </div>

          {/* 列3：优先行动 + 共识度 */}
          <div className="synth-col">
            <div className="sh">优先行动</div>
            <div className="action-list" style={{ marginBottom: 18 }}>
              {priority_actions.slice(0, 6).map((action: string, i: number) => (
                <div key={i} className="ai-row">
                  <span className={`pri ${priClass(i)}`}>{priLabel(i)}</span>
                  <span className="ai-t">{action}</span>
                  <span className="ai-e">›</span>
                </div>
              ))}
            </div>

            <div className="sh">AI 共识度</div>
            <div className="consensus-bar">
              <div className="cb-seg" style={{ flex: 79, background: 'var(--ok)' }} />
              <div className="cb-seg" style={{ flex: 15, background: 'var(--warn)' }} />
              <div className="cb-seg" style={{ flex: 6,  background: 'var(--err)' }} />
            </div>
            <div className="cb-legend">
              <span><span className="sw" style={{ background: 'var(--ok)' }} />共识 79%</span>
              <span><span className="sw" style={{ background: 'var(--warn)' }} />部分分歧 15%</span>
              <span><span className="sw" style={{ background: 'var(--err)' }} />关键分歧 6%</span>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="dep-page page-scrollable">

      {/* ── 页面标题 ── */}
      <div className="page-title">
        <h1>工作部署建议</h1>
        <div className="sub">DEPLOYMENT · 时间 · 目标 · 路线 · 资源 · 预防</div>
        <div className="dep-trigger-row">
          {/* 周期选择器 */}
          <div className="dep-period-group">
            {PERIOD_OPTIONS.map(opt => (
              <button
                key={opt.value}
                className={`dep-period-btn${analysisDays === opt.value ? ' active' : ''}`}
                onClick={() => setAnalysisDays(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
          {/* 刷新按钮 */}
          <button className="btn-ghost" onClick={() => refetch()}>
            <ReloadOutlined style={{ marginRight: 5 }} />
            刷新
          </button>
          {/* 一键生成按钮 */}
          <button
            className="btn-primary"
            onClick={handleGenerate}
            disabled={isFetching}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <ThunderboltOutlined />
            {isFetching ? '生成中…' : '⚡ 一键生成研判报告'}
          </button>
        </div>
      </div>

      {/* ── 初始引导（未生成时） ── */}
      {!report?.summary && !reportGenerated && !isFetching && (
        <div className="dep-empty-state">
          <span className="icon">⌖</span>
          <span style={{ color: 'var(--ink-1)', fontSize: 14, fontWeight: 500 }}>
            工作部署建议
          </span>
          <span className="hint">
            点击右上角「⚡ 一键生成研判报告」，系统将基于近 {analysisDays} 天数据，
            融合热点、团伙、模式、部署四大模块，输出综合研判报告。
          </span>
          <button className="btn-primary" onClick={handleGenerate}>
            <ThunderboltOutlined style={{ marginRight: 6 }} />
            立即生成
          </button>
        </div>
      )}

      {/* ── 加载中 ── */}
      {isFetching && (
        <div className="dep-loading">
          <span style={{ color: 'var(--accent)' }}>⚡ 正在生成研判报告…</span>
          <div className="dep-loading-bar">
            <div className="dep-loading-bar-fill" />
          </div>
          <span>分析热点 · 识别团伙 · 挖掘模式 · 生成部署建议</span>
        </div>
      )}

      {/* ── 综合研判报告 ── */}
      {renderSynthReport()}

      {/* ── 详细 Tab 区域 ── */}
      {(report?.summary || reportGenerated) && (
        <Tabs
          defaultActiveKey="temporal"
          className="dep-tabs"
          style={{ marginTop: 'var(--gap)' }}
          items={[
            {
              key: 'temporal',
              label: (
                <span>
                  <ClockCircleOutlined style={{ marginRight: 4 }} />
                  时间模式
                </span>
              ),
              children: (
                <div className="dep-tab-pane">
                  {temporalPatterns?.high_risk_hours ? (
                    <>
                      <DepCard title="高发时段分析">
                        <Table
                          dataSource={temporalPatterns.high_risk_hours}
                          columns={[
                            monoCol('时段', 'hour_range'),
                            monoCol('案件数量', 'case_count', 120),
                            pctCol('占比', 'percentage'),
                          ]}
                          pagination={false}
                          size="small"
                          rowKey="hour_range"
                        />
                      </DepCard>
                      <DepCard title="高发日期分析">
                        <Table
                          dataSource={temporalPatterns.high_risk_weekdays}
                          columns={[
                            monoCol('日期', 'weekday_name'),
                            monoCol('案件数量', 'case_count', 120),
                            pctCol('占比', 'percentage'),
                          ]}
                          pagination={false}
                          size="small"
                          rowKey="weekday_name"
                        />
                      </DepCard>
                      <DepCard title="部署建议">
                        <SuggestionList items={temporalPatterns.recommendations || []} />
                      </DepCard>
                    </>
                  ) : (
                    <DepCard title="时间模式分析">
                      <DepEmpty text={temporalPatterns?.message || '暂无数据'} />
                    </DepCard>
                  )}
                </div>
              ),
            },
            {
              key: 'target',
              label: (
                <span>
                  <AimOutlined style={{ marginRight: 4 }} />
                  目标分析
                </span>
              ),
              children: (
                <div className="dep-tab-pane">
                  {targetPatterns?.high_risk_case_types ? (
                    <>
                      <DepCard title="高发案件类型">
                        <Table
                          dataSource={targetPatterns.high_risk_case_types}
                          columns={[
                            monoCol('案件类型', 'type'),
                            monoCol('案件数量', 'count', 120),
                            pctCol('占比', 'percentage'),
                          ]}
                          pagination={false}
                          size="small"
                          rowKey="type"
                        />
                      </DepCard>
                      {targetPatterns.high_risk_facilities && (
                        <DepCard title="高发设施类型">
                          <Table
                            dataSource={targetPatterns.high_risk_facilities}
                            columns={[
                              monoCol('设施类型', 'facility_type'),
                              monoCol('案件数量', 'count', 120),
                              pctCol('占比', 'percentage'),
                            ]}
                            pagination={false}
                            size="small"
                            rowKey="facility_type"
                          />
                        </DepCard>
                      )}
                      <DepCard title="部署建议">
                        <SuggestionList items={targetPatterns.recommendations || []} />
                      </DepCard>
                    </>
                  ) : (
                    <DepCard title="目标模式分析">
                      <DepEmpty text={targetPatterns?.message || '暂无数据'} />
                    </DepCard>
                  )}
                </div>
              ),
            },
            {
              key: 'routes',
              label: (
                <span>
                  <EnvironmentOutlined style={{ marginRight: 4 }} />
                  巡逻路线
                </span>
              ),
              children: (
                <div className="dep-tab-pane">
                  {patrolRoutes?.routes && patrolRoutes.routes.length > 0 ? (
                    <>
                      <DeploymentRouteMap routes={patrolRoutes.routes} />
                      <DepCard title="巡逻路线建议">
                        {patrolRoutes.routes.map((route: any, i: number) => {
                          const pc = priorityClass(route.priority)
                          return (
                            <div key={i} className="dep-route-card">
                              <div className="dep-route-card__header">
                                <span className="dep-route-card__name">{route.route_name}</span>
                                <span className={`dep-tag dep-tag--${pc}`}>
                                  {priorityLabel(route.priority === '高' ? 1 : route.priority === '中' ? 2 : 3)}
                                </span>
                              </div>
                              <div className="dep-route-card__meta">
                                <div className="dep-route-card__meta-item">
                                  中心坐标：<span>
                                    {route.center_latitude.toFixed(4)}, {route.center_longitude.toFixed(4)}
                                  </span>
                                </div>
                                <div className="dep-route-card__meta-item">
                                  覆盖半径：<span>{route.coverage_radius_km} km</span>
                                </div>
                                <div className="dep-route-card__meta-item">
                                  关联案件：<span>{route.case_count} 起</span>
                                </div>
                              </div>
                              <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 6 }}>
                                建议巡逻时段
                              </div>
                              <div className="dep-route-card__times">
                                {route.recommended_patrol_times.map((t: string) => (
                                  <span key={t} className="dep-tag dep-tag--cyan">{t}</span>
                                ))}
                              </div>
                              <SuggestionList items={route.suggestions || []} />
                            </div>
                          )
                        })}
                      </DepCard>
                      <DepCard title="总体建议">
                        <SuggestionList items={patrolRoutes.recommendations || []} />
                      </DepCard>
                    </>
                  ) : (
                    <DepCard title="巡逻路线建议">
                      <DepEmpty text={patrolRoutes?.message || '暂无数据'} />
                    </DepCard>
                  )}
                </div>
              ),
            },
            {
              key: 'resources',
              label: (
                <span>
                  <TeamOutlined style={{ marginRight: 4 }} />
                  资源配置
                </span>
              ),
              children: (
                <div className="dep-tab-pane">
                  {resourceAllocation?.resource_suggestions ? (
                    <>
                      {/* 统计行 */}
                      <div className="dep-resource-stats">
                        {[
                          { num: resourceAllocation.total_hotspots,        lbl: '热点区域总数', icon: <EnvironmentOutlined /> },
                          { num: resourceAllocation.high_priority_areas,   lbl: '高优先级区域', icon: <AimOutlined /> },
                          { num: resourceAllocation.medium_priority_areas, lbl: '中优先级区域', icon: <AimOutlined /> },
                        ].map((s, i) => (
                          <div key={i} className="aa-kpill" style={{ flex: '1 1 140px' }}>
                            <div className="lbl" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                              {s.icon}{s.lbl}
                            </div>
                            <div className="val">{s.num}</div>
                          </div>
                        ))}
                      </div>

                      <DepCard title="资源配置建议">
                        {resourceAllocation.resource_suggestions.map((item: any, i: number) => {
                          const pc = priorityClass(item.priority)
                          return (
                            <div key={i} className="dep-resource-item">
                              <div className="dep-resource-item__header">
                                <span className={`dep-tag dep-tag--${pc}`}>{item.priority}优先级</span>
                                <span style={{ fontWeight: 600, color: 'var(--ink-0)', fontSize: 13 }}>
                                  {item.type}
                                </span>
                                <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                                  {item.count} 个/组
                                </span>
                              </div>
                              <div className="dep-resource-item__desc">{item.description}</div>
                            </div>
                          )
                        })}
                      </DepCard>

                      <DepCard title="总体建议">
                        <SuggestionList items={resourceAllocation.recommendations || []} />
                      </DepCard>
                    </>
                  ) : (
                    <DepCard title="资源配置建议">
                      <DepEmpty />
                    </DepCard>
                  )}
                </div>
              ),
            },
            {
              key: 'prevention',
              label: (
                <span>
                  <SafetyOutlined style={{ marginRight: 4 }} />
                  预防措施
                </span>
              ),
              children: (
                <div className="dep-tab-pane">
                  {preventionMeasures?.measures && preventionMeasures.measures.length > 0 ? (
                    <>
                      <DepCard title="预防措施建议">
                        {preventionMeasures.measures.map((measure: any, i: number) => {
                          const pc = priorityClass(measure.priority)
                          return (
                            <div key={i} className="dep-measure-card">
                              <div className="dep-measure-card__header">
                                <span className={`dep-tag dep-tag--${pc}`}>{measure.priority}优先级</span>
                                <span className="dep-measure-card__category">{measure.category}</span>
                              </div>
                              <div className="dep-measure-list">
                                {(measure.measures || []).map((item: string, mi: number) => (
                                  <div key={mi} className="dep-measure-item">
                                    <span className="dep-measure-item__dot">•</span>
                                    <span>{item}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )
                        })}
                      </DepCard>

                      <DepCard title="实施优先级">
                        <SuggestionList items={preventionMeasures.implementation_priority || []} />
                      </DepCard>
                    </>
                  ) : (
                    <DepCard title="预防措施建议">
                      <DepEmpty text={preventionMeasures?.message || '暂无数据'} />
                    </DepCard>
                  )}
                </div>
              ),
            },
          ]}
        />
      )}
    </div>
  )
}

export default Deployment
