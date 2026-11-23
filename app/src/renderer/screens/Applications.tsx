import { useCallback, useEffect, useRef, useState } from 'react'
import { ErrorBox, named } from './AppName'
import { call, errorText } from '../api'
import type { Document, Match, Opening, MatchesResult, SetStatusResult } from '../api'
import { useNarrow } from '../useNarrow'
import { ImportDialog } from './ImportDialog'
import { boardColumns, cardNote, silence } from './board'
import { ReadingPane } from './ReadingPane'
import type { PaneView } from './ReadingPane'
import { statusNotice } from './statusNotice'

/** The jobs in play under word headings, in the order of a search; a heading with no job is left out (the phone's list). */
export function groupApplications(rows: Match[]): { heading: string; rows: Match[] }[] {
  return boardColumns(rows, [])
    .slice(0, 4)
    .filter((g) => g.rows.length > 0)
}

/** The dots in words, for a screen reader: "2 rounds passed, one under way: ". */
function roundsText(dots: ('passed' | 'pending')[]): string {
  const passed = dots.filter((d) => d === 'passed').length
  const words = [passed ? `${passed} ${passed === 1 ? 'round' : 'rounds'} passed` : '', dots.includes('pending') ? 'one under way' : ''].filter(Boolean)
  return `${words.join(', ')}: `
}

/** One card: title, company, and when it moved, its interview rounds as dots, or how it ended. */
function Card({ m, onOpen, onGhost, ghosting }: { m: Match; onOpen: () => void; onGhost: () => void; ghosting: boolean }) {
  const note = cardNote(m)
  return (
    <li className="board-card-item">
      <button type="button" className="board-card" onClick={onOpen}>
        <span className="board-card-title">{m.title_en || m.title}</span>
        <span className="board-card-company small muted">{m.company}</span>
        {(note.dots.length > 0 || note.text) && (
          <span className="board-card-note small muted">
            {note.dots.map((d, i) => (
              <span key={i} className={d === 'passed' ? 'round-dot round-passed' : 'round-dot round-next'} aria-hidden="true" />
            ))}
            {note.dots.length > 0 && <span className="visually-hidden">{roundsText(note.dots)}</span>}
            {note.text}
          </span>
        )}
      </button>
      {silence(m) !== null && (
        <button type="button" className="secondary board-card-ghost small" onClick={onGhost} disabled={ghosting}>
          Mark ghosted
        </button>
      )}
    </li>
  )
}

export function Applications({
  onPushed,
  opening,
  onOpened,
}: {
  onPushed?: (pushed: boolean) => void
  /** A clicked notification names a job to open (see App). */
  opening?: Opening | null
  /** The opening was applied: App lets go of it. */
  onOpened?: () => void
} = {}) {
  const narrow = useNarrow()
  const [pushed, setPushed] = useState(false)
  const [rows, setRows] = useState<Match[] | null>(null)
  const [closed, setClosed] = useState<Match[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [view, setView] = useState<PaneView>('posting')
  const [initialDoc, setInitialDoc] = useState<Document | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  // the card being marked ghosted: its button waits for the answer
  const [ghostingId, setGhostingId] = useState<string | null>(null)
  const ghosting = useRef<string | null>(null)
  const [tick, setTick] = useState(0)
  const [importing, setImporting] = useState(false)
  const [notice, setNotice] = useState<{ text: string; warning?: string } | null>(null)
  const opened = useRef<string | null>(null)
  // Ready to send was opened straight from a Prepared card: its back link returns to the board, not to a posting
  const [fromBoard, setFromBoard] = useState(false)

  useEffect(() => {
    let live = true
    setError(null)
    Promise.all([call<MatchesResult>('list_matches', { ongoing: true }), call<MatchesResult>('list_matches', { closed: true })]).then(
      ([on, off]) => {
        if (!live) return
        setRows(on.matches)
        setClosed(off.matches)
      },
      (e) => live && setError(errorText(e)),
    )
    return () => {
      live = false
    }
  }, [tick])

  // A card opens its posting full width ("← Applications" goes back); on a narrow window the sidebar steps aside too.
  const pushedNow = pushed && selected !== null
  useEffect(() => {
    onPushed?.(narrow && pushedNow)
  }, [narrow, pushedNow, onPushed])

  const refresh = useCallback(() => setTick((t) => t + 1), [])

  /** Opens one job on its own page. `keep`: it stays open though it leaves the list; `fromBoard`: Ready to send
   * opened straight from a Prepared card, whose back link returns to the board. */
  const select = (id: string, to: PaneView, { doc, fromBoard = false, keep }: { doc?: Document; fromBoard?: boolean; keep: boolean }) => {
    opened.current = keep ? id : null
    setSelected(id)
    setNotice(null)
    setView(to)
    setInitialDoc(doc)
    setFromBoard(fromBoard)
    setPushed(true)
  }

  // A clicked notification names this job: select it, on the view it asked for, though the list may not hold it.
  useEffect(() => {
    if (!opening) return
    const { target } = opening
    if (target.screen === 'materials') select(target.jobId, 'materials', { doc: target.document, keep: true })
    else select(target.jobId, 'posting', { keep: true })
    refresh()
    onOpened?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opening?.n])

  const told = (result: SetStatusResult, title: string) => {
    setNotice({ text: statusNotice(result.current ?? result.status, title), warning: result.warning })
    refresh()
  }
  const changed = (result: SetStatusResult, title: string) => {
    setPushed(false)
    setView('posting')
    setFromBoard(false)
    told(result, title)
  }
  // No answer for the tracker's days: record it as ghosted, dated today.
  // One call at a time: a second click before the answer would record ghosted twice.
  const markGhosted = (m: Match) => {
    if (ghosting.current) return
    ghosting.current = m.id
    setGhostingId(m.id)
    setError(null)
    call<SetStatusResult>('set_status', { job_id: m.id, status: 'ghosted' })
      .then(
        (result) => told(result, m.title_en || m.title),
        (e) => setError(errorText(e)),
      )
      .finally(() => {
        ghosting.current = null
        setGhostingId(null)
      })
  }

  // Preparing moves the job out of this list: it stays open while its application is on screen.
  const switchView = (next: PaneView) => {
    if (next === 'materials') {
      opened.current = selected
      refresh()
    }
    setView(next)
  }
  const backToBoard = () => {
    setPushed(false)
    setView('posting')
    opened.current = null
    refresh()
  }
  const posting = selected && (
    <ReadingPane
      jobId={selected}
      view={view}
      onView={switchView}
      onChanged={changed}
      initialDoc={initialDoc}
      back={fromBoard ? { label: '← Applications', onBack: backToBoard } : undefined}
    />
  )
  const noticeLines = notice && (
    <>
      <p role="status" className="notice">
        {named(notice.text)}
      </p>
      {notice.warning && <p className="notice">{named(notice.warning)}</p>}
    </>
  )

  // A card's posting, or its prepared application: full width, the board steps aside until "← Applications".
  if (pushedNow || (selected && view === 'materials'))
    return (
      <div className="matches pushed">
        <section className="reading-pane">
          {view === 'posting' && (
            <button type="button" className="back" onClick={() => setPushed(false)}>
              ← Applications
            </button>
          )}
          {posting}
        </section>
      </div>
    )

  // A Prepared card goes straight to its application; the other columns open the posting.
  // Preparing moves a job out of the list once it is sent: a prepared one stays open while on screen
  const open = (m: Match) => {
    const prepared = m.status === 'prepared'
    select(m.id, prepared ? 'materials' : 'posting', { fromBoard: prepared, keep: prepared })
  }
  const columns = boardColumns(rows ?? [], closed)
  const interviewing = columns[2]!.rows.length
  // A phone gets a list, furthest along first (Offer, Interviewing, Applied, Prepared), Closed last.
  const shown = narrow
    ? [...columns.slice(0, 4).reverse().filter((c) => c.rows.length > 0), ...(closed.length > 0 ? [columns[4]!] : [])]
    : columns
  return (
    <div className="board-screen">
      <div className="board-head">
        <div>
          <h1 className="display-l">Applications</h1>
          {rows && rows.length > 0 && <p className="subtitle">{`${rows.length} in play${interviewing ? ` · ${interviewing} in interviews` : ''}`}</p>}
        </div>
        <div className="actions head-actions">
          <button type="button" className="secondary" onClick={() => setImporting(true)}>
            Add a job…
          </button>
        </div>
      </div>
      {noticeLines}
      {rows === null && !error && (
        <p role="status" className="body muted">
          Loading…
        </p>
      )}
      {error && (
        <ErrorBox text={error} />
      )}
      {rows && rows.length === 0 && closed.length === 0 && !error && (
        <p className="body muted">Nothing in play yet. Mark a match Prepared or Applied and it shows here.</p>
      )}
      {rows && (rows.length > 0 || closed.length > 0) && (
        <div className={narrow ? 'board-list' : 'board'} role="group" aria-label={narrow ? 'Applications' : 'Applications board'}>
          {shown.map((c) => (
              <section key={c.heading} className="board-column" aria-labelledby={`col-${c.heading}`}>
                <div className="board-column-head rule-heavy">
                  <h2 className="label" id={`col-${c.heading}`}>
                    {c.heading}
                  </h2>
                  <span className="label board-count"> · {c.rows.length}</span>
                </div>
                <ul className="board-cards">
                  {c.rows.map((m) => (
                    <Card key={m.id} m={m} onOpen={() => open(m)} onGhost={() => markGhosted(m)} ghosting={ghostingId === m.id} />
                  ))}
                </ul>
              </section>
          ))}
        </div>
      )}
      {importing && (
        <ImportDialog
          onClose={() => setImporting(false)}
          onOpen={(id) => {
            setImporting(false)
            select(id, 'posting', { keep: true })
            refresh()
          }}
        />
      )}
    </div>
  )
}
