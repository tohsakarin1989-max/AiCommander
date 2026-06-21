/**
 * 时空研判页面
 * - 指挥中心视图：热点复盘卡片（高危区域 + 高发时窗）
 * - 分析员视图：时段×星期规律矩阵 + 月度趋势
 */

import React, { useMemo, useState } from 'react'
import {
  DatePicker,
  Radio,
  Spin,
  Empty,
} from 'antd'
import {
  RiseOutlined,
  FallOutlined,
  MinusOutlined,
  EnvironmentOutlined,
  ClockCircleOutlined,
  CalendarOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import dayjs, { Dayjs } from 'dayjs'
import { caseApi } from '../../services/cases'
import SpaceTimeMap, { type HeatPoint, type PredictionHotspot } from '../../components/Map/SpaceTimeMap'
import type { Case, Hotspot } from '../../types'
import './SpaceTimeAnalysis.css'

const { RangePicker } = DatePicker

// ── 辅助函数 ───────────────────────────────────────────────────────

/** Haversine 公式计算两点距离（km） */
function haversineKm(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number
): number {
  const R = 6371
  const dLat = ((lat2 - lat1) * Math.PI) / 180
  const dLng = ((lng2 - lng1) * Math.PI) / 180
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

/** 返回出现次数最多的元素的索引 */
function argMax(arr: number[]): number {
  return arr.reduce((best, v, i) => (v > arr[best] ? i : best), 0)
}

/** 把高峰小时转为可读时段描述 */
function hourToRange(hour: number): string {
  const end = (hour + 3) % 24
  return `${String(hour).padStart(2, '0')}:00 — ${String(end).padStart(2, '0')}:00`
}

const DAY_NAMES = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

type TimeSlot = 'all' | 'midnight' | 'day' | 'evening'
type DayFilter = 'all' | 'weekday' | 'weekend'

// ── 热点复盘逻辑：为每个热点生成时空关注摘要 ─────────────────────────────

interface TopType { type: string; count: number; pct: number }

interface PredictionResult extends PredictionHotspot {
  peakHourLabel: string
  peakDayLabel: string
  caseCount: number
  riskScore: number
  topTypes: TopType[]
  riskTrend: 'increasing' | 'stable' | 'decreasing'
  recommendation: string
  nightRatio: number
  recentTrend: number
}

function buildPredictions(hotspots: Hotspot[], allCases: Case[]): PredictionResult[] {
  const casesWithGeo = allCases.filter(
    (c) => c.latitude != null && c.longitude != null && c.occurred_time
  )
  const now = dayjs()

  return hotspots.slice(0, 3).map((h, idx) => {
    const nearby = casesWithGeo.filter(
      (c) => haversineKm(h.center.latitude, h.center.longitude, c.latitude!, c.longitude!) <= h.radius_km
    )

    const hourCounts = new Array(24).fill(0)
    const dayCounts = new Array(7).fill(0)
    const typeCounts: Record<string, number> = {}
    let nightCount = 0
    nearby.forEach((c) => {
      const t = dayjs(c.occurred_time)
      hourCounts[t.hour()]++
      dayCounts[t.day()]++
      const ct = c.case_type || '未分类'
      typeCounts[ct] = (typeCounts[ct] || 0) + 1
      if (t.hour() >= 22 || t.hour() < 6) nightCount++
    })

    const peakHour = argMax(hourCounts)
    const peakDay = argMax(dayCounts)
    const riskLevel: 'high' | 'medium' | 'low' =
      h.risk_score > 0.6 ? 'high' : h.risk_score > 0.3 ? 'medium' : 'low'

    const total = nearby.length || 1
    const topTypes: TopType[] = Object.entries(typeCounts)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 3)
      .map(([type, count]) => ({ type, count, pct: Math.round(count / total * 100) }))

    // 近30天 vs 前30天对比
    const last30 = nearby.filter(c => now.diff(dayjs(c.occurred_time), 'day') < 30).length
    const prev30 = nearby.filter(c => {
      const d = now.diff(dayjs(c.occurred_time), 'day')
      return d >= 30 && d < 60
    }).length
    const riskTrend: 'increasing' | 'stable' | 'decreasing' =
      prev30 === 0 ? 'stable'
      : last30 > prev30 * 1.2 ? 'increasing'
      : last30 < prev30 * 0.8 ? 'decreasing'
      : 'stable'
    const recentTrend = prev30 > 0 ? Math.round((last30 - prev30) / prev30 * 100) : 0
    const nightRatio = Math.round(nightCount / total * 100)

    const recommendation = riskLevel === 'high'
      ? `建议复核 ${hourToRange(peakHour)} ${peakDay === 0 || peakDay === 6 ? '周末' : '工作日'}防控覆盖，${nightRatio > 40 ? '夜间需重点关注' : '侧重日间关键时段'}`
      : riskLevel === 'medium'
      ? `关注 ${DAY_NAMES[peakDay]} ${hourToRange(peakHour)} 时段动态，可结合邻近路线和技防覆盖复核`
      : `常规跟踪，如近期案件上升需升级研判等级`

    return {
      index: idx + 1,
      lat: h.center.latitude,
      lng: h.center.longitude,
      radiusKm: h.radius_km,
      riskLevel,
      label: `热点${idx + 1}：${h.case_count}起案件，风险评分 ${h.risk_score.toFixed(2)}`,
      peakHourLabel: hourToRange(peakHour),
      peakDayLabel: DAY_NAMES[peakDay],
      caseCount: nearby.length,
      riskScore: h.risk_score,
      topTypes,
      riskTrend,
      recommendation,
      nightRatio,
      recentTrend,
    }
  })
}

// ── 主组件 ────────────────────────────────────────────────────────

const SpaceTimeAnalysis: React.FC = () => {
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(180, 'day'),
    dayjs(),
  ])
  const [timeSlot, setTimeSlot] = useState<TimeSlot>('all')
  const [dayFilter, setDayFilter] = useState<DayFilter>('all')

  const { data: cases, isLoading } = useQuery({
    queryKey: ['cases', 'space-time-all'],
    queryFn: () => caseApi.getCases({ limit: 2000 }),
  })

  const { data: hotspots } = useQuery({
    queryKey: ['hotspots'],
    queryFn: () => caseApi.getHotspots(),
  })

  // 时段 + 星期 筛选
  const filteredCases = useMemo(() => {
    const [start, end] = dateRange
    return (cases ?? []).filter((c) => {
      if (!c.latitude || !c.longitude || !c.occurred_time) return false
      const t = dayjs(c.occurred_time)
      if (!t.isAfter(start) || !t.isBefore(end)) return false

      const hour = t.hour()
      const dow = t.day()

      if (timeSlot === 'midnight' && hour >= 6) return false
      if (timeSlot === 'day' && (hour < 6 || hour >= 18)) return false
      if (timeSlot === 'evening' && (hour < 18 || hour >= 24)) return false

      if (dayFilter === 'weekday' && (dow === 0 || dow === 6)) return false
      if (dayFilter === 'weekend' && dow >= 1 && dow <= 5) return false

      return true
    })
  }, [cases, dateRange, timeSlot, dayFilter])

  // 热力图点位
  const heatPoints: HeatPoint[] = useMemo(
    () => filteredCases.map((c) => ({ lat: c.latitude!, lng: c.longitude!, intensity: 1.0 })),
    [filteredCases]
  )

  // 时段×星期 规律矩阵 (24小时 × 7天)
  const hourDayData = useMemo(() => {
    const matrix: number[][] = Array.from({ length: 7 }, () => new Array(24).fill(0))
    ;(cases ?? []).forEach((c) => {
      if (!c.occurred_time) return
      const t = dayjs(c.occurred_time)
      matrix[t.day()][t.hour()]++
    })
    const flat: [number, number, number][] = []
    matrix.forEach((row, d) => row.forEach((count, h) => flat.push([h, d, count])))
    const max = Math.max(...matrix.flat(), 1)
    return { flat, max }
  }, [cases])

  // 月度趋势
  const monthlyTrend = useMemo(() => {
    const map: Record<string, number> = {}
    ;(cases ?? []).forEach((c) => {
      if (!c.occurred_time) return
      const m = dayjs(c.occurred_time).format('YYYY-MM')
      map[m] = (map[m] || 0) + 1
    })
    const sorted = Object.entries(map).sort(([a], [b]) => a.localeCompare(b))
    if (sorted.length < 2) return { months: [], counts: [], signal: 'stable' as const }

    const recentAvg =
      sorted.slice(-3).reduce((s, [, c]) => s + c, 0) / Math.min(sorted.length, 3)
    const histAvg =
      sorted.slice(0, -3).reduce((s, [, c]) => s + c, 0) /
      Math.max(sorted.length - 3, 1)

    const signal: 'increasing' | 'stable' | 'decreasing' =
      histAvg === 0 ? 'stable'
        : recentAvg > histAvg * 1.2 ? 'increasing'
        : recentAvg < histAvg * 0.8 ? 'decreasing'
        : 'stable'

    return {
      months: sorted.map(([m]) => m),
      counts: sorted.map(([, c]) => c),
      signal,
    }
  }, [cases])

  // 热点演化数据查询
  const { data: evolution, isLoading: evolutionLoading } = useQuery({
    queryKey: ['hotspot-evolution'],
    queryFn: () => caseApi.getHotspotEvolution({ months: 6 }),
  })

  // 热点关注区
  const predictions: PredictionResult[] = useMemo(
    () => (hotspots && cases ? buildPredictions(hotspots, cases) : []),
    [hotspots, cases]
  )

  // ECharts 配置
  const matrixOption = {
    backgroundColor: 'transparent',
    tooltip: {
      formatter: (p: { data: [number, number, number] }) =>
        `${String(p.data[0]).padStart(2, '0')}:00  ${DAY_NAMES[p.data[1]]}  ${p.data[2]}起`,
      backgroundColor: 'var(--bg-0)',
      borderColor: 'var(--line)',
      textStyle: { color: 'var(--ink-1)', fontSize: 11 },
    },
    grid: { top: 28, left: 36, right: 8, bottom: 28 },
    xAxis: {
      type: 'category' as const,
      data: Array.from({ length: 24 }, (_, i) => `${i}`),
      splitArea: { show: true, areaStyle: { color: ['oklch(0.12 0.012 250)', 'oklch(0.155 0.013 250)'] } },
      axisLabel: { color: 'oklch(0.45 0.013 90)', fontSize: 9 },
      axisLine: { lineStyle: { color: 'oklch(0.32 0.014 250 / 0.7)' } },
    },
    yAxis: {
      type: 'category' as const,
      data: DAY_NAMES,
      splitArea: { show: true, areaStyle: { color: ['oklch(0.12 0.012 250)', 'oklch(0.155 0.013 250)'] } },
      axisLabel: { color: 'oklch(0.45 0.013 90)', fontSize: 10 },
      axisLine: { lineStyle: { color: 'oklch(0.32 0.014 250 / 0.7)' } },
    },
    visualMap: {
      min: 0,
      max: hourDayData.max,
      show: false,
      inRange: { color: ['oklch(0.12 0.012 250)', 'oklch(0.195 0.014 250)', 'oklch(0.62 0.013 90)', 'oklch(0.78 0.14 45)', 'oklch(0.70 0.20 25)'] },
    },
    series: [
      {
        type: 'heatmap' as const,
        data: hourDayData.flat,
        itemStyle: { borderRadius: 1 },
      },
    ],
  }

  const trendLineColor =
    monthlyTrend.signal === 'increasing' ? 'oklch(0.70 0.20 25)'
    : monthlyTrend.signal === 'decreasing' ? 'oklch(0.78 0.14 155)'
    : 'oklch(0.78 0.14 45)'

  const trendOption = {
    backgroundColor: 'transparent',
    grid: { top: 8, bottom: 20, left: 24, right: 8 },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: 'var(--bg-0)',
      borderColor: 'var(--line)',
      textStyle: { color: 'var(--ink-1)', fontSize: 11 },
    },
    xAxis: {
      type: 'category' as const,
      data: monthlyTrend.months,
      axisLabel: { color: 'oklch(0.45 0.013 90)', fontSize: 8, rotate: 30 },
      axisLine: { lineStyle: { color: 'oklch(0.32 0.014 250 / 0.7)' } },
    },
    yAxis: {
      type: 'value' as const,
      axisLabel: { color: 'oklch(0.45 0.013 90)', fontSize: 9 },
      splitLine: { lineStyle: { color: 'oklch(0.32 0.014 250 / 0.35)' } },
    },
    series: [
      {
        type: 'line' as const,
        data: monthlyTrend.counts,
        smooth: true,
        lineStyle: { color: trendLineColor, width: 2 },
        areaStyle: { color: trendLineColor.replace(')', ' / 0.08)') },
        itemStyle: { color: trendLineColor },
      },
    ],
  }

  // 趋势标签
  const trendMeta = {
    increasing: { icon: <RiseOutlined />, color: 'var(--err)',  label: '上升趋势' },
    stable:     { icon: <MinusOutlined />, color: 'var(--accent)', label: '平稳' },
    decreasing: { icon: <FallOutlined />,  color: 'var(--ok)',   label: '下降趋势' },
  }[monthlyTrend.signal]

  // 热点演化折线图配置
  const EVOLUTION_COLORS = ['#e85d4a', '#f5a623', '#50fa7b', '#8be9fd', '#bd93f9']

  const evolutionOption = useMemo(() => {
    if (!evolution || evolution.periods.length === 0) return null

    const periods = evolution.periods
    // 收集所有唯一 hotspot_key（最多取前5个，按累计案件数排序）
    const keyCountMap: Record<string, number> = {}
    periods.forEach((p) => {
      p.hotspots.forEach((hs) => {
        keyCountMap[hs.hotspot_key] = (keyCountMap[hs.hotspot_key] || 0) + hs.case_count
      })
    })
    const topKeys = Object.entries(keyCountMap)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 5)
      .map(([k]) => k)

    // x轴月份标签（如 "11月"）
    const xLabels = periods.map((p) => {
      const parts = p.period.split('-')
      return `${parseInt(parts[1])}月`
    })

    // 为每个热点 key 构建一条折线数据
    const series = topKeys.map((key, idx) => {
      const data = periods.map((p) => {
        const hs = p.hotspots.find((h) => h.hotspot_key === key)
        return hs ? hs.case_count : 0
      })
      // 截取坐标后4位作为图例标签
      const [lat, lng] = key.split('_')
      return {
        name: `热点 ${lat},${lng}`,
        type: 'line' as const,
        smooth: true,
        data,
        lineStyle: { color: EVOLUTION_COLORS[idx % EVOLUTION_COLORS.length], width: 2 },
        itemStyle: { color: EVOLUTION_COLORS[idx % EVOLUTION_COLORS.length] },
        symbol: 'circle',
        symbolSize: 5,
      }
    })

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis' as const,
        backgroundColor: 'var(--bg-0)',
        borderColor: 'var(--line)',
        textStyle: { color: 'var(--ink-1)', fontSize: 11 },
      },
      legend: {
        data: topKeys.map((key) => {
          const [lat, lng] = key.split('_')
          return `热点 ${lat},${lng}`
        }),
        textStyle: { color: 'var(--ink-2)', fontSize: 10 },
        itemWidth: 14,
        itemHeight: 6,
        top: 4,
      },
      grid: { top: 36, bottom: 24, left: 28, right: 12 },
      xAxis: {
        type: 'category' as const,
        data: xLabels,
        axisLabel: { color: 'oklch(0.45 0.013 90)', fontSize: 10 },
        axisLine: { lineStyle: { color: 'oklch(0.32 0.014 250 / 0.7)' } },
      },
      yAxis: {
        type: 'value' as const,
        minInterval: 1,
        axisLabel: { color: 'oklch(0.45 0.013 90)', fontSize: 9 },
        splitLine: { lineStyle: { color: 'oklch(0.32 0.014 250 / 0.35)' } },
      },
      series,
    }
  }, [evolution])

  return (
    <div className="sta-page">

      {/* 页面标题 */}
      <div className="page-title" style={{ marginBottom: 0 }}>
        <h1>时空研判分析</h1>
        <span className="sub">SPACE-TIME ANALYSIS</span>
      </div>

      {/* 筛选栏 */}
      <div className="sta-filter-bar">
        <span className="sta-filter-label">时间范围：</span>
        <RangePicker
          size="small"
          value={dateRange}
          onChange={(v) => v && v[0] && v[1] && setDateRange([v[0], v[1]])}
        />
        <Radio.Group
          size="small"
          value={timeSlot}
          onChange={(e) => setTimeSlot(e.target.value)}
          optionType="button"
          buttonStyle="solid"
        >
          <Radio.Button value="all">全天</Radio.Button>
          <Radio.Button value="midnight">深夜 0-6</Radio.Button>
          <Radio.Button value="day">白天 6-18</Radio.Button>
          <Radio.Button value="evening">夜间 18-24</Radio.Button>
        </Radio.Group>
        <Radio.Group
          size="small"
          value={dayFilter}
          onChange={(e) => setDayFilter(e.target.value)}
          optionType="button"
          buttonStyle="solid"
        >
          <Radio.Button value="all">全部</Radio.Button>
          <Radio.Button value="weekday">工作日</Radio.Button>
          <Radio.Button value="weekend">周末</Radio.Button>
        </Radio.Group>
        <span className="sta-count-chip">{filteredCases.length} 起有效案件</span>
      </div>

      {/* 主体 */}
      <div className="sta-body">

        {/* 地图 */}
        <div className="sta-map-wrap">
          {isLoading ? (
            <div className="sta-spin-wrap"><Spin tip="加载数据..." /></div>
          ) : (
            <SpaceTimeMap
              heatPoints={heatPoints}
              predictionHotspots={predictions}
              height="100%"
            />
          )}
        </div>

        {/* 右侧面板 */}
        <div className="sta-right-panel">

          {/* 热点关注区域 */}
          <div className="card">
            <div className="card-head">
              <EnvironmentOutlined className="ico" />
              <span className="ti">高危区域深度研判</span>
              <span className="spacer" />
              <span className="chip">{predictions.length} 个热点</span>
            </div>
            <div className="card-body pad">
              {predictions.length === 0 ? (
                <div className="empty-state" style={{ padding: '16px' }}>
                  <span>暂无热点数据，请确保已录入足够案件</span>
                </div>
              ) : (
                predictions.map((p) => {
                  const trendColor = p.riskTrend === 'increasing' ? 'var(--err)'
                    : p.riskTrend === 'decreasing' ? 'var(--ok)' : 'var(--warn)'
                  const trendIcon = p.riskTrend === 'increasing' ? '↑' : p.riskTrend === 'decreasing' ? '↓' : '→'
                  const trendLabel = p.riskTrend === 'increasing' ? `近30天上升 ${p.recentTrend}%`
                    : p.riskTrend === 'decreasing' ? `近30天下降 ${Math.abs(p.recentTrend)}%` : '态势平稳'
                  return (
                    <div key={p.index} className={`sta-hotspot-item sta-hotspot-item--${p.riskLevel}`}>
                      {/* 标题行 */}
                      <div className="sta-hotspot-item__top">
                        <span className="sta-hotspot-item__name">热点区域 {p.index}</span>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: trendColor }}>
                            {trendIcon} {trendLabel}
                          </span>
                          <span className={`sta-hotspot-item__risk-${p.riskLevel}`}>
                            {{ high: '高风险', medium: '中风险', low: '低风险' }[p.riskLevel]}
                          </span>
                        </span>
                      </div>

                      {/* 基础时空信息 */}
                      <div className="sta-hotspot-item__rows">
                        <div className="sta-hotspot-item__row">
                          <ClockCircleOutlined style={{ color: 'var(--warn)' }} />
                          <span className="sta-hotspot-item__row-key">高发时段：</span>
                          <span className="sta-hotspot-item__row-val">{p.peakHourLabel}</span>
                          {p.nightRatio > 40 && (
                            <span style={{ marginLeft: 6, fontFamily: 'var(--mono)', fontSize: 9.5, color: 'var(--err)' }}>
                              夜间占 {p.nightRatio}%
                            </span>
                          )}
                        </div>
                        <div className="sta-hotspot-item__row">
                          <CalendarOutlined style={{ color: 'var(--oil)' }} />
                          <span className="sta-hotspot-item__row-key">高发星期：</span>
                          <span className="sta-hotspot-item__row-val">{p.peakDayLabel}</span>
                        </div>
                        <div className="sta-hotspot-item__row">
                          <EnvironmentOutlined style={{ color: 'var(--info)' }} />
                          <span className="sta-hotspot-item__row-geo">
                            {p.lat.toFixed(4)}, {p.lng.toFixed(4)} · 半径 {p.radiusKm.toFixed(1)} km · <b style={{ color: 'var(--accent)' }}>{p.caseCount}</b> 起
                          </span>
                        </div>
                      </div>

                      {/* 案件类型分布 */}
                      {p.topTypes.length > 0 && (
                        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--line-soft)' }}>
                          <div style={{ fontFamily: 'var(--mono)', fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '0.1em', marginBottom: 5 }}>
                            CASE TYPES · 主要案件类型
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                            {p.topTypes.map((t, ti) => (
                              <div key={ti} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                                <div style={{
                                  height: 3, width: `${Math.max(t.pct * 0.6, 6)}px`,
                                  background: ti === 0 ? 'var(--err)' : ti === 1 ? 'var(--warn)' : 'var(--info)',
                                  borderRadius: 0,
                                }} />
                                <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-1)' }}>
                                  {t.type}
                                </span>
                                <span style={{ fontFamily: 'var(--mono)', fontSize: 9.5, color: 'var(--ink-3)' }}>
                                  {t.pct}%
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* 研判建议 */}
                      <div style={{
                        marginTop: 8, padding: '7px 10px',
                        background: p.riskLevel === 'high' ? 'oklch(0.70 0.20 25 / 0.08)' : 'oklch(0.78 0.14 45 / 0.05)',
                        borderLeft: `2px solid ${p.riskLevel === 'high' ? 'var(--err)' : p.riskLevel === 'medium' ? 'var(--warn)' : 'var(--ok)'}`,
                        fontSize: 11, color: 'var(--ink-1)', lineHeight: 1.6,
                      }}>
                        <span style={{ fontFamily: 'var(--mono)', fontSize: 9.5, color: 'var(--ink-3)', marginRight: 6 }}>建议：</span>
                        {p.recommendation}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* 时段×星期 规律矩阵 */}
          <div className="card">
            <div className="card-head">
              <span className="ti">时段 × 星期 规律矩阵</span>
            </div>
            <div className="card-body">
              <div style={{ padding: '2px 12px 4px', fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)' }}>
                颜色越深表示该时间段发案越集中
              </div>
              <ReactECharts option={matrixOption} style={{ height: 160 }} />
            </div>
          </div>

          {/* 月度趋势 */}
          <div className="card">
            <div className="card-head">
              <span className="ti">月度发案趋势</span>
              <span className="spacer" />
              <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontFamily: 'var(--mono)', fontSize: 11, color: trendMeta.color }}>
                {trendMeta.icon} {trendMeta.label}
              </span>
            </div>
            <div className="card-body">
              <ReactECharts option={trendOption} style={{ height: 110 }} />
              {monthlyTrend.signal === 'increasing' && (
                <div style={{ padding: '6px 12px 8px', fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--err)', background: 'oklch(0.70 0.20 25 / 0.07)', borderTop: '1px solid var(--line-soft)' }}>
                  ⚠ 近3个月发案频率高于历史均值，建议提升巡防频次并启动专项整治
                </div>
              )}
              {monthlyTrend.signal === 'decreasing' && (
                <div style={{ padding: '6px 12px 8px', fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ok)', background: 'oklch(0.78 0.14 155 / 0.06)', borderTop: '1px solid var(--line-soft)' }}>
                  ✓ 近期态势持续好转，建议保持现有部署强度，关注隐患反弹
                </div>
              )}
            </div>
          </div>

          {/* 热点区域演化趋势 */}
          <div className="card">
            <div className="card-head">
              <span className="ico">◎</span>
              <span className="ti">热点区域演化趋势（近6个月）</span>
            </div>
            <div className="card-body">
              {evolutionLoading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '24px 0' }}>
                  <Spin tip="加载中..." />
                </div>
              ) : !evolution || evolution.periods.every((p) => p.hotspots.length === 0) ? (
                <div style={{ padding: '16px 12px' }}>
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={<span style={{ color: 'var(--ink-3)', fontSize: 12 }}>暂无热点演化数据</span>}
                  />
                </div>
              ) : (
                <>
                  {/* 折线图 */}
                  {evolutionOption && (
                    <ReactECharts option={evolutionOption} style={{ height: 180 }} />
                  )}
                  {/* 趋势摘要数字 */}
                  {evolution.trend_summary && (
                    <div style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(4, 1fr)',
                      gap: 6,
                      padding: '8px 12px 10px',
                      borderTop: '1px solid var(--line-soft)',
                    }}>
                      {[
                        { emoji: '🔴', label: '升温热点', val: evolution.trend_summary.heating_up, color: 'var(--err)' },
                        { emoji: '🟢', label: '降温热点', val: evolution.trend_summary.cooling_down, color: 'var(--ok)' },
                        { emoji: '⚪', label: '稳定热点', val: evolution.trend_summary.stable, color: 'var(--ink-2)' },
                        { emoji: '🆕', label: '新出现热点', val: evolution.trend_summary.new_hotspots, color: 'var(--info)' },
                      ].map(({ emoji, label, val, color }) => (
                        <div key={label} style={{ textAlign: 'center', padding: '6px 4px', background: 'var(--bg-2)', border: '1px solid var(--line)' }}>
                          <div style={{ fontSize: 14 }}>{emoji}</div>
                          <div style={{ fontFamily: 'var(--mono)', fontSize: 16, fontWeight: 700, color, lineHeight: 1.2 }}>{val}</div>
                          <div style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-3)', marginTop: 2 }}>{label}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {/* 综合研判意见 */}
          <div className="card">
            <div className="card-head">
              <span className="ico">⌖</span>
              <span className="ti">综合研判意见</span>
              <span className="spacer" />
              <span className="chip accent">AI 自动生成</span>
            </div>
            <div className="card-body pad">
              {filteredCases.length === 0 ? (
                <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)', padding: '8px 0' }}>
                  无案件数据，调整筛选条件后重试
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {/* 关键数字 */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 4 }}>
                    {[
                      { label: '分析案件', val: filteredCases.length, color: 'var(--accent)' },
                      { label: '热点数量', val: predictions.length, color: 'var(--err)' },
                      { label: '态势', val: { increasing: '上升', stable: '平稳', decreasing: '下降' }[monthlyTrend.signal], color: trendMeta.color },
                    ].map(({ label, val, color }) => (
                      <div key={label} style={{ border: '1px solid var(--line)', padding: '8px 10px', background: 'var(--bg-2)' }}>
                        <div style={{ fontFamily: 'var(--mono)', fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '0.1em', marginBottom: 3 }}>{label}</div>
                        <div style={{ fontFamily: 'var(--mono)', fontSize: 18, fontWeight: 700, color }}>{val}</div>
                      </div>
                    ))}
                  </div>

                  {/* 重点关注事项 */}
                  {predictions.length > 0 && (
                    <div style={{ fontSize: 11.5, color: 'var(--ink-1)', lineHeight: 1.75 }}>
                      {predictions.filter(p => p.riskLevel === 'high').length > 0 && (
                        <div style={{ padding: '6px 10px', borderLeft: '2px solid var(--err)', background: 'oklch(0.70 0.20 25 / 0.06)', marginBottom: 6 }}>
                          <b style={{ color: 'var(--err)', fontFamily: 'var(--mono)', fontSize: 10 }}>高风险区域 ({predictions.filter(p => p.riskLevel === 'high').length}处)：</b>
                          {' '}{predictions.filter(p => p.riskLevel === 'high').map(p =>
                            `热点${p.index}（${p.peakHourLabel} · ${p.peakDayLabel}）`
                          ).join('、')}，应优先复核防控覆盖
                        </div>
                      )}
                      {predictions[0]?.topTypes[0] && (
                        <div style={{ padding: '6px 10px', borderLeft: '2px solid var(--warn)', background: 'oklch(0.80 0.16 75 / 0.05)', marginBottom: 6 }}>
                          <b style={{ color: 'var(--warn)', fontFamily: 'var(--mono)', fontSize: 10 }}>主要案件类型：</b>
                          {' '}{predictions[0].topTypes[0].type}（占比 {predictions[0].topTypes[0].pct}%），建议针对此类手法制定专项预防措施
                        </div>
                      )}
                      <div style={{ padding: '6px 10px', borderLeft: '2px solid var(--info)', background: 'oklch(0.78 0.11 220 / 0.05)' }}>
                        <b style={{ color: 'var(--info)', fontFamily: 'var(--mono)', fontSize: 10 }}>时空规律：</b>
                        {' '}热力矩阵中颜色最深区域即为高发时段，重点关注
                        {predictions[0] ? ` ${predictions[0].peakDayLabel} ${predictions[0].peakHourLabel}` : ''}
                        前后 2 小时窗口，夜间案件比例较高时应加强灯光和技防覆盖
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}

export default SpaceTimeAnalysis
