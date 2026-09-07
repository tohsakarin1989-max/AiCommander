export type DualDomainState = 'disabled' | 'unavailable' | 'ready'

export interface DualDomainReadiness {
  enabled: boolean
  can_start: boolean
  max_cases_per_run?: number
  max_assets_per_run?: number
  state?: DualDomainState
}

export function dualDomainStateLabel(state: DualDomainState): string {
  const labels: Record<DualDomainState, string> = {
    disabled: '未开放',
    unavailable: '环境未就绪',
    ready: '只读研判中',
  }
  return labels[state]
}

export function canStartDualDomain(status?: DualDomainReadiness | null): boolean {
  return Boolean(status?.enabled && status.can_start)
}

export function canSubmitDualDomainRun(
  status: DualDomainReadiness | null | undefined,
  selectedCaseCount: number,
  selectedAssetCount: number,
): boolean {
  const maxCases = status?.max_cases_per_run ?? 0
  const maxAssets = status?.max_assets_per_run ?? 0
  return canStartDualDomain(status)
    && selectedCaseCount > 0
    && selectedCaseCount <= maxCases
    && selectedAssetCount > 0
    && selectedAssetCount <= maxAssets
}

export type DualDomainControlAction = 'enable' | 'disable'

export function dualDomainControlReason(
  reason: string,
  action: DualDomainControlAction,
): string {
  const trimmed = reason.trim()
  if (trimmed && trimmed !== '启动双域融合只读试用') return trimmed
  return action === 'enable'
    ? '启动双域融合只读试用'
    : '管理员一键停用双域融合研判试用'
}

export function dualDomainControlHint(status: DualDomainReadiness): string {
  if (!status.enabled) return '管理员尚未开放双域融合研判试用。'
  if (status.state === 'unavailable') return '当前环境不是受控辅助模式，双域任务不会启动。'
  if (!status.can_start) return '当前账号不在指定试用名单内。'
  return '可对明确选择的案件和地图资源复盘历史时空条件；不预测犯罪、不确认串并案、不写入正式数据。'
}
