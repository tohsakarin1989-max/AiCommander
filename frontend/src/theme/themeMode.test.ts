import { describe, expect, it } from 'vitest'
import { getThemeTokens, normalizeThemeMode, toggleThemeMode } from './themeMode'

describe('themeMode', () => {
  it('normalizes persisted theme values safely', () => {
    expect(normalizeThemeMode('light')).toBe('light')
    expect(normalizeThemeMode('dark')).toBe('dark')
    expect(normalizeThemeMode('unknown')).toBe('dark')
    expect(normalizeThemeMode(null)).toBe('dark')
  })

  it('toggles between dark and light mode', () => {
    expect(toggleThemeMode('dark')).toBe('light')
    expect(toggleThemeMode('light')).toBe('dark')
  })

  it('returns matching design tokens for each mode', () => {
    const dark = getThemeTokens('dark')
    const light = getThemeTokens('light')

    expect(dark.algorithm).toBe('dark')
    expect(light.algorithm).toBe('light')
    expect(dark.tokens.colorBgBase).not.toBe(light.tokens.colorBgBase)
    expect(light.tokens.colorPrimary).toBe(dark.tokens.colorPrimary)
  })
})
