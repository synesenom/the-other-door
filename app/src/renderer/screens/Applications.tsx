import { BackButton } from './BackButton'
import { useHistoryBack } from './history-back'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ErrorBox, named } from './AppName'
import { call, errorText } from '../api'
import type { Document, Match, Opening, MatchesResult, SetStatusResult } from '../api'
import { useNarrow } from '../useNarrow'
import { boardColumns, cardNote, stalledText } from './board'
import { WarningMark } from './CheckMark'
import { ReadingPane } from './ReadingPane'
import type { PaneView } from './ReadingPane'
import { statusNotice } from './statusNotice'

/** The jobs in play under word headings, in the order of a search; a heading with no job is left out (the phone's list). */
export function groupApplications(rows: Match[]): { heading: string; rows: Match[] }[] {
  return boardColumns(rows, [])
    .slice(0, 4)
    .filter((g) => g.rows.length > 0)
}

/** One card: title, company, a dot per interview round passed or how it ended, and a warning when it has been quiet too long. */
function Card({ m, onOpen }: { m: Match; onOpen: () => void }) {
  const note = cardNote(m)
  const stalled = stalledText(m)
  return (
    <li>
      <button type="button" className="board-card" onClick={onOpen}>
        <span className="board-card-head">
          <span className="board-card-title">{m.title_en || m.title}</span>
          {stalled && (
            <span className="board-card-warning" role="img" aria-label={stalled}>
              <WarningMark />
              <span className="hint-pop small" aria-hidden="true">
                {stalled}
              </span>
            </span>
          )}
        </span>
        <span className="board-card-company small muted">{m.company}</span>
        {(note.passed > 0 || note.text) && (
          <span className="board-card-note small muted">
            {Array.from({ length: note.passed }, (_, i) => (
              <span key={i} className="round-dot" aria-hidden="true" />
            ))}
            {note.passed > 0 && <span className="visually-hidden">{`${note.passed} ${note.passed === 1 ? 'round' : 'rounds'} passed: `}</span>}
            {note.text}
          </span>
        )}
      </button>
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
  const [tick, setTick] = useState(0)
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
  // The phone's Back: the application back to its posting (or to the board, opened from a Prepared card), the
  // posting back to the board, never further.
  const inMaterials = selected !== null && view === 'materials'
  useHistoryBack(inMaterials && fromBoard ? 1 : (pushedNow ? 1 : 0) + (inMaterials ? 1 : 0), () =>
    inMaterials ? (fromBoard ? backToBoard() : switchView('posting')) : setPushed(false),
  )
  const posting = selected && (
    <ReadingPane
      jobId={selected}
      view={view}
      onView={switchView}
      onChanged={changed}
      initialDoc={initialDoc}
      back={fromBoard ? { label: 'Applications', onBack: backToBoard } : undefined}
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
            <BackButton label="Applications" onClick={() => setPushed(false)} />
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
      <div>
        <h1 className="display-l">Applications</h1>
        {rows && rows.length > 0 && <p className="subtitle">{`${rows.length} in play${interviewing ? ` · ${interviewing} in interviews` : ''}`}</p>}
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
                    <Card key={m.id} m={m} onOpen={() => open(m)} />
                  ))}
                </ul>
              </section>
          ))}
        </div>
      )}
    </div>
  )
}
