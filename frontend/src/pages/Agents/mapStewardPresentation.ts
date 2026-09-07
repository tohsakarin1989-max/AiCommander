export type MapStewardState = 'disabled' | 'suspended' | 'read_only' | 'ready'

export interface MapStewardReadiness {
  enabled?: boolean
  can_start: boolean
  can_apply_changes?: boolean
  state?: MapStewardState
}

export function mapStewardStateLabel(state: MapStewardState): string {
  const labels: Record<MapStewardState, string> = {
    disabled: '试用未开启',
    suspended: '候选写入已暂停',
    read_only: '只读检查',
    ready: '受控辅助运行中',
  }
  return labels[state]
}

export function canStartMapSteward(status?: MapStewardReadiness | null): boolean {
  return Boolean(status?.enabled && status.can_start)
}

export function canSubmitMapStewardRun(
  status: MapStewardReadiness | null | undefined,
  selectedAssetCount: number,
): boolean {
  return canStartMapSteward(status) && selectedAssetCount > 0
}

export type MapStewardControlAction = 'enable' | 'pause' | 'disable'

export function mapStewardControlReason(
  reason: string,
  action: MapStewardControlAction,
): string {
  const trimmed = reason.trim()
  if (trimmed && trimmed !== '启动地图数据管家受控试用') return trimmed
  return {
    enable: '启动地图数据管家受控试用',
    pause: '管理员暂停候选写入',
    disable: '管理员一键停用地图数据管家试用',
  }[action]
}

export function mapStewardControlHint(status: MapStewardReadiness): string {
  if ((status.state === 'ready' || status.state === 'suspended') && !status.can_start) {
    return '当前账号未被加入试用名单，可查看历史运行记录。'
  }
  const state = status.state ?? 'disabled'
  const hints: Record<MapStewardState, string> = {
    disabled: '管理员开启试用并指定人员后，才可发起地图质检任务。',
    suspended: '仍可检查数据并查看历史轨迹；所有候选写入已停止执行。',
    read_only: '可以识别地图数据问题并生成证据，暂不允许应用候选修正。',
    ready: '只处理明确选中的地图资源，候选修正需由管理员审批。',
  }
  return hints[state]
}
