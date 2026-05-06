/**
 * 巡逻部署页面
 * 实现巡逻反馈闭环，记录巡逻执行结果并自动更新区域风险评分
 * 设计稿：Patrol.html（2×2 grid：花名册、时间线、热力图、AI 建议）
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
  message,
  Space,
  Descriptions,
  Popconfirm,
  Rate,
  Spin,
  Progress,
} from 'antd'
import {
  PlusOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  EnvironmentOutlined,
  SyncOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { patrolApi } from '../../services/patrols'
import { caseApi } from '../../services/cases'
import { keyLocationApi } from '../../services/key_locations'
import type { PatrolRecord, PatrolCreate, PatrolComplete, AreaRisk, KeyLocation, CaseDrivenPatrolPlan } from '../../types'
import dayjs from 'dayjs'
import './Patrols.css'

const { TextArea } = Input
const { Option } = Select

// ── 工具函数 ────────────────────────────────────────────────

const STATUS_MAP: Record<string, { cls: string; text: string; icon?: React.ReactNode }> = {
  planned:     { cls: 'idle', text: '待命', icon: null },
  in_progress: { cls: 'on',   text: '执行中', icon: <SyncOutlined spin style={{ marginRight: 3 }} /> },
  completed:   { cls: 'done', text: '完成', icon: <CheckCircleOutlined style={{ marginRight: 3 }} /> },
  cancelled:   { cls: 'off',  text: '已取消', icon: <CloseCircleOutlined style={{ marginRight: 3 }} /> },
}

const TYPE_MAP: Record<string, string> = {
  routine:   '日常',
  targeted:  '重点',
  emergency: '紧急',
}

const RISK_COLOR: Record<string, string> = {
  low:      'var(--ok)',
  medium:   'var(--warn)',
  high:     'var(--err)',
  critical: 'var(--err)',
}
const RISK_LABEL: Record<string, string> = {
  low: '低风险', medium: '中风险', high: '高风险', critical: '极高风险',
}

/**
 * 将 PatrolRecord 映射到设计稿中的 squad-row 变体
 * on = 执行中, idle = 待命, done = 完成, off = 取消/休整
 */
function squadClass(status: string): string {
  return STATUS_MAP[status]?.cls ?? 'off'
}

/**
 * 将时间（小时:分钟）转为时间线百分比位置
 * @param hour 0-24
 * @param minute 0-59
 */
function timeToPercent(hour: number, minute = 0): number {
  return ((hour * 60 + minute) / (24 * 60)) * 100
}

/**
 * 从 start_time / end_time 计算 lane-bar 的 left% 和 width%
 * 若无时间则返回 null
 */
function calcBarStyle(start?: string | null, end?: string | null): { left: string; width: string } | null {
  if (!start || !end) return null
  const s = dayjs(start)
  const e = dayjs(end)
  const left  = timeToPercent(s.hour(), s.minute())
  const right = timeToPercent(e.hour(), e.minute())
  const width = Math.max(right - left, 2) // 最少 2% 宽度可见
  return { left: `${left}%`, width: `${width}%` }
}

/** 颜色轮转（与时间线车道颜色一致） */
const LANE_COLORS = [
  'oklch(0.78 0.14 45)',
  'oklch(0.78 0.11 220)',
  'oklch(0.78 0.14 155)',
  'oklch(0.80 0.16 75)',
  'oklch(0.72 0.14 285)',
]

/** 7 天热力图数据（实际项目中从 API 获取；此处用确定性伪随机填充） */
function buildHeatmapData(patrols: PatrolRecord[]) {
  // 使用实际巡逻数据生成近似热力（按小时统计在岗人数）
  const days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
  return days.map((day, dayIdx) => {
    const cells = Array.from({ length: 24 }, (_, hour) => {
      // 基于已完成巡逻的创建时间粗略估算；实际可通过专用 API 获取
      const count = patrols.filter(p => {
        if (!p.start_time) return false
        const d = dayjs(p.start_time)
        return d.day() === (dayIdx + 1) % 7 && Math.abs(d.hour() - hour) < 2
      }).length
      return count
    })
    return { day, cells }
  })
}

function heatmapColor(count: number): string {
  if (count === 0)  return 'oklch(0.20 0.014 250)'
  if (count === 1)  return 'oklch(0.78 0.14 45 / 0.18)'
  if (count === 2)  return 'oklch(0.78 0.14 45 / 0.35)'
  if (count === 3)  return 'oklch(0.78 0.14 45 / 0.55)'
  return                   'oklch(0.78 0.14 45 / 0.85)'
}

// ── 子组件：24h 时间线 ──────────────────────────────────────

interface TimelineProps {
  patrols: PatrolRecord[]
  nowPercent: number
}

function ScheduleTimeline({ patrols, nowPercent }: TimelineProps) {
  const active = patrols.filter(p => p.status === 'in_progress' || p.start_time)

  return (
    <div>
      <div className="timeline-hours">
        <span>00:00</span>
        <span>04:00</span>
        <span>08:00</span>
        <span>12:00</span>
        <span>16:00</span>
        <span>20:00</span>
        <span>24:00</span>
      </div>
      <div className="timeline-lanes">
        {active.slice(0, 6).map((p, i) => {
          const barStyle = calcBarStyle(p.start_time, p.end_time)
          const color = LANE_COLORS[i % LANE_COLORS.length]
          return (
            <div key={p.id} className="lane">
              <div className="lane-name">{p.patrol_number}</div>
              <div className="lane-track">
                {barStyle && (
                  <div
                    className="lane-bar"
                    style={{ left: barStyle.left, width: barStyle.width, background: color }}
                  >
                    {p.area_name}
                  </div>
                )}
                <div className="now-line" style={{ left: `${nowPercent}%` }} />
              </div>
            </div>
          )
        })}
        {active.length === 0 && (
          <div style={{ padding: '16px 0 8px 80px', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
            暂无排班数据
          </div>
        )}
      </div>
      <div className="timeline-footer">
        <span className="chip live">
          <span className="dot" />
          当前 {dayjs().format('HH:mm')}
        </span>
        <span>
          今日进行中 {patrols.filter(p => p.status === 'in_progress').length} 班 ·
          已完成 {patrols.filter(p => p.status === 'completed').length} 班 ·
          待命 {patrols.filter(p => p.status === 'planned').length} 班
        </span>
      </div>
    </div>
  )
}

// ── 子组件：覆盖热力图 ──────────────────────────────────────

function CoverageHeatmap({ patrols }: { patrols: PatrolRecord[] }) {
  const heatData = useMemo(() => buildHeatmapData(patrols), [patrols])

  return (
    <div>
      <div className="cov-grid">
        {heatData.map(({ day, cells }) => (
          <div key={day} className="cov-row">
            <div className="cov-day">{day}</div>
            {cells.map((count, hour) => (
              <div
                key={hour}
                className="cov-cell"
                style={{ background: heatmapColor(count) }}
                title={`${day} ${hour}:00 · ${count} 人`}
              />
            ))}
          </div>
        ))}
        {/* 时间轴表头 */}
        <div className="cov-row header">
          <div className="cov-day" />
          {Array.from({ length: 12 }, (_, i) => (
            <div
              key={i}
              className="cov-hdr"
              style={{ gridColumn: 'span 2' }}
            >
              {String(i * 2).padStart(2, '0')}
            </div>
          ))}
        </div>
      </div>
      <div className="cov-legend">
        <span>低</span>
        {[
          'oklch(0.20 0.014 250)',
          'oklch(0.78 0.14 45 / 0.18)',
          'oklch(0.78 0.14 45 / 0.35)',
          'oklch(0.78 0.14 45 / 0.55)',
          'oklch(0.78 0.14 45 / 0.85)',
        ].map(bg => (
          <span key={bg} className="cov-sw" style={{ background: bg }} />
        ))}
        <span>高</span>
        <span style={{ marginLeft: 'auto', color: 'var(--warn)' }}>⚠ 注意夜间 01-04 覆盖率</span>
      </div>
    </div>
  )
}

// ── 子组件：AI 部署建议 ─────────────────────────────────────

function AIRecommendations({
  areaRisks,
  onAdopt,
  isAdopting,
}: {
  areaRisks: AreaRisk[]
  onAdopt: (area: AreaRisk) => void
  isAdopting: boolean
}) {
  const highRisk = areaRisks
    .filter(a => a.risk_level === 'high' || a.risk_level === 'critical')
    .slice(0, 3)

  if (highRisk.length === 0) {
    return (
      <div style={{ padding: '24px 16px', textAlign: 'center', fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
        暂无高风险区域，当前部署良好
      </div>
    )
  }

  return (
    <div>
      {highRisk.map((area, i) => {
        const pri = i === 0 ? '' : i === 1 ? 'p1' : 'p2'
        const tag = i === 0 ? 'P0 · 立即调整' : i === 1 ? 'P1 · 本周落地' : 'P2 · 观察'
        return (
          <div key={area.id} className={`rec-card ${pri}`}>
            <div className="rec-tag">{tag}</div>
            <div className="rec-title">
              {area.area_name} · 加强巡逻频次
            </div>
            <div className="rec-body">
              当前风险评分 <b>{area.risk_score.toFixed(0)}</b>，
              {area.days_since_patrol != null
                ? `距上次巡逻已 ${area.days_since_patrol} 天，`
                : '该区域从未巡逻，'}
              建议立即安排专项巡逻，重点关注{' '}
              {area.risk_level === 'critical' ? '管线设施及夜间时段' : '重点路段及可疑车辆'}。
            </div>
            <div className="rec-foot">
              <span>风险等级 <b>{RISK_LABEL[area.risk_level] ?? area.risk_level}</b></span>
              <button
                className={`btn-ghost-sm${i === 0 ? ' patrol-action-btn--accent' : ''}`}
                disabled={isAdopting}
                onClick={() => onAdopt(area)}
              >
                {i === 0 ? '采纳并排班' : '采纳'}
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── 子组件：智能调度分析 ─────────────────────────────────────

/** 风险级别对应的颜色 */
const SCHEDULE_RISK_COLOR: Record<string, string> = {
  high:   'var(--err)',
  medium: 'var(--warn)',
  low:    'var(--ok)',
}
const SCHEDULE_RISK_LABEL: Record<string, string> = {
  high: '高风险', medium: '中风险', low: '低风险',
}

interface SmartScheduleData {
  recommended_windows: Array<{
    start_hour: number
    end_hour: number
    label: string
    case_count: number
    percentage: number
    risk_level: 'high' | 'medium' | 'low'
  }>
  weekday_priority: Array<{
    weekday: number
    name: string
    case_count: number
    percentage: number
  }>
  total_cases_analyzed: number
  analysis_days: number
}

interface OptimizedRoutesData {
  routes: Array<{
    visit_order: number
    center_latitude: number
    center_longitude: number
    case_count: number
    est_distance_km: number
  }>
  total_distance_km: number
  hotspot_count: number
}

interface SmartDispatchProps {
  schedule: SmartScheduleData | undefined
  optimized: OptimizedRoutesData | undefined
  casePlan: CaseDrivenPatrolPlan | undefined
  scheduleLoading: boolean
  optimizedLoading: boolean
  casePlanLoading: boolean
}

function SmartDispatchPanel({ schedule, optimized, casePlan, scheduleLoading, optimizedLoading, casePlanLoading }: SmartDispatchProps) {
  if (scheduleLoading || optimizedLoading || casePlanLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 24 }}>
        <Spin size="small" />
      </div>
    )
  }

  const noData = !schedule || schedule.total_cases_analyzed === 0
  const noRoutes = !optimized || optimized.hotspot_count === 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

      {/* 动态建议时段 */}
      <div>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 8 }}>
          高风险时段
          {schedule && (
            <span style={{ marginLeft: 8, color: 'var(--ink-4)' }}>
              · 近 {schedule.analysis_days} 天 {schedule.total_cases_analyzed} 案
            </span>
          )}
        </div>
        {noData ? (
          <div style={{ color: 'var(--ink-4)', fontFamily: 'var(--mono)', fontSize: 11 }}>暂无历史案件数据</div>
        ) : (
          schedule!.recommended_windows.map((win, i) => {
            const color = SCHEDULE_RISK_COLOR[win.risk_level]
            const label = SCHEDULE_RISK_LABEL[win.risk_level]
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                {/* 序号 */}
                <div style={{
                  width: 18, height: 18, borderRadius: '50%',
                  background: `${color}22`, border: `1px solid ${color}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: 'var(--mono)', fontSize: 9, color,
                  flexShrink: 0,
                }}>
                  {i + 1}
                </div>
                {/* 时段标签 */}
                <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-1)', minWidth: 100 }}>
                  {win.label}
                </div>
                {/* 进度条 */}
                <div style={{ flex: 1, height: 4, background: 'var(--bg-3)', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{
                    height: '100%',
                    width: `${Math.min(win.percentage * 2.5, 100)}%`,
                    background: color,
                    borderRadius: 2,
                    transition: 'width 0.4s ease',
                  }} />
                </div>
                {/* 数值 */}
                <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', minWidth: 40, textAlign: 'right' }}>
                  {win.percentage}%
                </div>
                {/* 风险标签 */}
                <span className="chip" style={{ color, borderColor: color, fontSize: 9, padding: '1px 5px', minWidth: 42, textAlign: 'center' }}>
                  {label}
                </span>
              </div>
            )
          })
        )}
      </div>

      {/* 案件驱动区域规划 */}
      <div>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 8 }}>
          案件驱动区域
          {casePlan && (
            <span style={{ marginLeft: 8, color: 'var(--ink-4)' }}>
              · {casePlan.area_count} 区域 · 缺坐标 {casePlan.data_quality.missing_geo_case_count} 案
            </span>
          )}
        </div>
        {!casePlan || casePlan.areas.length === 0 ? (
          <div style={{ color: 'var(--ink-4)', fontFamily: 'var(--mono)', fontSize: 11 }}>暂无可规划区域</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {casePlan.areas.slice(0, 3).map((area, i) => {
              const color = area.risk_level === 'critical' ? 'var(--err)' : area.risk_level === 'high' ? 'var(--warn)' : 'var(--info)'
              return (
                <div key={area.area_name} style={{ border: '1px solid var(--line)', background: 'var(--bg-2)', padding: '8px 10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                    <span style={{ width: 18, height: 18, borderRadius: 3, border: `1px solid ${color}`, color, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--mono)', fontSize: 10 }}>
                      {i + 1}
                    </span>
                    <span style={{ color: 'var(--ink-1)', fontSize: 12, fontWeight: 600 }}>{area.area_name}</span>
                    <span className="chip" style={{ marginLeft: 'auto', color, borderColor: color, fontSize: 9 }}>
                      {Math.round(area.priority_score)}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--ink-3)', lineHeight: 1.6 }}>
                    {area.case_count} 案 · 质量均分 {Math.round(area.average_quality_score)} · {area.oil_natures.join('、') || '油品未标注'}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>
                    重点：{area.patrol_focus.slice(0, 3).join('、')}
                  </div>
                  {area.recommended_windows[0] && (
                    <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--warn)', marginTop: 4 }}>
                      建议时段：{area.recommended_windows.map(w => w.label).join(' / ')}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 高发星期 */}
      {schedule && schedule.weekday_priority.length > 0 && (
        <div>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 8 }}>
            重点加强日
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {schedule.weekday_priority.map((wd, i) => (
              <span key={i} className="chip" style={{
                color: i === 0 ? 'var(--err)' : i === 1 ? 'var(--warn)' : 'var(--ink-2)',
                borderColor: i === 0 ? 'var(--err)' : i === 1 ? 'var(--warn)' : 'var(--line)',
                fontFamily: 'var(--mono)', fontSize: 11,
              }}>
                {wd.name} · {wd.case_count}案
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 优化路线顺序 */}
      <div>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 8 }}>
          最优访问顺序
          {optimized && optimized.hotspot_count > 0 && (
            <span style={{ marginLeft: 8, color: 'var(--ink-4)' }}>
              · 总距离 {optimized.total_distance_km} km
            </span>
          )}
        </div>
        {noRoutes ? (
          <div style={{ color: 'var(--ink-4)', fontFamily: 'var(--mono)', fontSize: 11 }}>暂无热点数据，无法生成路线</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {optimized!.routes.map((route, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {/* 访问序号 */}
                <div style={{
                  width: 20, height: 20, borderRadius: 3,
                  background: 'oklch(0.78 0.14 45 / 0.15)',
                  border: '1px solid oklch(0.78 0.14 45 / 0.5)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: 'var(--mono)', fontSize: 10,
                  color: 'oklch(0.78 0.14 45)', flexShrink: 0,
                }}>
                  {route.visit_order}
                </div>
                {/* 坐标 */}
                <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-2)', flex: 1 }}>
                  {route.center_latitude.toFixed(3)}, {route.center_longitude.toFixed(3)}
                </div>
                {/* 案件数 */}
                <span className="chip" style={{ fontSize: 9, color: 'var(--warn)', borderColor: 'var(--warn)', padding: '1px 5px' }}>
                  {route.case_count}案
                </span>
                {/* 到下一点距离 */}
                {route.est_distance_km > 0 && (
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-4)', minWidth: 48, textAlign: 'right' }}>
                    →{route.est_distance_km}km
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── 地图投影（与 Dashboard 保持一致）──────────────────────────
const LAT_MIN = 44.5, LAT_MAX = 48.0
const LNG_MIN = 122.5, LNG_MAX = 127.5
const MAP_W = 1200, MAP_H = 600, MAP_PAD = 30

function llToXY(lat: number, lng: number): [number, number] {
  const x = MAP_PAD + (lng - LNG_MIN) / (LNG_MAX - LNG_MIN) * (MAP_W - MAP_PAD * 2)
  const y = (MAP_H - MAP_PAD) - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN) * (MAP_H - MAP_PAD * 2)
  return [parseFloat(x.toFixed(1)), parseFloat(y.toFixed(1))]
}

function inBounds(lat?: number | null, lng?: number | null) {
  return lat != null && lng != null
    && lat >= LAT_MIN && lat <= LAT_MAX
    && lng >= LNG_MIN && lng <= LNG_MAX
}

// ── AI 巡逻路线规划地图 ─────────────────────────────────────

interface HotspotData {
  center: { latitude: number; longitude: number }
  case_count: number
  risk_score: number
  radius_km: number
}

interface PatrolRouteMapProps {
  areaRisks: AreaRisk[]
  hotspots: HotspotData[]
  keyLocations: KeyLocation[]
}

const ROUTE_COLORS = [
  'oklch(0.78 0.14 45)',
  'oklch(0.78 0.11 220)',
  'oklch(0.78 0.14 155)',
  'oklch(0.80 0.16 75)',
]

const CITY_DOTS = [
  { name: '大庆',  lat: 46.639, lng: 125.134, r: 4 },
  { name: '安达',  lat: 46.426, lng: 125.349, r: 3 },
  { name: '林甸',  lat: 47.183, lng: 124.833, r: 2.5 },
  { name: '大同',  lat: 46.046, lng: 124.819, r: 2.5 },
  { name: '让胡路', lat: 46.658, lng: 124.878, r: 2.5 },
  { name: '红岗',  lat: 46.404, lng: 124.897, r: 2.5 },
  { name: '杜尔伯特', lat: 46.867, lng: 124.433, r: 2 },
] as const

const PATROL_WAYPOINTS = [
  // 大庆油田核心区 → 让胡路 → 杏树岗 → 红岗 → 大庆市区
  [[46.72, 124.86], [46.66, 124.88], [46.52, 124.88], [46.40, 124.90], [46.64, 125.13]],
  // 大庆市区 → 安达 → 肇东（东向输油管沿线）
  [[46.64, 125.13], [46.56, 125.04], [46.43, 125.33], [46.06, 125.97]],
  // 林甸 → 杜尔伯特 → 大同（西北片区）
  [[47.18, 124.83], [46.87, 124.43], [46.05, 124.82]],
  // 中俄管道沿线（北向）
  [[46.85, 124.35], [47.10, 124.40], [47.50, 124.00]],
] as const

function PatrolRouteMap({ areaRisks, hotspots, keyLocations }: PatrolRouteMapProps) {
  const [hoveredRoute, setHoveredRoute] = useState<number | null>(null)

  // 高风险区域转 SVG 坐标（来自 areaRisks）
  const riskPoints = useMemo(() => areaRisks
    .filter(a => a.risk_level === 'high' || a.risk_level === 'critical')
    .filter(a => a.area_coordinates && a.area_coordinates.length >= 1)
    .slice(0, 6)
    .map(a => {
      const pts = a.area_coordinates!.filter(c => inBounds(c.lat, c.lng))
      if (pts.length === 0) return null
      const cx = pts.reduce((s, c) => s + c.lat, 0) / pts.length
      const cy = pts.reduce((s, c) => s + c.lng, 0) / pts.length
      const [sx, sy] = llToXY(cx, cy)
      return { area: a, sx, sy }
    })
    .filter((x): x is NonNullable<typeof x> => x !== null), [areaRisks])

  // 热点转 SVG 坐标
  const hotspotPoints = useMemo(() => hotspots
    .filter(h => inBounds(h.center.latitude, h.center.longitude))
    .slice(0, 5)
    .map((h, i) => {
      const [sx, sy] = llToXY(h.center.latitude, h.center.longitude)
      const r = Math.min(10 + h.case_count * 4, 50)
      return { h, sx, sy, r, label: ['α','β','γ','δ','ε'][i] }
    }), [hotspots])

  // 巡逻路线 SVG path
  const routePaths = useMemo(() => PATROL_WAYPOINTS.map(route =>
    route.map(([la, ln], i) => {
      const [x, y] = llToXY(la as number, ln as number)
      return `${i === 0 ? 'M' : 'L'}${x},${y}`
    }).join(' ')
  ), [])

  // 重要部位
  const keyPts = useMemo(() => keyLocations
    .filter(kl => inBounds(kl.latitude, kl.longitude))
    .map(kl => { const [kx, ky] = llToXY(kl.latitude!, kl.longitude!); return { kl, kx, ky } }),
    [keyLocations])

  return (
    <div className="patrol-map-section">
      <div className="card">
        <div className="card-head">
          <span className="ico">⊕</span>
          <span className="ti">AI 巡逻路线规划</span>
          <span className="spacer" />
          <span className="chip accent">基于风险分析自动规划</span>
          <span className="chip" style={{ marginLeft: 6 }}>
            {routePaths.length} 条路线 · {hotspotPoints.length} 个热点
          </span>
        </div>
        <div className="card-body" style={{ padding: 0, position: 'relative' }}>
          <svg
            className="patrol-map-svg"
            viewBox={`0 0 ${MAP_W} ${MAP_H}`}
            preserveAspectRatio="xMidYMid meet"
          >
            <defs>
              <linearGradient id="pm-land" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor="oklch(0.205 0.015 250)" />
                <stop offset="100%" stopColor="oklch(0.175 0.012 250)" />
              </linearGradient>
              <pattern id="pm-grid" width="60" height="60" patternUnits="userSpaceOnUse">
                <path d="M60 0 L0 0 0 60" fill="none" stroke="oklch(0.32 0.014 250 / 0.18)" strokeWidth="0.5" />
              </pattern>
              {ROUTE_COLORS.map((_c, i) => (
                <filter key={i} id={`glow-r${i}`}>
                  <feGaussianBlur stdDeviation="2.5" result="blur" />
                  <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                </filter>
              ))}
            </defs>

            {/* 底图 */}
            <rect width={MAP_W} height={MAP_H} fill="url(#pm-land)" />
            <rect width={MAP_W} height={MAP_H} fill="url(#pm-grid)" />

            {/* 嫩江 */}
            <path d="M383,45 C372,80 361,128 349,173 C337,218 344,255 349,285 C354,315 380,345 406,383 C428,413 460,435 509,600"
              fill="none" stroke="oklch(0.58 0.12 220 / 0.55)" strokeWidth="2.2" strokeLinecap="round" />

            {/* 主要道路 */}
            <g fill="none" stroke="oklch(0.52 0.018 70 / 0.50)" strokeWidth="0.9" strokeDasharray="7 3">
              <path d="M1200,235 C900,235 650,237 486,233 C350,230 180,234 0,235" />
              <path d="M621,0 C620,90 616,165 621,239 C612,323 590,405 570,600" />
              <path d="M621,239 L680,272 L810,323 L920,363" strokeDasharray="5 4" />
              <path d="M621,239 C610,202 578,174 562,152" strokeDasharray="5 4" />
            </g>

            {/* 热点热力圈 */}
            {hotspotPoints.map((h, i) => (
              <g key={i}>
                <circle cx={h.sx} cy={h.sy} r={h.r * 2}
                  fill={`oklch(0.70 0.20 25 / ${0.08 + i * 0.02})`} />
                <circle cx={h.sx} cy={h.sy} r={h.r}
                  fill="oklch(0.70 0.20 25 / 0.12)"
                  stroke="oklch(0.70 0.20 25 / 0.45)" strokeWidth="1.2" strokeDasharray="4 3" />
              </g>
            ))}

            {/* 高风险区域标记 */}
            {riskPoints.map((rp, i) => (
              <g key={i}>
                <circle cx={rp.sx} cy={rp.sy} r="14"
                  fill="oklch(0.70 0.20 25 / 0.18)"
                  stroke="oklch(0.70 0.20 25 / 0.60)" strokeWidth="1.5" />
                <text x={rp.sx} y={rp.sy + 4}
                  textAnchor="middle" fontSize="9"
                  fontFamily="JetBrains Mono, monospace"
                  fill="oklch(0.85 0.14 45)"
                  paintOrder="stroke" stroke="oklch(0.12 0.012 250 / 0.8)" strokeWidth="2.5">
                  ⚠
                </text>
              </g>
            ))}

            {/* AI 规划巡逻路线 */}
            {routePaths.map((d, i) => {
              const color = ROUTE_COLORS[i % ROUTE_COLORS.length]
              const isHover = hoveredRoute === i
              return (
                <g key={i}>
                  {/* 路线底色（加粗半透明）*/}
                  <path d={d} fill="none"
                    stroke={color.replace(')', ' / 0.15)')}
                    strokeWidth={isHover ? 12 : 8} strokeLinecap="round" strokeLinejoin="round" />
                  {/* 路线本体 */}
                  <path d={d} fill="none"
                    stroke={color.replace(')', ` / ${isHover ? 1 : 0.75})`)}
                    strokeWidth="2.2" strokeDasharray="10 5" strokeLinecap="round"
                    style={{ filter: isHover ? `url(#glow-r${i})` : undefined }}
                    onMouseEnter={() => setHoveredRoute(i)}
                    onMouseLeave={() => setHoveredRoute(null)}
                    cursor="pointer"
                  />
                  {/* 路线终点箭头 */}
                  {(() => {
                    const wpts = PATROL_WAYPOINTS[i]
                    const last = wpts[wpts.length - 1] as [number, number]
                    const prev = wpts[wpts.length - 2] as [number, number]
                    const [lx, ly] = llToXY(last[0], last[1])
                    const [px, py] = llToXY(prev[0], prev[1])
                    const ang = Math.atan2(ly - py, lx - px) * 180 / Math.PI
                    return (
                      <g transform={`translate(${lx},${ly}) rotate(${ang})`}>
                        <polygon points="0,0 -9,-4 -9,4"
                          fill={color.replace(')', ' / 0.85)')} />
                      </g>
                    )
                  })()}
                </g>
              )
            })}

            {/* 路线标签 */}
            {routePaths.map((_, i) => {
              const wpts = PATROL_WAYPOINTS[i]
              const mid = wpts[Math.floor(wpts.length / 2)] as [number, number]
              const [mx, my] = llToXY(mid[0], mid[1])
              const color = ROUTE_COLORS[i % ROUTE_COLORS.length]
              const labels = ['北线管道', '东线外输', '西北片区', '中俄管线']
              return (
                <text key={i} x={mx} y={my - 12}
                  textAnchor="middle" fontSize="10" fontFamily="JetBrains Mono, monospace"
                  fill={color.replace(')', ' / 0.95)')}
                  paintOrder="stroke" stroke="oklch(0.12 0.012 250 / 0.85)" strokeWidth="2.5">
                  {labels[i] ?? `路线${i + 1}`}
                </text>
              )
            })}

            {/* 巡逻节点 */}
            {(PATROL_WAYPOINTS.flat() as [number, number][]).map(([la, ln], i) => {
              const [px, py] = llToXY(la, ln)
              const routeIdx = PATROL_WAYPOINTS.findIndex(r => r.some(([a, b]) => a === la && b === ln))
              const color = ROUTE_COLORS[routeIdx % ROUTE_COLORS.length]
              return (
                <circle key={i} cx={px} cy={py} r="4"
                  fill={color.replace(')', ' / 0.85)')}
                  stroke="oklch(0.97 0.008 90)" strokeWidth="0.8" />
              )
            })}

            {/* 热点标签 */}
            {hotspotPoints.map((h, i) => (
              <g key={i}>
                <circle cx={h.sx} cy={h.sy} r="6"
                  fill="oklch(0.70 0.20 25)" stroke="oklch(0.97 0.008 90)" strokeWidth="0.8" />
                <text x={h.sx + 10} y={h.sy + 4}
                  fontSize="10" fontFamily="JetBrains Mono, monospace"
                  fill="oklch(0.78 0.14 45)"
                  paintOrder="stroke" stroke="oklch(0.12 0.012 250 / 0.8)" strokeWidth="2.5">
                  {h.label} · {h.h.case_count}案
                </text>
              </g>
            ))}

            {/* 重要部位 */}
            {keyPts.map(({ kl, kx, ky }) => (
              <g key={kl.id}>
                <rect x={kx - 4} y={ky - 4} width="8" height="8"
                  fill="oklch(0.72 0.16 155 / 0.8)"
                  stroke="oklch(0.92 0.12 155)" strokeWidth="0.8" />
                <text x={kx + 7} y={ky + 3} fontSize="8" fontFamily="JetBrains Mono, monospace"
                  fill="oklch(0.88 0.10 155)"
                  paintOrder="stroke" stroke="oklch(0.12 0.012 250 / 0.75)" strokeWidth="2">
                  {kl.name.slice(0, 4)}
                </text>
              </g>
            ))}

            {/* 城市标签 */}
            {CITY_DOTS.map(c => {
              const [cx, cy] = llToXY(c.lat, c.lng)
              return (
                <g key={c.name}>
                  <circle cx={cx} cy={cy} r={c.r} fill="oklch(0.70 0.010 90)" opacity="0.6" />
                  <text x={cx} y={cy - c.r - 3}
                    fontSize={c.r > 3 ? 10 : 8.5} fontFamily="IBM Plex Sans, sans-serif"
                    fill="oklch(0.70 0.010 90)" textAnchor="middle"
                    paintOrder="stroke" stroke="oklch(0.12 0.012 250 / 0.8)" strokeWidth="2.5">
                    {c.name}
                  </text>
                </g>
              )
            })}

            {/* 指南针 */}
            <g transform="translate(1150 540)" fontFamily="JetBrains Mono, monospace" fontSize="10" fill="oklch(0.60 0.013 90)">
              <circle r="20" fill="oklch(0.12 0.012 250 / 0.7)" stroke="oklch(0.32 0.014 250 / 0.8)" />
              <polygon points="0,-20 -4,-8 4,-8" fill="oklch(0.78 0.14 45)" />
              <text x="-3" y="-23" fill="oklch(0.70 0.013 90)">N</text>
            </g>
          </svg>

          {/* 路线说明 */}
          {hoveredRoute !== null && (
            <div style={{
              position: 'absolute', top: 12, left: 12,
              background: 'oklch(0.12 0.012 250 / 0.9)',
              border: `1px solid ${ROUTE_COLORS[hoveredRoute].replace(')', ' / 0.6)')}`,
              padding: '10px 14px',
              fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-1)',
              maxWidth: 280,
            }}>
              <div style={{ color: ROUTE_COLORS[hoveredRoute], fontWeight: 600, marginBottom: 4 }}>
                {['北线管道巡逻路线', '东线外输巡逻路线', '西北片区巡逻路线', '中俄管线巡逻路线'][hoveredRoute]}
              </div>
              <div style={{ color: 'var(--ink-2)', lineHeight: 1.6, fontSize: 10.5 }}>
                {[
                  '覆盖喇嘛甸、让胡路、杏树岗、红岗采油区，重点关注油田集输干线及夜间人员活动',
                  '沿大庆-安达-肇东外输管线，关注管线穿越区域及运油车辆异常',
                  '林甸-杜尔伯特-大同西北区域，关注偏远油井及无人值守设施',
                  '中俄原油管道大庆段，关注泵站及阀室周边，建议凌晨加强频次',
                ][hoveredRoute]}
              </div>
            </div>
          )}
        </div>
        <div className="patrol-map-legend">
          {ROUTE_COLORS.slice(0, 4).map((c, i) => (
            <span key={i} style={{ color: c }}>
              <span className="patrol-map-sw dashed" style={{ color: c, borderColor: c, width: 16, height: 3, display: 'inline-block', borderStyle: 'dashed', borderWidth: '1.5px 0 0 0', marginRight: 4 }} />
              {['北线管道', '东线外输', '西北片区', '中俄管线'][i]}
            </span>
          ))}
          <span><span className="patrol-map-sw" style={{ background: 'oklch(0.70 0.20 25)' }} />案件热点</span>
          <span><span className="patrol-map-sw sq" style={{ background: 'oklch(0.72 0.16 155)', width: 8, height: 8 }} />重要部位</span>
          <span style={{ marginLeft: 'auto', color: 'var(--ink-3)' }}>悬停路线可查看详情</span>
        </div>
      </div>
    </div>
  )
}

// ── 主组件 ──────────────────────────────────────────────────

const Patrols: React.FC = () => {
  const [createForm] = Form.useForm()
  const [completeForm] = Form.useForm()
  const [searchParams] = useSearchParams()
  const prefillKeyRef = useRef('')
  const [createModalVisible, setCreateModalVisible]   = useState(false)
  const [completeModalVisible, setCompleteModalVisible] = useState(false)
  const [selectedPatrol, setSelectedPatrol]           = useState<PatrolRecord | null>(null)
  const [detailModalVisible, setDetailModalVisible]   = useState(false)
  const [prefillRelatedCaseIds, setPrefillRelatedCaseIds] = useState<number[] | undefined>()
  const queryClient = useQueryClient()

  const prefillArea = searchParams.get('area') || ''
  const prefillCaseId = Number(searchParams.get('caseId'))

  // ── 数据获取 ────────────────────────────────────────────
  const { data: patrols = [], isLoading } = useQuery({
    queryKey: ['patrols'],
    queryFn:  () => patrolApi.list(),
  })

  const { data: areaRisks = [], isLoading: risksLoading } = useQuery({
    queryKey: ['areaRisks'],
    queryFn:  () => patrolApi.getAreaRisks(),
  })

  const { data: rawHotspots = [] } = useQuery({
    queryKey: ['patrol-hotspots'],
    queryFn:  () => caseApi.getHotspots(1.0, 2),
    refetchInterval: 300_000,
  })

  const { data: keyLocations = [] } = useQuery<KeyLocation[]>({
    queryKey: ['patrol-key-locations'],
    queryFn:  () => keyLocationApi.list({ status: 'active' }),
    refetchInterval: 300_000,
  })

  const { data: prefillCase } = useQuery({
    queryKey: ['patrol-prefill-case', prefillCaseId],
    queryFn: () => caseApi.getCase(prefillCaseId),
    enabled: Number.isFinite(prefillCaseId) && prefillCaseId > 0,
  })

  // 智能调度：动态时段建议
  const { data: smartSchedule, isLoading: scheduleLoading } = useQuery({
    queryKey: ['patrol-smart-schedule'],
    queryFn:  () => patrolApi.getSmartSchedule(90),
    refetchInterval: 600_000, // 10 分钟刷新一次
  })

  // 智能调度：最优路线排序
  const { data: optimizedRoutes, isLoading: optimizedLoading } = useQuery({
    queryKey: ['patrol-optimized-routes'],
    queryFn:  () => patrolApi.getOptimizedRoutes({ radius_km: 2.0, min_cases: 2 }),
    refetchInterval: 600_000,
  })

  const { data: caseDrivenPlan, isLoading: casePlanLoading } = useQuery({
    queryKey: ['patrol-case-driven-plan'],
    queryFn:  () => patrolApi.getCaseDrivenPlan({ days: 90, limit: 5 }),
    refetchInterval: 600_000,
  })

  // ── Mutations ─────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: patrolApi.create,
    onSuccess: () => {
      message.success('巡逻计划已创建')
      setCreateModalVisible(false)
      createForm.resetFields()
      setPrefillRelatedCaseIds(undefined)
      queryClient.invalidateQueries({ queryKey: ['patrols'] })
      queryClient.invalidateQueries({ queryKey: ['suggestions'] })
    },
    onError: (error: any) => {
      message.error(`创建失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  useEffect(() => {
    const key = `${prefillArea}|${prefillCase?.id ?? ''}`
    if (!key || key === '|' || prefillKeyRef.current === key) return
    prefillKeyRef.current = key
    createForm.setFieldsValue({
      area_name: prefillArea || prefillCase?.location || '',
      patrol_type: 'targeted',
      officer_count: 2,
    })
    setPrefillRelatedCaseIds(prefillCase?.id ? [prefillCase.id] : undefined)
    setCreateModalVisible(true)
  }, [createForm, prefillArea, prefillCase])

  const adoptAreaRisk = (area: AreaRisk) => {
    createMutation.mutate({
      area_name: area.area_name,
      patrol_type: area.risk_level === 'critical' ? 'emergency' : 'targeted',
      area_coordinates: area.area_coordinates,
      officer_count: area.risk_level === 'critical' ? 4 : 3,
      created_by: 'AI部署建议',
    })
  }

  const startMutation = useMutation({
    mutationFn: patrolApi.start,
    onSuccess: () => {
      message.success('巡逻已开始')
      queryClient.invalidateQueries({ queryKey: ['patrols'] })
    },
    onError: (error: any) => {
      message.error(`开始失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const completeMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: PatrolComplete }) =>
      patrolApi.complete(id, data),
    onSuccess: () => {
      message.success('巡逻已完成，区域风险评分已更新')
      setCompleteModalVisible(false)
      completeForm.resetFields()
      setSelectedPatrol(null)
      queryClient.invalidateQueries({ queryKey: ['patrols'] })
      queryClient.invalidateQueries({ queryKey: ['areaRisks'] })
    },
    onError: (error: any) => {
      message.error(`完成失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const cancelMutation = useMutation({
    mutationFn: patrolApi.cancel,
    onSuccess: () => {
      message.success('巡逻已取消')
      queryClient.invalidateQueries({ queryKey: ['patrols'] })
    },
    onError: (error: any) => {
      message.error(`取消失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const refreshRisksMutation = useMutation({
    mutationFn: patrolApi.refreshAreaRisks,
    onSuccess: (data) => {
      message.success(data.message)
      queryClient.invalidateQueries({ queryKey: ['areaRisks'] })
    },
    onError: (error: any) => {
      message.error(`刷新失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  // ── 统计 ─────────────────────────────────────────────
  const stats = {
    total:         patrols.length,
    inProgress:    patrols.filter(p => p.status === 'in_progress').length,
    completed:     patrols.filter(p => p.status === 'completed').length,
    highRiskAreas: areaRisks.filter(a => a.risk_level === 'high' || a.risk_level === 'critical').length,
  }

  // 当前时间线百分比
  const now = dayjs()
  const nowPercent = timeToPercent(now.hour(), now.minute())

  // Modal 通用样式
  const modalStyles = {
    content: { background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 0 },
    header:  { background: 'var(--bg-1)', borderBottom: '1px solid var(--line)' },
    footer:  { borderTop: '1px solid var(--line)' },
    body:    { paddingTop: 16 },
  }

  return (
    <div className="page-patrol">

      {/* ── 页面标题 ── */}
      <div className="page-title">
        <h1>巡逻部署</h1>
        <div className="sub">
          PATROL COMMAND ·{' '}
          {stats.inProgress} 路在编 · 今日 {stats.total} 班次 ·
          高风险区域 {stats.highRiskAreas}
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
          <button className="btn-ghost" onClick={() => refreshRisksMutation.mutate()} disabled={refreshRisksMutation.isPending}>
            {refreshRisksMutation.isPending ? <SyncOutlined spin /> : '刷新风险'}
          </button>
          <button
            className="btn-primary"
            onClick={() => setCreateModalVisible(true)}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <PlusOutlined />
            派遣新任务
          </button>
        </div>
      </div>

      {/* ── 加载中 ── */}
      {isLoading && (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin />
        </div>
      )}

      {/* ── 主布局：左列班组 / 右列三卡堆叠 ── */}
      {!isLoading && (
        <div className="patrol-grid">

          {/* ① 巡逻班组花名册 */}
          <div className="card">
            <div className="card-head">
              <span className="ico">◎</span>
              <span className="ti">巡逻班组 · 当前状态</span>
              <span className="spacer" />
              <span className="chip live">
                <span className="dot" />实时
              </span>
            </div>
            <div className="card-body scroll">
              {patrols.length === 0 ? (
                <div className="empty-state">
                  <div className="icon"><EnvironmentOutlined /></div>
                  <div>暂无巡逻班组</div>
                </div>
              ) : (
                patrols.map(p => {
                  const sCls = squadClass(p.status)
                  const sInfo = STATUS_MAP[p.status] ?? { cls: 'off', text: p.status }
                  return (
                    <div key={p.id} className={`squad-row ${sCls}`}>
                      {/* ID 徽章 */}
                      <div className="sq-id">{p.patrol_number}</div>

                      {/* 人员信息 */}
                      <div className="sq-members">
                        <div className="sq-ct">{p.officer_count} 人</div>
                        <div className="sq-names">{p.officer_names || '—'}</div>
                      </div>

                      {/* 区域 */}
                      <div className="sq-area">
                        {p.area_name}
                        {p.patrol_type && (
                          <span style={{ marginLeft: 6, color: 'var(--ink-3)', fontSize: 10 }}>
                            {TYPE_MAP[p.patrol_type] ?? p.patrol_type}
                          </span>
                        )}
                      </div>

                      {/* 状态 */}
                      <div className="sq-status">
                        <div className="sq-st">
                          {sInfo.icon}{sInfo.text}
                          {p.start_time && ` · ${dayjs().diff(dayjs(p.start_time), 'minute')}m`}
                        </div>
                        <div className="sq-loc">
                          {p.start_time
                            ? dayjs(p.start_time).format('HH:mm') + ' 开始'
                            : '等待出发'}
                          {p.issues_found > 0 && (
                            <span style={{ marginLeft: 8, color: 'var(--warn)' }}>
                              ⚠ {p.issues_found} 问题
                            </span>
                          )}
                        </div>
                      </div>

                      {/* 操作 */}
                      <div className="sq-action">
                        <button
                          className="btn-ghost-sm"
                          onClick={() => { setSelectedPatrol(p); setDetailModalVisible(true) }}
                        >
                          详情
                        </button>
                        {p.status === 'planned' && (
                          <button
                            className="patrol-action-btn patrol-action-btn--accent"
                            onClick={() => startMutation.mutate(p.id)}
                          >
                            <PlayCircleOutlined style={{ marginRight: 3 }} />
                            出发
                          </button>
                        )}
                        {p.status === 'in_progress' && (
                          <>
                            <button className="btn-ghost-sm">呼叫</button>
                            <button
                              className="patrol-action-btn patrol-action-btn--green"
                              onClick={() => { setSelectedPatrol(p); setCompleteModalVisible(true) }}
                            >
                              <CheckCircleOutlined style={{ marginRight: 3 }} />
                              回传
                            </button>
                          </>
                        )}
                        {p.status === 'completed' && (
                          <button className="btn-ghost-sm">报告</button>
                        )}
                        {(p.status === 'planned' || p.status === 'in_progress') && (
                          <Popconfirm title="确定取消此巡逻？" onConfirm={() => cancelMutation.mutate(p.id)}>
                            <button className="patrol-action-btn patrol-action-btn--danger">
                              取消
                            </button>
                          </Popconfirm>
                        )}
                        {p.status === 'off' || p.status === 'cancelled' ? (
                          <button
                            className="btn-ghost-sm"
                            onClick={() => {
                              createForm.setFieldsValue({ area_name: p.area_name })
                              setCreateModalVisible(true)
                            }}
                          >
                            调派
                          </button>
                        ) : null}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* ② ③ ④ 右列：时间线 + 覆盖热力 + AI建议 堆叠 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gap)' }}>

            {/* ② 今日排班时间线 */}
            <div className="card">
              <div className="card-head">
                <span className="ico">⏱</span>
                <span className="ti">今日排班时间线</span>
                <span className="spacer" />
                <span className="chip">24h</span>
              </div>
              <div className="card-body pad" style={{ padding: '18px 20px 14px' }}>
                <ScheduleTimeline patrols={patrols} nowPercent={nowPercent} />
              </div>
            </div>

            {/* ③ 巡逻覆盖热力图 */}
            <div className="card">
              <div className="card-head">
                <span className="ico">◈</span>
                <span className="ti">巡逻覆盖热力</span>
                <span className="spacer" />
                <span className="chip">近 7 天</span>
              </div>
              <div className="card-body pad" style={{ padding: 16 }}>
                <CoverageHeatmap patrols={patrols} />
              </div>
            </div>

            {/* ④ AI 部署建议 */}
            <div className="card">
              <div className="card-head">
                <span className="ico">⚡</span>
                <span className="ti">AI 部署建议</span>
                <span className="spacer" />
                <span className="chip accent">基于最新研判</span>
              </div>
              <div className="card-body pad" style={{ padding: 16 }}>
                {risksLoading ? (
                  <div style={{ textAlign: 'center', padding: 24 }}>
                    <Spin size="small" />
                  </div>
                ) : (
                  <AIRecommendations
                    areaRisks={areaRisks}
                    onAdopt={adoptAreaRisk}
                    isAdopting={createMutation.isPending}
                  />
                )}
              </div>
            </div>

            {/* ⑤ 智能调度分析 */}
            <div className="card">
              <div className="card-head">
                <span className="ico">⚡</span>
                <span className="ti">智能调度分析</span>
                <span className="spacer" />
                <span className="chip accent">动态时段 · TSP 路线</span>
              </div>
              <div className="card-body pad" style={{ padding: 16 }}>
                <SmartDispatchPanel
                  schedule={smartSchedule}
                  optimized={optimizedRoutes}
                  casePlan={caseDrivenPlan}
                  scheduleLoading={scheduleLoading}
                  optimizedLoading={optimizedLoading}
                  casePlanLoading={casePlanLoading}
                />
              </div>
            </div>

          </div>

        </div>
      )}

      {/* ── 区域风险表（折叠显示在底部） ── */}
      {areaRisks.length > 0 && (
        <div className="card" style={{ marginTop: 'var(--gap)' }}>
          <div className="card-head">
            <span className="ico"><WarningOutlined /></span>
            <span className="ti">区域风险评分</span>
            <span className="spacer" />
            <button
              className="btn-ghost-sm"
              onClick={() => refreshRisksMutation.mutate()}
              disabled={refreshRisksMutation.isPending}
            >
              <SyncOutlined spin={refreshRisksMutation.isPending} style={{ marginRight: 3 }} />
              刷新
            </button>
          </div>
          <div className="card-body">
            <table className="data">
              <thead>
                <tr>
                  <th>区域名称</th>
                  <th>风险等级</th>
                  <th style={{ width: 160 }}>风险评分</th>
                  <th>30天案件</th>
                  <th>30天巡逻</th>
                  <th>上次巡逻</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {areaRisks.map(area => {
                  const rColor = RISK_COLOR[area.risk_level] ?? 'var(--ink-3)'
                  const rLabel = RISK_LABEL[area.risk_level] ?? area.risk_level
                  const daysAgo = area.days_since_patrol ?? null
                  const dColor = daysAgo == null ? 'var(--warn)'
                    : daysAgo > 14 ? 'var(--err)'
                    : daysAgo > 7  ? 'var(--warn)'
                    : 'var(--ok)'
                  return (
                    <tr key={area.id}>
                      <td style={{ color: 'var(--ink-0)', fontWeight: 500 }}>{area.area_name}</td>
                      <td>
                        <span className="patrol-risk-tag" style={{ color: rColor, borderColor: rColor }}>
                          {rLabel}
                        </span>
                      </td>
                      <td>
                        <Progress
                          percent={area.risk_score}
                          size="small"
                          status={area.risk_score >= 80 ? 'exception' : area.risk_score >= 60 ? 'active' : 'success'}
                          format={p => `${p?.toFixed(0)}`}
                        />
                      </td>
                      <td style={{ fontFamily: 'var(--mono)' }}>{area.case_count_30d}</td>
                      <td style={{ fontFamily: 'var(--mono)' }}>{area.patrol_count_30d}</td>
                      <td>
                        {area.last_patrol_date ? (
                          <Space>
                            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-2)' }}>
                              {dayjs(area.last_patrol_date).format('MM-DD')}
                            </span>
                            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: dColor }}>
                              {daysAgo}天前
                            </span>
                          </Space>
                        ) : (
                          <span style={{ color: 'var(--warn)', fontFamily: 'var(--mono)', fontSize: 11 }}>从未巡逻</span>
                        )}
                      </td>
                      <td>
                        <button
                          className="patrol-action-btn patrol-action-btn--cyan"
                          onClick={() => {
                            createForm.setFieldsValue({ area_name: area.area_name })
                            setCreateModalVisible(true)
                          }}
                        >
                          创建巡逻
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── AI 巡逻路线规划地图 ── */}
      {!isLoading && (
        <PatrolRouteMap
          areaRisks={areaRisks}
          hotspots={rawHotspots as HotspotData[]}
          keyLocations={keyLocations}
        />
      )}

      {/* ── 创建巡逻 Modal ── */}
      <Modal
        title={
          <span style={{ fontFamily: 'var(--mono)', color: 'var(--accent)', fontSize: 13, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
            派遣新任务
          </span>
        }
        open={createModalVisible}
        onOk={() => createForm.submit()}
        onCancel={() => {
          setCreateModalVisible(false)
          createForm.resetFields()
          setPrefillRelatedCaseIds(undefined)
        }}
        confirmLoading={createMutation.isPending}
        styles={modalStyles}
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={(values: PatrolCreate) => createMutation.mutate({
            ...values,
            related_case_ids: prefillRelatedCaseIds,
          })}
        >
          <Form.Item
            name="area_name"
            label={<span style={{ color: 'var(--ink-2)', fontSize: 12 }}>巡逻区域</span>}
            rules={[{ required: true, message: '请输入巡逻区域' }]}
          >
            <Input placeholder="如：XX路段、XX小区周边" />
          </Form.Item>
          <Form.Item
            name="patrol_type"
            label={<span style={{ color: 'var(--ink-2)', fontSize: 12 }}>巡逻类型</span>}
            initialValue="routine"
          >
            <Select>
              <Option value="routine">日常巡逻</Option>
              <Option value="targeted">重点巡逻</Option>
              <Option value="emergency">紧急巡逻</Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="officer_count"
            label={<span style={{ color: 'var(--ink-2)', fontSize: 12 }}>巡逻人数</span>}
            initialValue={2}
          >
            <InputNumber min={1} max={20} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="officer_names"
            label={<span style={{ color: 'var(--ink-2)', fontSize: 12 }}>巡逻人员</span>}
          >
            <Input placeholder="多人用逗号分隔" />
          </Form.Item>
        </Form>
      </Modal>

      {/* ── 完成巡逻 Modal ── */}
      <Modal
        title={
          <span style={{ fontFamily: 'var(--mono)', color: 'var(--ok)', fontSize: 13, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
            完成巡逻 · 回传反馈
          </span>
        }
        open={completeModalVisible}
        onOk={() => completeForm.submit()}
        onCancel={() => {
          setCompleteModalVisible(false)
          completeForm.resetFields()
          setSelectedPatrol(null)
        }}
        confirmLoading={completeMutation.isPending}
        width={600}
        styles={modalStyles}
      >
        <Form
          form={completeForm}
          layout="vertical"
          onFinish={(values: PatrolComplete) => {
            if (selectedPatrol) {
              completeMutation.mutate({ id: selectedPatrol.id, data: values })
            }
          }}
        >
          <Form.Item
            name="findings"
            label={<span style={{ color: 'var(--ink-2)', fontSize: 12 }}>巡逻发现</span>}
          >
            <TextArea rows={3} placeholder="描述巡逻过程中的发现情况" />
          </Form.Item>
          <Form.Item
            name="issues_found"
            label={<span style={{ color: 'var(--ink-2)', fontSize: 12 }}>发现问题数量</span>}
            initialValue={0}
          >
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="actions_taken"
            label={<span style={{ color: 'var(--ink-2)', fontSize: 12 }}>采取措施</span>}
          >
            <TextArea rows={2} placeholder="描述针对发现问题采取的措施" />
          </Form.Item>
          <Form.Item
            name="effectiveness_score"
            label={<span style={{ color: 'var(--ink-2)', fontSize: 12 }}>巡逻效果评分</span>}
          >
            <Rate count={5} allowHalf />
            <span style={{ marginLeft: 8, color: 'var(--ink-3)', fontSize: 11 }}>（5星=100分）</span>
          </Form.Item>
          <Form.Item
            name="feedback_notes"
            label={<span style={{ color: 'var(--ink-2)', fontSize: 12 }}>反馈备注</span>}
          >
            <TextArea rows={2} placeholder="其他需要记录的信息" />
          </Form.Item>
        </Form>
      </Modal>

      {/* ── 详情 Modal ── */}
      <Modal
        title={
          <span style={{ fontFamily: 'var(--mono)', color: 'var(--accent)', fontSize: 13, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
            巡逻详情
          </span>
        }
        open={detailModalVisible}
        onCancel={() => { setDetailModalVisible(false); setSelectedPatrol(null) }}
        footer={null}
        width={700}
        styles={modalStyles}
      >
        {selectedPatrol && (
          <div className="patrol-detail">
            {/* 基本信息 */}
            <div className="patrol-detail-section">
              <div className="section-head">基本信息</div>
              <div className="patrol-detail-grid">
                {[
                  { label: '巡逻编号', value: selectedPatrol.patrol_number, mono: true, color: 'var(--accent)' },
                  { label: '状态',     value: (
                    <span className="patrol-status-tag"
                      style={{ color: STATUS_MAP[selectedPatrol.status]?.cls === 'on' ? 'var(--ok)' : 'var(--ink-2)' }}>
                      {STATUS_MAP[selectedPatrol.status]?.text ?? selectedPatrol.status}
                    </span>
                  )},
                  { label: '区域',     value: selectedPatrol.area_name },
                  { label: '类型',     value: TYPE_MAP[selectedPatrol.patrol_type] ?? selectedPatrol.patrol_type },
                  { label: '巡逻人数', value: selectedPatrol.officer_count, mono: true },
                  { label: '巡逻人员', value: selectedPatrol.officer_names || '—' },
                  { label: '开始时间', value: selectedPatrol.start_time ? dayjs(selectedPatrol.start_time).format('YYYY-MM-DD HH:mm') : '—', mono: true, small: true },
                  { label: '结束时间', value: selectedPatrol.end_time   ? dayjs(selectedPatrol.end_time).format('YYYY-MM-DD HH:mm') : '—', mono: true, small: true },
                ].map(({ label, value, mono, color, small }) => (
                  <div key={label} className="patrol-detail-item">
                    <div className="patrol-detail-label">{label}</div>
                    <div
                      className="patrol-detail-value"
                      style={{
                        fontFamily: mono ? 'var(--mono)' : undefined,
                        color: color ?? undefined,
                        fontSize: small ? 12 : undefined,
                      }}
                    >
                      {value}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* 风险变化 */}
            <div className="patrol-detail-section">
              <div className="section-head">风险评分变化</div>
              <div className="patrol-detail-grid">
                <div className="patrol-detail-item">
                  <div className="patrol-detail-label">巡逻前风险</div>
                  <div className="patrol-detail-value" style={{ fontFamily: 'var(--mono)' }}>
                    {selectedPatrol.risk_before != null ? selectedPatrol.risk_before.toFixed(1) : '—'}
                  </div>
                </div>
                <div className="patrol-detail-item">
                  <div className="patrol-detail-label">巡逻后风险</div>
                  <div className="patrol-detail-value" style={{ fontFamily: 'var(--mono)' }}>
                    {selectedPatrol.risk_after != null ? selectedPatrol.risk_after.toFixed(1) : '—'}
                  </div>
                </div>
                <div className="patrol-detail-item">
                  <div className="patrol-detail-label">发现问题</div>
                  <div className="patrol-detail-value" style={{
                    fontFamily: 'var(--mono)',
                    color: selectedPatrol.issues_found > 0 ? 'var(--warn)' : 'var(--ink-2)',
                  }}>
                    {selectedPatrol.issues_found}
                  </div>
                </div>
                <div className="patrol-detail-item">
                  <div className="patrol-detail-label">效果评分</div>
                  <div className="patrol-detail-value">
                    {selectedPatrol.effectiveness_score != null
                      ? <Rate disabled value={selectedPatrol.effectiveness_score / 20} allowHalf />
                      : '—'}
                  </div>
                </div>
              </div>
            </div>

            {/* 巡逻反馈 */}
            <div className="patrol-detail-section">
              <div className="section-head">巡逻反馈</div>
              <Descriptions
                column={1}
                size="small"
                styles={{
                  label: { color: 'var(--ink-3)', width: 90, fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase' },
                  content: { color: 'var(--ink-1)' },
                }}
              >
                <Descriptions.Item label="巡逻发现">{selectedPatrol.findings || '—'}</Descriptions.Item>
                <Descriptions.Item label="采取措施">{selectedPatrol.actions_taken || '—'}</Descriptions.Item>
                <Descriptions.Item label="反馈备注">{selectedPatrol.feedback_notes || '—'}</Descriptions.Item>
              </Descriptions>
            </div>
          </div>
        )}
      </Modal>

    </div>
  )
}

export default Patrols
