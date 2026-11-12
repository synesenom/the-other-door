import { useId, useState } from 'react'
import { named } from './AppName'
import { call, errorText, placeLine, scoreText } from '../api'
import type { ImportResult, Posting } from '../api'
import { Dialog } from './Dialog'
import { Spinner } from './Spinner'

interface Props {
  onClose: () => void
  /** Show the imported posting; it may not be in the list of matches. */
  onOpen: (jobId: string) => void
}

export function ImportDialog({ onClose, onOpen }: Props) {
  const [mode, setMode] = useState<'link' | 'text'>('link')
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState('')
  const [location, setLocation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [duplicate, setDuplicate] = useState(false)
  const [result, setResult] = useState<{ import: ImportResult; posting: Posting | null } | null>(null)
  const id = useId()

  const ready = mode === 'link' ? url.trim() !== '' : text.trim() !== '' && title.trim() !== '' && company.trim() !== ''

  const send = async (force: boolean) => {
    const args: Record<string, unknown> = mode === 'link' ? { url: url.trim() } : { text: text.trim(), title: title.trim(), company: company.trim() }
    if (mode === 'link' && title.trim()) args.title = title.trim()
    if (mode === 'link' && company.trim()) args.company = company.trim()
    if (location.trim()) args.location = location.trim()
    if (force) args.force = true
    setBusy(true)
    setError(null)
    setDuplicate(false)
    try {
      const imported = await call<ImportResult>('import_posting', args)
      let posting: Posting | null = null
      try {
        posting = await call<Posting>('show', { job_id: imported.job_id })
      } catch {
        // the title is a nicety; the import itself worked
      }
      setResult({ import: imported, posting })
    } catch (e) {
      const message = errorText(e)
      if (/already stored/i.test(message)) setDuplicate(true)
      else setError(message)
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    const { import: r, posting } = result
    return (
      <Dialog title="Imported" onClose={onClose}>
        {posting && (
          <div>
            <p className="body title">{posting.title}</p>
            <p className="small muted">{placeLine(posting.company, posting.location)}</p>
          </div>
        )}
        {typeof r.score === 'number' ? (
          <>
            <p className="score-l">{scoreText(r.score)}</p>
            {r.score_reason && <p className="body reason">{r.score_reason}</p>}
          </>
        ) : (
          <>
            <p className="body">Not scored yet. It is scored on the next run.</p>
            {r.score_error && (
              <details className="small muted">
                <summary>Why?</summary>
                {r.score_error}
              </details>
            )}
          </>
        )}
        <div className="actions">
          <button type="button" className="quiet" onClick={onClose}>
            Close
          </button>
          <button type="button" className="primary" onClick={() => onOpen(r.job_id)}>
            Open
          </button>
        </div>
      </Dialog>
    )
  }

  // a field as in the other dialogs: its name above its own box
  const field = (label: string, value: string, set: (v: string) => void) => (
    <div className="field onb-field">
      <label htmlFor={`${id}-${label}`} className="field-label">
        {label}
      </label>
      <input id={`${id}-${label}`} className="onb-input" type="text" value={value} onChange={(e) => set(e.target.value)} disabled={busy} />
    </div>
  )

  return (
    <Dialog title="Add a job" onClose={onClose} initialFocus="input">
      <div className="pills dialog-pills">
        <button type="button" className="pill" aria-pressed={mode === 'link'} onClick={() => setMode('link')}>
          Link
        </button>
        <button type="button" className="pill" aria-pressed={mode === 'text'} onClick={() => setMode('text')}>
          Paste text
        </button>
      </div>
      {mode === 'link' ? (
        <>
          {field('Link', url, setUrl)}
          {field('Title (optional)', title, setTitle)}
          {field('Company (optional)', company, setCompany)}
        </>
      ) : (
        <>
          <div className="field onb-field">
            <label htmlFor={`${id}-text`} className="field-label">
              Ad text
            </label>
            <textarea id={`${id}-text`} className="onb-input" value={text} onChange={(e) => setText(e.target.value)} rows={6} disabled={busy} />
          </div>
          {field('Title', title, setTitle)}
          {field('Company', company, setCompany)}
        </>
      )}
      {field('Location (optional)', location, setLocation)}
      {busy && <Spinner message="Reading and scoring the ad…" />}
      {duplicate && (
        <>
          <p className="notice">You already imported this ad.</p>
          <button type="button" className="secondary" onClick={() => void send(true)}>
            Import again anyway
          </button>
        </>
      )}
      {error && (
        <p role="alert" className="field-error">
          {named(error)}
        </p>
      )}
      <div className="actions">
        <button type="button" className="quiet" onClick={onClose}>
          Cancel
        </button>
        <button type="button" className="primary" disabled={busy || !ready} onClick={() => void send(false)}>
          Import
        </button>
      </div>
    </Dialog>
  )
}
