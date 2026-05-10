import type { AreaRisk, Case, ChainLink, ChainPosition } from '../../types'
import { chainPositionMeta, getChainPosition } from '../../utils/chainType'

const DAY_MS = 86_400_000
const LAT_MIN = 44.5
const LAT_MAX = 48.0
const LNG_MIN = 122.5
const LNG_MAX = 127.5
const SVG_W = 1200
const SVG_H = 800
const SVG_PAD = 30

export interface DashboardStatisticsLike {
  total_cases?: number
  today_cases?: number
  pending_cases?: number
  resolved_cases?: number
  this_week_cases?: number
  this_month_cases?: number
}

export interface DashboardHotspot {
  center?: { latitude?: number | null; longitude?: number | null }
  center_latitude?: number | null
  center_longitude?: number | null
  case_count?: number
  radius_km?: number
}

export type DashboardItemTone = 'normal' | 'hot' | 'ai' | 'empty' | 'warn' | 'good'

export interface DashboardListItem {
  title: string
  detail: string
  tone?: DashboardItemTone
}

export interface DashboardKpi {
  label: string
  value: string
  detail: string
  tone?: DashboardItemTone
}

export interface TrendBucket {
  label: string
  count: number
  height: number
  tone: 'normal' | 'hot' | 'warn'
}

export interface DashboardFocusCard {
  label: string
  value: string
}

export interface DashboardMapPoint {
  id: number
  caseNumber: string
  x: number
  y: number
  chainPosition: ChainPosition
  label: string
  color: string
  shape: string
}

export interface ProjectedChainLine {
  id: number
  status: Exclude<ChainLink['status'], 'rejected'>
  confidence: number
  distanceKm: number
  timeDiffDays: number
  fromX: number
  fromY: number
  toX: number
  toY: number
  fromLabel: string
  toLabel: string
}

export interface DashboardSourceStats {
  coordinateCount: number
  missingCoordinateCount: number
  hotspotCount: number
  chainLineCount: number
}

export interface DashboardModel {
  kpis: {
    monthlyCases: DashboardKpi
    highRiskAreas: DashboardKpi
    chainInferences: DashboardKpi
    aiOutputs: DashboardKpi
    materialReadiness: DashboardKpi
  }
  weeklyTrend: TrendBucket[]
  riskChanges: DashboardListItem[]
  materialTrends: DashboardListItem[]
  aiOutputs: DashboardListItem[]
  reviewItems: DashboardListItem[]
  qualityItems: DashboardListItem[]
  focusCards: DashboardFocusCard[]
  mapPoints: DashboardMapPoint[]
  chainLines: ProjectedChainLine[]
  sourceStats: DashboardSourceStats
}

export interface DashboardModelInput {
  cases: Case[]
  chainLinks: ChainLink[]
  areaRisks: AreaRisk[]
  hotspots: DashboardHotspot[]
  statistics: DashboardStatisticsLike
  now?: Date
}

function latLngToSvg(lat: number, lng: number): [number, number] {
  const x = SVG_PAD + ((lng - LNG_MIN) / (LNG_MAX - LNG_MIN)) * (SVG_W - SVG_PAD * 2)
  const y = SVG_H - SVG_PAD - ((lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * (SVG_H - SVG_PAD * 2)
  return [Number(x.toFixed(1)), Number(y.toFixed(1))]
}

function isValidCoordinate(lat?: number | null, lng?: number | null): lat is number {
  return (
    typeof lat === 'number'
    && typeof lng === 'number'
    && Number.isFinite(lat)
    && Number.isFinite(lng)
    && lat >= LAT_MIN
    && lat <= LAT_MAX
    && lng >= LNG_MIN
    && lng <= LNG_MAX
  )
}

function countMissingRequired(caseItem: Case): number {
  return caseItem.quality_issues?.missing_required?.length ?? 0
}

function listItem(title: string, detail: string, tone: DashboardItemTone = 'normal'): DashboardListItem {
  return { title, detail, tone }
}

function ensureRows(items: DashboardListItem[], fallback: DashboardListItem[], minRows = 3): DashboardListItem[] {
  const rows = [...items]
  for (const item of fallback) {
    if (rows.length >= minRows) break
    if (!rows.some(row => row.title === item.title)) rows.push(item)
  }
  return rows.length > 0 ? rows : [listItem('暂无数据', '等待案件、链条或材料数据接入。', 'empty')]
}

export function buildWeeklyTrend(cases: Case[], now = new Date()): TrendBucket[] {
  const buckets = Array.from({ length: 7 }, (_, index) => ({
    label: `W${index + 1}`,
    count: 0,
  }))

  cases.forEach(caseItem => {
    const occurred = new Date(caseItem.occurred_time)
    if (Number.isNaN(occurred.getTime())) return
    const diffDays = Math.floor((now.getTime() - occurred.getTime()) / DAY_MS)
    if (diffDays < 0 || diffDays >= 49) return
    const bucketIndex = 6 - Math.floor(diffDays / 7)
    buckets[bucketIndex].count += 1
  })

  const max = Math.max(...buckets.map(item => item.count), 1)
  return buckets.map((item, index, all) => {
    const previous = index > 0 ? all[index - 1].count : item.count
    const rising = item.count > previous && item.count > 0
    return {
      ...item,
      height: Math.max(18, Math.round((item.count / max) * 100)),
      tone: rising ? 'hot' : item.count === max && item.count > 0 ? 'warn' : 'normal',
    }
  })
}

export function projectChainLinks(links: ChainLink[]): ProjectedChainLine[] {
  return links
    .filter((link): link is ChainLink & { status: 'inferred' | 'confirmed' } => link.status !== 'rejected')
    .map(link => {
      const from = link.from_case
      const to = link.to_case
      if (!from || !to) return null
      if (!isValidCoordinate(from.latitude, from.longitude)) return null
      if (!isValidCoordinate(to.latitude, to.longitude)) return null
      const [fromX, fromY] = latLngToSvg(from.latitude, from.longitude!)
      const [toX, toY] = latLngToSvg(to.latitude, to.longitude!)
      return {
        id: link.id,
        status: link.status,
        confidence: link.confidence,
        distanceKm: link.distance_km,
        timeDiffDays: link.time_diff_days,
        fromX,
        fromY,
        toX,
        toY,
        fromLabel: from.case_number,
        toLabel: to.case_number,
      }
    })
    .filter((line): line is ProjectedChainLine => line !== null)
}

function buildMapPoints(cases: Case[]): DashboardMapPoint[] {
  return cases
    .filter(caseItem => isValidCoordinate(caseItem.latitude, caseItem.longitude))
    .map(caseItem => {
      const [x, y] = latLngToSvg(caseItem.latitude!, caseItem.longitude!)
      const chainPosition = getChainPosition(caseItem)
      const meta = chainPositionMeta[chainPosition]
      return {
        id: caseItem.id,
        caseNumber: caseItem.case_number,
        x,
        y,
        chainPosition,
        label: meta.shortLabel,
        color: meta.color,
        shape: meta.shape,
      }
    })
}

function buildRiskChanges(input: DashboardModelInput, coordinateCount: number, missingCoordinateCount: number): DashboardListItem[] {
  const topRisks = input.areaRisks
    .slice()
    .sort((a, b) => (b.risk_score ?? 0) - (a.risk_score ?? 0))
    .slice(0, 2)
    .map(area => listItem(
      `${area.area_name}风险${(area.risk_score ?? 0) >= 0.75 ? '升温' : '关注'}`,
      `近 7 天 ${area.case_count_7d ?? 0} 起，近 30 天 ${area.case_count_30d ?? 0} 起。`,
      (area.risk_score ?? 0) >= 0.75 ? 'hot' : 'warn',
    ))

  const fallback = [
    listItem('坐标案件可用于空间研判', `当前 ${coordinateCount} 起案件具备有效坐标。`, coordinateCount > 0 ? 'good' : 'empty'),
    listItem('缺坐标案件影响热点判断', `仍有 ${missingCoordinateCount} 起案件需补录位置。`, missingCoordinateCount > 0 ? 'warn' : 'good'),
    listItem('风险变化等待更多数据', '热点密度和夜间占比会随案件录入更新。', 'empty'),
  ]
  return ensureRows(topRisks, fallback)
}

function buildMaterialTrends(cases: Case[], missingCoordinateCount: number): DashboardListItem[] {
  if (cases.length === 0) {
    return [listItem('暂无案件材料数据', '录入案件后显示检斤含水、人员处理、车辆移交等缺口。', 'empty')]
  }
  const missingMaterialCases = cases.filter(caseItem => countMissingRequired(caseItem) > 0)
  const lowQualityCases = cases.filter(caseItem => typeof caseItem.quality_score === 'number' && caseItem.quality_score < 70)
  const readyCases = cases.length - missingMaterialCases.length
  return ensureRows([
    listItem('材料齐全可复核', `${Math.max(readyCases, 0)} 起案件关键材料已齐全。`, readyCases > 0 ? 'good' : 'warn'),
    listItem('关键佐证材料缺口', `${missingMaterialCases.length} 起案件存在必填材料缺口。`, missingMaterialCases.length > 0 ? 'hot' : 'good'),
    listItem('坐标补录影响空间研判', `${missingCoordinateCount} 起案件缺少有效坐标。`, missingCoordinateCount > 0 ? 'warn' : 'good'),
    listItem('低质量案件需复核', `${lowQualityCases.length} 起案件质量评分低于 70。`, lowQualityCases.length > 0 ? 'warn' : 'good'),
  ], [])
}

function buildAiOutputs(cases: Case[], chainLinks: ChainLink[]): DashboardListItem[] {
  const inferred = chainLinks.filter(link => link.status === 'inferred').length
  const confirmed = chainLinks.filter(link => link.status === 'confirmed').length
  const structured = cases.filter(caseItem => caseItem.features).length
  const items: DashboardListItem[] = []
  if (inferred || confirmed) {
    items.push(listItem('链条研判摘要', `推断 ${inferred} 条，已确认 ${confirmed} 条。`, 'ai'))
  }
  if (structured) {
    items.push(listItem('案件结构化结果', `${structured} 起案件已有结构化特征，可用于报告生成。`, 'ai'))
  }
  if (items.length === 0) {
    return [listItem('暂无本周 AI 产出', '等待圆桌报告、部署建议或经验卡统计接入。', 'empty')]
  }
  return ensureRows(items, [
    listItem('经验卡沉淀待接入', '接入经验卡统计后展示可复用建议数量。', 'empty'),
    listItem('部署建议待接入', '接入建议采纳状态后展示本周采纳情况。', 'empty'),
  ])
}

function buildReviewItems(cases: Case[], chainLinks: ChainLink[], missingCoordinateCount: number): DashboardListItem[] {
  const inferred = chainLinks.filter(link => link.status === 'inferred').length
  const materialBlocked = cases.filter(caseItem => countMissingRequired(caseItem) > 0).length
  const lowQuality = cases.filter(caseItem => typeof caseItem.quality_score === 'number' && caseItem.quality_score < 70).length
  return ensureRows([
    ...(inferred ? [listItem('链条推断待确认', `${inferred} 条按置信度和时间差排序。`, 'hot')] : []),
    ...(materialBlocked ? [listItem('材料复核待处理', `${materialBlocked} 起案件需先补齐关键材料。`, 'hot')] : []),
    ...(missingCoordinateCount ? [listItem('坐标补录待处理', `${missingCoordinateCount} 起案件影响空间聚类。`, 'warn')] : []),
    ...(lowQuality ? [listItem('低质量案件待复核', `${lowQuality} 起案件需补充事实或证据引用。`, 'warn')] : []),
  ], [
    listItem('暂无待复核事项', '当前链条、坐标和材料缺口未形成待办。', 'empty'),
    listItem('结论分层待接入', '事实、推断、建议确认入口接入后展示。', 'empty'),
    listItem('材料规则待校验', '材料清单变更后可在此提示复核。', 'empty'),
  ])
}

function buildQualityItems(cases: Case[]): DashboardListItem[] {
  const scored = cases.filter(caseItem => typeof caseItem.quality_score === 'number')
  if (scored.length === 0) {
    return [listItem('暂无质量指标', '等待案件质量、事实引用和推断采纳数据接入。', 'empty')]
  }
  const average = Math.round(scored.reduce((sum, item) => sum + (item.quality_score ?? 0), 0) / scored.length)
  const high = scored.filter(item => (item.quality_score ?? 0) >= 85).length
  const missing = cases.filter(item => countMissingRequired(item) > 0).length
  return ensureRows([
    listItem('案件质量均值', `已评分案件平均 ${average} 分。`, average >= 80 ? 'good' : 'warn'),
    listItem('高质量案件占比', `${high}/${scored.length} 起达到高质量标准。`, high > 0 ? 'good' : 'normal'),
    listItem('材料缺口命中', `${missing} 起案件存在明确材料缺口。`, missing > 0 ? 'warn' : 'good'),
  ], [])
}

function buildFocusCards(riskChanges: DashboardListItem[], chainLines: ProjectedChainLine[], missingCoordinateCount: number): DashboardFocusCard[] {
  const topChain = chainLines.slice().sort((a, b) => b.confidence - a.confidence)[0]
  return [
    { label: '重点区域', value: riskChanges[0]?.title.replace(/风险.*/, '') || '暂无' },
    { label: '重点链条', value: topChain ? `${topChain.fromLabel} → ${topChain.toLabel}` : '待形成' },
    { label: '待补数据', value: missingCoordinateCount > 0 ? `坐标 ${missingCoordinateCount} 起` : '暂无缺口' },
  ]
}

export function buildDashboardModel(input: DashboardModelInput): DashboardModel {
  const now = input.now ?? new Date()
  const cases = input.cases
  const chainLines = projectChainLinks(input.chainLinks)
  const mapPoints = buildMapPoints(cases)
  const coordinateCount = mapPoints.length
  const missingCoordinateCount = cases.filter(caseItem => !isValidCoordinate(caseItem.latitude, caseItem.longitude)).length
  const highRiskAreaCount = input.areaRisks.filter(area => (area.risk_score ?? 0) >= 0.7).length
  const inferredCount = input.chainLinks.filter(link => link.status === 'inferred').length
  const aiOutputs = buildAiOutputs(cases, input.chainLinks)
  const materialTrends = buildMaterialTrends(cases, missingCoordinateCount)
  const materialReadyCases = cases.filter(caseItem => countMissingRequired(caseItem) === 0 && isValidCoordinate(caseItem.latitude, caseItem.longitude)).length
  const materialValue = cases.length > 0
    ? `${Math.round((materialReadyCases / cases.length) * 100)}%`
    : '待补录'
  const riskChanges = buildRiskChanges(input, coordinateCount, missingCoordinateCount)
  const reviewItems = buildReviewItems(cases, input.chainLinks, missingCoordinateCount)
  const qualityItems = buildQualityItems(cases)

  return {
    kpis: {
      monthlyCases: {
        label: '本月案件',
        value: String(input.statistics.this_month_cases ?? cases.length),
        detail: input.statistics.today_cases ? `今日 +${input.statistics.today_cases}` : '来自案件统计',
        tone: 'normal',
      },
      highRiskAreas: {
        label: '高风险区域',
        value: String(highRiskAreaCount || input.areaRisks.length || '待评估'),
        detail: input.areaRisks.length ? `${input.areaRisks.length} 个区域纳入监测` : '等待风险区数据',
        tone: highRiskAreaCount > 0 ? 'warn' : 'empty',
      },
      chainInferences: {
        label: '链条推断',
        value: String(input.chainLinks.filter(link => link.status !== 'rejected').length),
        detail: inferredCount ? `${inferredCount} 条待确认` : '无待确认推断',
        tone: inferredCount > 0 ? 'warn' : 'good',
      },
      aiOutputs: {
        label: 'AI 报告产出',
        value: aiOutputs[0]?.tone === 'empty' ? '待接入' : String(aiOutputs.length),
        detail: aiOutputs[0]?.tone === 'empty' ? '暂无本周统计源' : '链条 / 结构化 / 报告',
        tone: aiOutputs[0]?.tone === 'empty' ? 'empty' : 'ai',
      },
      materialReadiness: {
        label: '材料齐全率',
        value: materialValue,
        detail: cases.length > 0 ? '案件材料相关' : '等待案件质量数据',
        tone: cases.length > 0 ? 'normal' : 'empty',
      },
    },
    weeklyTrend: buildWeeklyTrend(cases, now),
    riskChanges,
    materialTrends,
    aiOutputs,
    reviewItems,
    qualityItems,
    focusCards: buildFocusCards(riskChanges, chainLines, missingCoordinateCount),
    mapPoints,
    chainLines,
    sourceStats: {
      coordinateCount,
      missingCoordinateCount,
      hotspotCount: input.hotspots.length,
      chainLineCount: chainLines.length,
    },
  }
}
