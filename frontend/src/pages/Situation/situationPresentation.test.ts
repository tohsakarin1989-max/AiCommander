import { describe, expect, it } from 'vitest'

import type { SituationOverview } from '../../services/situation'
import {
  buildBriefMarkdown,
  buildSituationMapOption,
  buildTrendOption,
  getChangePresentation,
  getPriorityPresentation,
} from './situationPresentation'


const overview = (): SituationOverview => ({
  generated_at: '2026-09-10T12:00:00',
  as_of: '2026-09-10T12:00:00',
  window: {
    days: 14,
    current_start: '2026-08-27T12:00:00',
    current_end: '2026-09-10T12:00:00',
    previous_start: '2026-08-13T12:00:00',
    previous_end: '2026-08-27T12:00:00',
    area_keyword: '北区',
  },
  source_snapshot: { algorithm: 'sha256', data_version: 'abc123' },
  summary: {
    current_case_count: 3,
    previous_case_count: 1,
    case_delta: 2,
    case_delta_percent: 200,
    change_direction: 'rising',
    geocoded_case_count: 3,
    data_readiness_percent: 100,
    hotspot_count: 1,
    well_attention_count: 1,
    analysis_status: 'ready',
  },
  timeline: [
    { date: '2026-08-25', period: 'previous', count: 1 },
    { date: '2026-09-07', period: 'current', count: 1 },
    { date: '2026-09-08', period: 'current', count: 2 },
  ],
  pattern_shifts: {
    case_types: [{ name: '涉油盗窃', current_count: 3, previous_count: 1, delta: 2, direction: 'rising' }],
    modus_operandi: [{ name: '破坏阀门', current_count: 3, previous_count: 1, delta: 2, direction: 'rising' }],
    peak_hours: [{ hour: 2, count: 2 }],
  },
  case_points: [
    { id: 1, case_number: 'SIT-001', occurred_time: '2026-09-08T02:00:00', location: '北区井场', case_type: '涉油盗窃', modus_operandi: '破坏阀门', latitude: 46.6, longitude: 125.1 },
  ],
  hotspots: [
    { id: 'hotspot:1', label: '热点组 01', center: { latitude: 46.601, longitude: 125.101 }, case_count: 3, previous_case_count: 1, case_delta: 2, case_ids: [1], case_numbers: ['SIT-001'], dominant_case_type: '涉油盗窃', dominant_modus_operandi: '破坏阀门', latest_case_at: '2026-09-08T02:00:00', radius_km: 1.5, boundary: '历史聚集，不代表未来一定发生案件。' },
  ],
  well_attention: [
    { asset_id: 10, name: '北区高产井-01', latitude: 46.602, longitude: 125.102, verified: true, is_high_production: true, region: '北区', nearby_case_count: 3, previous_nearby_case_count: 1, case_delta: 2, minimum_distance_km: 0.2, latest_case_at: '2026-09-08T02:00:00', case_ids: [1], attention_score: 82, attention_level: 'high', reasons: ['限定半径内本期3起案件'], boundary: '空间接近不能证明案件与井点存在事实关联。' },
  ],
  priorities: [
    { id: 'priority:hotspot:1', rank: 1, type: 'hotspot_change', level: 'high', title: '北区热点新增聚集', finding: '本期3起，较上期增加2起。', action: '核对共同时间、作案手法和现场条件。', evidence_refs: ['case:1'], map_focus: { latitude: 46.601, longitude: 125.101 }, boundary: '仅作为人工研判入口。' },
  ],
  pipeline: [
    { step: 'scope', label: '锁定时间与区域', status: 'completed', result: '本期3起案件' },
  ],
  brief: {
    title: '双域态势研判简报',
    headline: '本期新增3起案件，较上一窗口增加2起。',
    facts: ['本期3起案件'],
    findings: ['形成1个历史聚集热点'],
    suggestions: ['优先核查北区热点'],
    markdown: '# 双域态势研判简报\n\n本期新增3起案件。',
  },
  boundary: {
    read_only: true,
    historical_association_only: true,
    statements: ['结果只用于人工研判，不代表犯罪预测。'],
  },
})


describe('situationPresentation', () => {
  it('presents growth as a historical-window change rather than a prediction', () => {
    expect(getChangePresentation(overview().summary)).toEqual({
      label: '较上一窗口增加 2 起',
      tone: 'up',
    })
  })

  it('builds two-window trend series with real dates', () => {
    const option = buildTrendOption(overview().timeline)

    expect(option.xAxis.data).toEqual(['08-25', '09-07', '09-08'])
    expect(option.series[0].data).toEqual([1, null, null])
    expect(option.series[1].data).toEqual([null, 1, 2])
  })

  it('builds an offline dual-domain coordinate view with cases hotspots and wells', () => {
    const option = buildSituationMapOption(overview())

    expect(option.series.map(item => item.name)).toEqual(['案件', '历史聚集热点', '重点井参考', '案件—井点参考线'])
    expect(option.series[0].data[0].value).toEqual([125.1, 46.6])
    expect(option.series[2].data[0].value).toEqual([125.102, 46.602])
    expect(option.series[3].data).toHaveLength(1)
  })

  it('keeps priority wording actionable but non-executing', () => {
    expect(getPriorityPresentation(overview().priorities[0])).toEqual({
      levelLabel: '优先关注',
      tone: 'high',
      actionLabel: '建议核查',
    })
  })

  it('exports the server brief with its business boundary', () => {
    const markdown = buildBriefMarkdown(overview())

    expect(markdown).toContain('本期新增3起案件')
    expect(markdown).toContain('结果只用于人工研判，不代表犯罪预测')
    expect(markdown).not.toContain('自动派遣')
  })
})
