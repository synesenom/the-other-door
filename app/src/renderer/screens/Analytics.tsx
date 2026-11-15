import { useEffect, useState } from 'react'
import { statusSummary, type CostBlock, type PassRate, type ScoreBands, type StatusSummary } from '../api'
import { Market } from './Market'
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

/**
 * Applications (#66, #87): the interview rate, how many applications with an outcome (an interview, a rejection or
 * no reply) led to an interview: how well the matches fit. Where each application stands is the Applications
 * board's columns, not repeated here.
 */
function Rate({ rate }: { rate: PassRate | undefined }) {
  if (!rate || !rate.decided || rate.rate === null) return <p className="small muted">Your interview rate shows here once an application has an outcome.</p>
  const range = rate.low !== null && rate.high !== null ? `, likely between ${pct(rate.low)} and ${pct(rate.high)}` : ''
  return (
    <div className="part-head">
      <p className="display-s">{pct(rate.rate)}</p>
      <p className="small">{`of your applications with an outcome (an interview, a rejection or no reply) led to an interview: ${rate.passed} of ${rate.decided}${range}.`}</p>
    </div>
  )
}

function bandLine(label: string, rate: PassRate): string {
  const range = rate.low !== null && rate.high !== null ? `, likely between ${pct(rate.low)} and ${pct(rate.high)}` : ''
  return `${label}: ${rate.passed} of ${rate.decided} led to an interview${range}.`
}

/** The same rate for the better-scored half of the matches and the half near the minimum score (#90). */
function ScoreBandsView({ bands }: { bands: ScoreBands }) {
  return (
    <div className="part-head">
      <p className="small">{bandLine('Best-scored matches', bands.top)}</p>
      <p className="small">{bandLine('Matches near your minimum score', bands.near_min)}</p>
      {bands.reading === 'near_min_lower' && (
        <p className="small">Matches near your minimum score led to an interview less often: consider raising it.</p>
      )}
    </div>
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
 * Analytics: how it is going, read-only (#64, #66, #87, #65). Applications first (the interview rate, #87), then Claude usage: what the last week's calls cost at API prices per activity, and
 * one search and one prepared application (not the plan's window: that is live, and this screen is about the days
 * gone by), then Market (the skills the ads ask for most, #65). Reads `status_summary` once on opening; a failed
 * read is said nowhere (the next opening reads again).
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
        {summary?.pass_rates && (
          <section className="part" aria-labelledby="analytics-applications">
            <h2 className="display-s" id="analytics-applications">
              Applications
            </h2>
            <Rate rate={summary.pass_rates.application} />
            {summary.pass_rates.application?.rate != null && summary.pass_rates_by_score && (
              <ScoreBandsView bands={summary.pass_rates_by_score} />
            )}
          </section>
        )}
        <section className="part" aria-labelledby="analytics-usage">
          <h2 className="display-s" id="analytics-usage">
            Claude usage
          </h2>
          {summary && <Usage cost={summary.cost ?? null} />}
        </section>
        <Market />
      </div>
      <PageSections sections={summary?.pass_rates ? [APPLICATIONS, USAGE, MARKET] : [USAGE, MARKET]} />
    </div>
  )
}

const APPLICATIONS = { id: 'analytics-applications', label: 'Applications' }
const USAGE = { id: 'analytics-usage', label: 'Claude usage' }
const MARKET = { id: 'analytics-market', label: 'Market' }
