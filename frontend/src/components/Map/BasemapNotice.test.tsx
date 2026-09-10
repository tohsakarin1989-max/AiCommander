import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { BasemapNotice } from './BasemapNotice'

describe('底图状态与来源边界', () => {
  it('加载成功仍说明来源空白，不冒充已知不存在道路；默认折叠，不增加必需操作', () => {
    const html = renderToStaticMarkup(<BasemapNotice status="ready" onRetry={() => {}} />)
    expect(html).toContain('底图空白不代表没有道路')
    expect(html).toContain('空白可能是未收录或图层未显示')
    expect(html).toContain('能否通行')
    expect(html).toContain('<details')
    expect(html).not.toContain(' open=')
    expect(html).not.toContain('role="status"')
    expect(html).not.toContain('重试当前地图')
  })
  it('加载与失败保留明确状态和重试，不以来源空白掩盖故障', () => {
    const loading = renderToStaticMarkup(<BasemapNotice status="loading" onRetry={() => {}} />)
    const failed = renderToStaticMarkup(<BasemapNotice status="unavailable" onRetry={() => {}} />)
    expect(loading).toContain('正在加载内网地图')
    expect(failed).toContain('底图未配置或加载失败')
    expect(failed).toContain('重试当前地图')
    expect(failed).not.toContain('<details')
  })
})
