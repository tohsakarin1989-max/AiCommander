import { describe, expect, it } from 'vitest'
import { resultCreatedTime } from './caseResultCatalogPresentation'

describe('成果生成时间显示', () => {
  it('仅将带时区的生成时间转换为北京时间，不受浏览器时区影响', () => {
    expect(resultCreatedTime('2026-09-10T20:15:53.865242+00:00')).toBe('2026/09/11 04:15:53')
    expect(resultCreatedTime('2026-09-11T04:15:53+08:00')).toBe('2026/09/11 04:15:53')
  })
  it('缺时区不猜测，格式错误和不可读数据明确区分', () => {
    expect(resultCreatedTime('2026-09-10T20:15:53')).toContain('时区未注明')
    expect(resultCreatedTime('not-a-dateZ')).toBe('时间格式待核对')
    expect(resultCreatedTime()).toBe('不可读取')
  })
})
