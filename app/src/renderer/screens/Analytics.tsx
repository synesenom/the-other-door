import { useEffect, useState } from 'react'
import { statusSummary, type CostBlock, type StatusSummary } from '../api'
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

function Usage({ cost }: { cost: CostBlock | null }) {
  if (!cost) return <p className="small muted">What Claude's work costs shows here after your first search.</p>
  const per = [
    cost.per_run.find ? `${usd(cost.per_run.find)} a search` : null,
    cost.per_run.prepare ? `${usd(cost.per_run.prepare)} an application` : null,
  ].filter(Boolean)
  const note = `Last ${cost.days} days at API prices, not a bill${per.length ? ` · about ${per.join(', ')}` : ''}`
  return (
    <>
      <div className="part-head">
        <p className="display-s">{cost.activities.length > 0 ? usd(cost.usd) : `Nothing in the last ${cost.days} days`}</p>
        {/* the long form on hover: the plan is not charged per call */}
        <p className="small muted" title="What these calls would cost on Claude's API. Your plan is not charged per call.">
          {note}
        </p>
      </div>
      {cost.activities.length > 0 && (
        <ul className="usage-list">
          {cost.activities.map((a) => (
            <li key={a.activity} className="usage-activity">
              <div className="usage-row">
                <h3 className="body">{a.label}</h3>
                <span className="usage-figures">
                  <span className="small muted">{`${a.count} ${a.count === 1 ? (SINGULAR[a.of] ?? a.of) : a.of}`}</span>
                  <span className="body">{usd(a.usd)}</span>
                </span>
              </div>
              <div className="bar" aria-hidden="true">
                <span style={{ width: `${cost.usd ? Math.round((a.usd / cost.usd) * 100) : 0}%` }} />
              </div>
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
    </>
  )
}

/**
 * Analytics: how it is going, read-only (#64). Claude usage first: what the last week's calls cost at API
 * prices per activity, and one search and one prepared application. Not the plan's window: that is live, and
 * this screen is about the days gone by. Reads
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
          {summary && <Usage cost={summary.cost ?? null} />}
        </section>
      </div>
      <PageSections sections={PARTS} />
    </div>
  )
}

const PARTS = [{ id: 'analytics-usage', label: 'Claude usage' }]
