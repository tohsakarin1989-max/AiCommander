export type CaseStewardState = 'disabled' | 'unavailable' | 'ready'

export interface CaseStewardReadiness {
  enabled: boolean
  can_start: boolean
  max_cases_per_run?: number
  state?: CaseStewardState
}

export function caseStewardStateLabel(state: CaseStewardState): string {
  const labels: Record<CaseStewardState, string> = {
    disabled: '未开放',
    unavailable: '环境未就绪',
    ready: '只读试用中',
  }
  return labels[state]
}

export function canStartCaseSteward(status?: CaseStewardReadiness | null): boolean {
  return Boolean(status?.enabled && status.can_start)
}

export function canSubmitCaseStewardRun(
  status: CaseStewardReadiness | null | undefined,
  selectedCaseCount: number,
): boolean {
  const maxCases = status?.max_cases_per_run ?? 0
  return canStartCaseSteward(status) && selectedCaseCount > 0 && selectedCaseCount <= maxCases
}

export type CaseStewardControlAction = 'enable' | 'disable'

export function caseStewardControlReason(
  reason: string,
  action: CaseStewardControlAction,
): string {
  const trimmed = reason.trim()
  if (trimmed && trimmed !== '启动案件数据管家只读试用') return trimmed
  return action === 'enable'
    ? '启动案件数据管家只读试用'
    : '管理员一键停用案件数据管家试用'
}

export function caseStewardControlHint(status: CaseStewardReadiness): string {
  if (!status.enabled) return '管理员尚未开放案件数据管家试用。'
  if (status.state === 'unavailable') return '当前环境不是受控辅助模式，案件任务不会启动。'
  if (!status.can_start) return '当前账号不在指定试用名单内。'
  return '可对明确选择的案件执行只读质检；不会生成案件字段写入操作。'
}
