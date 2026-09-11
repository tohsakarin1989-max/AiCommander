import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import AutomaticBriefStatus from './AutomaticBriefStatus'

describe('automatic brief state', () => {
  it('distinguishes missing first brief from a completed zero-suggestion brief', () => {
    const missing = renderToStaticMarkup(<AutomaticBriefStatus loading={false} failed errorStatus={404} retry={() => {}} />)
    expect(missing).toContain('尚无简报')
    expect(missing).not.toContain('<strong>0')
    const zero = renderToStaticMarkup(<AutomaticBriefStatus loading={false} failed={false} count={0} summary="没有明显变化" retry={() => {}} />)
    expect(zero).toContain('<strong>0 项建议</strong>')
    expect(zero).toContain('没有明显变化')
  })
  it('does not retain stale suggestion counts after a failure or revocation', () => {
    for (const state of [{ failed: true }, { failed: false, unavailable: true }]) {
      const html = renderToStaticMarkup(<AutomaticBriefStatus loading={false} count={3} {...state} retry={() => {}} />)
      expect(html).toContain('暂不可用')
      expect(html).not.toContain('3 项建议')
      expect(html).toContain('重新读取简报')
    }
  })
  it('does not show a fabricated zero while loading', () => {
    const html = renderToStaticMarkup(<AutomaticBriefStatus loading failed={false} retry={() => {}} />)
    expect(html).toContain('正在读取')
    expect(html).not.toContain('项建议')
  })
})
