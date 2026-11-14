import { useEffect, useState, type ReactNode } from 'react'
import { statusSummary, type CostBlock, type PassRate, type StatusSummary } from '../api'
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

const pct = (x: number) => `${Math.round(x * 100)}%`

/** One stacked bar and its legend, as the cost breakdown draws them: each segment a share of `total`. */
function Split({ title, total, parts, children }: { title: string; total: number; parts: { label: string; count: number; tone: string }[]; children?: ReactNode }) {
  const shown = parts.filter((p) => p.count > 0)
  return (
    <div className="split" role="group" aria-label={title}>
      <h3 className="body">
        {title}
        <span className="muted">{` · ${total}`}</span>
      </h3>
      <div className="usage-stack" role="img" aria-label={shown.map((p) => `${p.label} ${p.count}`).join(', ')}>
        {shown.map((p) => (
          <span key={p.label} className={p.tone} style={{ flexGrow: Math.round(share(p.count, total) * 1000) / 1000 }} />
        ))}
      </div>
      <ul className="usage-list split-legend">
        {shown.map((p) => (
          <li key={p.label} className="usage-row small">
            <span>
              <span className={`usage-dot ${p.tone}`} aria-hidden="true" />
              {p.label}
            </span>
            <span>{p.count}</span>
          </li>
        ))}
      </ul>
      {children}
    </div>
  )
}

/** The interview rate: how many answered applications led to an interview, the measure of how well the matches fit. */
function Rate({ rate }: { rate: PassRate | undefined }) {
  if (!rate || !rate.decided || rate.rate === null) return <p className="small muted">Your interview rate shows here once employers answer.</p>
  const range = rate.low !== null && rate.high !== null ? `, likely between ${pct(rate.low)} and ${pct(rate.high)}` : ''
  return (
    <div className="part-head">
      <p className="display-s">{pct(rate.rate)}</p>
      <p className="small">{`of your answered applications led to an interview (${rate.passed} of ${rate.decided})${range}.`}</p>
    </div>
  )
}

/**
 * Applications (#66, #87): what you did with your matches, apart from how the employers answered. First the
 * interview rate of the answered applications (how well the matches fit), then two stacked bars like the cost
 * breakdown, each job in one segment: your matches (applied, prepared, not yet; the ones set aside said apart) and
 * your applications by where each stands now (`status_summary.standing`).
 */
function Applications({ summary }: { summary: StatusSummary }) {
  const by = summary.pipeline?.above_threshold_by_status ?? { unapplied: 0, prepared: 0, applied: 0, discarded: 0 }
  const s = summary.standing!
  const matches = by.unapplied + by.prepared + by.applied
  const sent = s.offer + s.interviewing + s.waiting + s.rejected + s.ghosted + s.withdrawn
  if (matches === 0 && sent === 0) return <p className="small muted">Your applications show here once you have matches.</p>
  const closed = s.rejected + s.ghosted + s.withdrawn
  return (
    <>
      <Rate rate={summary.pass_rates?.application} />
      {matches > 0 && (
        <Split
          title="Your matches"
          total={matches}
          parts={[
            { label: 'Applied', count: by.applied, tone: 'usage-tone-0' },
            { label: 'Prepared, not sent', count: by.prepared, tone: 'usage-tone-3' },
            { label: 'Not yet', count: by.unapplied, tone: 'usage-tone-2' },
          ]}
        >
          {by.discarded > 0 && <p className="small muted">{`And ${by.discarded} you set aside as not for me.`}</p>}
        </Split>
      )}
      {sent > 0 && (
        <Split
          title="Your applications"
          total={sent}
          parts={[
            { label: 'Offer', count: s.offer, tone: 'usage-tone-0' },
            { label: 'Interviewing', count: s.interviewing, tone: 'usage-tone-3' },
            { label: 'Waiting for an answer', count: s.waiting, tone: 'usage-tone-1' },
            { label: s.withdrawn > 0 ? 'Rejected, ghosted or withdrawn' : 'Rejected or ghosted', count: closed, tone: 'usage-tone-2' },
          ]}
        />
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
 * Analytics: how it is going, read-only (#64, #66). Applications first (`status_summary.funnel`, each stage as a
 * share of the one before), then Claude usage: what the last week's calls cost at API
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
        {summary?.standing && (
          <section className="part" aria-labelledby="analytics-applications">
            <h2 className="display-s" id="analytics-applications">
              Applications
            </h2>
            <Applications summary={summary} />
          </section>
        )}
        <section className="part" aria-labelledby="analytics-usage">
          <h2 className="display-s" id="analytics-usage">
            Claude usage
          </h2>
          {summary && <Usage cost={summary.cost ?? null} />}
        </section>
      </div>
      <PageSections sections={summary?.standing ? [APPLICATIONS, USAGE] : [USAGE]} />
    </div>
  )
}

const APPLICATIONS = { id: 'analytics-applications', label: 'Applications' }
const USAGE = { id: 'analytics-usage', label: 'Claude usage' }
