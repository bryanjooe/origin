import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark'

const THEME_KEY = 'origin-theme'
const ThemeContext = createContext<{ theme: Theme; toggleTheme: () => void } | null>(null)

function getStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(THEME_KEY)
    return stored === 'light' || stored === 'dark' ? stored : null
  } catch {
    return null
  }
}

function getInitialTheme(): Theme {
  return getStoredTheme() ?? (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)
  const hasManualPreference = useRef(Boolean(getStoredTheme()))

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    root.style.colorScheme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#101915' : '#f0f0e9')
  }, [theme])

  useEffect(() => {
    if (getStoredTheme()) return
    const preference = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!preference) return
    const handleChange = (event: MediaQueryListEvent) => {
      if (!hasManualPreference.current) setTheme(event.matches ? 'dark' : 'light')
    }
    preference.addEventListener?.('change', handleChange)
    return () => preference.removeEventListener?.('change', handleChange)
  }, [])

  const toggleTheme = useCallback(() => setTheme((current) => {
    const next = current === 'light' ? 'dark' : 'light'
    hasManualPreference.current = true
    try {
      window.localStorage.setItem(THEME_KEY, next)
    } catch {
      // The active theme remains usable when browser storage is unavailable.
    }
    return next
  }), [])
  const value = useMemo(() => ({ theme, toggleTheme }), [theme, toggleTheme])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used inside ThemeProvider')
  return context
}
