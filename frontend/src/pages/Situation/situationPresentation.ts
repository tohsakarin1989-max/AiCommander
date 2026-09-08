import type {
  SituationOverview,
  SituationPriority,
  SituationSummary,
  SituationTimelinePoint,
} from '../../services/situation'


interface SituationMapDatum {
  name?: string
  value?: number[]
  coords?: number[][]
  detail?: string
  wellName?: string
  caseNumber?: string
  caseCount?: number
  [key: string]: unknown
}

interface SituationMapSeries {
  name: string
  data: SituationMapDatum[]
  [key: string]: unknown
}

export interface SituationMapOption {
  series: SituationMapSeries[]
  [key: string]: unknown
}


export function getChangePresentation(summary: SituationSummary) {
  if (summary.case_delta > 0) {
    return { label: `较上一窗口增加 ${summary.case_delta} 起`, tone: 'up' }
  }
  if (summary.case_delta < 0) {
    return { label: `较上一窗口减少 ${Math.abs(summary.case_delta)} 起`, tone: 'down' }
  }
  return { label: '与上一窗口持平', tone: 'stable' }
}

export function getPriorityPresentation(priority: SituationPriority) {
  const levelLabels = {
    high: '优先关注',
    medium: '建议关注',
    low: '一般参考',
  }
  return {
    levelLabel: levelLabels[priority.level],
    tone: priority.level,
    actionLabel: '建议核查',
  }
}

export function buildTrendOption(timeline: SituationTimelinePoint[]) {
  const points = [...timeline].sort((a, b) => a.date.localeCompare(b.date))
  const labels = points.map(item => item.date.slice(5))
  return {
    animationDuration: 550,
    tooltip: {
      trigger: 'axis',
      renderMode: 'richText',
    },
    legend: {
      right: 8,
      top: 0,
      textStyle: { color: '#8f9dad', fontSize: 10 },
      data: ['上一窗口', '当前窗口'],
    },
    grid: { left: 34, right: 16, top: 36, bottom: 28 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: '#2a3544' } },
      axisTick: { show: false },
      axisLabel: { color: '#718096', fontSize: 9 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#1d2835', type: 'dashed' } },
      axisLabel: { color: '#718096', fontSize: 9 },
    },
    series: [
      {
        name: '上一窗口',
        type: 'bar',
        barMaxWidth: 12,
        data: points.map(item => item.period === 'previous' ? item.count : null),
        itemStyle: { color: '#445569' },
      },
      {
        name: '当前窗口',
        type: 'bar',
        barMaxWidth: 12,
        data: points.map(item => item.period === 'current' ? item.count : null),
        itemStyle: { color: '#45d9c0' },
      },
    ],
  }
}

export function buildSituationMapOption(overview: SituationOverview): SituationMapOption {
  const caseById = new Map(overview.case_points.map(item => [item.id, item]))
  const referenceLines = overview.well_attention.flatMap((well) => {
    const linked = well.case_ids
      .map(caseId => caseById.get(caseId))
      .filter((item): item is NonNullable<typeof item> => Boolean(item))
    const nearest = linked[0]
    return nearest ? [{
      coords: [
        [well.longitude, well.latitude],
        [nearest.longitude, nearest.latitude],
      ],
      wellName: well.name,
      caseNumber: nearest.case_number,
    }] : []
  })
  return {
    animationDuration: 700,
    tooltip: {
      trigger: 'item',
      renderMode: 'richText',
      formatter: (params: { seriesName?: string; data?: { name?: string; detail?: string; wellName?: string; caseNumber?: string } }) => {
        const data = params.data ?? {}
        if (params.seriesName === '案件—井点参考线') {
          return `${data.wellName ?? '井点'} → ${data.caseNumber ?? '案件'}\n空间接近仅作核查参考`
        }
        return `${data.name ?? params.seriesName ?? ''}${data.detail ? `\n${data.detail}` : ''}`
      },
    },
    grid: { left: 46, right: 24, top: 24, bottom: 42 },
    xAxis: {
      name: '经度',
      type: 'value',
      scale: true,
      nameTextStyle: { color: '#66778a', fontSize: 9 },
      axisLabel: { color: '#66778a', fontSize: 9 },
      splitLine: { lineStyle: { color: '#1d2b39', type: 'dashed' } },
    },
    yAxis: {
      name: '纬度',
      type: 'value',
      scale: true,
      nameTextStyle: { color: '#66778a', fontSize: 9 },
      axisLabel: { color: '#66778a', fontSize: 9 },
      splitLine: { lineStyle: { color: '#1d2b39', type: 'dashed' } },
    },
    series: [
      {
        name: '案件',
        type: 'scatter',
        symbol: 'diamond',
        symbolSize: 11,
        z: 4,
        data: overview.case_points.map(item => ({
          name: item.case_number,
          value: [item.longitude, item.latitude],
          detail: `${item.case_type} · ${item.occurred_time.slice(5, 16).replace('T', ' ')}`,
          itemStyle: { color: '#ffca63', borderColor: '#fff0c8', borderWidth: 1 },
        })),
      },
      {
        name: '历史聚集热点',
        type: 'effectScatter',
        rippleEffect: { scale: 2.4, brushType: 'stroke' },
        symbolSize: (_value: number[], params: { data?: { caseCount?: number } }) => 22 + (params.data?.caseCount ?? 1) * 3,
        z: 2,
        data: overview.hotspots.map(item => ({
          name: item.label,
          value: [item.center.longitude, item.center.latitude],
          caseCount: item.case_count,
          detail: `${item.case_count}起 · 较上期${item.case_delta >= 0 ? '+' : ''}${item.case_delta}起`,
          itemStyle: { color: 'rgba(255, 91, 91, 0.48)', borderColor: '#ff6969', borderWidth: 2 },
        })),
      },
      {
        name: '重点井参考',
        type: 'scatter',
        symbol: 'pin',
        symbolSize: 28,
        z: 5,
        data: overview.well_attention.map(item => ({
          name: item.name,
          value: [item.longitude, item.latitude],
          detail: `${item.is_high_production ? '高产井 · ' : ''}周边${item.nearby_case_count}起 · 关注度${item.attention_score}`,
          itemStyle: { color: item.verified ? '#4fd8ff' : '#718096' },
        })),
      },
      {
        name: '案件—井点参考线',
        type: 'lines',
        coordinateSystem: 'cartesian2d',
        polyline: false,
        silent: false,
        z: 1,
        data: referenceLines,
        lineStyle: { color: '#4fd8ff', width: 1, opacity: 0.38, type: 'dashed' },
        effect: { show: true, symbol: 'circle', symbolSize: 3, period: 5, color: '#4fd8ff' },
      },
    ],
  }
}

export function buildBriefMarkdown(overview: SituationOverview) {
  const missingBoundary = overview.boundary.statements.filter(
    statement => !overview.brief.markdown.includes(statement),
  )
  if (!missingBoundary.length) return overview.brief.markdown
  return [
    overview.brief.markdown.trim(),
    '',
    '## 使用边界',
    ...missingBoundary.map(item => `- ${item}`),
  ].join('\n')
}
