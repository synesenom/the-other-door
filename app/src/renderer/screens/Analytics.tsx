import { useEffect, useState } from 'react'
import { statusSummary, type CostBlock, type PlanBlock, type StatusSummary } from '../api'
import { PageSections } from './PageSections'

/** Dollars and cents, "<$0.01" for a sliver above nothing. */
export function usd(amount: number): string {
  if (amount > 0 && amount < 0.005) return '<$0.01'
  return `$${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const SINGULAR: Record<string, string> = {
  'postings scored': 'posting scored',
  'applications prepared': 'application prepared',
  'other requests': 'other request',
}

function clock(iso: string): string {
  const d = new Date(iso)
  const today = new Date().toDateString() === d.toDateString()
  return d.toLocaleString(undefined, today ? { hour: '2-digit', minute: '2-digit' } : { weekday: 'short', hour: '2-digit', minute: '2-digit' })
}

/** "42% of this 5-hour window used, resets 15:30 · room for about 6 searches or 2 prepared applications". */
function planLine(plan: PlanBlock): string | null {
  const window = plan.binding ?? (plan.five_hour?.used !== undefined ? 'five_hour' : plan.seven_day?.used !== undefined ? 'seven_day' : null)
  const reading = window ? plan[window] : undefined
  if (!window || reading?.used === undefined) return null
  const resets = reading.resets_at ? `, resets ${clock(reading.resets_at)}` : ''
  const parts = [`${Math.round(reading.used * 100)}% of this ${window === 'five_hour' ? '5-hour' : "week's"} window used${resets}`]
  const room = plan.status !== 'rejected' ? plan.room : null
  if (room) {
    const fits = [
      room.find !== null ? `${room.find} search${room.find === 1 ? '' : 'es'}` : null,
      room.prepare !== null ? `${room.prepare} prepared application${room.prepare === 1 ? '' : 's'}` : null,
    ].filter(Boolean)
    if (fits.length) parts.push(`room for about ${fits.join(' or ')}`)
  }
  return parts.join(' · ')
}

function Usage({ cost, plan }: { cost: CostBlock | null; plan: PlanBlock | null }) {
  const line = plan ? planLine(plan) : null
  const planNote = line && <p className={plan?.warning ? 'small' : 'small muted'}>{plan?.warning ? `${plan.warning}. ${line}` : line}</p>
  if (!cost) return planNote || <p className="small muted">What Claude's work costs shows here after your first search.</p>
  const per = [
    cost.per_run.find ? `One search for new jobs about ${usd(cost.per_run.find)}` : null,
    cost.per_run.prepare ? `${cost.per_run.find ? 'one' : 'One'} prepared application about ${usd(cost.per_run.prepare)}` : null,
  ].filter(Boolean)
  return (
    <>
      <div className="part-head">
        <p className="display-s">{cost.activities.length > 0 ? usd(cost.usd) : `Nothing in the last ${cost.days} days`}</p>
        <p className="small muted">
          In the last {cost.days} days, at Claude's API prices: what these calls would cost on the API. Your plan is not charged per call.
        </p>
      </div>
      {per.length > 0 && <p className="body">{per.join(' · ')}</p>}
      {cost.activities.length > 0 && (
        <ul className="usage-list">
          {cost.activities.map((a) => (
            <li key={a.activity} className="usage-activity">
              <div className="usage-row">
                <h3 className="body">{a.label}</h3>
                <span className="body">{usd(a.usd)}</span>
              </div>
              <div className="bar" aria-hidden="true">
                <span style={{ width: `${cost.usd ? Math.round((a.usd / cost.usd) * 100) : 0}%` }} />
              </div>
              <p className="small muted">{`${a.count} ${a.count === 1 ? (SINGULAR[a.of] ?? a.of) : a.of}`}</p>
              {a.features.length > 1 && (
                <ul className="usage-features">
                  {a.features.map((f) => (
                    <li key={f.feature} className="usage-row small muted">
                      <span>{f.label}</span>
                      <span>{usd(f.usd)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      {planNote}
    </>
  )
}

/**
 * Analytics: how it is going, read-only (#64). Claude usage first: what the last week's calls cost at API
 * prices per activity, one search and one prepared application, and how full the plan's window is. Reads
 * `status_summary` once on opening; a failed read is said nowhere (the next opening reads again).
 */
export function Analytics() {
  const [summary, setSummary] = useState<StatusSummary | null>(null)
  useEffect(() => {
    let live = true
    statusSummary().then(
      (s) => live && setSummary(s),
      () => undefined,
    )
    return () => {
      live = false
    }
  }, [])
  return (
    <div className="page-with-aside">
      <div className="settings">
        <h1 className="display-l">Analytics</h1>
        <section className="part" aria-labelledby="analytics-usage">
          <h2 className="display-s" id="analytics-usage">
            Claude usage
          </h2>
          {summary && <Usage cost={summary.cost ?? null} plan={summary.plan ?? null} />}
        </section>
      </div>
      <PageSections sections={PARTS} />
    </div>
  )
}

const PARTS = [{ id: 'analytics-usage', label: 'Claude usage' }]
