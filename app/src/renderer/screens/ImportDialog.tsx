import { useId, useState } from 'react'
import { ErrorBox } from './AppName'
import { call, errorText, placeLine, scoreText } from '../api'
import type { ImportMissing, ImportResult, Posting } from '../api'
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
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [duplicate, setDuplicate] = useState(false)
  // a link whose page could not be read (or named no title or company) turns to Paste text, saying why; the link is kept with the ad
  const [fromLink, setFromLink] = useState<string | null>(null)
  // what the ad was read for and not found, asked by name (and what was found, sent back with the answers)
  const [missing, setMissing] = useState<ImportMissing | null>(null)
  const [result, setResult] = useState<{ import: ImportResult; posting: Posting | null } | null>(null)
  const id = useId()

  const typed = { title, company }
  const ready = mode === 'link' ? url.trim() !== '' : text.trim() !== '' && (missing?.missing ?? []).every((k) => typed[k].trim() !== '')

  const send = async (force: boolean) => {
    // the ad alone: its title, company and place are read from it; only what could not be found is typed
    const args: Record<string, unknown> = mode === 'link' ? { url: url.trim() } : { text: text.trim(), ...missing?.found }
    if (mode === 'text') for (const k of missing?.missing ?? []) args[k] = typed[k].trim()
    if (mode === 'text' && fromLink && url.trim()) args.url = url.trim()
    if (force) args.force = true
    setBusy(true)
    setError(null)
    setDuplicate(false)
    try {
      const answer = await call<ImportResult | ImportMissing>('import_posting', args)
      if ('missing' in answer) {
        if (mode === 'link') {
          setFromLink(`The ${answer.missing.join(' and ')} could not be found on that page.`)
          setMode('text')
        } else setMissing(answer)
        return
      }
      const imported = answer
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
      else if (mode === 'link' && /^could not fetch/i.test(message)) {
        setFromLink('That page could not be read: it may need a sign-in.')
        setMode('text')
      } else setError(message)
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
  const field = (label: string, value: string, set: (v: string) => void, focus = false) => (
    <div className="field onb-field">
      <label htmlFor={`${id}-${label}`} className="field-label">
        {label}
      </label>
      <input id={`${id}-${label}`} className="onb-input" type="text" autoFocus={focus} value={value} onChange={(e) => set(e.target.value)} disabled={busy} />
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
        // the tab names it: a box with only a placeholder, as the onboarding's page link
        <input type="text" className="onb-input" aria-label="Link" placeholder="The ad's address, https://…" value={url} onChange={(e) => setUrl(e.target.value)} disabled={busy} />
      ) : (
        <>
          {fromLink && <p className="notice">{`${fromLink} Paste the ad's text here.`}</p>}
          <div className="field onb-field">
            <label htmlFor={`${id}-text`} className="field-label">
              Ad text
            </label>
            <textarea id={`${id}-text`} className="onb-input" autoFocus={fromLink !== null} value={text} onChange={(e) => setText(e.target.value)} rows={6} disabled={busy} />
          </div>
          {missing && (
            <>
              <p className="notice">{`The ${missing.missing.join(' and ')} could not be found in the ad. Fill ${missing.missing.length > 1 ? 'them' : 'it'} in.`}</p>
              {missing.missing.includes('title') && field('Title', title, setTitle, true)}
              {missing.missing.includes('company') && field('Company', company, setCompany, !missing.missing.includes('title'))}
            </>
          )}
        </>
      )}
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
        <ErrorBox text={error} />
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
