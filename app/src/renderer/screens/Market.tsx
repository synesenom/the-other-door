import { useState } from 'react'
import { named } from './AppName'
import { call, errorText } from '../api'
import { Dialog } from './Dialog'
import { Spinner } from './Spinner'

interface MarketReport {
  counts: { scraped: number; scored: number; above_min_score: number }
  skills: { name: string; count: number; share: number; have: boolean }[]
  near_misses: { n: number; rows: { skill: string; count: number }[] }
  uncovered_titles: { title: string; count: number }[]
  warning: string | null
}

const SKILLS_SHOWN = 8
const pct = (share: number) => `${Math.round(share * 100)}%`

/**
 * "What the ads asked for this month", in Profile → CV: the market tool, run only when opened and never
 * saved. "Make a plan" hands the skills the CV lacks to "What should I learn?" beside it; titles added to the
 * search are said through `onSearchChanged`, so the details form reads them.
 */
export function Market({ onPlan, onSearchChanged }: { onPlan: (skills: string[]) => void; onSearchChanged?: () => void }) {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<{ kind: 'idle' } | { kind: 'counting' } | { kind: 'done'; m: MarketReport } | { kind: 'error'; message: string }>({ kind: 'idle' })
  const [asking, setAsking] = useState(false)
  const [added, setAdded] = useState<string | null>(null)

  const toggle = async () => {
    const next = !open
    setOpen(next)
    // a report that failed is asked again when reopened
    if (!next || (state.kind !== 'idle' && state.kind !== 'error')) return
    setState({ kind: 'counting' })
    try {
      setState({ kind: 'done', m: await call<MarketReport>('market', { save: false }) })
    } catch (e) {
      setState({ kind: 'error', message: errorText(e) })
    }
  }
  const addTitles = async (titles: string[]) => {
    setAsking(false)
    try {
      const p = await call<{ config: { search_keywords?: string[]; role_targets?: string[] } | null }>('show_profile')
      const current = p.config?.search_keywords?.length ? p.config.search_keywords : (p.config?.role_targets ?? [])
      await call('init_profile', { search_keywords: [...current, ...titles.filter((t) => !current.includes(t))] })
      setAdded('Added to your search keywords.')
      onSearchChanged?.()
    } catch (e) {
      setAdded(errorText(e))
    }
  }

  const m = state.kind === 'done' ? state.m : null
  const missing = m ? m.skills.slice(0, SKILLS_SHOWN).filter((s) => !s.have).map((s) => s.name).slice(0, 3) : []
  const titles = m ? m.uncovered_titles.map((t) => t.title) : []
  return (
    <section className="cv-panel market" aria-labelledby="cv-market">
      <button type="button" className="quiet market-fold" id="cv-market" aria-expanded={open} onClick={() => void toggle()}>
        What the ads asked for this month
      </button>
      {!open && <p className="small muted">Counts the ads of the last 30 days. New skill names may need one short Claude call on your plan.</p>}
      {open && state.kind === 'counting' && <Spinner message="Counting the ads (new skill names may take one short Claude call)…" />}
      {open && state.kind === 'error' && (
        <p role="alert" className="field-error">
          {named(state.message)}
        </p>
      )}
      {open && m && (
        <div className="market-body">
          <p className="small muted">{`${m.counts.scraped} ads read, ${m.counts.scored} scored, ${m.counts.above_min_score} at your minimum score.`}</p>
          {m.warning && <p className="small muted">{m.warning}</p>}
          <h3 className="label">Most asked for</h3>
          <ul className="market-skills">
            {m.skills.slice(0, SKILLS_SHOWN).map((s) => (
              <li key={s.name} aria-label={s.name}>
                <span>{s.name}</span>
                <span className="small muted">{` · ${pct(s.share)} of the ads · ${s.have ? 'in your CV' : 'not in your CV'}`}</span>
              </li>
            ))}
          </ul>
          {missing.length > 0 && (
            <div className="actions">
              <button type="button" className="secondary" onClick={() => onPlan(missing)}>
                {`Make a plan for ${missing.length === 1 ? missing[0] : `${missing.slice(0, -1).join(', ')} and ${missing[missing.length - 1]}`}`}
              </button>
            </div>
          )}
          {m.near_misses.rows.length > 0 && (
            <p className="small">{`What kept ${m.near_misses.n} ads just under your minimum: ${m.near_misses.rows.map((r) => r.skill).join(', ')}.`}</p>
          )}
          {titles.length > 0 && (
            <>
              <h3 className="label">Titles your search does not cover</h3>
              <p className="small">{m.uncovered_titles.map((t) => `${t.title} (${t.count})`).join(', ')}</p>
              <div className="actions">
                <button type="button" className="quiet" onClick={() => setAsking(true)}>
                  Add these titles to my search
                </button>
              </div>
              {added && <p className="small">{added}</p>}
            </>
          )}
        </div>
      )}
      {asking && (
        <Dialog title="Add these titles to your search?" onClose={() => setAsking(false)}>
          <p className="body">{`The job boards will also be searched for ${titles.join(', ')}.`}</p>
          <div className="actions">
            <button type="button" className="quiet" onClick={() => setAsking(false)}>
              Cancel
            </button>
            <button type="button" className="primary" onClick={() => void addTitles(titles)}>
              Add
            </button>
          </div>
        </Dialog>
      )}
    </section>
  )
}
