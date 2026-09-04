export type ThemeMode = 'dark' | 'light'

export interface ThemeTokenConfig {
  algorithm: ThemeMode
  tokens: {
    colorBgBase: string
    colorBgContainer: string
    colorBgElevated: string
    colorBgLayout: string
    colorBorder: string
    colorBorderSecondary: string
    colorTextBase: string
    colorTextSecondary: string
    colorPrimary: string
    colorPrimaryHover: string
    colorLink: string
    colorSplit: string
  }
}

export function normalizeThemeMode(value: string | null | undefined): ThemeMode {
  return value === 'light' ? 'light' : 'dark'
}

export function toggleThemeMode(mode: ThemeMode): ThemeMode {
  return mode === 'dark' ? 'light' : 'dark'
}

export function getThemeTokens(mode: ThemeMode): ThemeTokenConfig {
  if (mode === 'light') {
    return {
      algorithm: 'light',
      tokens: {
        colorBgBase: '#f3f5f8',
        colorBgContainer: '#ffffff',
        colorBgElevated: '#ffffff',
        colorBgLayout: '#eef2f6',
        colorBorder: 'oklch(0.80 0.016 250 / 0.9)',
        colorBorderSecondary: 'oklch(0.82 0.016 250 / 0.55)',
        colorTextBase: '#1f2937',
        colorTextSecondary: '#64748b',
        colorPrimary: '#c8a44a',
        colorPrimaryHover: '#b89135',
        colorLink: '#9d7420',
        colorSplit: 'oklch(0.82 0.016 250 / 0.7)',
      },
    }
  }

  return {
    algorithm: 'dark',
    tokens: {
      colorBgBase: '#0e1520',
      colorBgContainer: '#161e2e',
      colorBgElevated: '#1c2638',
      colorBgLayout: '#0a0f1a',
      colorBorder: 'oklch(0.32 0.014 250 / 0.7)',
      colorBorderSecondary: 'oklch(0.32 0.014 250 / 0.35)',
      colorTextBase: '#d0d8e8',
      colorTextSecondary: '#7a8a9a',
      colorPrimary: '#c8a44a',
      colorPrimaryHover: '#d4b05a',
      colorLink: '#c8a44a',
      colorSplit: 'oklch(0.32 0.014 250 / 0.7)',
    },
  }
}
