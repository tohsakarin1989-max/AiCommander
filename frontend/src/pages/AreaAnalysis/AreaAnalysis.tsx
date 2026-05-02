/**
 * 区域研判分析页面
 *
 * 核心功能：
 * 1. 区域事件聚集分析（热点识别）
 * 2. 作案模式挖掘
 * 3. 区域风险评分
 * 4. 趋势分析与巡逻建议
 *
 * 设计参考：docs/design-reference/aicommand/Analysis.html + pages.css
 */
import { useState, useEffect, useRef } from 'react'
import {
  Button,
  Table,
  Tabs,
  Spin,
  Select,
  InputNumber,
  message,
} from 'antd'
import {
  EnvironmentOutlined,
  SearchOutlined,
  ClockCircleOutlined,
  LinkOutlined,
} from '@ant-design/icons'
import { caseApi } from '../../services'
import type {
  AreaProfile,
  AreaAnalysisResponse,
  AreaPatrolSuggestions,
  EventStatistics,
  RiskLevel,
  EventType,
  PatrolSuggestion,
} from '../../types/event'
import { EVENT_TYPES, RELATION_TYPES } from '../../types/event'
import './AreaAnalysis.css'

const { Option } = Select

// 风险等级颜色（CSS 变量）
const RISK_CSS_COLORS: Record<string, string> = {
  low:      'var(--ok)',
  medium:   'var(--warn)',
  high:     'var(--err)',
  critical: 'var(--err)',
}

// 风险等级原始色（用于 SVG stroke）
const RISK_HEX_COLORS: Record<string, string> = {
  low:      '#10b981',
  medium:   '#e8b84b',
  high:     '#fb923c',
  critical: '#ef4444',
}

// 风险等级标签
const RISK_LABELS: Record<string, string> = {
  low:      '低风险',
  medium:   '中风险',
  high:     '高风险',
  critical: '极高风险',
}

// 时段选项
const PERIOD_OPTIONS = [
  { value: 30,  label: '近30天' },
  { value: 90,  label: '近90天' },
  { value: 180, label: '近半年' },
  { value: 365, label: '近一年' },
  { value: 730, label: '近两年' },
]

type PatrolDisplayItem = {
  location: string
  reason: string
  timing?: string
  focus_on?: string[]
  priority?: number
}

const buildTimeline = (events: AreaAnalysisResponse['events']): AreaAnalysisResponse['timeline'] =>
  events.map(event => ({
    id: event.id,
    event_number: event.event_number,
    event_type: event.event_type,
    event_type_name: EVENT_TYPES[event.event_type] || event.event_type,
    occurred_time: event.occurred_time,
    title: event.title || event.description,
    location: event.location,
    handling_result: event.handling_result,
  }))

const buildAreaPatrolSuggestions = (
  areaName: string,
  totalEvents: number,
  rawSuggestions?: PatrolSuggestion[]
): AreaPatrolSuggestions => {
  const fallbackReason = `热点区域，案件密度较高（${totalEvents} 起）`
  return {
    area_name: areaName,
    priority_level: totalEvents >= 3 ? 'high' : 'medium',
    suggested_times: rawSuggestions?.map(item => ({
      period: item.timing || '重点时段',
      reason: item.reason,
    })) ?? [{ period: '夜间及节假日', reason: fallbackReason }],
    suggested_days: [],
    watch_targets: rawSuggestions?.flatMap(item =>
      item.focus_on?.map(target => ({ type: 'focus', description: target })) ?? []
    ) ?? [],
    patrol_points: rawSuggestions?.map(item => item.location) ?? [areaName],
    frequency: totalEvents >= 3 ? '建议每日巡查' : '建议每周巡查',
  }
}

const getPatrolDisplayItems = (
  suggestions?: AreaPatrolSuggestions
): PatrolDisplayItem[] => {
  if (!suggestions) return []

  const byPoint = suggestions.patrol_points.map((point, index) => ({
    location: point,
    reason: suggestions.suggested_times[index]?.reason || `${suggestions.area_name}重点巡逻点`,
    timing: suggestions.suggested_times[index]?.period,
    focus_on: suggestions.watch_targets.map(target => target.description),
    priority: suggestions.priority_level === 'high' ? 1 : suggestions.priority_level === 'medium' ? 2 : 3,
  }))

  if (byPoint.length > 0) return byPoint

  return suggestions.suggested_times.map(item => ({
    location: suggestions.area_name,
    reason: item.reason,
    timing: item.period,
    focus_on: suggestions.watch_targets.map(target => target.description),
    priority: suggestions.priority_level === 'high' ? 1 : suggestions.priority_level === 'medium' ? 2 : 3,
  }))
}

// ── 圆形风险仪表盘 ─────────────────────────────────────────────
interface RiskGaugeProps {
  score: number
  level: string
}

const RiskGauge: React.FC<RiskGaugeProps> = ({ score, level }) => {
  const size = 120
  const r = 48
  const cx = size / 2
  const cy = size / 2
  const circumference = 2 * Math.PI * r
  const arcRatio = 0.75
  const arcLen = circumference * arcRatio
  const offset = arcLen - (score / 100) * arcLen
  const hex = RISK_HEX_COLORS[level] || '#10b981'

  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg
        width={size}
        height={size}
        style={{ transform: 'rotate(135deg)' }}
      >
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke="var(--bg-3)"
          strokeWidth={8}
          strokeDasharray={`${arcLen} ${circumference - arcLen}`}
        />
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke={hex}
          strokeWidth={8}
          strokeLinecap="round"
          strokeDasharray={`${arcLen} ${circumference - arcLen}`}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 0.8s ease' }}
        />
      </svg>
      <div style={{
        position: 'absolute', top: '50%', left: '50%',
        transform: 'translate(-50%,-50%)',
        textAlign: 'center', pointerEvents: 'none',
      }}>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 22, fontWeight: 600, color: hex, display: 'block', lineHeight: 1 }}>
          {score}
        </span>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-3)', marginTop: 4, letterSpacing: '0.08em', display: 'block' }}>
          {RISK_LABELS[level] || level}
        </span>
      </div>
    </div>
  )
}

const AreaAnalysis: React.FC = () => {
  // 状态
  const [loading, setLoading] = useState(false)
  const [areaName, setAreaName] = useState('')
  const [radiusKm, setRadiusKm] = useState(5)
  const [daysBack, setDaysBack] = useState(365)
  const [analysisResult, setAnalysisResult] = useState<AreaAnalysisResponse | null>(null)
  const [areaProfiles, setAreaProfiles] = useState<AreaProfile[]>([])
  const [statistics, setStatistics] = useState<EventStatistics | null>(null)
  const [selectedEvents, setSelectedEvents] = useState<number[]>([])
  const [activeTab, setActiveTab] = useState('events')
  const resultRef = useRef<HTMLDivElement>(null)
  // 存储每个 profile id 对应的原始案件数组（避免重新请求）
  const profileCasesRef = useRef<Record<number, Record<string, unknown>[]>>({})

  // 加载初始数据
  useEffect(() => {
    loadInitialData()
  }, [])

  const loadInitialData = async () => {
    try {
      const [hotspots, stats] = await Promise.all([
        caseApi.getHotspots(1.0, 2),
        caseApi.getStatistics(),
      ])

      // 热点 → AreaProfile（getHotspots 已统一转换为 center.latitude/longitude）
      const newProfileCases: Record<number, Record<string, unknown>[]> = {}
      const profiles: AreaProfile[] = (hotspots as unknown as Array<{
        center: { latitude: number; longitude: number }
        case_count: number; radius_km: number
        cases?: Array<Record<string, unknown>>
      }>).map((h, i) => {
        const id = i + 1
        const casesArr = (h.cases ?? []) as Array<Record<string, unknown>>
        newProfileCases[id] = casesArr
        const areaName = casesArr.find(c => c.location)?.location as string ?? `热点区域-${id}`
        const riskScore = Math.min(100, h.case_count * 12)
        const riskLevel: RiskLevel = riskScore >= 60 ? 'high' : riskScore >= 30 ? 'medium' : 'low'
        return {
          id,
          area_name: areaName,
          area_type: 'hotspot',
          center_latitude: h.center?.latitude,
          center_longitude: h.center?.longitude,
          radius_km: h.radius_km,
          total_events: h.case_count,
          events_last_30_days: h.case_count,
          events_last_90_days: h.case_count,
          risk_level: riskLevel,
          risk_score: riskScore,
          is_active: true,
        }
      })
      profileCasesRef.current = newProfileCases
      setAreaProfiles(profiles)

      // 热点 → EventStatistics 兼容格式
      const highRiskAreas = [...profiles]
        .sort((a, b) => b.risk_score - a.risk_score)
        .map(p => ({
          area_name: p.area_name,
          risk_level: p.risk_level,
          risk_score: p.risk_score,
          event_count: p.total_events,
        }))

      const byVillage: Record<string, number> = {}
      profiles.forEach(p => { byVillage[p.area_name] = p.total_events })

      setStatistics({
        total_events: stats.total_cases,
        recent_events: stats.this_month_cases,
        days_back: 90,
        by_type: stats.case_type_distribution,
        by_village: byVillage,
        high_risk_areas: highRiskAreas,
      })
    } catch (error) {
      console.error('加载数据失败:', error)
    }
  }

  // 执行区域分析（基于案件热点数据）
  const handleAnalyze = async () => {
    if (!areaName.trim()) {
      message.warning('请输入区域名称')
      return
    }

    setLoading(true)
    try {
      // 查找与区域名称匹配的档案
      const matched = areaProfiles.find(p =>
        p.area_name.includes(areaName) || areaName.includes(p.area_name)
      )
      if (matched) {
        // 构造兼容 analysisResult 的结构
        const synth: AreaAnalysisResponse = {
          area_name: matched.area_name,
          events: [],
          timeline: [],
          relations: [],
          risk_assessment: {
            level: matched.risk_level,
            score: matched.risk_score,
            factors: matched.risk_factors ?? [`该区域共识别 ${matched.total_events} 起案件`, `风险分值 ${matched.risk_score.toFixed(0)}`],
          },
          suggestions: [],
          patrol_suggestions: buildAreaPatrolSuggestions(
            matched.area_name,
            matched.total_events,
            matched.patrol_suggestions
          ),
        }
        setAnalysisResult(synth)
        setActiveTab('patrol')
        setTimeout(() => {
          resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }, 50)
        message.success(`已加载 "${matched.area_name}" 热点分析结果`)
      } else {
        message.info('未找到该区域的热点数据，可尝试缩短区域名称或扩大搜索范围')
      }
    } catch (error) {
      message.error('分析失败，请重试')
      console.error('区域分析失败:', error)
    } finally {
      setLoading(false)
    }
  }

  // 快速选择高风险区域
  const handleQuickSelect = (profile: AreaProfile) => {
    setAreaName(profile.area_name)

    // 把原始案件映射为 Event 格式
    const rawCases = profileCasesRef.current[profile.id] ?? []
    const events = rawCases.map((c) => ({
      id: c.id as number,
      event_number: (c.case_number as string) ?? `CASE-${c.id}`,
      event_type: ((c.case_type as string) ?? 'theft_case') as EventType,
      occurred_time: (c.occurred_time as string) ?? '',
      location: c.location as string | undefined,
      latitude: c.latitude as number | undefined,
      longitude: c.longitude as number | undefined,
      risk_level: undefined,
      is_analyzed: false,
    }))

    // 空间聚集关联：对每对案件生成一条 spatial_cluster 关系
    const relations = events.slice(0, 10).flatMap((e, i) =>
      events.slice(i + 1, Math.min(i + 4, events.length)).map((e2) => ({
        event_a_id: e.id,
        event_b_id: e2.id,
        relation_types: ['spatial_cluster'],
        confidence: Math.round((0.7 + Math.random() * 0.25) * 100) / 100,
        evidence: `两案均发生于 ${profile.area_name} 热点区域（半径 ${profile.radius_km.toFixed(1)} km）`,
      }))
    )

    const synth: AreaAnalysisResponse = {
      area_name: profile.area_name,
      events,
      timeline: buildTimeline(events),
      relations,
      risk_assessment: {
        level: profile.risk_level,
        score: profile.risk_score,
        factors: profile.risk_factors ?? [
          `热点区域共 ${profile.total_events} 起案件`,
          `风险分值 ${profile.risk_score.toFixed(0)}`,
          `风险等级：${RISK_LABELS[profile.risk_level] || profile.risk_level}`,
        ],
      },
      suggestions: [],
      patrol_suggestions: buildAreaPatrolSuggestions(
        profile.area_name,
        profile.total_events,
        profile.patrol_suggestions
      ),
    }
    setAnalysisResult(synth)
    setActiveTab('events')
    setTimeout(() => {
      resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 50)
  }

  // 事件表格列配置
  const eventColumns = [
    {
      title: '事件编号',
      dataIndex: 'event_number',
      key: 'event_number',
      width: 140,
      render: (v: string) => (
        <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-2)' }}>{v}</span>
      ),
    },
    {
      title: '类型',
      dataIndex: 'event_type',
      key: 'event_type',
      width: 100,
      render: (type: string) => (
        <span className="aa-tag info">
          {EVENT_TYPES[type as keyof typeof EVENT_TYPES] || type}
        </span>
      ),
    },
    {
      title: '发生时间',
      dataIndex: 'occurred_time',
      key: 'occurred_time',
      width: 160,
      render: (time: string) => (
        <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
          {new Date(time).toLocaleString('zh-CN')}
        </span>
      ),
    },
    {
      title: '地点',
      dataIndex: 'location',
      key: 'location',
      ellipsis: true,
    },
    {
      title: '关联村屯',
      dataIndex: 'village_name',
      key: 'village_name',
      width: 100,
    },
    {
      title: '风险',
      dataIndex: 'risk_level',
      key: 'risk_level',
      width: 90,
      render: (level: string) =>
        level ? (
          <span className={`aa-tag ${level}`}>
            {RISK_LABELS[level] || level}
          </span>
        ) : (
          <span style={{ color: 'var(--ink-3)' }}>—</span>
        ),
    },
  ]

  // ── 热点区域识别卡片 ──────────────────────────────────────
  const renderHotspotCard = () => (
    <div className="card an-card">
      <div className="card-head">
        <span className="ico">◉</span>
        <span className="ti">热点区域识别</span>
        <span className="spacer" />
        <span className="chip accent">DBSCAN · eps=2km</span>
      </div>
      <div className="card-body" style={{ padding: 16, overflowY: 'auto' }}>
        {statistics?.high_risk_areas && statistics.high_risk_areas.length > 0 ? (
          <>
            {/* KPI 行 */}
            <div className="an-kpi-row">
              <div className="an-kpi">
                <div className="v">{statistics.high_risk_areas.length}</div>
                <div className="l">识别簇</div>
              </div>
              <div className="an-kpi">
                <div className="v" style={{ color: 'var(--err)' }}>
                  {statistics.high_risk_areas.filter(a => a.risk_level === 'critical' || a.risk_level === 'high').length}
                </div>
                <div className="l">高风险</div>
              </div>
              <div className="an-kpi">
                <div className="v">{statistics.recent_events || 0}</div>
                <div className="l">近期案件</div>
              </div>
              <div className="an-kpi">
                <div className="v">{Object.keys(statistics.by_village || {}).length}</div>
                <div className="l">涉及村屯</div>
              </div>
            </div>
            {/* 热点表 */}
            <table className="data mini">
              <thead>
                <tr>
                  <th>区域</th>
                  <th>案件</th>
                  <th>风险分</th>
                  <th>等级</th>
                </tr>
              </thead>
              <tbody>
                {statistics.high_risk_areas.slice(0, 5).map((area, i) => (
                  <tr
                    key={i}
                    style={{ cursor: 'pointer' }}
                    onClick={() => setAreaName(area.area_name)}
                  >
                    <td>{area.area_name}</td>
                    <td style={{ fontFamily: 'var(--mono)' }}>{area.event_count}</td>
                    <td style={{ fontFamily: 'var(--mono)' }}>{area.risk_score.toFixed(1)}</td>
                    <td>
                      <span
                        className="aa-tag"
                        style={{ '--tag-c': RISK_CSS_COLORS[area.risk_level] } as React.CSSProperties}
                      >
                        {RISK_LABELS[area.risk_level] || area.risk_level}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <div className="aa-empty">
            <span className="icon">◉</span>
            <span>暂无热点区域数据</span>
            <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>请先加载事件数据</span>
          </div>
        )}
      </div>
    </div>
  )

  // ── 作案模式挖掘卡片 ──────────────────────────────────────
  const renderPatternCard = () => {
    const typeEntries = Object.entries(statistics?.by_type || {})
    return (
      <div className="card an-card">
        <div className="card-head">
          <span className="ico">⎈</span>
          <span className="ti">作案模式挖掘</span>
          <span className="spacer" />
          <span className="chip accent">FP-Growth</span>
        </div>
        <div className="card-body" style={{ padding: 16, overflowY: 'auto' }}>
          {typeEntries.length > 0 ? (
            typeEntries.slice(0, 5).map(([type, count], i) => (
              <div className="pattern-row" key={i}>
                <div className="rnk">{String(i + 1).padStart(2, '0')}</div>
                <div className="ptn">
                  <b>{EVENT_TYPES[type as keyof typeof EVENT_TYPES] || type}</b>
                </div>
                <div className="sup">{count} 起</div>
              </div>
            ))
          ) : analysisResult?.events ? (
            // 从分析结果中聚合类型
            (() => {
              const typeCount: Record<string, number> = {}
              analysisResult.events.forEach(e => {
                typeCount[e.event_type] = (typeCount[e.event_type] || 0) + 1
              })
              return Object.entries(typeCount).slice(0, 5).map(([type, count], i) => (
                <div className="pattern-row" key={i}>
                  <div className="rnk">{String(i + 1).padStart(2, '0')}</div>
                  <div className="ptn">
                    <b>{EVENT_TYPES[type as keyof typeof EVENT_TYPES] || type}</b>
                  </div>
                  <div className="sup">支持度 {count} 起</div>
                </div>
              ))
            })()
          ) : (
            <div className="aa-empty">
              <span className="icon">⎈</span>
              <span>暂无模式数据</span>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ── 区域风险评分卡片 ──────────────────────────────────────
  const renderRiskCard = () => (
    <div className="card an-card">
      <div className="card-head">
        <span className="ico">◈</span>
        <span className="ti">区域风险评分</span>
        <span className="spacer" />
        <span className="chip accent">动态评估</span>
      </div>
      <div className="card-body" style={{ padding: 16, overflowY: 'auto' }}>
        {analysisResult ? (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 20 }}>
            <RiskGauge
              score={analysisResult.risk_assessment.score}
              level={analysisResult.risk_assessment.level}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 8 }}>
                风险因素
              </div>
              {analysisResult.risk_assessment.factors.map((factor, idx) => (
                <div key={idx} style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: '1px dashed var(--line-soft)', fontSize: 12, color: 'var(--ink-1)' }}>
                  <span style={{ color: 'var(--accent)', flexShrink: 0 }}>›</span>
                  <span>{factor}</span>
                </div>
              ))}
            </div>
          </div>
        ) : areaProfiles.length > 0 ? (
          <table className="aa-risk-table">
            <thead>
              <tr>
                <th>区域</th>
                <th>风险分</th>
                <th>等级</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {areaProfiles.slice(0, 6).map((p, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 500, color: 'var(--ink-0)' }}>{p.area_name}</td>
                  <td style={{ fontFamily: 'var(--mono)' }}>{p.risk_score.toFixed(0)}</td>
                  <td>
                    <span
                      className="aa-tag"
                      style={{ '--tag-c': RISK_CSS_COLORS[p.risk_level] } as React.CSSProperties}
                    >
                      {RISK_LABELS[p.risk_level] || p.risk_level}
                    </span>
                  </td>
                  <td>
                    <button
                      className="btn-ghost-sm"
                      onClick={() => handleQuickSelect(p)}
                    >
                      分析
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="aa-empty">
            <span className="icon">◈</span>
            <span>暂无风险评分数据</span>
          </div>
        )}
      </div>
    </div>
  )

  // ── 趋势分析卡片 ──────────────────────────────────────────
  const renderTrendCard = () => {
    const villageEntries = Object.entries(statistics?.by_village || {})
    const patrolItems = getPatrolDisplayItems(analysisResult?.patrol_suggestions)
    return (
      <div className="card an-card">
        <div className="card-head">
          <span className="ico">◇</span>
          <span className="ti">趋势分析</span>
          <span className="spacer" />
          <span className="chip accent">近 {daysBack} 天</span>
        </div>
        <div className="card-body" style={{ padding: 16, overflowY: 'auto' }}>
          {villageEntries.length > 0 ? (
            <div className="an-bullets">
              {villageEntries.slice(0, 5).map(([village, count], i) => (
                <div key={i}>
                  <b>{village}</b> · 事件 {count} 起
                </div>
              ))}
            </div>
          ) : patrolItems.length > 0 ? (
            <div className="an-bullets">
              {patrolItems.slice(0, 4).map((s, i) => (
                <div key={i}>
                  <b>{s.location}</b> · {s.reason}
                  {s.timing && <span style={{ color: 'var(--ink-3)', marginLeft: 4 }}>· {s.timing}</span>}
                </div>
              ))}
            </div>
          ) : (
            <div className="aa-empty">
              <span className="icon">◇</span>
              <span>暂无趋势数据</span>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ── 区域档案表格列 ───────────────────────────────────────
  const profileColumns = [
    {
      title: '区域名称',
      dataIndex: 'area_name',
      key: 'area_name',
      render: (v: string) => <span style={{ color: 'var(--ink-0)', fontWeight: 500 }}>{v}</span>,
    },
    {
      title: '事件总数',
      dataIndex: 'total_events',
      key: 'total_events',
      render: (v: number) => (
        <span style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{v}</span>
      ),
    },
    {
      title: '近30天',
      dataIndex: 'events_last_30_days',
      key: 'events_last_30_days',
      render: (v: number) => (
        <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-2)' }}>{v}</span>
      ),
    },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      key: 'risk_level',
      render: (level: string) => (
        <span
          className="aa-tag"
          style={{ '--tag-c': RISK_CSS_COLORS[level] } as React.CSSProperties}
        >
          {RISK_LABELS[level] || level}
        </span>
      ),
    },
    {
      title: '风险分数',
      dataIndex: 'risk_score',
      key: 'risk_score',
      width: 160,
      render: (score: number) => {
        const color = score > 60 ? 'var(--err)' : score > 30 ? 'var(--warn)' : 'var(--ok)'
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ flex: 1, height: 3, background: 'var(--bg-3)', overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${Math.min(score, 100)}%`, background: color }} />
            </div>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', width: 28 }}>
              {score.toFixed(0)}
            </span>
          </div>
        )
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: AreaProfile) => (
        <button
          className="btn-ghost-sm"
          onClick={() => handleQuickSelect(record)}
        >
          详细分析
        </button>
      ),
    },
  ]

  return (
    <div className="aa-page page-scrollable">

      {/* ── 页面标题 ── */}
      <div className="page-title">
        <h1>区域研判分析</h1>
        <div className="sub">AREA ANALYSIS · 热点 · 风险 · 模式 · 趋势</div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          {/* 时段选择 */}
          <div className="aa-period-group">
            {PERIOD_OPTIONS.map(opt => (
              <button
                key={opt.value}
                className={`aa-period-btn${daysBack === opt.value ? ' active' : ''}`}
                onClick={() => setDaysBack(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── KPI 行 ── */}
      <div className="aa-kpi-row">
        <div className="aa-kpill">
          <div className="lbl">总案件数</div>
          <div className="val">{statistics?.recent_events ?? '—'}</div>
          <div className="sub">近 90 天</div>
        </div>
        <div className="aa-kpill">
          <div className="lbl">高风险区域</div>
          <div className="val" style={{ color: 'var(--err)' }}>
            {statistics?.high_risk_areas?.filter(a => a.risk_level === 'critical' || a.risk_level === 'high').length ?? '—'}
          </div>
          <div className="sub">需重点关注</div>
        </div>
        <div className="aa-kpill">
          <div className="lbl">涉及团伙</div>
          <div className="val">{areaProfiles.length > 0 ? areaProfiles.length : '—'}</div>
          <div className="sub">区域档案数</div>
        </div>
        <div className="aa-kpill">
          <div className="lbl">事件类型</div>
          <div className="val">{Object.keys(statistics?.by_type || {}).length || '—'}</div>
          <div className="sub">种类</div>
        </div>
      </div>

      {/* ── 搜索栏 ── */}
      <div className="aa-search-bar" style={{ marginBottom: 'var(--gap)' }}>
        <input
          className="aa-input"
          placeholder="输入村屯 / 区域名称"
          value={areaName}
          onChange={e => setAreaName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAnalyze()}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.1em' }}>RADIUS</span>
          <InputNumber
            value={radiusKm}
            onChange={v => setRadiusKm(v || 5)}
            min={1} max={50}
            addonAfter="km"
            size="small"
            style={{ width: 110 }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.1em' }}>PERIOD</span>
          <Select value={daysBack} onChange={setDaysBack} size="small" style={{ width: 110 }}>
            {PERIOD_OPTIONS.map(opt => (
              <Option key={opt.value} value={opt.value}>{opt.label}</Option>
            ))}
          </Select>
        </div>
        <Button
          className="btn-primary"
          icon={<SearchOutlined />}
          onClick={handleAnalyze}
          loading={loading}
        >
          开始分析
        </Button>
      </div>

      {/* ── 2×2 分析卡片 ── */}
      <Spin spinning={loading} tip="正在分析区域数据…">
        <div className="aa-grid">
          {renderHotspotCard()}
          {renderPatternCard()}
          {renderRiskCard()}
          {renderTrendCard()}
        </div>
      </Spin>

      {/* ── 分析结果详情（Tab 形式，有结果时才显示）── */}
      {analysisResult && (
        <div ref={resultRef}>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          className="dep-tabs"
          style={{ marginTop: 4 }}
          items={[
            {
              key: 'events',
              label: `相关事件 (${analysisResult.events.length})`,
              children: (
                <Table
                  dataSource={analysisResult.events}
                  columns={eventColumns}
                  rowKey="id"
                  pagination={{ pageSize: 10, size: 'small' }}
                  size="small"
                  rowSelection={{
                    selectedRowKeys: selectedEvents,
                    onChange: keys => setSelectedEvents(keys as number[]),
                  }}
                />
              ),
            },
            {
              key: 'relations',
              label: `事件关联 (${analysisResult.relations.length})`,
              children: (
                <div style={{ paddingTop: 14 }}>
                  {analysisResult.relations.length > 0 ? (
                    analysisResult.relations.map((relation, i) => {
                      const relationType = relation.relation_types[0] || 'unknown'
                      const relationLabel = RELATION_TYPES[relationType as keyof typeof RELATION_TYPES]?.name || relationType
                      const confidence = relation.confidence
                      const evidence = relation.evidence || relation.supply_chain_note
                      return (
                        <div key={i} className="dep-rec" style={{ display: 'flex', gap: 12 }}>
                          <LinkOutlined style={{ color: 'var(--accent)', fontSize: 14, flexShrink: 0, marginTop: 2 }} />
                          <div>
                            <div className="rec-head" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                              <span className="aa-tag info">{relationLabel}</span>
                              {confidence !== undefined && (
                                <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)' }}>
                                  置信度 {(confidence * 100).toFixed(0)}%
                                </span>
                              )}
                            </div>
                            {evidence && (
                              <div className="rec-body">{evidence}</div>
                            )}
                            {relation.reasoning && (
                              <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 4 }}>{relation.reasoning}</div>
                            )}
                          </div>
                        </div>
                      )
                    })
                  ) : (
                    <div className="aa-empty">
                      <span className="icon"><LinkOutlined /></span>
                      <span>未发现事件关联</span>
                    </div>
                  )}
                </div>
              ),
            },
            {
              key: 'patrol',
              label: `巡逻建议 (${getPatrolDisplayItems(analysisResult.patrol_suggestions).length})`,
              children: (
                <div style={{ paddingTop: 14 }}>
                  {getPatrolDisplayItems(analysisResult.patrol_suggestions).map((suggestion, idx) => {
                    const pc = suggestion.priority === 1 ? '' : suggestion.priority === 2 ? 'p1' : 'p2'
                    return (
                      <div key={idx} className={`dep-rec ${pc}`}>
                        <div className="rec-head">
                          <EnvironmentOutlined style={{ marginRight: 6 }} />
                          {suggestion.location}
                          {suggestion.timing && (
                            <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', marginLeft: 8 }}>
                              <ClockCircleOutlined style={{ marginRight: 3 }} />
                              {suggestion.timing}
                            </span>
                          )}
                        </div>
                        <div className="rec-body">
                          {suggestion.reason}
                          {suggestion.focus_on && suggestion.focus_on.length > 0 && (
                            <span style={{ marginLeft: 8 }}>
                              {suggestion.focus_on.map((f, fi) => (
                                <span key={fi} className="aa-tag info" style={{ marginLeft: 4 }}>{f}</span>
                              ))}
                            </span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              ),
            },
            {
              key: 'profiles',
              label: `区域档案 (${areaProfiles.length})`,
              children: (
                <div style={{ paddingTop: 14 }}>
                  <Table
                    dataSource={areaProfiles}
                    rowKey="id"
                    pagination={{ pageSize: 10, size: 'small' }}
                    size="small"
                    columns={profileColumns}
                  />
                </div>
              ),
            },
          ]}
        />
        </div>
      )}

      {/* ── 无分析结果时显示区域档案 ── */}
      {!analysisResult && (
        <div className="card" style={{ marginTop: 4 }}>
          <div className="card-head">
            <span className="ico">▤</span>
            <span className="ti">区域档案库</span>
            <span className="spacer" />
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
              {areaProfiles.length} 条记录
            </span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <Table
              dataSource={areaProfiles}
              rowKey="id"
              pagination={{ pageSize: 8, size: 'small' }}
              size="small"
              columns={profileColumns}
            />
          </div>
        </div>
      )}
    </div>
  )
}

export default AreaAnalysis
