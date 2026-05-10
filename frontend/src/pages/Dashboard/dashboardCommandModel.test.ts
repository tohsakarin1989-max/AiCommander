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

})
