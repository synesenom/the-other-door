import { useEffect, useState } from 'react'
import { statusSummary, type CostBlock, type FunnelStage, type PassRate, type StageCounts, type StatusSummary } from '../api'
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

function share(part: number, total: number): number {
  return total > 0 ? part / total : 0
}

/** The tone of the i-th activity (largest first) in the stacked bar and its dot: blue, grey, beige. */
function tone(i: number): string {
  return `usage-tone-${Math.min(i, 2)}`
}

const FUNNEL_LABELS: Record<string, string> = {
  postings: 'Scraped',
  applicable: 'Worth a look',
  matches: 'Matches',
  prepared: 'Prepared',
  applied: 'Applied',
  interview: 'Interview',
  offer: 'Offer',
}

const OUTCOMES: (keyof StageCounts)[] = ['passed', 'rejected', 'ghosted', 'withdrawn', 'pending']

/** "1/2 passed  50% (21–79%)", as `jobs summary` writes it; a dash until a round is decided. */
export function pct(rate: PassRate | undefined): string {
  if (!rate || rate.rate === null || rate.low === null || rate.high === null) return '–'
  return `${rate.passed}/${rate.decided} passed  ${Math.round(rate.rate * 100)}% (${Math.round(rate.low * 100)}–${Math.round(rate.high * 100)}%)`
}

/** The funnel's bars once anything is scraped; the stage table once something is applied. */
function Applications({ funnel, summary }: { funnel: FunnelStage[]; summary: StatusSummary }) {
  const first = funnel[0]?.count ?? 0
  if (first === 0) return <p className="small muted">Your funnel shows here once jobs are found</p>
  const applied = funnel.find((f) => f.stage === 'applied')?.count ?? 0
  const stages: [string, StageCounts][] = [
    ...(summary.application ? ([['application', summary.application]] as [string, StageCounts][]) : []),
    ...Object.entries(summary.interviews ?? {}),
  ]
  return (
    <>
      <ul className="funnel-list">
        {funnel
          .filter((f) => f.stage in FUNNEL_LABELS)
          .map((f) => {
            const label = FUNNEL_LABELS[f.stage]
            return (
              <li key={f.stage} className="funnel-row">
                <span className="body">{label}</span>
                <span className="funnel-bar" role="img" aria-label={`${label}: ${f.count} of ${first}`}>
                  <span style={{ width: `${Math.round(share(f.count, first) * 1000) / 10}%` }} />
                </span>
                <span className="body">{f.count}</span>
              </li>
            )
          })}
      </ul>
      {applied === 0 && <p className="small muted">How each stage went shows here once you have applied</p>}
      {applied > 0 && stages.length > 0 && (
        <>
          <table className="stage-table small">
            <thead>
              <tr>
                <th scope="col">Stage</th>
                {OUTCOMES.map((o) => (
                  <th key={o} scope="col">{o[0].toUpperCase() + o.slice(1)}</th>
                ))}
                <th scope="col">Pass rate</th>
              </tr>
            </thead>
            <tbody>
              {stages.map(([name, counts]) => (
                <tr key={name}>
                  <th scope="row">{name[0].toUpperCase() + name.slice(1)}</th>
                  {OUTCOMES.map((o) => (
                    <td key={o}>{counts[o]}</td>
                  ))}
                  <td>{pct(summary.pass_rates?.[name])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted">pass rate of the decided rounds (± one sigma, Wilson interval)</p>
        </>
      )}
    </>
  )
}

function Usage({ cost }: { cost: CostBlock | null }) {
  if (!cost) return <p className="small muted">What Claude's work costs shows here after your first search.</p>
  const per = [
    cost.per_run.find ? `${usd(cost.per_run.find)} a search` : null,
    cost.per_run.prepare ? `${usd(cost.per_run.prepare)} an application` : null,
  ].filter(Boolean)
  return (
    <>
      <div className="part-head">
        {/* "≈": an estimate, never a price to pay */}
        <p className="display-s">{cost.activities.length > 0 ? `≈ ${usd(cost.usd)}` : `Nothing in the last ${cost.days} days`}</p>
        <p className="small">
          <strong>You don't pay this.</strong> Your Claude plan covers it. The last {cost.days} days, estimated at API prices.
        </p>
        {per.length > 0 && <p className="small muted">{`About ${per.join(', ')}`}</p>}
      </div>
      {cost.activities.length > 0 && (
        // one bar for the whole total, always full: where it went, never a quota filling up
        <div className="usage-stack" role="img" aria-label={cost.activities.map((a) => `${a.label} ${Math.round(share(a.usd, cost.usd) * 100)}%`).join(', ')}>
          {cost.activities.map((a, i) => (
            <span key={a.activity} className={tone(i)} style={{ flexGrow: Math.round(share(a.usd, cost.usd) * 1000) / 1000 }} />
          ))}
        </div>
      )}
      {cost.activities.length > 0 && (
        <ul className="usage-list">
          {cost.activities.map((a, i) => (
            <li key={a.activity} className="usage-activity">
              <div className="usage-row">
                <h3 className="body">
                  <span className={`usage-dot ${tone(i)}`} aria-hidden="true" />
                  {a.label}
                  <span className="muted">{` · ${a.count} ${a.count === 1 ? (SINGULAR[a.of] ?? a.of) : a.of}`}</span>
                </h3>
                <span className="body">{usd(a.usd)}</span>
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
 * Analytics: how it is going, read-only (#64, #66). Applications first (`status_summary.funnel`, how each
 * stage went and its pass rate, as `jobs summary` shows them), then Claude usage: what the last week's calls cost at API
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
        {summary?.funnel && (
          <section className="part" aria-labelledby="analytics-applications">
            <h2 className="display-s" id="analytics-applications">
              Applications
            </h2>
            <Applications funnel={summary.funnel} summary={summary} />
          </section>
        )}
        <section className="part" aria-labelledby="analytics-usage">
          <h2 className="display-s" id="analytics-usage">
            Claude usage
          </h2>
          {summary && <Usage cost={summary.cost ?? null} />}
        </section>
      </div>
      <PageSections sections={summary?.funnel ? [APPLICATIONS, USAGE] : [USAGE]} />
    </div>
  )
}

const APPLICATIONS = { id: 'analytics-applications', label: 'Applications' }
const USAGE = { id: 'analytics-usage', label: 'Claude usage' }
