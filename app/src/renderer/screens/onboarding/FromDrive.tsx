import { useState } from 'react'
import { call, errorText } from '../../api'
import { named } from '../AppName'

/**
 * The wizard's other way in, for someone who already uses The other door on another computer: connect Google Drive and
 * take what is there. `connect_drive` waits for the browser (up to five minutes), then `sync_data` pulls (this home has no
 * profile, so nothing can conflict). A pull ends the wizard; an empty Drive or a failure leaves the normal steps below,
 * Drive staying connected so the new profile is sent after Save.
 */
export function FromDrive({ onPulled }: { onPulled: () => void }) {
  const [step, setStep] = useState<'idle' | 'connecting' | 'pulling'>('idle')
  const [empty, setEmpty] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setError(null)
    setEmpty(false)
    setStep('connecting')
    try {
      await call('connect_drive', {})
      setStep('pulling')
      const r = await call<{ action: string }>('sync_data', {})
      if (r.action === 'pull') {
        onPulled()
        return
      }
      setEmpty(true)
    } catch (e) {
      setError(errorText(e))
    }
    setStep('idle')
  }

  return (
    <div className="onb-drive">
      <p className="small muted">
        Already use The other door on another computer?{' '}
        <button type="button" className="quiet" disabled={step !== 'idle'} onClick={() => void run()}>
          Bring my profile from Google Drive
        </button>
      </p>
      {step === 'connecting' && <p role="status" className="small muted">Finish signing in to Google in your browser. The other door waits here.</p>}
      {step === 'pulling' && <p role="status" className="small muted">Bringing your data from Google Drive…</p>}
      {empty && (
        <p role="status" className="small muted">
          There is nothing from The other door on your Google Drive yet. Go on below; your new profile is sent there when you save it.
        </p>
      )}
      {error && (
        <p role="alert" className="error small">
          {named(error)}
        </p>
      )}
    </div>
  )
}
