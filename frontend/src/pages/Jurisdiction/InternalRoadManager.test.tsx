import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import InternalRoadManager from './InternalRoadManager'

describe('道路治理入口', () => {
  it('未选择来源不展示资料或核验按钮，空态说明登记入口', () => {
    const html = renderToStaticMarkup(<InternalRoadManager sources={[]} />)
    expect(html).toContain('请先在生产地图数据治理中登记内部资料来源')
    expect(html).toContain('不直接发布可通行道路')
    expect(html).not.toContain('记录核验决定')
    expect(html).not.toContain('发布合格记录')
  })
})
