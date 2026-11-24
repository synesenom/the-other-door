import { useEffect, useState } from 'react'
import { call } from '../api'
import { CheckMark, CrossMark } from './CheckMark'
import { Spinner } from './Spinner'

interface MarketReport {
  skills: { name: string; count: number; share: number; have: boolean }[]
}

const SKILLS_SHOWN = 8
const pct = (share: number) => `${Math.round(share * 100)}%`

/** One column of the market's skills, as a posting's: the CV's with the check, the rest with the cross. */
function SkillColumn({ name, skills, have }: { name: string; skills: MarketReport['skills']; have: boolean }) {
  return (
    <ul className="market-skills small" aria-label={name}>
      {skills.map((s) => (
        <li key={s.name} className={`marked ${have ? 'skill-fits' : 'skill-gap'}`} aria-label={`${s.name}, ${have ? 'in your CV' : 'not in your CV'}`}>
          <span className="mark" aria-hidden="true">
            {have ? <CheckMark /> : <CrossMark />}
          </span>
          <span>
            {s.name}
            <span className="muted">{` · ${pct(s.share)} of the ads`}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

/**
 * "Market", in Analytics (#65): the skills the ads of the last 30 days ask for most, each with its share of the ads,
 * a check when the CV has it and a cross when it does not, in two columns as a posting's skills. The market tool runs
 * once when the screen opens and writes no report. A skill the CV lacks leads to the CV by one button under the list.
 */
export function Market({ onOpenCv }: { onOpenCv?: () => void } = {}) {
  const [state, setState] = useState<{ kind: 'counting' } | { kind: 'done'; m: MarketReport } | { kind: 'error' }>({ kind: 'counting' })

  useEffect(() => {
    let live = true
    call<MarketReport>('market', { save: false }).then(
      (m) => live && setState({ kind: 'done', m }),
      () => live && setState({ kind: 'error' }),
    )
    return () => {
      live = false
    }
  }, [])

  // a section of Analytics, which stands without it: a count that failed is said nowhere and left out (principle 9)
  if (state.kind === 'error') return null
  const skills = state.kind === 'done' ? state.m.skills.slice(0, SKILLS_SHOWN) : []
  const missing = skills.filter((s) => !s.have).length
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
          <div className="columns">
            <SkillColumn name="In your CV" skills={skills.filter((s) => s.have)} have />
            <SkillColumn name="Not in your CV" skills={skills.filter((s) => !s.have)} have={false} />
          </div>
          {missing > 0 && onOpenCv && (
            <p>
              <button type="button" className="secondary" onClick={onOpenCv}>
                {`Add the missing ${missing === 1 ? 'skill' : 'skills'} to your CV`}
              </button>
            </p>
          )}
        </>
      )}
    </section>
  )
}
