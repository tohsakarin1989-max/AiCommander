export function dashboardWindow(params: URLSearchParams) {
  const selected = params.get('dashboard_period')
  const allHistory = params.get('time_scope') === 'all_history' && !params.has('start_date') && !params.has('end_date')
  const rolling = !allHistory && (selected === '7' || selected === '30' || (!params.has('start_date') && !params.has('end_date')))
  return { rolling, allHistory, days: selected === '30' ? 30 : 7,
    request: rolling || allHistory ? undefined : { start_date: params.get('start_date') ?? undefined, end_date: params.get('end_date') ?? undefined } }
}

export function rollingWindowParams(previous: URLSearchParams, days: number, period: { start: string; end: string }) {
  const next = new URLSearchParams(previous)
  next.set('dashboard_period', String(days)); next.delete('time_scope')
  next.set('start_date', period.start); next.set('end_date', period.end)
  return next
}
