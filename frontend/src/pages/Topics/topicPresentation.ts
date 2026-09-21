import type { TopicFilters } from '../../services/analysisTopics'
export const categoryNames: Record<string, string> = {
  method: '作案手法', oil: '油品', facility: '设施', place_condition: '地点条件', time_condition: '时间条件',
  tool: '工具', vehicle: '车辆', upstream_clue: '来源线索', downstream_clue: '去向线索',
}
export const kindNames: Record<string, string> = { stated: '原文明述', negated: '原文否定', uncertain: '不确定',
  inferred: '推断', conflicting: '相互冲突', missing: '缺少表述' }
export const topicState: Record<string, string> = { queued: '等待更新', running: '正在更新', ready: '成果可用',
  failed: '更新失败，保留上一成果', paused: '已暂停更新' }
export function filterLines(filters: TopicFilters): string[] {
  const { conditions, ...ordinary } = filters
  const names: Record<string, string> = { keyword: '关键词', statuses: '状态', case_types: '案件类型', oil_types: '油品字段',
    start_date: '起始时间（含）', end_date: '结束时间（不含）', has_geo: '有坐标', case_id: '案件 ID', operational_area_id: '辖区 ID' }
  return [
    ...Object.entries(ordinary).filter(([, value]) => value != null).map(([key, value]) => `${names[key] || key}：${String(value)}`),
    ...(conditions || []).map(item => `${categoryNames[item.category] || item.category}：${item.value || '任一词项'}（${kindNames[item.kind] || item.kind}）`),
  ]
}
export function topicError(error: unknown): string {
  const value = error as { status?: number; response?: { status?: number } }
  const status = value?.response?.status ?? value?.status
  if (status === 401) return '登录已失效，请重新登录。'
  if (status === 403) return '权限或来源已变化，当前成果不可显示。'
  if (status === 404) return '专题或成果不存在、不可访问；若在提交追问，请确认智能查询已启用。'
  if (status === 409) return '专题已暂停，请恢复后再更新。'
  if (status === 429) return '待处理专题或查询已达上限，请先暂停不需要的专题。'
  if (status === 422) return '条件不能等价保存或参数不符合要求；相似度、道路和成果时间等专用条件不能直接转换为案件专题。'
  return '操作未得到确认，请重新读取后再试；不能据此认为没有数据。'
}
