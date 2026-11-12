import { useState } from 'react'
import { DATA_STATES, SCENES, type DataState } from './scenes'

const THEMES = ['system', 'light', 'dark'] as const

/** The list of scenes: each is a link, so it opens in a tab of its own. */
export function Picker() {
  const [state, setState] = useState<DataState>('ok')
  const [theme, setTheme] = useState<(typeof THEMES)[number]>('system')
  const groups = [...new Set(SCENES.map((s) => s.group))]
  const href = (id: string) => {
    const q = new URLSearchParams({ scene: id })
    if (state !== 'ok') q.set('state', state)
    if (theme !== 'system') q.set('theme', theme)
    return `?${q}`
  }
  return (
    <main style={{ maxWidth: 640, margin: '0 auto', padding: 32, background: 'var(--paper, transparent)', minHeight: '100vh' }}>
      <h1 className="display-l">Screen preview</h1>
      <p className="body">The real screens on made-up data. Nothing here starts Python or claude, and nothing is saved.</p>
      <p className="body">
        <label>
          Data{' '}
          <select value={state} onChange={(e) => setState(e.target.value as DataState)}>
            {DATA_STATES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>{' '}
        <label>
          Theme{' '}
          <select value={theme} onChange={(e) => setTheme(e.target.value as (typeof THEMES)[number])}>
            {THEMES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
      </p>
      {groups.map((group) => (
        <section key={group}>
          <h2 className="heading">{group}</h2>
          <ul>
            {SCENES.filter((s) => s.group === group).map((s) => (
              <li key={s.id} className="body">
                <a href={href(s.id)}>{s.title}</a>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  )
}
