import { describe, expect, it } from 'vitest'
import { getThemeTokens, normalizeThemeMode, toggleThemeMode } from './themeMode'

describe('themeMode', () => {
  it('normalizes persisted theme values safely', () => {
    expect(normalizeThemeMode('light')).toBe('light')
    expect(normalizeThemeMode('dark')).toBe('dark')
    expect(normalizeThemeMode('unknown')).toBe('light')
    expect(normalizeThemeMode(null)).toBe('light')
  })

  it('switches in both directions', () => {
    expect(toggleThemeMode('dark')).toBe('light')
    expect(toggleThemeMode('light')).toBe('dark')
  })

  it('returns matching design tokens for each mode', () => {
    const dark = getThemeTokens('dark')
    const light = getThemeTokens('light')

    expect(dark.algorithm).toBe('dark')
    expect(light.algorithm).toBe('light')
    expect(dark.tokens.colorBgContainer).not.toEqual(light.tokens.colorBgContainer)
    // 两种主题可以使用独立主色，但必须提供有效颜色与悬停态。
    for (const { tokens } of [light, dark]) {
      expect(tokens.colorPrimary).toMatch(/^#[0-9a-f]{6}$/i)
      expect(tokens.colorPrimaryHover).toMatch(/^#[0-9a-f]{6}$/i)
      expect(tokens.colorPrimaryHover).not.toBe(tokens.colorPrimary)
    }
  })
})
