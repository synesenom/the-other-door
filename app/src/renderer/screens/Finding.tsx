import { AppName, named } from './AppName'
import { CheckMark, CrossMark, WarningMark } from './CheckMark'
import { useEffect, useState } from 'react'
import { scoreText, showRun } from '../api'
import type { RunBoard, RunRecord, StepRow } from '../api'
import type { DiscoveryChoice } from './onboarding/reducer'
import { andList, LegalLink } from './discovery-notice'
import { activityText } from './run-text'

export type FindingState =
  /** A run of this window's own; `startedAt` is when it was asked for, until the board says. */
  | { kind: 'running'; startedAt?: string }
  /** `firstRun`: the run started when the onboarding was saved (search and match only). */
  | { kind: 'summary'; record: RunRecord; firstRun?: boolean }
  | { kind: 'error'; message: string }

const STEPS = ['search', 'discover', 'follow', 'collect', 'match'] as const
const TITLES: Record<string, string> = { search: 'Search', discover: 'Discover', follow: 'Follow', collect: 'Collect', match: 'Match' }
const WAITING: Record<string, string> = {
  search: 'Reads the job boards for your country',
  discover: 'Finds employers hiring for your keywords',
  follow: "Finds those employers' career pages",
  collect: 'Reads the career pages you follow',
  match: 'Scores the new ads against your CV',
}
const UNITS: Record<string, string> = { search: 'boards', follow: 'candidates', collect: 'employers', match: 'scored' }

const clock = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}


function elapsedText(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  return s < 60 ? `${s} s` : `${Math.round(s / 60)} min`
}

function secondsBetween(from?: string, to?: number | string): number | null {
  if (!from) return null
  const a = Date.parse(from)
  const b = typeof to === 'string' ? Date.parse(to) : (to ?? Date.now())
  return Number.isNaN(a) || Number.isNaN(b) ? null : (b - a) / 1000
}

const skippedWhy = (reason: string) => (reason === '--skip' || !reason ? 'left out of this run' : reason)
// a source never chosen is said by the warning line under the step, one turned off by nothing: never by its config key
const NOT_CHOSEN = /^\w+_discovery (not chosen|is off)$/
const skippedText = (reason: string) => (reason.split('; ').every((r) => NOT_CHOSEN.test(r)) ? 'Skipped' : `Skipped: ${skippedWhy(reason)}`)


/** What a running step is doing, in one line: its host, its count, the pass it is in. A step that lists
 *  its sources (Search, Discover) has no count: the list shows how far it got. */
function runningLine(step: StepRow): string {
  // discover: what the source is doing, in words
  if (step.requests) {
    const source = step.items?.find((it) => it.state === 'running')?.name
    if (!source) return ''
    return step.request?.startsWith('job page') ? `Reading job pages on ${source}` : `Searching ${source}`
  }
  const parts: string[] = []
  if (step.hosts?.length) parts.push(`Reading ${step.hosts[0]}`)
  if (step.request) parts.push(step.request)
  else if (step.phase) parts.push(step.phase)
  if (step.items?.length) return parts.join(' · ')
  if (step.total) parts.push(`${step.done ?? 0} of ${step.total} ${UNITS[step.name] ?? ''}`.trim())
  else if (step.done) parts.push(`${step.done} ${UNITS[step.name] ?? ''}`.trim())
  return parts.join(' · ')
}

function Row({ step, index, now, unchosen, onChoose }: { step: StepRow; index: number; now: number; unchosen: DiscoveryChoice[]; onChoose?: () => void }) {
  const { status } = step
  // the bar: a step's own count; a step that lists its sources has none (the list shows how far it got)
  const [done, total] = step.status !== 'running' || step.items?.length ? [0, 0] : [step.done ?? 0, step.total ?? 0]
  const secs = status === 'running' ? secondsBetween(step.started_at, now) : status === 'done' || status === 'failed' ? secondsBetween(step.started_at, step.finished_at) : null
  const detail = status === 'skipped' ? skippedText(step.detail) : status === 'waiting' ? '' : status === 'running' ? runningLine(step) : step.detail
  // the boards or sources being read, until every one of them is
  const items = status === 'running' && step.items?.some((it) => it.state !== 'done') ? step.items : []
  // postings found so far: beside its board when it is listed, in a line of their own for the rest (Collect's employers)
  const listed = new Set((step.items ?? []).map((it) => it.id))
  const sites = status === 'running' ? Object.entries(step.sites ?? {}).filter(([site]) => !listed.has(site)) : []
  return (
    <li className={`step step-${status}`}>
      <span className="step-mark" aria-hidden="true">
        {status === 'done' ? <CheckMark /> : index + 1}
      </span>
      <div className="step-body">
        <div className="title-line">
          <h2 className="display-s step-name">{TITLES[step.name] ?? step.name}</h2>
          {/* what a step does, beside its name until it starts; then the line below says what it is doing */}
          {status === 'waiting' && WAITING[step.name] && <span className="small muted">{WAITING[step.name]}</span>}
        </div>
        {detail && <p className="small muted">{detail}</p>}
        {total > 0 && (
          <div className="bar" role="progressbar" aria-label={`${TITLES[step.name] ?? step.name} progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((done / total) * 100)}>
            <span style={{ width: `${Math.min(100, (done / total) * 100)}%` }} />
          </div>
        )}
        {items.length + unchosen.length > 0 && (
          <ul className="step-items small" aria-label={`${TITLES[step.name] ?? step.name} sources`}>
            {items.map((it) => (
              <li key={it.id} className={`step-item marked step-item-${it.state}`}>
                <span className="mark step-item-mark" aria-hidden="true">
                  {it.state === 'done' ? <CheckMark /> : it.state === 'failed' ? <CrossMark /> : ''}
                </span>
                <span>
                  {it.name}
                  {step.sites?.[it.id] ? <span className="muted"> · {step.sites[it.id]}</span> : null}
                  {/* a board's count stands still while it reads ads: say what it is doing */}
                  {it.state === 'running' && it.activity ? <span className="muted"> · {activityText(it.activity)}</span> : null}
                </span>
              </li>
            ))}
            {/* a source never chosen sits among the ones read, saying so */}
            {unchosen.map((d) => (
              <li key={d.key} className="step-item marked">
                <span className="mark"><WarningMark /></span>
                <span>
                  {d.label}{' '}
                  <span className="muted">
                    (not enabled,{' '}
                    <button type="button" className="link-inline" aria-label={`Enable ${d.label}`} onClick={onChoose}>
                      enable
                    </button>
                    )
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
        {sites.length > 0 && (
          <p className="step-sites small muted">
            {sites.map(([site, n]) => (
              <span key={site}>{`${site} ${n}`}</span>
            ))}
          </p>
        )}
      </div>
      <span className="step-time small muted">{secs !== null && status !== 'waiting' && status !== 'skipped' ? elapsedText(secs) : ''}</span>
    </li>
  )
}

/** Postings the sites that worked handed over (search and collect), the way `core/runs.postings_scraped` counts. */
function postingsFound(record: RunRecord): number {
  const sites = [...(record.search?.sites ?? []), ...(record.collect?.sites ?? [])]
  return sites.filter((s) => s.outcome === 'ok').reduce((sum, s) => sum + (s.count ?? 0), 0)
}

/** The run in one line, for a run with nothing new above the bar; null when the record lacks the counts. */
export function runAccount(record: RunRecord): string | null {
  const m = record.match
  if (!m || typeof m.scored !== 'number' || typeof m.min_score !== 'number') return null
  const found = postingsFound(record)
  const bar = `${Math.round(m.min_score * 100)}%`
  const seen = m.above_threshold ?? 0
  const reached = seen > 0 ? `${seen} reached your bar (${bar}), none new` : `none reached your bar (${bar})`
  const scored = m.scored === 0 ? 'none close enough to score' : `${m.scored} close enough to score`
  return `${found} ${found === 1 ? 'job' : 'jobs'} found, ${scored}${m.scored === 0 ? '' : `, ${reached}`}`
}

const SKIPPED_CAREER_STEPS = ['discover', 'follow', 'collect']

/** A first run with fewer new matches than this reminds about the discovery sources left off. */
export const FEW_MATCHES = 3

/** One quiet line: the sources exist and are off. It informs, never recommends: their terms forbid automated access. */
function DiscoveryReminder({ sources, onChoose }: { sources: DiscoveryChoice[]; onChoose?: () => void }) {
  return (
    <p role="note" aria-label="Employer discovery" className="small muted">
      <AppName /> can also find employers on {andList(sources.map((d) => d.label))}, by reading their public job search. Their terms forbid automated access, so this is at
      your own risk: read the <LegalLink />.{' '}
      <button type="button" className="link-inline" onClick={onChoose}>
        Turn it on in Settings
      </button>
    </p>
  )
}

/** The sites of a record that did not work, each in a sentence. */
function Summary({
  record,
  onViewMatches,
  reminder,
  onChooseDiscovery,
  onFollowEmployers,
  onLowerBar,
  onCheckSearch,
}: {
  record: RunRecord
  onViewMatches: () => void
  reminder: DiscoveryChoice[]
  onChooseDiscovery?: () => void
  onFollowEmployers?: () => void
  onLowerBar?: () => void
  onCheckSearch?: () => void
}) {
  const n = record.new_above_threshold.length
  const account = n === 0 ? runAccount(record) : null
  const careerNote = account !== null && SKIPPED_CAREER_STEPS.some((step) => step in (record.skipped ?? {}))
  return (
    <section className="summary-card" aria-label="Run summary">
      <h2 className="display-l">{n === 0 ? 'No new matches' : `${n} new ${n === 1 ? 'match' : 'matches'}`}</h2>
      {record.top.length > 0 && (
        <ul className="summary-top">
          {record.top.map((t) => (
            <li key={t.id}>
              <span className="summary-job">
                <span className="title">{t.title}</span>
                <span className="small muted">{t.company}</span>
              </span>
              <span className="score-s">{scoreText(t.score)}</span>
            </li>
          ))}
        </ul>
      )}
      {account !== null && <p className="body">{account}</p>}
      {careerNote && <p className="small muted">The next full run also reads employers' own career sites.</p>}
      <p className="small muted">Took {elapsedText(record.elapsed_s)}</p>
      {reminder.length > 0 && <DiscoveryReminder sources={reminder} onChoose={onChooseDiscovery} />}
      <div className="actions">
        <button type="button" className="primary" onClick={onViewMatches}>
          View matches
        </button>
        <button type="button" className="quiet" onClick={() => void showRun(record.started_at)}>
          Show run record
        </button>
      </div>
      {account !== null && (onFollowEmployers || onLowerBar || onCheckSearch) && (
        <div className="actions">
          {onFollowEmployers && (
            <button type="button" className="quiet" onClick={onFollowEmployers}>
              Follow employers
            </button>
          )}
          {onLowerBar && (
            <button type="button" className="quiet" onClick={onLowerBar}>
              Lower the bar
            </button>
          )}
          {onCheckSearch && (
            <button type="button" className="quiet" onClick={onCheckSearch}>
              Check your search terms
            </button>
          )}
        </div>
      )}
    </section>
  )
}

export function Finding({
  state,
  board,
  onStart,
  onStop,
  onViewMatches,
  discoveryUnchosen = [],
  discoveryOff = [],
  onChooseDiscovery,
  onFollowEmployers,
  onLowerBar,
  onCheckSearch,
}: {
  /** null only while watching a run started elsewhere: this window has none of its own */
  state: FindingState | null
  board: RunBoard
  /** The discovery sources serving the profile's city that were never chosen, said under Discover. */
  discoveryUnchosen?: DiscoveryChoice[]
  /** The discovery sources serving the profile's city, all off: a first run with few matches says they exist. */
  discoveryOff?: DiscoveryChoice[]
  /** Opens Profile, where they are chosen. */
  onChooseDiscovery?: () => void
  /** The zero-match card's actions, each opening a Profile section; none given, no button (the phone has no Profile). */
  onFollowEmployers?: () => void
  onLowerBar?: () => void
  onCheckSearch?: () => void
  onStart: () => void
  onStop: () => void
  onViewMatches: () => void
}) {
  const [stopping, setStopping] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const live = board.active
  useEffect(() => {
    if (!live && state?.kind !== 'running') return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [live, state?.kind])

  const startedAt = board.active ? board.started_at : state?.kind === 'running' ? state.startedAt : undefined
  const watching = board.active && !board.own // somebody else's run: read only
  const showing = state?.kind === 'running' || watching
  const steps: StepRow[] =
    board.active && board.steps.length > 0 ? board.steps : STEPS.map((name) => ({ name, status: 'waiting' as const, detail: '' }))

  return (
    <div className="finding">
      <div className="finding-head">
        <h1 className="display-l">Finding jobs</h1>
        {/* on the title's line, where you look when you open the screen; a run elsewhere is not this window's to stop */}
        {showing && !watching && (
          <button
            type="button"
            className="secondary"
            title="Nothing is lost: the next run picks up where this one stopped."
            disabled={stopping}
            onClick={() => {
              setStopping(true)
              onStop()
            }}
          >
            {stopping ? 'Stopping…' : 'Stop'}
          </button>
        )}
      </div>
      {showing && (
        <>
          {watching ? (
            <p role="status" className="subtitle">
              {`A run started elsewhere is in progress${startedAt ? ` (started ${clock(startedAt)})` : ''}`}
            </p>
          ) : (
            <p className="subtitle">
              {startedAt ? `Started ${clock(startedAt)} · ` : ''}you can switch screens while it runs; quitting <AppName /> stops it.
            </p>
          )}
          <ol className="steps" aria-label="Steps">
            {steps.map((s, i) => (
              // the sources never enabled are said once Discover has its turn, not while it waits
              <Row key={s.name} step={s} index={i} now={now} unchosen={s.name === 'discover' && s.status !== 'waiting' ? discoveryUnchosen : []} onChoose={onChooseDiscovery} />
            ))}
          </ol>
        </>
      )}
      {state?.kind === 'summary' && !watching && (
        <Summary
          record={state.record}
          onViewMatches={onViewMatches}
          reminder={state.firstRun && state.record.new_above_threshold.length < FEW_MATCHES ? discoveryOff : []}
          onChooseDiscovery={onChooseDiscovery}
          onFollowEmployers={onFollowEmployers}
          onLowerBar={onLowerBar}
          onCheckSearch={onCheckSearch}
        />
      )}
      {!showing && state && state.kind !== 'summary' && (
        <>
          {state.kind === 'error' && (
            <p role="alert" className="error">
              {named(`The other door could not start the run: ${state.message}`)}
            </p>
          )}
          <div className="actions">
            <button type="button" className="primary" onClick={onStart}>
              Find new jobs
            </button>
          </div>
        </>
      )}
    </div>
  )
}
