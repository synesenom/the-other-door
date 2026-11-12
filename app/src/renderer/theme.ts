// The theme choice (Settings, Appearance): the system's, light or dark. It is this computer's, so it is
// kept in the window's own storage (not in profile/), and set on <html> as data-theme, which theme.css reads.
export type Theme = 'system' | 'light' | 'dark'

const KEY = 'door.theme'

export function readTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(theme: Theme): void {
  if (theme === 'system') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', theme)
}

export function saveTheme(theme: Theme): void {
  try {
    if (theme === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, theme)
  } catch {
    // kept for this window only
  }
  applyTheme(theme)
}
