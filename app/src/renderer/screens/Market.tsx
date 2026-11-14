import { useEffect, useState } from 'react'
import { named } from './AppName'
import { call, errorText } from '../api'
import { Dialog } from './Dialog'
import { Spinner } from './Spinner'

interface MarketReport {
  counts: { scraped: number; scored: number; above_min_score: number }
  skills: { name: string; count: number; share: number; have: boolean }[]
  uncovered_titles: { title: string; count: number }[]
  companies: { population: string; rows: { name: string; count: number; followed: boolean }[] }
}

interface AddCompanyResult {
  results: { name: string; status: string; reason: string | null }[]
}

const SKILLS_SHOWN = 8
const pct = (share: number) => `${Math.round(share * 100)}%`

/**
 * "Market", in Analytics (#65): what the ads of the last 30 days asked for. The market tool runs once when the
 * screen opens and writes no report. Two things can be done from it: add the titles the search does not cover to
 * the search keywords, and follow a repeat employer. Both ask or say their result here; the report is not read
 * again.
 */
export function Market() {
  const [state, setState] = useState<{ kind: 'counting' } | { kind: 'done'; m: MarketReport } | { kind: 'error'; message: string }>({ kind: 'counting' })
  const [asking, setAsking] = useState(false)
  const [added, setAdded] = useState<{ ok: boolean; text: string } | null>(null)
  // per employer: asking, followed, or a line to show
  const [follows, setFollows] = useState<Record<string, { kind: 'pending' } | { kind: 'followed' } | { kind: 'note'; text: string }>>({})

  useEffect(() => {
    let live = true
    call<MarketReport>('market', { save: false }).then(
      (m) => live && setState({ kind: 'done', m }),
      (e) => live && setState({ kind: 'error', message: errorText(e) }),
    )
    return () => {
      live = false
    }
  }, [])

  const addTitles = async (titles: string[]) => {
    setAsking(false)
    try {
      const p = await call<{ config: { search_keywords?: string[]; role_targets?: string[] } | null }>('show_profile')
      const current = p.config?.search_keywords?.length ? p.config.search_keywords : (p.config?.role_targets ?? [])
      await call('init_profile', { search_keywords: [...current, ...titles.filter((t) => !current.includes(t))] })
      setAdded({ ok: true, text: 'Added to your search keywords.' })
    } catch (e) {
      setAdded({ ok: false, text: errorText(e) })
    }
  }
  const follow = async (name: string) => {
    setFollows((f) => ({ ...f, [name]: { kind: 'pending' } }))
    try {
      const r = await call<AddCompanyResult>('add_company', { inputs: [name] })
      const one = r.results?.[0]
      setFollows((f) => ({
        ...f,
        [name]: one?.status === 'followed' ? { kind: 'followed' } : { kind: 'note', text: one?.reason ?? `${name} could not be followed.` },
      }))
    } catch (e) {
      setFollows((f) => ({ ...f, [name]: { kind: 'note', text: errorText(e) } }))
    }
  }

  const m = state.kind === 'done' ? state.m : null
  const titles = m ? m.uncovered_titles.map((t) => t.title) : []
  const employers = m ? m.companies.rows : []
  return (
    <section className="part" aria-labelledby="analytics-market">
      <h2 className="display-s" id="analytics-market">
        Market
      </h2>
      {state.kind === 'counting' && <Spinner message="Counting the ads (new skill names may take one short Claude call)…" />}
      {state.kind === 'error' && (
        <p role="alert" className="field-error">
          {named(state.message)}
        </p>
      )}
      {m && m.skills.length === 0 && <p className="small muted">The market shows here once ads are read.</p>}
      {m && m.skills.length > 0 && (
        <div className="market-body">
          <p className="small muted">{`${m.counts.scraped} ads read, ${m.counts.scored} scored, ${m.counts.above_min_score} at your minimum score.`}</p>
          <h3 className="label">Most asked for</h3>
          <ul className="market-skills">
            {m.skills.slice(0, SKILLS_SHOWN).map((s) => (
              <li key={s.name} aria-label={s.name}>
                <span>{s.name}</span>
                <span className="small muted">{` · ${pct(s.share)} of the ads · ${s.have ? 'in your CV' : 'not in your CV'}`}</span>
              </li>
            ))}
          </ul>
          {titles.length > 0 && (
            <>
              <h3 className="label">Titles your search does not cover</h3>
              <p className="small">{m.uncovered_titles.map((t) => `${t.title} (${t.count})`).join(', ')}</p>
              {!added?.ok && (
                <div className="actions">
                  <button type="button" className="quiet" onClick={() => setAsking(true)}>
                    Add these titles to my search
                  </button>
                </div>
              )}
              {added?.ok && <p className="small">{added.text}</p>}
              {added && !added.ok && (
                <p role="alert" className="field-error">
                  {named(added.text)}
                </p>
              )}
            </>
          )}
          {employers.length > 0 && (
            <>
              <h3 className="label">Repeat employers</h3>
              <ul className="market-skills">
                {employers.map((c) => {
                  const f = follows[c.name]
                  const followed = c.followed || f?.kind === 'followed'
                  return (
                    <li key={c.name} aria-label={c.name}>
                      <span>{c.name}</span>
                      <span className="small muted">{` · ${c.count} ads`}</span>
                      {followed && <span className="small">{' · followed'}</span>}
                      {!followed && (
                        <button type="button" className="quiet" disabled={f?.kind === 'pending'} aria-label={`Follow ${c.name}`} onClick={() => void follow(c.name)}>
                          Follow
                        </button>
                      )}
                      {f?.kind === 'note' && (
                        <span role="alert" className="small field-error">
                          {named(f.text)}
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
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
