export const activeQuery = (status?: string) => status === 'queued' || status === 'running'
export const queryIdValid = (id: string) => /^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(id)
export const toolNames: Record<string, string> = {
  find_cases: '案件查找', find_places: '地点与设施', count_cases: '案件统计',
  compare_periods: '周期比较', summarize_results: '已有研判成果',
}
export const statusNames: Record<string, string> = {
  queued: '排队中', running: '正在查询', completed: '查询完成',
  degraded: '部分完成或条件不足', failed: '查询未完成', cancelled: '已取消', expired: '运行已超时',
}
export function failureText(code?: string | null): string {
  const messages: Record<string, string> = {
    query_model_unavailable: '内网模型不可用，请联系管理员检查配置；案件和地图功能仍可使用。',
    query_timeout: '查询超时，已取得的结果保留在下方。',
    query_step_limit: '已达到本次查询步骤上限，可缩小问题范围后重新查询。',
    query_insufficient_data: '当前条件不足，请补充明确的时间或查询条件。',
    query_unsupported: '当前仅支持案件、地点、统计、周期比较和已有成果查询。',
  }
  return code ? messages[code] || '本次查询未完整完成，请查看已有结果和信息缺口。' : ''
}
export const textValue = (value: unknown) => typeof value === 'string' || typeof value === 'number' ? String(value) : '未提供'
export const rowsOf = (value: unknown): Record<string, unknown>[] => Array.isArray(value)
  ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item)) : []
export function requestFailure(error: unknown, creating = false): string {
  const status = (error as { response?: { status?: number }; status?: number })?.response?.status
    ?? (error as { status?: number })?.status
  if (status === 404) return creating ? '智能查询尚未启用，请联系管理员。' : '任务不存在、不可访问或智能查询已关闭。'
  if (status === 403) return '账号或数据范围已变化，不能继续显示旧查询结果。'
  if (status === 401) return '登录已失效，请重新登录。'
  if (status === 429) return '待处理任务已达上限，请先等待或取消已有任务。'
  return creating ? '提交未得到确认。请勿连续重复提交，稍后检查服务状态。' : '暂时无法读取任务，请重试；这不代表没有匹配数据。'
}
