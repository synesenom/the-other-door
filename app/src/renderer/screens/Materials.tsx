import { named } from './AppName'
import { useRemote } from '../remote'
import { useEffect, useState } from 'react'
import { call, errorText, materialUrl, saveMaterial, visiblePages } from '../api'
import type { Document, Materials as MaterialsData, Posting, ReviseResult, SetStatusResult } from '../api'
import { useNarrow } from '../useNarrow'
import { WarningMark } from './CheckMark'
import { SalaryLine } from './SalaryLine'
import { Spinner } from './Spinner'

interface Props {
  jobId: string
  /** The back link: to the posting this was opened from. */
  onBack: () => void
  /** "I've applied" was recorded, on the job titled `title`. */
  onApplied: (result: SetStatusResult, title: string) => void
  /** The document shown first (a clicked notification); the letter when left out. */
  initialDoc?: Document
}

// The limits the tailor works to (.claude/agents/tailor.md).
const CV_PAGES = 2
const LETTER_PAGES = 1
const WORDS_MIN = 250
const WORDS_MAX = 350

const NAMES: Record<Document, string> = { cv: 'CV', cover_letter: 'Letter' }
const pages = (n: number) => `${n} ${n === 1 ? 'page' : 'pages'}`

/** The save button's words: which file it saves, as the switch names it. */
const SAVE: Record<Document, string> = { cv: 'Save CV', cover_letter: 'Save letter' }
/** "Saved as Jane Doe - CV.pdf in Downloads.": the file and the folder it went to. */
function savedText(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean)
  const file = parts.pop() ?? path
  return parts.length ? `Saved as ${file} in ${parts.pop()}.` : `Saved as ${file}.`
}

/** The limit a document is over, in words; null when it is within them. */
function limitNote(m: MaterialsData, which: Document): string | null {
  if (which === 'cv') return m.page_counts.cv > CV_PAGES ? `(limit is ${CV_PAGES})` : null
  if (m.page_counts.cover_letter > LETTER_PAGES) return `(limit is ${LETTER_PAGES})`
  const words = m.cover_letter_words
  return words !== null && (words < WORDS_MIN || words > WORDS_MAX) ? `(aim for ${WORDS_MIN}–${WORDS_MAX})` : null
}

// The files are in `jobs/output/<id>`, or in `jobs/output/<id>/sent` for the copy kept when the application
// was sent (a job sent before that copy was kept has only the first).
const fromSentCopy = (m: MaterialsData) => m.output_dir.split(/[\\/]/).filter(Boolean).pop() === 'sent'

/** The claims the CV does not back, each named once; null when there are none. */
function unbackedLine(m: MaterialsData): string | null {
  const values = [...new Set((m.unsupported ?? []).map((c) => c.value))]
  return values.length ? `Not in your CV: ${values.join(', ')}. Check them before you send it.` : null
}

type Notice = { text: string } | null

export function Materials({ jobId, onBack, onApplied, initialDoc }: Props) {
  const remote = useRemote()
  const narrow = useNarrow()
  const [posting, setPosting] = useState<Posting | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [doc, setDoc] = useState<Document>(initialDoc ?? 'cover_letter')
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<Notice>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [version, setVersion] = useState(0)
  const [applying, setApplying] = useState(false)

  // "I've applied" records the application at once; the board's status dialog changes it later.
  const apply = async (title: string) => {
    setApplying(true)
    setNotice(null)
    setFailure(null)
    try {
      onApplied(await call<SetStatusResult>('set_status', { job_id: jobId, status: 'applied' }), title)
    } catch (e) {
      setFailure(errorText(e))
    } finally {
      setApplying(false)
    }
  }

  const load = () =>
    call<Posting>('show', { job_id: jobId }).then((p) => {
      setPosting(p)
      setLoadError(null)
    })

  useEffect(() => {
    let live = true
    call<Posting>('show', { job_id: jobId }).then(
      (p) => live && setPosting(p),
      (e) => live && setLoadError(errorText(e)),
    )
    return () => {
      live = false
    }
  }, [jobId])

  if (loadError)
    return (
      <div className="materials">
        <button type="button" className="back" onClick={onBack}>
          ← Posting
        </button>
        <p role="alert" className="error">
          {named(loadError)}
        </p>
      </div>
    )
  if (!posting) return <p className="muted">Loading</p>
  const m = posting.materials
  if (!m)
    return (
      <div className="materials">
        <button type="button" className="back" onClick={onBack}>
          ← Posting
        </button>
        <p className="body muted">There is nothing prepared for this job yet.</p>
      </div>
    )

  const id = posting.id
  // Sent: what the employer has, from the copy kept when it went out; read only (no Revise, no I've applied).
  const sent = m.sent === true
  const inSent = fromSentCopy(m)
  const unbacked = sent ? null : unbackedLine(m)
  const subtitle = `${posting.title_en || posting.title} · ${posting.company}`

  // The desktop's save dialog answers where the file went; the phone's download is the browser's own, and says so itself.
  const save = async (which: Document) => {
    setFailure(null)
    setNotice(null)
    const r = await saveMaterial(id, which, inSent, m.file_names[which])
    if (r.ok && r.path) setNotice({ text: savedText(r.path) })
    else if (!r.ok && !r.canceled) setFailure(r.error ?? 'Could not save the PDF.')
  }

  // A revision or an undo that worked says nothing: the pages redraw and the box empties.
  const run = async (args: Record<string, unknown>) => {
    setBusy(true)
    setNotice(null)
    setFailure(null)
    try {
      const r = await call<ReviseResult>('revise', { job_id: jobId, file: doc, ...args })
      if (r.compile?.some((c) => c.status === 'error')) {
        // The new text is saved but its PDF is the old one: the pages shown are still what is on disk.
        setNotice({
          text: 'The change was made but the PDF could not be rebuilt, so the pages still show the previous version. Undo last change puts it back.',
        })
        return
      }
      await load()
      setVersion((v) => v + 1)
      setInstruction('')
    } catch (e) {
      const text = errorText(e)
      if (args.undo && /nothing to undo/i.test(text)) setNotice({ text: 'Nothing to undo.' })
      else setFailure(text)
    } finally {
      setBusy(false)
    }
  }

  const figureFor = (which: Document) => {
    const note = limitNote(m, which)
    return (
      <figure key={which} className="paper-figure">
        <div className="pages-stack">
          {visiblePages(m, which).map((png, i) => (
            <img key={png} className="paper" src={materialUrl(id, png, version, inSent)} alt={`${NAMES[which]}, page ${i + 1}`} />
          ))}
        </div>
        {/* The switch above names the document and its size; only a limit it is over is said here. */}
        {note && (
          <figcaption role="note" className="small">
            {note}
          </figcaption>
        )}
        {!narrow && (
          <button type="button" className="secondary" disabled={busy} onClick={() => void save(which)}>
            {SAVE[which]}
          </button>
        )}
      </figure>
    )
  }

  const docs: Document[] = ['cv', 'cover_letter']
  return (
    <div className="materials">
      <button type="button" className="back" onClick={onBack}>
        ← Posting
      </button>
      <header className="materials-head">
        <div className="posting-head">
          <h1 className="display-l">{sent ? 'What you sent' : 'Ready to send'}</h1>
          <p className="body muted">{subtitle}</p>
        </div>
        {!narrow && !remote && !sent && (
          <button type="button" className="primary" disabled={busy || applying} onClick={() => void apply(posting.title_en || posting.title)}>
            I've applied
          </button>
        )}
      </header>
      <SalaryLine salary={posting.salary} />
      {unbacked && (
        <p className="small marked">
          <span className="mark">
            <WarningMark />
          </span>
          <span>{unbacked}</span>
        </p>
      )}
      {notice && (
        <p role="status" className="notice">
          {named(notice.text)}
        </p>
      )}
      {failure && (
        <p role="alert" className="error">
          {named(failure)}
        </p>
      )}
      {busy && <Spinner message="Revising…" />}
      {/* One document at a time, large enough to read; the switch also picks what Revise changes. */}
      <div className="doc-switch" role="group" aria-label="Document">
        {docs.map((d) => (
          <button key={d} type="button" className="pill" aria-pressed={doc === d} disabled={busy} onClick={() => setDoc(d)}>
            {`${NAMES[d]} · ${d === 'cv' ? pages(m.page_counts.cv) : m.cover_letter_words === null ? pages(m.page_counts.cover_letter) : `${m.cover_letter_words} words`}`}
          </button>
        ))}
      </div>
      <div className="materials-body">
        <div className={busy ? 'pages dimmed' : 'pages'} data-testid="pages" aria-busy={busy}>
          {figureFor(doc)}
        </div>
        {!sent && (
          <aside className="materials-aside">
            <section className="revise">
              <label className="field" htmlFor="revise-instruction">
                <span className="display-s">Anything to change?</span>
              </label>
              <textarea
                id="revise-instruction"
                rows={3}
                value={instruction}
                disabled={busy}
                placeholder={doc === 'cv' ? 'Change the CV: lead with the dashboards project…' : 'Change the letter: make it shorter and warmer…'}
                onChange={(e) => setInstruction(e.target.value)}
              />
              <div className="actions">
                <button
                  type="button"
                  className="primary"
                  disabled={busy || instruction.trim() === ''}
                  onClick={() => void run({ instruction: instruction.trim() })}
                >
                  Revise
                </button>
                <button type="button" className="quiet" disabled={busy} onClick={() => void run({ undo: true })}>
                  Undo last change
                </button>
              </div>
            </section>
          </aside>
        )}
      </div>
      {narrow && (
        <div className="action-bar">
          <button type="button" className="secondary" disabled={busy} onClick={() => void save(doc)}>
            {SAVE[doc]}
          </button>
          {!sent && (
            <button type="button" className="primary" disabled={busy || applying} onClick={() => void apply(posting.title_en || posting.title)}>
              I've applied
            </button>
          )}
        </div>
      )}
    </div>
  )
}
