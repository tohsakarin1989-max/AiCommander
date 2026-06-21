/**
 * 相似条件组分析页面
 * 基于已侦破案件的时间、空间、手法和现场条件自动聚类，生成防控参考画像
 * 设计稿：Gangs.html（gangs-grid 布局：英雄卡 + 条件组列表）
 */
import { useState } from 'react'
import {
  Space,
  Modal,
  Timeline,
  Slider,
  InputNumber,
  Spin,
  Empty,
  Tag,
} from 'antd'
import {
  TeamOutlined,
  SearchOutlined,
  WarningOutlined,
  ClockCircleOutlined,
  EnvironmentOutlined,
  CarOutlined,
  UserOutlined,
  DatabaseOutlined,
  FireOutlined,
  RadarChartOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import { gangApi } from '../../services/gangs'
import type { GangProfile, TimelineEntry } from '../../types'
import dayjs from 'dayjs'
import './GangAnalysis.css'

// ── 工具函数 ────────────────────────────────────────────────

const getRiskInfo = (score: number) => {
  if (score >= 80) return { color: 'var(--err)',  label: '极高风险', isHigh: true }
  if (score >= 60) return { color: 'var(--err)',  label: '高风险',   isHigh: true }
  if (score >= 40) return { color: 'var(--warn)', label: '中风险',   isHigh: false }
  return            { color: 'var(--ok)',          label: '低风险',   isHigh: false }
}

const getDayName = (day: number) => ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][day] || ''

/** 热力图 y 轴星期标签（顺序与后端 display_wd 对应：0=周日...6=周六） */
const HEATMAP_DAY_NAMES = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

/** 将 risk_score(0-100) 转为 0-1 精度的显示字符串 */
const fmtRisk = (score: number) => (score / 100).toFixed(2)

/** 从条件组数据派生显示标签（无 gang_id 字段，用案件数量+索引生成） */
const gangLabel = (gang: GangProfile, index: number) =>
  `C${String(index + 1).padStart(2, '0')} · ${gang.case_count}案`

/** 派生短标签（用于头像、列表） */
const gangShortLabel = (index: number) => `C${String(index + 1).padStart(2, '0')}`

/** 聚类颜色 class，轮转 0-5 */
const clusterClass = (index: number) => `c-${index % 6}`

  // ── 网络图 SVG（根据条件组要素动态绘制简易关系图） ──────────────

interface NetworkNode {
  id: string
  label: string
  x: number
  y: number
  r: number
  fill: string
  textFill: string
}

function buildNetworkNodes(gang: GangProfile, index: number): NetworkNode[] {
  const nodes: NetworkNode[] = []
  // 核心节点
  const coreLabel = gangShortLabel(index)
  nodes.push({ id: 'core', label: coreLabel, x: 350, y: 130, r: 22,
    fill: 'oklch(0.70 0.20 25)', textFill: 'white' })

  // 人员节点
  const persons = (gang.known_persons ?? []).slice(0, 4)
  const angles = [225, 270, 315, 180]
  persons.forEach((p, i) => {
    const angle = (angles[i] ?? (i * 60)) * (Math.PI / 180)
    const dist = 130
    nodes.push({
      id: `p${i}`,
      label: p.slice(0, 3),
      x: Math.round(350 + Math.cos(angle) * dist),
      y: Math.round(130 + Math.sin(angle) * dist),
      r: 12,
      fill: 'oklch(0.78 0.14 45)',
      textFill: 'oklch(0.18 0.02 45)',
    })
  })

  // 车辆节点
  const vehicles = (gang.known_vehicles ?? []).slice(0, 2)
  vehicles.forEach((v, i) => {
    const angle = (30 + i * 60) * (Math.PI / 180)
    const dist = 140
    nodes.push({
      id: `v${i}`,
      label: v.slice(0, 3),
      x: Math.round(350 + Math.cos(angle) * dist),
      y: Math.round(130 + Math.sin(angle) * dist),
      r: 10,
      fill: 'oklch(0.78 0.11 220)',
      textFill: 'oklch(0.18 0.02 220)',
    })
  })

  return nodes
}

function GangNetworkSvg({ gang, index }: { gang: GangProfile; index: number }) {
  const nodes = buildNetworkNodes(gang, index)
  const coreNode = nodes[0]
  const otherNodes = nodes.slice(1)

  return (
    <svg viewBox="0 0 700 260" className="gh-network-svg">
      {/* 连线 */}
      <g stroke="oklch(0.42 0.014 250 / 0.45)" strokeWidth={0.8} fill="none">
        {otherNodes.map(n => (
          <line key={`l-${n.id}`} x1={coreNode.x} y1={coreNode.y} x2={n.x} y2={n.y} />
        ))}
      </g>
      {/* 节点 */}
      {nodes.map(n => (
        <g key={n.id}>
          <circle cx={n.x} cy={n.y} r={n.r} fill={n.fill} />
          <text
            x={n.x}
            y={n.y + 4}
            fontFamily="JetBrains Mono, monospace"
            fontSize={n.r < 14 ? 9 : 11}
            textAnchor="middle"
            fill={n.textFill}
            fontWeight="600"
          >
            {n.label}
          </text>
        </g>
      ))}
    </svg>
  )
}

// ── 英雄卡侧面板 ────────────────────────────────────────────

function GangSidePanel({ gang, index }: { gang: GangProfile; index: number }) {
  const riskInfo = getRiskInfo(gang.risk_score)
  const riskDisplay = fmtRisk(gang.risk_score)
  const label = gangLabel(gang, index)
  const shortLabel = gangShortLabel(index)

  return (
    <aside className="gang-side">
      <div className={`gh-avatar${riskInfo.isHigh ? '' : ' safe'}`}>
        {shortLabel}
      </div>
      <div className="gh-name">{label}</div>
      <div className="gh-codename">内部代号 {shortLabel}</div>
      <div className={`gh-risk${riskInfo.isHigh ? '' : ' safe'}`}>
        <div className="gh-risk-v">{riskDisplay}</div>
        <div className="gh-risk-l">综合风险</div>
      </div>
      <div className="gh-kvs">
        <div className="kv">
          <span className="k">案件数</span>
          <span className="v">{gang.case_count} 起</span>
        </div>
        <div className="kv">
          <span className="k">时间跨度</span>
          <span className="v">{gang.time_span_days} 天</span>
        </div>
        <div className="kv">
          <span className="k">活跃时段</span>
          <span className="v">
            {gang.active_hours?.length
              ? gang.active_hours.map(h => `${h}:00`).join(' · ')
              : '—'}
          </span>
        </div>
        <div className="kv">
          <span className="k">活跃日期</span>
          <span className="v">
            {gang.active_days?.length
              ? gang.active_days.map(getDayName).join(' · ')
              : '—'}
          </span>
        </div>
        <div className="kv">
          <span className="k">主要手法</span>
          <span className="v">
            {gang.modus_operandi?.length
              ? gang.modus_operandi.slice(0, 2).join(' · ')
              : '—'}
          </span>
        </div>
        <div className="kv">
          <span className="k">目标设施</span>
          <span className="v">
            {gang.target_facilities?.length
              ? gang.target_facilities.slice(0, 2).join(' · ')
              : '—'}
          </span>
        </div>
        <div className="kv">
          <span className="k">涉及油品</span>
          <span className="v">
            {gang.oil_types?.length
              ? gang.oil_types.slice(0, 3).join(' · ')
              : '—'}
          </span>
        </div>
        {gang.geographic_center && (
          <div className="kv">
            <span className="k">活动中心</span>
            <span className="v" style={{ fontFamily: 'var(--mono)', fontSize: 10 }}>
              {gang.geographic_center.latitude.toFixed(4)},{' '}
              {gang.geographic_center.longitude.toFixed(4)}
            </span>
          </div>
        )}
      </div>
    </aside>
  )
}

// ── 主组件 ──────────────────────────────────────────────────

const GangAnalysis: React.FC = () => {
  const [analysisParams, setAnalysisParams] = useState({
    min_similarity:   0.5,
    min_cases:        2,
    time_window_days: 90,
  })
  const [selectedGang, setSelectedGang]               = useState<GangProfile | null>(null)
  const [detailModalVisible, setDetailModalVisible]   = useState(false)
  const [timelineModalVisible, setTimelineModalVisible] = useState(false)

  // ── 数据获取 ────────────────────────────────────────────
  const { data: statistics, isLoading: statsLoading } = useQuery({
    queryKey: ['gangStatistics', analysisParams.time_window_days],
    queryFn:  () => gangApi.getStatistics(analysisParams.time_window_days),
  })

  const identifyMutation = useMutation({ mutationFn: gangApi.identify })

  const { data: timeline, isLoading: timelineLoading } = useQuery({
    queryKey: ['gangTimeline', selectedGang?.case_ids],
    queryFn:  () => gangApi.getTimeline(selectedGang!.case_ids),
    enabled:  !!selectedGang && timelineModalVisible,
  })

  const handleAnalyze = () => identifyMutation.mutate(analysisParams)

  // ── 条件组数据 ──────────────────────────────────────────
  const gangs: GangProfile[] = identifyMutation.data || statistics?.top_gangs || []

  // 当前英雄（默认第一个）
  const heroGang = selectedGang ?? gangs[0] ?? null
  const heroIndex = heroGang ? gangs.indexOf(heroGang) : 0
  const otherGangs = heroGang ? gangs.filter(g => g !== heroGang) : gangs

  // ── 热力图数据（针对当前条件组） ─────────────────────────
  const { data: heatmapData } = useQuery({
    queryKey: ['gangHeatmap', heroIndex, analysisParams],
    queryFn: () => gangApi.getActivityHeatmap(heroIndex, analysisParams),
    enabled: gangs.length > 0,
  })

  // ── 重复锚点提示（后端当前返回空列表，仅保留兼容旧接口） ───
  const { data: crossPersons } = useQuery({
    queryKey: ['crossGangPersons', analysisParams],
    queryFn: () => gangApi.getCrossGangPersons(analysisParams),
    enabled: gangs.length > 0,
  })

  // Modal 通用样式
  const modalStyles = {
    content: { background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 0 },
    header:  { background: 'var(--bg-1)', borderBottom: '1px solid var(--line)' },
    footer:  { borderTop: '1px solid var(--line)' },
    body:    { paddingTop: 16 },
  }

  return (
    <div className="page-gangs">

      {/* ── 页面标题 ── */}
      <div className="page-title">
        <h1>相似条件组分析</h1>
        <div className="sub">
          CONDITION CLUSTERS ·{' '}
          {statsLoading ? '—' : `${statistics?.total_gangs ?? 0} 组 · ${statistics?.high_risk_gangs ?? 0} 高关注`}
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
          {/* 分析参数 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="gang-ctrl-label">相似度</span>
            <Slider
              min={0.3} max={0.9} step={0.1}
              value={analysisParams.min_similarity}
              onChange={v => setAnalysisParams(p => ({ ...p, min_similarity: v }))}
              style={{ width: 100 }}
            />
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--accent)', width: 30 }}>
              {analysisParams.min_similarity}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="gang-ctrl-label">最少案件</span>
            <InputNumber
              min={2} max={10} size="small"
              value={analysisParams.min_cases}
              onChange={v => v && setAnalysisParams(p => ({ ...p, min_cases: v }))}
              style={{ width: 60 }}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="gang-ctrl-label">时间窗口</span>
            <InputNumber
              min={30} max={365} size="small"
              value={analysisParams.time_window_days}
              onChange={v => v && setAnalysisParams(p => ({ ...p, time_window_days: v }))}
              style={{ width: 70 }}
            />
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>天</span>
          </div>
          <button
            className="btn-ghost"
            onClick={handleAnalyze}
            disabled={identifyMutation.isPending}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <SearchOutlined />
            {identifyMutation.isPending ? '分析中…' : '开始分析'}
          </button>
          <button
            className="btn-primary"
            onClick={() => setDetailModalVisible(true)}
            disabled={!heroGang}
          >
            ＋ 新建条件组档案
          </button>
        </div>
      </div>

      {/* ── 加载中 ── */}
      {(statsLoading || identifyMutation.isPending) && (
        <div style={{ textAlign: 'center', padding: 48, fontFamily: 'var(--mono)', color: 'var(--ink-3)', fontSize: 12 }}>
          <Spin />
          <div style={{ marginTop: 12, letterSpacing: '0.2em' }}>
            {identifyMutation.isPending ? '正在分析相似条件…' : '加载数据…'}
          </div>
        </div>
      )}

      {/* ── 无数据提示 ── */}
      {!statsLoading && !identifyMutation.isPending && gangs.length === 0 && (
        <div className="empty-state">
          <div className="icon"><TeamOutlined /></div>
          <div>暂无条件组数据，请调整参数后点击「开始分析」</div>
        </div>
      )}

      {/* ── 主内容网格 ── */}
      {gangs.length > 0 && (
        <div className="gangs-grid">

          {/* ── 英雄卡 ── */}
          <div className="card gang-hero">
            <div className="card-head">
              <span className="ico">!</span>
              {heroGang && (() => {
                const ri = getRiskInfo(heroGang.risk_score)
                return (
                  <>
                    <span className="ti" style={{ color: ri.isHigh ? 'var(--err)' : 'var(--ink-1)' }}>
                      {gangLabel(heroGang, heroIndex)} · {ri.label}
                    </span>
                    <span className="spacer" />
                    <span className={`chip ${ri.isHigh ? 'err' : ''}`}>
                      {ri.isHigh && <span className="dot" style={{ background: 'var(--err)' }} />}
                      活跃 {heroGang.time_span_days} 天
                    </span>
                    <button
                      className="btn-ghost-sm"
                      onClick={() => { setSelectedGang(heroGang); setDetailModalVisible(true) }}
                    >
                      画像详情
                    </button>
                    <button
                      className="btn-ghost-sm"
                      onClick={() => { setSelectedGang(heroGang); setTimelineModalVisible(true) }}
                    >
                      时间线
                    </button>
                  </>
                )
              })()}
            </div>

            {heroGang ? (
              <div className="gang-hero-body">
                <GangSidePanel gang={heroGang} index={heroIndex} />

                {/* 主区 */}
                <div className="gh-main">
                  {/* 网络图谱 */}
                  <div className="gh-section">
                    <div className="sh">条件要素图谱</div>
                    <GangNetworkSvg gang={heroGang} index={heroIndex} />
                  </div>

                  {/* 作案时间线网格 */}
                  {heroGang.case_ids && heroGang.case_ids.length > 0 && (
                    <div className="gh-section">
                      <div className="sh">作案时间线 · 近 30 天</div>
                      <div className="gtl">
                        {heroGang.case_ids.slice(0, 9).map((cid, i) => (
                          <div
                            key={cid}
                            className={`gtl-item${i === heroGang.case_ids.length - 1 ? ' active' : ''}`}
                          >
                            <div className="gtl-t">#{String(i + 1).padStart(2, '0')}</div>
                            <div className="gtl-box">
                              <span className={`cluster ${clusterClass(i)}`}>{i + 1}</span>
                              <span className="gtl-loc" style={{ fontSize: 9 }}>
                                {heroGang.preferred_locations?.[i % (heroGang.preferred_locations.length || 1)] ?? '—'}
                              </span>
                              <span className="gtl-val">案件</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* 人员 / 车辆简表 */}
                  {(heroGang.known_persons?.length > 0 || heroGang.known_vehicles?.length > 0) && (
                    <div className="gh-section">
                      <div className="sh">涉案人员与车辆</div>
                      <table className="gh-members-table">
                        <thead>
                          <tr>
                            <th>#</th>
                            <th><UserOutlined /> 人员</th>
                            <th><CarOutlined /> 车辆</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Array.from({
                            length: Math.max(
                              heroGang.known_persons?.length ?? 0,
                              heroGang.known_vehicles?.length ?? 0,
                            ),
                          }).map((_, i) => (
                            <tr key={i}>
                              <td style={{ fontFamily: 'var(--mono)', color: 'var(--ink-3)', fontSize: 11 }}>
                                {String(i + 1).padStart(2, '0')}
                              </td>
                              <td style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>
                                {heroGang.known_persons?.[i] ?? '—'}
                              </td>
                              <td style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>
                                {heroGang.known_vehicles?.[i] ?? '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* 作案时段规律热力图 */}
                  <div className="gh-section">
                    <div className="sh">
                      <RadarChartOutlined style={{ marginRight: 6 }} />
                      作案时段规律
                    </div>
                    {heatmapData && heatmapData.total_cases > 0 ? (
                      <ReactECharts
                        style={{ height: 200 }}
                        option={{
                          tooltip: {
                            position: 'top',
                            formatter: (params: any) => {
                              const [hour, wd] = params.value
                              return `${HEATMAP_DAY_NAMES[wd]} ${hour}:00 — ${params.value[2]} 起`
                            },
                          },
                          grid: { left: 48, right: 8, top: 8, bottom: 28 },
                          xAxis: {
                            type: 'category',
                            data: Array.from({ length: 24 }, (_, i) => `${i}`),
                            axisLabel: {
                              fontSize: 9,
                              color: 'var(--ink-3)',
                              formatter: (v: string) => `${v}h`,
                            },
                            axisLine: { lineStyle: { color: 'var(--line)' } },
                            splitArea: { show: true, areaStyle: { color: ['transparent', 'transparent'] } },
                          },
                          yAxis: {
                            type: 'category',
                            data: HEATMAP_DAY_NAMES,
                            axisLabel: { fontSize: 9, color: 'var(--ink-3)' },
                            axisLine: { lineStyle: { color: 'var(--line)' } },
                            splitArea: { show: true, areaStyle: { color: ['oklch(0.22 0.01 250 / 0.4)', 'transparent'] } },
                          },
                          visualMap: {
                            min: 0,
                            max: Math.max(...heatmapData.matrix.flat(), 1),
                            calculable: false,
                            show: false,
                            inRange: { color: ['#1a1a2e', '#ff6b35', '#c0392b'] },
                          },
                          series: [{
                            type: 'heatmap',
                            data: heatmapData.matrix.flatMap((row, wd) =>
                              row.map((count, hour) => [hour, wd, count])
                            ),
                            label: { show: false },
                            emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'oklch(0.60 0.22 25 / 0.6)' } },
                          }],
                        }}
                        notMerge
                      />
                    ) : (
                      <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={<span style={{ fontSize: 11, color: 'var(--ink-3)' }}>暂无时段数据</span>}
                        style={{ padding: '16px 0' }}
                      />
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="gang-hero-empty">
                <div className="icon"><TeamOutlined /></div>
                <div>点击右侧条件组以查看详情</div>
              </div>
            )}
          </div>

          {/* ── 其他条件组列表 ── */}
          <div className="card other-gangs">
            <div className="card-head">
              <span className="ico">◉</span>
              <span className="ti">其他相似条件组</span>
              {gangs.length > 0 && (
                <>
                  <span className="spacer" />
                  <span className="chip">
                    共 {gangs.length} 个
                  </span>
                </>
              )}
            </div>
            <div className="card-body">
              {/* 所有条件组显示在列表中，当前选中高亮 */}
              {gangs.map((g, gi) => {
                const ri = getRiskInfo(g.risk_score)
                const isSelected = g === heroGang
                return (
                  <div
                    key={g.case_ids?.[0] ?? gi}
                    className={`og-row${ri.isHigh ? ' hi' : ''}${isSelected ? ' selected' : ''}`}
                    onClick={() => setSelectedGang(g)}
                  >
                    <div className="og-avatar">
                      {gangShortLabel(gi)}
                    </div>
                    <div className="og-body">
                      <div className="og-name">{gangLabel(g, gi)}</div>
                      <div className="og-meta">
                        活跃 {g.time_span_days} 天 · {g.case_count} 起
                        {g.modus_operandi?.length ? ` · ${g.modus_operandi[0]}` : ''}
                        {g.oil_types?.length ? ` · ${g.oil_types[0]}` : ''}
                      </div>
                    </div>
                    <div className="og-risk">
                      <span className="v">{fmtRisk(g.risk_score)}</span>
                      <span className="l">风险</span>
                    </div>
                  </div>
                )
              })}

              {/* 无其他条件组提示 */}
              {otherGangs.length === 0 && gangs.length <= 1 && (
                <div style={{
                  padding: 24, textAlign: 'center',
                  fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)',
                }}>
                  无其他相似条件组
                </div>
              )}
            </div>

            {/* ── 重复锚点核验提示 ── */}
            <div style={{ borderTop: '1px solid var(--line)', padding: '10px 14px' }}>
              <div className="card-head" style={{ padding: 0, marginBottom: 8, border: 'none' }}>
                <span className="ico" style={{ fontSize: 11 }}>⇌</span>
                <span className="ti" style={{ fontSize: 11 }}>重复锚点核验</span>
                {crossPersons && crossPersons.length > 0 && (
                  <>
                    <span className="spacer" />
                    <span className="chip" style={{ fontSize: 10 }}>{crossPersons.length} 人</span>
                  </>
                )}
              </div>
              {crossPersons && crossPersons.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {crossPersons.map(p => (
                    <div
                      key={p.person_name}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 8,
                        padding: '4px 6px',
                        background: 'var(--bg-0)',
                        border: '1px solid var(--line)',
                        fontSize: 11,
                      }}
                    >
                      <UserOutlined style={{ color: 'var(--warn)', flexShrink: 0 }} />
                      <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-1)', minWidth: 60 }}>
                        {p.person_name}
                      </span>
                      <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                        {p.gang_indices.map(gi => (
                          <Tag
                            key={gi}
                            style={{
                              fontFamily: 'var(--mono)',
                              fontSize: 9,
                              padding: '0 4px',
                              lineHeight: '16px',
                              margin: 0,
                              background: 'transparent',
                              borderColor: 'var(--accent)',
                              color: 'var(--accent)',
                            }}
                          >
                            {gangShortLabel(gi)}
                          </Tag>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{
                  fontFamily: 'var(--mono)', fontSize: 10,
                  color: 'var(--ink-3)', padding: '6px 0',
                  letterSpacing: '0.05em',
                }}>
                  同人同车不作为跨案规律，仅在案件研判中提示重复录入或同案拆分核验
                </div>
              )}
            </div>
          </div>

        </div>
      )}

      {/* ── 统计概要（底部） ── */}
      {gangs.length > 0 && (
        <div style={{ display: 'flex', gap: 10, marginTop: 10, flexWrap: 'wrap' }}>
          {[
            { ico: <TeamOutlined />,    val: statistics?.total_gangs ?? gangs.length, lbl: '识别条件组' },
            { ico: <DatabaseOutlined />, val: statistics?.total_cases_in_gangs ?? gangs.reduce((s, g) => s + g.case_count, 0), lbl: '涉及案件数' },
            { ico: <FireOutlined />,     val: statistics?.high_risk_gangs ?? gangs.filter(g => g.risk_score >= 60).length, lbl: '高关注条件组' },
            { ico: <WarningOutlined />,  val: statistics?.average_gang_size?.toFixed(1) ?? '—', lbl: '平均规模（案/组）' },
          ].map(({ ico, val, lbl }) => (
            <div
              key={lbl}
              style={{
                flex: '1 1 160px',
                padding: '12px 16px',
                background: 'var(--bg-1)',
                border: '1px solid var(--line)',
                display: 'flex', alignItems: 'center', gap: 12,
              }}
            >
              <span style={{ fontSize: 18, color: 'var(--accent)' }}>{ico}</span>
              <div>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 22, color: 'var(--accent)', lineHeight: 1, fontWeight: 500 }}>
                  {val}
                </div>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', marginTop: 3, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                  {lbl}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── 画像详情 Modal ── */}
      <Modal
        title={
          <span style={{ fontFamily: 'var(--mono)', color: 'var(--accent)', fontSize: 13, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
            相似条件组画像
          </span>
        }
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={null}
        width={820}
        styles={modalStyles}
      >
        {heroGang && (() => {
          const info = getRiskInfo(heroGang.risk_score)
          return (
            <div className="gang-detail">
              {/* 风险 Banner */}
              <div className="gang-risk-banner" style={{ borderColor: info.color }}>
                <div className="gang-risk-banner__left">
                  <WarningOutlined style={{ color: info.color, fontSize: 20 }} />
                  <div>
                    <div style={{ fontFamily: 'var(--mono)', fontSize: 9.5, letterSpacing: '0.2em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 2 }}>
                      RISK ASSESSMENT
                    </div>
                    <div style={{ color: info.color, fontFamily: 'var(--mono)', fontSize: 18, fontWeight: 600 }}>
                      {info.label}
                    </div>
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 28, fontWeight: 700, color: info.color, lineHeight: 1 }}>
                    {heroGang.risk_score.toFixed(0)}
                  </div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-3)', letterSpacing: '0.1em' }}>/ 100</div>
                </div>
              </div>

              {/* 核心指标 */}
              <div className="gang-detail-section">
                <div className="section-head">核心指标</div>
                <div className="gang-detail-grid-2">
                  <div className="gang-kv">
                    <div className="gang-kv__key">案件数量</div>
                    <div className="gang-kv__val" style={{ fontFamily: 'var(--mono)', color: 'var(--ink-0)', fontSize: 16 }}>
                      {heroGang.case_count}
                    </div>
                  </div>
                  <div className="gang-kv">
                    <div className="gang-kv__key">时间跨度</div>
                    <div className="gang-kv__val" style={{ fontFamily: 'var(--mono)', color: 'var(--ink-0)', fontSize: 16 }}>
                      {heroGang.time_span_days} 天
                    </div>
                  </div>
                </div>
              </div>

              {/* 活动规律 */}
              <div className="gang-detail-section">
                <div className="section-head">活动规律</div>
                <div className="gang-detail-grid-2">
                  <div className="gang-kv">
                    <div className="gang-kv__key">
                      <ClockCircleOutlined style={{ marginRight: 4 }} />活跃时段
                    </div>
                    <div className="gang-kv__val">
                      <Space size={4} wrap>
                        {heroGang.active_hours?.map(h => (
                          <span key={h} className="gang-mini-tag" style={{ color: 'var(--info)', borderColor: 'oklch(0.78 0.11 220 / 0.5)' }}>
                            {h}:00
                          </span>
                        )) || <span style={{ color: 'var(--ink-3)' }}>—</span>}
                      </Space>
                    </div>
                  </div>
                  <div className="gang-kv">
                    <div className="gang-kv__key">活跃日期</div>
                    <div className="gang-kv__val">
                      <Space size={4} wrap>
                        {heroGang.active_days?.map(d => (
                          <span key={d} className="gang-mini-tag" style={{ color: 'var(--ink-2)', borderColor: 'var(--line)' }}>
                            {getDayName(d)}
                          </span>
                        )) || <span style={{ color: 'var(--ink-3)' }}>—</span>}
                      </Space>
                    </div>
                  </div>
                </div>
              </div>

              {/* 作案特征 */}
              <div className="gang-detail-section">
                <div className="section-head">作案特征</div>
                {[
                  { key: '主要手法', items: heroGang.modus_operandi, color: 'var(--warn)' },
                  { key: '目标设施', items: heroGang.target_facilities, color: 'var(--oil)' },
                  { key: '涉及油品', items: heroGang.oil_types, color: 'var(--accent)' },
                ].map(({ key, items, color }) => (
                  <div key={key} className="gang-kv" style={{ marginBottom: 10 }}>
                    <div className="gang-kv__key">{key}</div>
                    <div className="gang-kv__val">
                      <Space size={4} wrap>
                        {items?.length
                          ? items.map(x => (
                            <span key={x} className="gang-mini-tag" style={{ color, borderColor: `${color} / 0.5` }}>
                              {x}
                            </span>
                          ))
                          : <span style={{ color: 'var(--ink-3)' }}>—</span>}
                      </Space>
                    </div>
                  </div>
                ))}
              </div>

              {/* 人员与地理 */}
              <div className="gang-detail-section">
                <div className="section-head">人员与地理信息</div>
                {[
                  { key: '涉案人员', icon: <UserOutlined style={{ marginRight: 4 }} />, items: heroGang.known_persons, color: 'var(--ink-1)' },
                  { key: '涉案车辆', icon: <CarOutlined  style={{ marginRight: 4 }} />, items: heroGang.known_vehicles, color: 'var(--ink-1)' },
                  { key: '常见地点', icon: <EnvironmentOutlined style={{ marginRight: 4 }} />, items: heroGang.preferred_locations, color: 'var(--ok)' },
                ].map(({ key, icon, items, color }) => (
                  <div key={key} className="gang-kv" style={{ marginBottom: 10 }}>
                    <div className="gang-kv__key">{icon}{key}</div>
                    <div className="gang-kv__val">
                      <Space size={4} wrap>
                        {items?.length
                          ? items.map(x => (
                            <span key={x} className="gang-mini-tag" style={{ color, borderColor: 'var(--line)' }}>
                              {x}
                            </span>
                          ))
                          : <span style={{ color: 'var(--ink-3)' }}>—</span>}
                      </Space>
                    </div>
                  </div>
                ))}
                {heroGang.geographic_center && (
                  <div className="gang-kv">
                    <div className="gang-kv__key">活动中心</div>
                    <div className="gang-kv__val" style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-2)' }}>
                      {heroGang.geographic_center.latitude.toFixed(6)},{' '}
                      {heroGang.geographic_center.longitude.toFixed(6)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )
        })()}
      </Modal>

      {/* ── 时间线 Modal ── */}
      <Modal
        title={
          <span style={{ fontFamily: 'var(--mono)', color: 'var(--accent)', fontSize: 13, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
            条件组案件时间线
          </span>
        }
        open={timelineModalVisible}
        onCancel={() => { setTimelineModalVisible(false); setSelectedGang(null) }}
        footer={null}
        width={700}
        styles={modalStyles}
      >
        {timelineLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin />
            <div style={{ marginTop: 12, fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.2em' }}>
              加载时间轴…
            </div>
          </div>
        ) : (
          <div style={{ padding: '8px 0' }}>
            <Timeline
              items={timeline?.map((entry: TimelineEntry) => {
                const riskScore = (entry as any).risk_score
                const tlColor = riskScore >= 80 ? '#ef4444'
                  : riskScore >= 60 ? '#fb923c'
                  : riskScore >= 40 ? '#e8b84b'
                  : '#10b981'
                return {
                  color: tlColor,
                  children: (
                    <div className="gang-timeline-item">
                      <div className="gang-timeline-item__header">
                        <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>
                          {entry.case_number}
                        </span>
                        {entry.occurred_time && (
                          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)' }}>
                            {dayjs(entry.occurred_time).format('YYYY-MM-DD HH:mm')}
                          </span>
                        )}
                      </div>
                      {entry.location && (
                        <div style={{ marginTop: 4, fontSize: 12, color: 'var(--ink-2)' }}>
                          <EnvironmentOutlined style={{ marginRight: 4, color: 'var(--ink-3)' }} />
                          {entry.location}
                        </div>
                      )}
                      {entry.modus_operandi && (
                        <span
                          className="gang-mini-tag"
                          style={{ marginTop: 6, display: 'inline-block', color: 'var(--warn)', borderColor: 'oklch(0.80 0.16 75 / 0.5)' }}
                        >
                          {entry.modus_operandi}
                        </span>
                      )}
                    </div>
                  ),
                }
              }) || []}
            />
            {(!timeline || timeline.length === 0) && (
              <div className="empty-state">
                <div className="icon"><ClockCircleOutlined /></div>
                <div>暂无时间线数据</div>
              </div>
            )}
          </div>
        )}
      </Modal>

    </div>
  )
}

export default GangAnalysis
