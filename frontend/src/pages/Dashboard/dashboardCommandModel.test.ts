import { describe, expect, it } from 'vitest'
import type { AreaRisk, Case, ChainLink } from '../../types'
import {
  buildDashboardModel,
  buildWeeklyTrend,
  projectChainLinks,
} from './dashboardCommandModel'

const baseCase = (id: number, patch: Partial<Case>): Case => ({
  id,
  case_number: `CASE-${id}`,
  occurred_time: '2026-05-01T00:00:00.000Z',
  status: 'pending',
  ...patch,
})

const baseStatistics = {
  total_cases: 0,
  today_cases: 0,
  pending_cases: 0,
  resolved_cases: 0,
  this_week_cases: 0,
  this_month_cases: 0,
}

describe('dashboardCommandModel', () => {
  it('builds seven weekly trend buckets from real case dates', () => {
    const cases = [
      baseCase(1, { occurred_time: '2026-05-09T00:00:00.000Z' }),
      baseCase(2, { occurred_time: '2026-05-08T00:00:00.000Z' }),
      baseCase(3, { occurred_time: '2026-04-20T00:00:00.000Z' }),
    ]

    const trend = buildWeeklyTrend(cases, new Date('2026-05-10T00:00:00.000Z'))

    expect(trend).toHaveLength(7)
    expect(trend[6]).toMatchObject({ label: 'W7', count: 2 })
    expect(trend.some(item => item.count === 1)).toBe(true)
  })

  it('projects only non-rejected chain links with complete coordinates', () => {
    const link: ChainLink = {
      id: 1,
      case_id_a: 1,
      case_id_b: 2,
      link_type: 'upstream_transport',
      status: 'inferred',
      confidence: 0.82,
      distance_km: 3.5,
      time_diff_days: 4,
      from_case: {
        id: 1,
        case_number: 'A',
        chain_position: 'upstream',
        chain_label: '盗采环节',
        latitude: 46.6,
        longitude: 125.1,
      },
      to_case: {
        id: 2,
        case_number: 'B',
        chain_position: 'midstream',
        chain_label: '运输环节',
        latitude: 46.62,
        longitude: 125.12,
      },
    }

    const rejected: ChainLink = { ...link, id: 2, status: 'rejected' }
    const missingCoordinate: ChainLink = {
      ...link,
      id: 3,
      to_case: { ...link.to_case!, latitude: undefined },
    }

    const lines = projectChainLinks([link, rejected, missingCoordinate])

    expect(lines).toHaveLength(1)
    expect(lines[0]).toMatchObject({ id: 1, status: 'inferred', confidence: 0.82 })
  })

  it('creates empty-state dashboard lists instead of fake numbers when data is missing', () => {
    const model = buildDashboardModel({
      cases: [],
      chainLinks: [],
      areaRisks: [],
      hotspots: [],
      statistics: baseStatistics,
      now: new Date('2026-05-10T00:00:00.000Z'),
    })

    expect(model.kpis.materialReadiness.value).toBe('待补录')
    expect(model.aiOutputs[0].tone).toBe('empty')
    expect(model.qualityItems[0].tone).toBe('empty')
  })

  it('marks panels with enough display rows for unattended screen rotation', () => {
    const areaRisks: AreaRisk[] = [
      {
        id: 1,
        area_name: '萨中片区',
        risk_score: 0.82,
        case_count_7d: 4,
        case_count_30d: 11,
      } as AreaRisk,
    ]
    const model = buildDashboardModel({
      cases: [
        baseCase(1, { latitude: 46.6, longitude: 125.1, facility_type: '管线', quality_score: 91 }),
        baseCase(2, { latitude: 46.62, longitude: 125.12, facility_type: '油罐车', quality_score: 65 }),
      ],
      chainLinks: [],
      areaRisks,
      hotspots: [],
      statistics: { ...baseStatistics, total_cases: 2, pending_cases: 2, this_week_cases: 2, this_month_cases: 2 },
      now: new Date('2026-05-10T00:00:00.000Z'),
    })

    expect(model.riskChanges.length).toBeGreaterThanOrEqual(3)
    expect(model.materialTrends.length).toBeGreaterThanOrEqual(3)
  })

  it('spreads repeated case coordinates so command map points do not collapse into one dot', () => {
    const model = buildDashboardModel({
      cases: [
        baseCase(1, { latitude: 46.6, longitude: 125.1 }),
        baseCase(2, { latitude: 46.6, longitude: 125.1 }),
        baseCase(3, { latitude: 46.6, longitude: 125.1 }),
      ],
      chainLinks: [],
      areaRisks: [],
      hotspots: [],
      statistics: { ...baseStatistics, total_cases: 3, this_month_cases: 3 },
      now: new Date('2026-05-10T00:00:00.000Z'),
    })

    const uniquePositions = new Set(model.mapPoints.map(point => `${point.x}:${point.y}`))

    expect(model.mapPoints).toHaveLength(3)
    expect(uniquePositions.size).toBeGreaterThan(1)
  })

  it('uses structured case data as real AI outputs instead of pending placeholders', () => {
    const model = buildDashboardModel({
      cases: [
        baseCase(1, {
          latitude: 46.6,
          longitude: 125.1,
          description: '夜间巡护发现井场附近异常车辆停留，现场留有疑似盗采工具和新鲜车辙。',
          features: {
            summary: '井场周边异常停留',
            tags: ['偏远井场', '夜间时段'],
            management: {
              recommended_completion_actions: ['补充车辆移交材料'],
            },
          },
          quality_score: 88,
        }),
      ],
      chainLinks: [],
      areaRisks: [],
      hotspots: [],
      statistics: { ...baseStatistics, total_cases: 1, this_month_cases: 1 },
      now: new Date('2026-05-10T00:00:00.000Z'),
    })

    expect(model.kpis.aiOutputs.value).not.toBe('待接入')
    expect(model.aiOutputs.map(item => item.title)).toContain('经验卡沉淀')
    expect(model.aiOutputs.map(item => item.title)).toContain('结论分层初筛')
    expect(model.aiOutputs.some(item => item.detail.includes('待接入'))).toBe(false)
  })

  it('adds structured low-quality cases to conclusion review work queue', () => {
    const model = buildDashboardModel({
      cases: [
        baseCase(1, {
          features: { summary: '已有结构化摘要', tags: ['运输车辆'] },
          quality_score: 58,
          quality_issues: {
            score: 58,
            level: 'low',
            category_scores: {},
            facts: {},
            missing_required: [{ field: 'source_type', label: '线索来源', reason: '缺少线索来源' }],
            warnings: [],
            recommendations: [],
          },
        }),
      ],
      chainLinks: [],
      areaRisks: [],
      hotspots: [],
      statistics: { ...baseStatistics, total_cases: 1, this_month_cases: 1 },
      now: new Date('2026-05-10T00:00:00.000Z'),
    })

    expect(model.reviewItems.map(item => item.title)).toContain('结论分层待确认')
    expect(model.reviewItems.find(item => item.title === '结论分层待确认')?.detail).toContain('1 起')
  })

  it('includes digital automation alert triage packs in AI outputs and review queue', () => {
    const model = buildDashboardModel({
      cases: [],
      chainLinks: [],
      areaRisks: [],
      hotspots: [],
      automationAlerts: [
        {
          id: 1,
          status: 'pending',
          risk_level: 'high',
          ai_assessment: { result: '建议人工核查', confidence: 0.74 },
          suggested_actions: ['调阅云台视频'],
        },
      ],
      statistics: baseStatistics,
      now: new Date('2026-05-10T00:00:00.000Z'),
    })

    expect(model.aiOutputs.map(item => item.title)).toContain('数智告警研判包')
    expect(model.reviewItems.map(item => item.title)).toContain('数智告警待核查')
  })

  it('labels every top metric with a stable business scope', () => {
    const model = buildDashboardModel({
      cases: [
        baseCase(1, { latitude: 46.6, longitude: 125.1, quality_score: 90 }),
      ],
      chainLinks: [],
      areaRisks: [],
      hotspots: [],
      statistics: { ...baseStatistics, total_cases: 1, this_month_cases: 1 },
      now: new Date('2026-05-10T00:00:00.000Z'),
    })

    Object.values(model.kpis).forEach((kpi) => {
      expect(kpi.scope).toMatch(/^(本月|近30天|近7周|全量)/)
      expect(kpi.detail).not.toContain('来自案件统计')
    })
    expect(model.kpis.monthlyCases.scope).toBe('本月')
    expect(model.kpis.materialReadiness.scope).toBe('全量案件')
  })

  it('uses report and conclusion draft status as AI output production signals', () => {
    const model = buildDashboardModel({
      cases: [],
      chainLinks: [],
      areaRisks: [],
      hotspots: [],
      reports: [
        {
          id: 1,
          draft_status: 'draft',
          review_status: 'pending_review',
          model_status: 'deterministic_fallback',
        },
      ],
      conclusions: [
        {
          id: 2,
          case_id: 10,
          status: 'needs_review',
          draft_status: 'draft',
          review_status: 'pending_review',
          model_status: 'deterministic_fallback',
          confidence: 0.52,
          risk_level: 'medium',
          created_at: '2026-05-10T00:00:00.000Z',
        },
      ],
      statistics: baseStatistics,
      now: new Date('2026-05-10T00:00:00.000Z'),
    })

    expect(model.aiOutputs.map(item => item.title)).toContain('报告草稿产出')
    expect(model.aiOutputs.find(item => item.title === '报告草稿产出')?.detail).toContain('1 份待人工复核')
    expect(model.aiOutputs.map(item => item.title)).toContain('结论草稿产出')
    expect(model.reviewItems.map(item => item.title)).toContain('结论草稿待复核')
    expect(model.kpis.aiOutputs.value).toBe('2')
    expect(model.kpis.aiOutputs.scope).toBe('近30天产出')
  })

  it('surfaces high priority suggestion center items as jump-only dashboard entries', () => {
    const model = buildDashboardModel({
      cases: [],
      chainLinks: [],
      areaRisks: [],
      hotspots: [],
      suggestions: [
        {
          id: 'case-quality-7',
          type: 'data_quality',
          priority: 'high',
          title: '复核案件质量：CASE-7',
          description: '该案件存在信息质量缺口。',
          target_type: 'case',
          target_id: 7,
          action: 'open_case',
          status: 'open',
          created_at: '2026-05-10T00:00:00.000Z',
        },
      ],
      statistics: baseStatistics,
      now: new Date('2026-05-10T00:00:00.000Z'),
    })

    const suggestionItem = model.reviewItems.find(item => item.title === '高优先级待办')

    expect(suggestionItem?.detail).toContain('复核案件质量')
    expect(suggestionItem?.route).toBe('/cases?caseId=7')
    expect(suggestionItem?.mutationAction).toBeUndefined()
  })

})
