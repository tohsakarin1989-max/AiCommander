export type DashboardTimeBasis = 'legacy_incident' | 'discovery' | 'incident' | 'entry'
export function dashboardWindow(params: URLSearchParams) {
  const selected = params.get('dashboard_period')
  const allHistory = params.get('time_scope') === 'all_history' && !params.has('start_date') && !params.has('end_date')
  const rolling = !allHistory && (selected === '7' || selected === '30' || (!params.has('start_date') && !params.has('end_date')))
  const rawBasis = params.get('time_basis')
  const basis = rawBasis || (rolling ? 'discovery' : 'legacy_incident')
  const valid = ['legacy_incident', 'discovery', 'incident', 'entry'].includes(basis) && params.getAll('time_basis').length <= 1
  return { rolling, allHistory, days: selected === '7' ? 7 : 30,
    timeBasis: basis as DashboardTimeBasis, error: valid ? null : '时间口径无效，未改用其他统计口径。',
    request: rolling || allHistory ? undefined : { start_date: params.get('start_date') ?? undefined, end_date: params.get('end_date') ?? undefined } }
}

/** Existing area views use their own incident-time contract; do not mislabel a discovery window. */
export function dashboardAreaParams(previous: URLSearchParams, basis: DashboardTimeBasis) {
  if (basis === 'legacy_incident') return previous
  const next = new URLSearchParams(previous)
  for (const key of ['start_date', 'end_date', 'dashboard_period', 'time_basis']) next.delete(key)
  next.set('time_scope', 'all_history')
  return next
}

export function rollingWindowParams(previous: URLSearchParams, days: number, period: { start: string; end: string }) {
  const next = new URLSearchParams(previous)
  next.set('dashboard_period', String(days)); next.delete('time_scope')
  next.set('start_date', period.start); next.set('end_date', period.end)
  return next
}
