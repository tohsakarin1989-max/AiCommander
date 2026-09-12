import { createContext, useContext, useLayoutEffect, useState, type ReactNode } from 'react'
import { normalizeThemeMode, toggleThemeMode, type ThemeMode } from './themeMode'

export const THEME_STORAGE_KEY = 'aicommander.ui.theme'
const ThemeContext = createContext<{ mode: ThemeMode; toggle: () => void }>({ mode: 'light', toggle: () => {} })

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(() => {
    try { return normalizeThemeMode(localStorage.getItem(THEME_STORAGE_KEY)) } catch { return 'light' }
  })
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = mode
    document.documentElement.style.colorScheme = mode
    try { localStorage.setItem(THEME_STORAGE_KEY, mode) } catch { /* Private storage may be unavailable. */ }
  }, [mode])
  return <ThemeContext.Provider value={{ mode, toggle: () => setMode(toggleThemeMode) }}>{children}</ThemeContext.Provider>
}

export const useThemeMode = () => useContext(ThemeContext)
