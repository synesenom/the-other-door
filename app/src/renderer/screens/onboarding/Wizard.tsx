import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { call, errorText } from '../../api'
import { Splash } from '../../Splash'
import { Connect } from './Connect'
import { Reading } from './Reading'
import { canRunFirst, claudeReady, initialState, STEPS, wizardReducer } from './reducer'
import type { DoctorReport, ShowProfile, WizardState } from './reducer'
import { Review } from './Review'
import { Sources } from './Sources'

interface Props {
  /** `show_profile` as the window found it: `config` null on a fresh home. */
  profile: ShowProfile
  /** The onboarding sandbox: the first run is simulated, nothing real is installed or read from the boards. */
  sandbox: boolean
  /** The wizard is over: back to the app, with the first run started when `run`. */
  onFinish: (run: boolean) => void
  /** A redo can be left at its first step without changing anything. */
  onCancel?: () => void
  /** Answers and a step to open on: only the screen preview (src/preview) passes it. */
  start?: Partial<WizardState>
}

/** The first-launch wizard (and "Set up again"): sources, reading, one review; written only by the review's Save. */
export function Wizard({ profile: initial, sandbox, onFinish, onCancel, start }: Props) {
  const [state, dispatch] = useReducer(wizardReducer, undefined, () => ({ ...initialState(initial), ...start }))
  const [doctor, setDoctor] = useState<DoctorReport | null>(null)
  const quietInstall = useRef(false)

  // The CV files picked are forgotten when the wizard closes (finish, cancel, reload).
  useEffect(() => () => void window.door.clearCvSources(), [])

  // The last answer stays while the next is on its way: the sign-in screen stays up during a check.
  const recheck = useCallback(() => {
    return call<DoctorReport>('doctor').then(setDoctor, (e) => setDoctor({ ok: false, checks: [], error: errorText(e) }))
  }, [])
  useEffect(() => {
    void recheck()
  }, [recheck])

  // LaTeX is needed only at `prepare`, so it is no question here: it installs quietly (the installed app brings its own, so this is a checkout's).
  useEffect(() => {
    if (sandbox || quietInstall.current || !doctor?.checks.some((c) => c.name === 'latex' && c.status !== 'ok')) return
    quietInstall.current = true
    call('setup', { install: ['latex'], yes: true }).catch(() => undefined)
  }, [doctor, sandbox])

  // A first set-up (no profile) that may reach Google Drive can bring the profile from there instead (issue 616).
  const pulled = sandbox || initial.config ? undefined : () => onFinish(false)
  if (doctor === null) return <Splash />
  const connecting = !claudeReady(doctor)
  // Always the three steps of setting up: connecting Claude comes before them, the three still to come.
  const steps = STEPS
  const at = connecting ? -1 : steps.indexOf(state.step)
  let body
  switch (state.step) {
    case 'sources':
      body = (
        <Sources
          state={state}
          dispatch={dispatch}
          onNext={() => dispatch({ type: 'next' })}
          onBack={onCancel}
          onPulled={pulled}
        />
      )
      break
    case 'reading':
      body = <Reading state={state} dispatch={dispatch} onDone={() => dispatch({ type: 'next' })} onBack={() => dispatch({ type: 'back' })} />
      break
    case 'review':
      body = (
        <Review
          state={state}
          profile={initial}
          dispatch={dispatch}
          onBack={() => dispatch({ type: 'back' })}
          onSaved={(saved) => onFinish(state.mode === 'fresh' && canRunFirst(state, saved, doctor, sandbox))}
        />
      )
  }

  return (
    <div className="onb">
      <ol className="segments" aria-label="Progress">
        {steps.map((s, i) => (
          <li key={s} className={i < at ? 'segment segment-done' : 'segment'} aria-current={i === at ? 'step' : undefined} aria-label={`Step ${i + 1} of ${steps.length}`} />
        ))}
      </ol>
      {connecting ? <Connect doctor={doctor} onRecheck={recheck} onBack={onCancel} /> : body}
    </div>
  )
}
