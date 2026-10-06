// Light/dark theme preference. 'system' follows the OS setting.
// index.html applies the stored choice before first paint; keep the storage key in sync with it.

export type Theme = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'theme'
const media = window.matchMedia('(prefers-color-scheme: dark)')

export function getTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // storage unavailable (private mode etc.): fall back to system
  }
  return 'system'
}

export function applyTheme(theme: Theme) {
  const dark = theme === 'dark' || (theme === 'system' && media.matches)
  document.documentElement.classList.toggle('dark', dark)
}

export function setTheme(theme: Theme) {
  try {
    if (theme === 'system') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // ignore: the choice still applies for this page view
  }
  applyTheme(theme)
}

// Re-apply when the OS setting changes while following the system.
media.addEventListener('change', () => {
  if (getTheme() === 'system') applyTheme('system')
})
