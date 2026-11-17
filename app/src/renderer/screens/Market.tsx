import { useEffect, useState } from 'react'
import { call } from '../api'
import { CheckMark, CrossMark } from './CheckMark'
import { Spinner } from './Spinner'

interface MarketReport {
  skills: { name: string; count: number; share: number; have: boolean }[]
}

const SKILLS_SHOWN = 8
const pct = (share: number) => `${Math.round(share * 100)}%`

/**
 * "Market", in Analytics (#65): the skills the ads of the last 30 days ask for most, each with its share of the ads,
 * a check when the CV has it and a cross when it does not (the marks of a posting's skills). The market tool runs
 * once when the screen opens and writes no report.
 */
export function Market({ onFailed }: { onFailed?: () => void } = {}) {
  const [state, setState] = useState<{ kind: 'counting' } | { kind: 'done'; m: MarketReport } | { kind: 'error' }>({ kind: 'counting' })

  useEffect(() => {
    let live = true
    call<MarketReport>('market', { save: false }).then(
      (m) => live && setState({ kind: 'done', m }),
      () => {
        if (!live) return
        setState({ kind: 'error' })
        onFailed?.()
      },
    )
    return () => {
      live = false
    }
  }, [])

  // a section of Analytics, which stands without it: a count that failed is said nowhere and left out (principle 9)
  if (state.kind === 'error') return null
  const skills = state.kind === 'done' ? state.m.skills.slice(0, SKILLS_SHOWN) : []
  return (
    <section className="part" aria-labelledby="analytics-market">
      <h2 className="display-s" id="analytics-market">
        Market
      </h2>
      {state.kind === 'counting' && <Spinner message="Counting the ads (new skill names may take one short Claude call)…" />}
      {state.kind === 'done' && skills.length === 0 && <p className="small muted">The market shows here once ads are read.</p>}
      {skills.length > 0 && (
        <>
          <p className="small muted">What the ads ask for most.</p>
          <ul className="market-skills small">
            {skills.map((s) => (
              <li key={s.name} className={`marked ${s.have ? 'skill-fits' : 'skill-gap'}`} aria-label={`${s.name}, ${s.have ? 'in your CV' : 'not in your CV'}`}>
                <span className="mark" aria-hidden="true">
                  {s.have ? <CheckMark /> : <CrossMark />}
                </span>
                <span>
                  {s.name}
                  <span className="muted">{` · ${pct(s.share)} of the ads`}</span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
