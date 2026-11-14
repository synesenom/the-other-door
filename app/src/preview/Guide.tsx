// The visual guide (`?scene=guide`): every control and mark of the renderer on one page, in its real
// classes, so a change to a shared style is seen (and hovered, pressed, focused) in one place.
// Its own layout is inline: a development page, in no build of the app.
import { useState, type ReactNode } from 'react'
import { CheckMark, CrossMark, WarningMark } from '../renderer/screens/CheckMark'
import { Switch } from '../renderer/screens/Switch'

const COLOURS = [
  'ground', 'surface', 'page', 'ink', 'ink-muted', 'border',
  'accent', 'success', 'danger', 'warning', 'on-warning',
]
const TYPE = ['display-l', 'display-s', 'score-l', 'score-s', 'body', 'small', 'label', 'field-label']

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="part" aria-label={title}>
      <h2 className="display-s">{title}</h2>
      {children}
    </section>
  )
}

const Row = ({ label, children }: { label: string; children: ReactNode }) => (
  <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr', alignItems: 'center', gap: 16 }}>
    <span className="small muted">{label}</span>
    <div className="actions">{children}</div>
  </div>
)

export function Guide() {
  const [pressed, setPressed] = useState('All')
  const [nav, setNav] = useState('Matches')
  const [on, setOn] = useState(true)
  return (
    <main style={{ minHeight: '100vh', background: 'var(--color-ground)', overflowY: 'auto', height: '100vh' }}>
      <div className="settings" style={{ maxWidth: 820 }}>
        <h1 className="display-l">Visual guide</h1>
        <p className="subtitle">Every control in its real classes. Hover, press and tab through them; switch the theme in the scene list.</p>

        <Part title="Buttons">
          {(['primary', 'secondary', 'quiet'] as const).map((kind) => (
            <Row key={kind} label={kind}>
              <button type="button" className={kind}>View matches</button>
              <button type="button" className={kind} disabled>Disabled</button>
            </Row>
          ))}
          <Row label="link-inline">
            <span className="small">
              LinkedIn (not enabled, <button type="button" className="link-inline">enable</button>)
            </span>
          </Row>
        </Part>

        <Part title="Pills, switches and sidebar items">
          <Row label="pill">
            <div className="doc-switch" role="group" aria-label="Pills">
              {['All', 'New only'].map((p) => (
                <button key={p} type="button" className="pill" aria-pressed={pressed === p} onClick={() => setPressed(p)}>
                  {p}
                </button>
              ))}
              <button type="button" className="pill" disabled>Disabled</button>
            </div>
          </Row>
          <Row label="switch">
            <Switch label="Preview" checked={on} onChange={setOn} />
            <Switch label="Off" checked={false} onChange={() => undefined} />
          </Row>
          <Row label="nav-item">
            <nav aria-label="Sidebar items" style={{ display: 'flex', flexDirection: 'column', gap: 2, width: 180 }}>
              {['Matches', 'Applications', 'Profile'].map((n) => (
                <button key={n} type="button" className="nav-item" aria-current={nav === n ? 'page' : undefined} onClick={() => setNav(n)}>
                  {n}
                </button>
              ))}
            </nav>
          </Row>
          <Row label="sidebar-problem">
            <div className="sidebar-problems">
              <button type="button" className="quiet sidebar-problem marked">
                <span className="mark"><WarningMark /></span>
                <span>You have no CV yet</span>
              </button>
            </div>
          </Row>
        </Part>

        <Part title="Fields">
          <Row label="field-label">
            <label className="field">
              <span className="field-label">Why not this one?</span>
              <textarea rows={2} placeholder="A placeholder" />
            </label>
          </Row>
          <Row label="text">
            <input className="onb-input" placeholder="A placeholder" aria-label="Text" />
            <input className="onb-input" defaultValue="Disabled" disabled aria-label="Disabled text" />
          </Row>
          <Row label="select">
            <select className="onb-input" aria-label="Select" defaultValue="Copenhagen">
              <option>Copenhagen</option>
              <option>Aarhus</option>
            </select>
          </Row>
          <Row label="choices">
            <label className="choice"><input type="checkbox" defaultChecked /> <span>Checked</span></label>
            <label className="choice"><input type="checkbox" /> <span>Not checked</span></label>
            <label className="choice"><input type="radio" name="g" defaultChecked /> <span>Radio</span></label>
            <label className="choice"><input type="radio" name="g" /> <span>Radio</span></label>
            <label className="choice"><input type="checkbox" disabled /> <span>Disabled</span></label>
          </Row>
          <Row label="chips">
            <span className="chip">controller</span>
            <span className="chip">økonomi*</span>
          </Row>
        </Part>

        <Part title="Marks and notes">
          <Row label="marks">
            <span className="small marked"><span className="mark"><CheckMark /></span><span>Done</span></span>
            <span className="small marked"><span className="mark" style={{ color: 'var(--color-danger)' }}><CrossMark /></span><span>Failed</span></span>
            <span className="small marked"><span className="mark"><WarningMark /></span><span>Not enabled</span></span>
          </Row>
          <Row label="notice">
            <p className="notice small">Marked as applied.</p>
          </Row>
          <Row label="error">
            <p className="error small">The other door could not start the run.</p>
          </Row>
          <Row label="title-line">
            <div className="title-line">
              <h3 className="body item-name">Claude</h3>
              <span className="small muted">Required</span>
            </div>
          </Row>
        </Part>

        <Part title="Figures">
          <Row label="bar">
            <div className="bar" aria-hidden="true">
              <span style={{ width: '62%' }} />
            </div>
          </Row>
          <Row label="usage-stack">
            <div className="usage-stack" aria-hidden="true">
              <span className="usage-tone-0" style={{ flexGrow: 0.62 }} />
              <span className="usage-tone-1" style={{ flexGrow: 0.35 }} />
              <span className="usage-tone-2" style={{ flexGrow: 0.03 }} />
            </div>
          </Row>
          <Row label="usage-activity">
            <ul className="usage-list">
              <li className="usage-activity">
                <div className="usage-row">
                  <h3 className="body">
                    <span className="usage-dot usage-tone-1" aria-hidden="true" />
                    Finding jobs
                    <span className="muted"> · 184 postings scored</span>
                  </h3>
                  <span className="body">$1.22</span>
                </div>
                <ul className="usage-features">
                  <li className="usage-row small muted">
                    <span>Scoring postings</span>
                    <span>$1.14</span>
                  </li>
                  <li className="usage-row small muted">
                    <span>Translating job titles</span>
                    <span>$0.08</span>
                  </li>
                </ul>
              </li>
            </ul>
          </Row>
        </Part>

        <Part title="Type">
          {TYPE.map((t) => (
            <Row key={t} label={t}>
              <span className={t}>The other door</span>
            </Row>
          ))}
        </Part>

        <Part title="Colours">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 12 }}>
            {COLOURS.map((c) => (
              <div key={c} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ height: 40, borderRadius: 8, border: '1px solid var(--color-border)', background: `var(--color-${c})` }} />
                <span className="small muted">{c}</span>
              </div>
            ))}
          </div>
        </Part>
      </div>
    </main>
  )
}
