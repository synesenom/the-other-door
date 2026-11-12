import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { AppName, named } from './AppName'
import { call, errorText, statusSummary } from '../api'
import type { Document, Match, Opening, MatchesResult, SetStatusResult, StatusSummary } from '../api'
import { useNarrow } from '../useNarrow'
import { ImportDialog } from './ImportDialog'
import { andList, LegalLink } from './discovery-notice'
import { MatchRow } from './MatchRow'
import { ReadingPane } from './ReadingPane'
import type { PaneView } from './ReadingPane'
import { seenHere, unsentSeen } from './seen-store'
import { statusNotice } from './statusNotice'
import { Spinner } from './Spinner'
import { runText } from './run-text'
import { Switch } from './Switch'

/** Why Find new jobs is off while a Prepare runs (the sidebar's button and this header's pill). */
export const PREPARING_TIP = 'Preparing an application. Find new jobs again when it is done.'

/** What an empty list says: nothing scored, nothing new since a review, or nothing at the bar. */
export function emptyText(scored: number | undefined, minScore: number | undefined, reviewedAt: string | null, newOnly: boolean): string {
  if (scored === undefined || scored === 0) return 'Nothing scored yet. Find new jobs to start.'
  if (newOnly && reviewedAt) return 'Nothing new since your last review.'
  const bar = minScore === undefined ? '' : ` (${Math.round(minScore * 100)}%)`
  return `Nothing has reached your bar${bar} yet.`
}

/** Above the weak matches: how many, and what would widen the search. It informs, never recommends: the sources' terms forbid automated access. */
function WeakLine({ weak, onChooseDiscovery, onCheckSearch }: { weak: NonNullable<MatchesResult['weak']>; onChooseDiscovery?: () => void; onCheckSearch?: () => void }) {
  const n = weak.matches.length
  const head = `${n} weak ${n === 1 ? 'match' : 'matches'} found.`
  if (weak.hint === 'sources')
    return (
      <p className="body muted">
        {head} <AppName /> can also find employers on {andList(weak.sources.map((s) => s.label))}, at your own risk: read the{' '}
        {onChooseDiscovery ? (
          <>
            <LegalLink />. <button type="button" className="link-inline" onClick={onChooseDiscovery}>Turn it on in Settings</button>
          </>
        ) : (
          'legal disclaimer.'
        )}
      </p>
    )
  return (
    <p className="body muted">
      {head}{' '}
      {onCheckSearch ? (
        <button type="button" className="link-inline" onClick={onCheckSearch}>Broaden your search keywords to find closer ones.</button>
      ) : (
        'Broaden your search keywords to find closer ones.'
      )}
    </p>
  )
}

export function Matches({
  onPushed,
  onFindJobs,
  preparing = false,
  finding,
  newOnlyFirst = false,
  opening,
  onOpened,
  onLowerBar,
  onChooseDiscovery,
  onCheckSearch,
}: {
  onPushed?: (pushed: boolean) => void
  /** Starts a run (or, while one is going, goes to it): the "Find new jobs" pill of a narrow window, which has no sidebar foot. */
  onFindJobs?: () => void
  /** A Prepare is running: the server refuses a run until it is done. */
  preparing?: boolean
  /** A run is going: ours (the pill goes to it) or another process's (the pill is off). */
  finding?: 'own' | 'elsewhere'
  /** Open on "New only" (after a run's "View matches"). */
  newOnlyFirst?: boolean
  /** A clicked notification names a job to open (see App). */
  opening?: Opening | null
  /** The opening was applied: App lets go of it. */
  onOpened?: () => void
  /** Opens Profile at the bar (`min_score`); none given (the phone), no button. */
  onLowerBar?: () => void
  /** Opens Profile at the employers (the discovery sources); none given (the phone), the line is plain text. */
  onChooseDiscovery?: () => void
  /** Opens Profile at the search keywords; none given (the phone), the line is plain text. */
  onCheckSearch?: () => void
} = {}) {
  const narrow = useNarrow()
  const [pushed, setPushed] = useState(false)
  const [newOnly, setNewOnly] = useState(newOnlyFirst)
  const [summary, setSummary] = useState<StatusSummary | null>(null)
  const [matches, setMatches] = useState<Match[] | null>(null)
  const [listed, setListed] = useState<{ scored?: number; minScore?: number; reviewedAt: string | null }>({ reviewedAt: null })
  const [weak, setWeak] = useState<MatchesResult['weak']>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [view, setView] = useState<PaneView>('posting')
  const [initialDoc, setInitialDoc] = useState<Document | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)

  const [notice, setNotice] = useState<{ text: string; warning?: string } | null>(null)
  const order = useRef<string[]>([])
  const sendSeen = useCallback((id: string) => {
    call('mark_seen', { job_id: id }).then(
      () => unsentSeen.delete(id),
      () => undefined,
    )
  }, [])
  // an imported ad the user opened: it stays selected though the list does not hold it
  const opened = useRef<string | null>(null)
  const [importing, setImporting] = useState(false)
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  /** Bumped by each list read: "New only" takes the new ones afresh from it. */
  const [loaded, setLoaded] = useState(0)

  useEffect(() => {
    let live = true
    setMatches(null)
    setError(null)
    call<MatchesResult>('list_matches').then(
      (m) => {
        if (!live) return
        const before = order.current
        const weakIds = m.matches.length === 0 && m.weak ? m.weak.matches.map((x) => x.id) : []
        order.current = [...m.matches.map((x) => x.id), ...weakIds]
        setWeak(m.weak ?? null)
        setMatches(m.matches.map((x) => (seenHere.has(x.id) ? { ...x, is_new: false } : x)))
        setListed({ scored: m.scored, minScore: m.min_score, reviewedAt: m.last_reviewed_at ?? null })
        setLoaded((n) => n + 1)
        unsentSeen.forEach(sendSeen)
        setSelected((cur) => {
          if (!cur) return null
          const rows = [...m.matches, ...(m.matches.length === 0 && m.weak ? m.weak.matches : [])]
          if (cur === opened.current || rows.some((x) => x.id === cur)) return cur
          // the selected posting left the list: the one that took its place, not the first
          const was = cur ? before.indexOf(cur) : -1
          return rows[Math.max(0, Math.min(was, rows.length - 1))]?.id ?? null
        })
      },
      (e) => live && setError(errorText(e)),
    )
    return () => {
      live = false
    }
  }, [tick, sendSeen])

  useEffect(() => {
    let live = true
    statusSummary().then(
      (s) => {
        if (!live) return
        setSummary(s)
        setSummaryError(null)
      },
      (e) => live && setSummaryError(errorText(e)),
    )
    return () => {
      live = false
    }
  }, [tick])

  // A row opens its posting full width ("← Matches" goes back), as a card does in Applications;
  // on a narrow window the sidebar steps aside too.
  const pushedNow = pushed && selected !== null
  useEffect(() => {
    onPushed?.(narrow && pushedNow)
  }, [narrow, pushedNow, onPushed])

  // The list keeps its place: where it was scrolled when a posting opened, and that row marked.
  const listRef = useRef<HTMLElement | null>(null)
  const listScroll = useRef(0)
  useLayoutEffect(() => {
    if (!pushedNow && listRef.current) listRef.current.scrollTop = listScroll.current
  }, [pushedNow])

  const refresh = useCallback(() => setTick((t) => t + 1), [])

  // A clicked notification names this job: select it, on the view it asked for, though the list may not hold it.
  useEffect(() => {
    if (!opening) return
    const { target } = opening
    opened.current = target.jobId
    setSelected(target.jobId)
    setNotice(null)
    setView(target.screen === 'materials' ? 'materials' : 'posting')
    setInitialDoc(target.screen === 'materials' ? target.document : undefined)
    setPushed(true)
    refresh()
    onOpened?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opening?.n])

  // "New only" filters the list the window has (each match says whether it is new): no call, nothing to wait for.
  // The new ones are taken when the switch turns on or the list is read again, so a match opened under it
  // stays listed (without its dot) until then.
  const newIds = useMemo(
    () => (newOnly && matches ? new Set(matches.filter((m) => m.is_new).map((m) => m.id)) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [newOnly, loaded],
  )
  const shown = newIds && matches ? matches.filter((m) => newIds.has(m.id)) : matches
  // Until a first posting reaches the bar, the empty list shows the best below it, marked weak.
  const weakRows = matches !== null && matches.length === 0 && weak && !(newOnly && listed.reviewedAt) ? weak.matches : []
  const rowsShown = weakRows.length > 0 ? weakRows : (shown ?? [])

  // A match is seen once it is opened: its dot goes.
  useEffect(() => {
    if (!pushed || !selected || seenHere.has(selected)) return
    if (!(matches ?? []).find((m) => m.id === selected)?.is_new) return
    seenHere.add(selected)
    unsentSeen.add(selected)
    setMatches((ms) => ms && ms.map((m) => (m.id === selected ? { ...m, is_new: false } : m)))
    sendSeen(selected)
  }, [pushed, selected, matches, sendSeen])

  const changed = (result: SetStatusResult, title: string) => {
    const status = result.current ?? result.status
    setNotice({ text: statusNotice(status, title), warning: result.warning })
    setView('posting')
    // "Not this one" moves on: the next match opens in its place (the list's refresh picks it).
    // Any other status goes back to the list, which says what changed.
    if (status !== 'discarded') setPushed(false)
    opened.current = null
    refresh()
  }

  // Previous and next match, from the open posting (‹ › or the k and j keys; Esc goes back).
  const ids = rowsShown.map((m) => m.id)
  const at = selected ? ids.indexOf(selected) : -1
  const step = (by: number) => {
    const next = ids[at + by]
    if (at < 0 || !next) return
    setSelected(next)
    setNotice(null)
    opened.current = null
  }
  const stepRef = useRef(step)
  stepRef.current = step
  const onPosting = pushedNow && view === 'posting'
  useEffect(() => {
    if (!onPosting) return
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.metaKey || e.ctrlKey || e.altKey || t?.closest('input, textarea, select, [contenteditable], [role=dialog]')) return
      if (e.key === 'j') stepRef.current(1)
      else if (e.key === 'k') stepRef.current(-1)
      else if (e.key === 'Escape') setPushed(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onPosting])

  // Preparing moves the job out of this list: it stays open while its application is on screen.
  const switchView = (next: PaneView) => {
    if (next === 'materials') {
      opened.current = selected
      refresh()
    }
    setView(next)
  }
  const posting = selected && <ReadingPane jobId={selected} view={view} onView={switchView} onChanged={changed} initialDoc={initialDoc} />
  const noticeLines = notice && (
    <>
      <p role="status" className="notice">
        {named(notice.text)}
      </p>
      {notice.warning && <p className="notice">{named(notice.warning)}</p>}
    </>
  )

  // An open posting, or its prepared application: full width, the list steps aside until "← Matches".
  if (pushedNow || (selected && view === 'materials'))
    return (
      <div className="matches pushed">
        <section className="reading-pane" key={selected}>
          {view === 'posting' && (
            <div className="pushed-bar">
              <button type="button" className="back" onClick={() => setPushed(false)} title="Esc">
                ← Matches
              </button>
              {at >= 0 && ids.length > 1 && (
                <div className="stepper" role="group" aria-label="Previous and next match">
                  <span className="small muted">
                    {at + 1} of {ids.length}
                  </span>
                  <button type="button" className="quiet step" aria-label="Previous match" title="Previous match (k)" disabled={at === 0} onClick={() => step(-1)}>
                    ‹
                  </button>
                  <button type="button" className="quiet step" aria-label="Next match" title="Next match (j)" disabled={at === ids.length - 1} onClick={() => step(1)}>
                    ›
                  </button>
                </div>
              )}
            </div>
          )}
          {noticeLines}
          {posting}
        </section>
      </div>
    )

  return (
    <div className="matches">
      <section className="list-pane" ref={listRef}>
        <div className="list-head">
          {/* As Applications' head: the title on the left, adding a job on the right. */}
          <div className="board-head">
            <h1 className="display-l">Matches</h1>
            <div className="actions head-actions">
              <button type="button" className="secondary" onClick={() => setImporting(true)}>
                Add a job
              </button>
              {/* The sidebar's button starts a run; a narrow window has no sidebar foot, so it is here instead. */}
              {narrow && onFindJobs && (
                <button type="button" className="pill" disabled={finding === 'elsewhere' || preparing} title={preparing ? PREPARING_TIP : undefined} onClick={onFindJobs}>
                  {finding ? 'Finding jobs…' : 'Find new jobs'}
                </button>
              )}
            </div>
          </div>
          {summary?.in_progress && <Spinner message={runText(summary.in_progress)} />}
          <Switch label="New only" checked={newOnly} onChange={setNewOnly} />
        </div>
        {noticeLines}
        {summaryError && <p className="notice small">Could not read the run summary: {summaryError}</p>}
        {matches === null && !error && (
          <p role="status" className="body muted">
            Loading…
          </p>
        )}
        {error && (
          <p role="alert" className="error">
            {named(error)}
          </p>
        )}
        {shown && shown.length === 0 && !error && (
          <div className="empty">
            {weak && weakRows.length > 0 ? (
              <WeakLine weak={weak} onChooseDiscovery={onChooseDiscovery} onCheckSearch={onCheckSearch} />
            ) : (
              <p className="body muted">{emptyText(listed.scored, listed.minScore, listed.reviewedAt, newOnly)}</p>
            )}
            {onLowerBar && listed.scored !== undefined && listed.scored > 0 && !(newOnly && listed.reviewedAt) && (
              <div className="actions">
                <button type="button" className="quiet" onClick={onLowerBar}>
                  Lower the bar
                </button>
              </div>
            )}
          </div>
        )}
        <ul className="rows">
          {rowsShown.map((m) => (
            <MatchRow
              key={m.id}
              match={m}
              weak={weakRows.length > 0}
              selected={m.id === selected}
              onSelect={() => {
                listScroll.current = listRef.current?.scrollTop ?? 0
                setSelected(m.id)
                setView('posting')
                setNotice(null)
                opened.current = null
                setPushed(true)
              }}
            />
          ))}
        </ul>
      </section>
      {importing && (
        <ImportDialog
          onClose={() => setImporting(false)}
          onOpen={(id) => {
            opened.current = id
            setImporting(false)
            setNotice(null)
            setSelected(id)
            setView('posting')
            setPushed(true)
          }}
        />
      )}
    </div>
  )
}
