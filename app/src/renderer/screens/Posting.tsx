import { useEffect, useRef, useState } from 'react'
import { ErrorBox } from './AppName'
import { call, errorText, languageLine, placeLine, scoreText } from '../api'
import type { PrepareResult, Posting as PostingData, SetStatusResult } from '../api'
import { useNarrow } from '../useNarrow'
import { SkillColumn } from './SkillColumn'
import { Dialog } from './Dialog'
import { Hint } from './Hint'
import { SalaryLine } from './SalaryLine'
import { Spinner } from './Spinner'
import { prepareText } from './run-text'
import { StatusDialog } from './StatusDialog'
import { preparing, preparingChanged } from './prepare-store'

interface Props {
  jobId: string
  /** The status was saved on the job titled `title`; the result carries the server's `warning`, if any. */
  onChanged: (result: SetStatusResult, title: string) => void
  /** Show the prepared CV and letter ("See the application", and after a Prepare). */
  onOpenMaterials?: () => void
}

const POLL_MS = 5_000
const IN_PROGRESS = /in progress/i
const CAN_PREPARE = ['unapplied', 'prepared']

const elapsed = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** "Oct 3", or nothing for a date that cannot be read. */
function shortDate(value: string): string | null {
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function metaLine(p: PostingData): string {
  const parts = [placeLine(p.company, p.location)]
  const posted = p.posted_at ? shortDate(p.posted_at) : null
  if (posted) parts.push(`posted ${posted}`)
  if (p.source_name) parts.push(`via ${p.source_name}`)
  return parts.join(' · ')
}

/** Whether the ad links to a separate application page (http or https, not the ad itself). */
function hasApplyPage(applyUrl: string | null | undefined, adUrl: string | undefined): applyUrl is string {
  if (!applyUrl || applyUrl === adUrl) return false
  try {
    const u = new URL(applyUrl)
    return u.protocol === 'https:' || u.protocol === 'http:'
  } catch {
    return false
  }
}

export function Posting({ jobId, onChanged, onOpenMaterials }: Props) {
  const [posting, setPosting] = useState<PostingData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dialog, setDialog] = useState<'status' | 'discarded' | null>(null)
  const [version, setVersion] = useState(0)
  const narrow = useNarrow()
  const [, setTick] = useState(0)
  const [again, setAgain] = useState(false)
  const [prepareError, setPrepareError] = useState<string | null>(null)
  const [busyNotice, setBusyNotice] = useState(false)
  // poll `show` for the materials of a Prepare this pane did not start (remounted, or another run's)
  const [watching, setWatching] = useState<'adopted' | 'busy' | null>(() => (preparing.has(jobId) ? 'adopted' : null))
  const mounted = useRef(true)
  const running = preparing.get(jobId)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  // a clock for the elapsed line while a Prepare is running
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [running])

  useEffect(() => {
    if (!watching) return
    const t = setInterval(() => {
      call<PostingData>('show', { job_id: jobId }).then((p) => {
        if (!mounted.current) return
        if (p.materials) {
          setPosting(p)
          setWatching(null)
          setBusyNotice(false)
        } else if (watching === 'adopted' && !preparing.has(jobId)) setWatching(null)
      }, () => undefined)
    }, POLL_MS)
    return () => clearInterval(t)
  }, [watching, jobId])

  useEffect(() => {
    let live = true
    setError(null)
    call<PostingData>('show', { job_id: jobId }).then(
      (p) => live && setPosting(p),
      (e) => live && setError(errorText(e)),
    )
    return () => {
      live = false
    }
  }, [jobId, version])

  useEffect(() => setPosting(null), [jobId])

  if (error)
    return (
      <ErrorBox text={error} />
    )
  if (!posting) return <p className="muted">Loading</p>

  const startPrepare = async (force: boolean) => {
    const entry = { since: Date.now(), message: 'Preparing…' }
    preparing.set(jobId, entry)
    preparingChanged()
    setPrepareError(null)
    setBusyNotice(false)
    setTick((n) => n + 1)
    try {
      await call<PrepareResult>('prepare', force ? { job_id: jobId, force: true } : { job_id: jobId }, {
        onProgress: (p) => {
          entry.message = p.message
          if (mounted.current) setTick((n) => n + 1)
        },
      })
      if (mounted.current) onOpenMaterials?.()
    } catch (e) {
      if (!mounted.current) return
      const text = errorText(e)
      if (IN_PROGRESS.test(text)) {
        setBusyNotice(true)
        setWatching('busy')
      } else setPrepareError(text)
    } finally {
      preparing.delete(jobId)
      preparingChanged()
      if (mounted.current) setTick((n) => n + 1)
    }
  }

  const score = scoreText(posting.score)
  // The ad's text is here already: the link worth opening is the employer's application page, when the
  // board's ad points to one; else the ad where it was found.
  const applyPage = hasApplyPage(posting.apply_url, posting.url)
  const target = applyPage ? (posting.apply_url as string) : posting.url
  const open = target ? () => void window.door.invoke('open-external', target) : null
  const openLabel = applyPage ? 'Apply' : 'Open in browser'
  const locked = Boolean(running)
  const hasMaterials = Boolean(posting.materials)
  const preparable = CAN_PREPARE.includes(posting.status)
  // One ink button per view: Prepare, else See the application, else the ad itself on a phone.
  const primary = running ? null : hasMaterials ? (
    <button type="button" className="primary" onClick={() => onOpenMaterials?.()}>
      {posting.materials?.sent ? 'See what you sent' : 'See the application'}
    </button>
  ) : preparable ? (
    <button type="button" className="primary" onClick={() => void startPrepare(false)}>
      Prepare application
    </button>
  ) : null
  const prepareAgain =
    hasMaterials && preparable && !running ? (
      <button type="button" className="secondary" onClick={() => setAgain(true)}>
        Prepare again…
      </button>
    ) : null
  const openIsPrimary = narrow && !primary && !running
  const openClass = openIsPrimary ? 'primary go' : 'secondary go' // it leaves the app: the arrow either way
  const matching = posting.matching_skills ?? []
  const missing = posting.missing_skills ?? []
  return (
    <article className="posting">
      <header className="posting-head">
        <h2 className="display-l">{posting.title}</h2>
        {posting.title_en && posting.title_en !== posting.title && <p className="body muted">{posting.title_en}</p>}
        <p className="body muted">{metaLine(posting)}</p>
      </header>
      {/* The status is the board's lane, the list's row and the Status dialog; why the score, behind an info icon. */}
      {(score || posting.score_reason) && (
        <div className="score-line">
          {score && <p className="score-l">{score}</p>}
          {posting.score_reason && <Hint label="Why this score">{posting.score_reason}</Hint>}
        </div>
      )}
      {running && (
        <div className="preparing">
          <Spinner message={prepareText(running.message)} />
          <p className="small muted">Elapsed {elapsed(Date.now() - running.since)}</p>
          <p className="small muted">You can leave this open; it takes a few minutes.</p>
        </div>
      )}
      {busyNotice && (
        <p role="status" className="notice">
          Another run is in progress. Try again when it finishes.
        </p>
      )}
      {prepareError && (
        <ErrorBox text={prepareError} />
      )}
      {!narrow && (
        <div className="actions">
          {primary}
          {open && (
            <button type="button" className={openClass} disabled={locked} onClick={open}>
              {openLabel}
            </button>
          )}
          <button type="button" className="secondary" disabled={locked} onClick={() => setDialog('status')}>
            Status…
          </button>
          {prepareAgain}
          {/* With an application the job is in play: "Not for me" stays in Status. */}
          {!hasMaterials && (
            <button type="button" className="quiet" disabled={locked} onClick={() => setDialog('discarded')}>
              Not for me…
            </button>
          )}
        </div>
      )}
      {(matching.length > 0 || missing.length > 0) && (
        <section className="columns rule-heavy rule-top">
          {matching.length > 0 && <SkillColumn name="Why it fits" className="skill-list" skills={matching} fits />}
          {missing.length > 0 && <SkillColumn name="Gaps" className="skill-list" skills={missing} fits={false} />}
        </section>
      )}
      <SalaryLine salary={posting.salary} />
      {posting.language && <p className="body">{languageLine(posting.language, posting.language_requirement)}</p>}
      {posting.description && (
        <section>
          <Description posting={posting} />
        </section>
      )}
      {narrow && (
        // The phone layout: the actions sit in a bar at the bottom, one ink button.
        <div className="action-bar">
          <button type="button" className="secondary" disabled={locked} onClick={() => setDialog('status')}>
            Status…
          </button>
          {!hasMaterials && (
            <button type="button" className="secondary" disabled={locked} onClick={() => setDialog('discarded')}>
              Not for me…
            </button>
          )}
          {prepareAgain}
          {open && (
            <button type="button" className={openClass} disabled={locked} onClick={open}>
              {openLabel}
            </button>
          )}
          {primary}
        </div>
      )}
      {again && (
        <Dialog title="Prepare again?" onClose={() => setAgain(false)}>
          <p className="body">This replaces the tailored CV and letter, and any revisions.</p>
          <div className="actions">
            <button type="button" className="quiet" onClick={() => setAgain(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="primary"
              onClick={() => {
                setAgain(false)
                void startPrepare(true)
              }}
            >
              Prepare again
            </button>
          </div>
        </Dialog>
      )}
      {dialog && (
        <StatusDialog
          jobId={jobId}
          title={posting.title_en || posting.title}
          current={posting.status}
          preset={dialog === 'discarded' ? 'discarded' : undefined}
          onClose={() => setDialog(null)}
          onDone={(result) => {
            setDialog(null)
            setVersion((v) => v + 1)
            onChanged(result, posting.title_en || posting.title)
          }}
        />
      )}
    </article>
  )
}

/** The ad's text: a set-out one (`formatted`) with its `## ` headings and `- ` list items, every word shown as
 * written (the ad is a stranger's: no link, emphasis or numbering is read from it); any other as it came. */
function Description({ posting }: { posting: PostingData }) {
  if (!posting.formatted) return <p className="body description">{posting.description}</p>
  const blocks = (posting.description ?? '').split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean)
  return (
    <div className="markdown body">
      {blocks.map((block, i) => {
        if (block.startsWith('## ')) return <h3 key={i} className="md-heading">{block.slice(3)}</h3>
        const lines = block.split('\n')
        if (lines.every((line) => line.startsWith('- ')))
          return (
            <ul key={i}>
              {lines.map((line, n) => (
                <li key={n}>{line.slice(2)}</li>
              ))}
            </ul>
          )
        return <p key={i}>{block}</p>
      })}
    </div>
  )
}
