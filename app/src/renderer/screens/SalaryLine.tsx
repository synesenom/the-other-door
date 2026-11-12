import { openExternal } from '../api'
import type { Salary } from '../api'
import { Hint } from './Hint'

const PERIOD: Record<Salary['period'], string> = { month: 'a month', year: 'a year' }
const POSITION: Record<NonNullable<Salary['position']>, string> = {
  below: 'Your experience puts you below the usual range for this job.',
  within: 'Your experience puts you within the usual range for this job.',
  above: 'Your experience puts you above the usual range for this job.',
}

/** "55,000–70,000 DKK a month, gross", or one figure when the range is one. */
export function salaryRange(s: Salary): string {
  const amount = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 0 })
  const figures = s.low === s.high ? amount(s.low) : `${amount(s.low)}–${amount(s.high)}`
  return `${figures} ${s.currency} ${PERIOD[s.period]}, ${s.gross ? 'gross' : 'net'}`
}

/** "Nov 7", or nothing for a date that cannot be read. */
function asOf(value: string): string | null {
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/**
 * The salary to expect for a job, as `prepare` estimated it: the range, why, and the pages it was read
 * from. Nothing when there is no estimate: one that found no source is not the user's to act on.
 */
export function SalaryLine({ salary }: { salary: Salary | null | undefined }) {
  if (!salary) return null
  const date = asOf(salary.as_of)
  return (
    <section className="salary-line" aria-label="Salary">
      <div className="score-line">
        <p className="body">
          <span className="muted">Salary </span>
          {salaryRange(salary)}
        </p>
        <Hint label="About this estimate">
          {salary.position && `${POSITION[salary.position]} `}
          {salary.basis && `${salary.basis} `}
          {`An estimate from public pages${date ? ` as of ${date}` : ''}, not advice.`}
        </Hint>
      </div>
      <p className="small muted">
        {salary.ad_salary && `The ad says ${salary.ad_salary}. `}
        {'From '}
        {salary.sources.map((s, i) => (
          <span key={s.url}>
            {i > 0 && ', '}
            <button type="button" className="link-inline" onClick={() => void openExternal(s.url)}>
              {s.title}
            </button>
          </span>
        ))}
      </p>
    </section>
  )
}
