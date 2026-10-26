import { Moon, Sun } from 'lucide-react'
import { useTheme } from '../../context/ThemeContext'

export function ThemeToggle({ className = '' }: { className?: string }) {
  const { theme, toggleTheme } = useTheme()
  const nextTheme = theme === 'light' ? 'dark' : 'light'

  return <button
    type="button"
    className={`theme-toggle ${className}`.trim()}
    data-theme={theme}
    onClick={toggleTheme}
    aria-label={`Switch to ${nextTheme} mode`}
    aria-pressed={theme === 'dark'}
    title={`Switch to ${nextTheme} mode`}
  >
    <Sun className="theme-toggle-sun" size={17} strokeWidth={1.8} aria-hidden="true" />
    <Moon className="theme-toggle-moon" size={17} strokeWidth={1.8} aria-hidden="true" />
    <span className="sr-only">{theme === 'dark' ? 'Dark mode' : 'Light mode'}</span>
  </button>
}
