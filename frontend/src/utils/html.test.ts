import { describe, expect, it } from 'vitest'

import { escapeHtml } from './html'

describe('escapeHtml', () => {
  it('escapes untrusted values before they are placed in Leaflet popup HTML', () => {
    expect(escapeHtml(`<img src=x onerror="alert(1)"> & '`)).toBe(
      '&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; &#39;'
    )
  })
})
