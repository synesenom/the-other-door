import { useState } from 'react'
import { AppName, named } from '../AppName'
import { call, errorText } from '../../api'
import { Dialog } from '../Dialog'
import { SignIn } from '../SignIn'
import { Spinner } from '../Spinner'
import { Frame } from './parts'
import { claudeMissing } from './reducer'
import type { DoctorReport } from './reducer'

/** The step before the sources, only when Claude is missing or signed out: everything after it reads with Claude. */
export function Connect({ doctor, onRecheck, onBack }: { doctor: DoctorReport; onRecheck: () => void | Promise<void>; onBack?: () => void }) {
  const [asking, setAsking] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [installed, setInstalled] = useState(false)

  const install = async () => {
    setWorking(true)
    setError(null)
    setInstalled(false)
    setAsking(false)
    try {
      const r = await call<{ results?: { tool: string; ok: boolean; error?: string }[] }>('setup', { install: ['claude'], yes: true })
      // Busy until the check answers: Claude installed is another screen, and a click now would install again.
      await onRecheck()
      // This step's own result: `outcome` also counts everything else a fresh home is still missing.
      const step = r.results?.find((s) => s.tool === 'claude')
      if (step && !step.ok) setError(step.error || 'The install did not finish.')
      else setInstalled(true)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setWorking(false)
    }
  }

  if (claudeMissing(doctor)) {
    return (
      <Frame title="Connect Claude" lead={<><AppName /> works through Claude, on your Pro or Max plan. Claude is not on this computer yet.</>} onBack={onBack}>
        <div className="actions">
          <button type="button" className="primary" disabled={working} onClick={() => setAsking(true)}>
            Install Claude
          </button>
        </div>
        {working && <Spinner message="Installing…" />}
        {(error || (installed && !working)) && (
          <p role="alert" className="error">
            {named(error ?? "The install finished, but Claude still can't be found. Try again, or close and reopen The other door.")}
          </p>
        )}
        {(error || (installed && !working)) && (
          <p className="small muted">
            Installed it yourself?{' '}
            <button type="button" className="quiet" onClick={() => void onRecheck()}>
              Check again
            </button>
          </p>
        )}
        {asking && (
          <Dialog title="Install Claude?" onClose={() => setAsking(false)}>
            <p className="body">This installs the Claude command line on this computer, without asking for a password.</p>
            <div className="actions">
              <button type="button" className="quiet" onClick={() => setAsking(false)}>
                Cancel
              </button>
              <button type="button" className="primary" onClick={() => void install()}>
                Install
              </button>
            </div>
          </Dialog>
        )}
      </Frame>
    )
  }
  return (
    <Frame title="Connect Claude" lead={<><AppName /> works through Claude, on your Pro or Max plan. It never uses an API key.</>} onBack={onBack}>
      <SignIn onDone={onRecheck} />
      <p className="small muted">
        Signed in some other way?{' '}
        <button type="button" className="quiet" onClick={() => void onRecheck()}>
          Check again
        </button>
      </p>
    </Frame>
  )
}
