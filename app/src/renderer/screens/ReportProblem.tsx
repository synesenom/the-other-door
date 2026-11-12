import { useState } from 'react'
import { named } from './AppName'
import { Spinner } from './Spinner'

const basename = (p: string) => p.split(/[\\/]/).pop() ?? p
// Where a report goes, until it opens an issue on the public repo instead.
export const REPORT_TO = 'enys.mones@gmail.com'

/**
 * Settings' Report a problem (issue 593): one archive, saved where a save dialog the main process runs says, for
 * the user to send. It says first that it holds no personal data; the window never names a file. What the
 * screens leave unsaid (docs/design/README.md, principle 9) is in its log.
 */
export function ReportProblem({ onSaved }: { onSaved?: () => void } = {}) {
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const report = async () => {
    setBusy(true)
    setSaved(null)
    setError(null)
    const r = await window.door.reportProblem()
    setBusy(false)
    if (r.ok) {
      setSaved(basename((r.data as { path: string }).path))
      onSaved?.() // the sidebar's "Something keeps going wrong" goes: door said no more once a report is saved
    } else if (!('canceled' in r)) setError(r.error)
  }

  return (
    <div className="report-problem">
      <p className="small muted">
        Saves one file to send when something does not work: what went wrong lately, the last runs and the checks of this computer. No CV, profile, job
        ads or applications; emails and folder names are hidden.
      </p>
      <div className="actions">
        <button type="button" className="secondary" disabled={busy} onClick={() => void report()}>
          Save logs…
        </button>
      </div>
      {busy && <Spinner message="Saving…" />}
      {saved && <p className="small">{`Saved as ${saved}. Send it to ${REPORT_TO}.`}</p>}
      {error && (
        <p role="alert" className="field-error">
          {named(error)}
        </p>
      )}
    </div>
  )
}
