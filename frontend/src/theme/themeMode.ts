export type ThemeMode = 'dark' | 'light'

export function normalizeThemeMode(value: string | null | undefined): ThemeMode {
  return value === 'dark' ? 'dark' : 'light'
}

export function toggleThemeMode(mode: ThemeMode): ThemeMode {
  return mode === 'dark' ? 'light' : 'dark'
}

export function getThemeTokens(mode: ThemeMode = 'light') {
  if (mode === 'dark') return {
    algorithm: 'dark' as const,
    tokens: {
      colorBgBase: '#141819', colorBgContainer: '#1d2325', colorBgElevated: '#272f31',
      colorBgLayout: '#141819', colorBorder: '#435053', colorBorderSecondary: '#303b3e',
      colorTextBase: '#e8eeec', colorTextSecondary: '#a9b8b5',
      colorPrimary: '#69c9ad', colorPrimaryHover: '#91ddc5', colorLink: '#84baf1', colorSplit: '#435053',
    },
  }
  return {
    algorithm: 'light' as const,
    tokens: {
      colorBgBase: '#f4f6f7',
      colorBgContainer: '#ffffff',
      colorBgElevated: '#ffffff',
      colorBgLayout: '#f4f6f7',
      colorBorder: '#d8e0e2',
      colorBorderSecondary: '#e8edef',
      colorTextBase: '#202628',
      colorTextSecondary: '#606c70',
      colorPrimary: '#126759',
      colorPrimaryHover: '#0e564a',
      colorLink: '#246da5',
      colorSplit: '#d8e0e2',
    },
  }
}
