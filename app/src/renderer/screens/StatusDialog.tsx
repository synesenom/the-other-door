import { useState } from 'react'
import { named } from './AppName'
import { INTERVIEW_KINDS, STATUSES, call, errorText } from '../api'
import type { SetStatusResult } from '../api'
import { Dialog } from './Dialog'

interface Props {
  jobId: string
  title: string
  /** The posting's ledger status now. */
  current: string
  /** `discarded`: the quick "Not for me" form, a reason and nothing else. */
  preset?: 'discarded'
  onClose: () => void
  onDone: (result: SetStatusResult) => void
}

/** The group a ledger status belongs to in the radio list. */
function groupOf(status: string): string {
  return status.startsWith('interview:') ? 'interview' : status
}

export function StatusDialog({ jobId, title, current, preset, onClose, onDone }: Props) {
  const [group, setGroup] = useState<string>(preset ?? (STATUSES.some((s) => s.value === groupOf(current)) ? groupOf(current) : ''))
  const [kind, setKind] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const status = group === 'interview' ? kind : group
  const discarding = group === 'discarded'
  const ready = status !== '' && (!discarding || notes.trim() !== '')

  const save = async () => {
    setBusy(true)
    setError(null)
    const args: Record<string, unknown> = { job_id: jobId, status }
    if (notes.trim()) args.notes = notes.trim()
    try {
      onDone(await call<SetStatusResult>('set_status', args))
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  const buttons = (label: string) => (
    <div className="actions">
      <button type="button" className="quiet" onClick={onClose}>
        Cancel
      </button>
      <button type="button" className="primary" disabled={busy || !ready} onClick={save}>
        {label}
      </button>
    </div>
  )

  const reason = (label: string) => (
    <label className="field">
      <span className="field-label">{label}</span>
      <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
    </label>
  )

  const failure = error && (
    <p role="alert" className="error">
      {named(error)}
    </p>
  )

  if (preset === 'discarded')
    return (
      <Dialog title={`Not for me: ${title}`} onClose={onClose} initialFocus="textarea">
        {reason('Why not?')}
        {failure}
        {buttons('Discard')}
      </Dialog>
    )

  return (
    <Dialog title={`Status: ${title}`} onClose={onClose} initialFocus="input:checked">
      <div role="radiogroup" aria-label="Status" className="choices">
        {STATUSES.map((s) => (
          <div key={s.value}>
            <label className="choice">
              <input type="radio" name="status" checked={group === s.value} onChange={() => setGroup(s.value)} />
              <span>{s.word}</span>
            </label>
            {s.value === 'interview' && group === 'interview' && (
              <div role="radiogroup" aria-label="Kind of interview" className="choices nested">
                {INTERVIEW_KINDS.map((k) => (
                  <label key={k.value} className="choice">
                    <input type="radio" name="kind" checked={kind === k.value} onChange={() => setKind(k.value)} />
                    <span>
                      {k.word}
                      <span className="small muted"> {k.meaning}</span>
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      {reason(discarding ? 'Why not?' : 'Notes (optional)')}
      {failure}
      {buttons('Save')}
    </Dialog>
  )
}
