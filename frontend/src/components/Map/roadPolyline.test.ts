import { describe, expect, it } from 'vitest'
import { roadPolyline } from './roadPolyline'

describe('参考路径固定六位精度', () => {
  it('保持纬经轴顺序及百万分之一度精度', () => {
    expect(roadPolyline('??AC')).toEqual([[0, 0], [.000001, .000002]])
    expect(roadPolyline('??@B')).toEqual([[0, 0], [-.000001, -.000002]])
  })
  it.each(['', '?', '??', '??A', '~~~~~~~', '\u0000\u0000'])('拒绝不完整或异常编码 %s', encoded => {
    expect(() => roadPolyline(encoded)).toThrow()
  })
})
