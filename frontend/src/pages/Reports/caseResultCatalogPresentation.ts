export function resultCreatedTime(value?: string): string {
  if (!value) return '不可读取'
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)) return `${value}（时区未注明）`
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '时间格式待核对'
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit',
    day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(date)
}
