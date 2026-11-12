import { useEffect, useRef, useState } from 'react'
import { named } from './AppName'
import type { LoginState } from '../../main/claude-login'
import { Spinner } from './Spinner'

/**
 * "Sign in with Claude": the main process runs claude's own login, which opens the browser; this
 * shows where it is and offers the page again and a box for the code the page shows when the browser
 * cannot hand it back. `onDone` asks doctor again: doctor, not claude's words, says who is signed in;
 * once it has answered and this is still shown, doctor did not see the sign-in, and this says so.
 * The onboarding step uses it now, Settings' Connections list later (issue 393).
 */
export function SignIn({ email, onDone }: { email?: string; onDone: () => void | Promise<void> }) {
  const [login, setLogin] = useState<LoginState>({ state: 'idle' })
  // The `done` doctor has answered for (before this screen opened, or since) and still said signed out.
  const [stale, setStale] = useState(false)
  const [codeOpen, setCodeOpen] = useState(false)
  const [code, setCode] = useState('')
  const [codeError, setCodeError] = useState<string | null>(null)
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  useEffect(() => {
    let live = true
    const off = window.door.claudeLogin.onState((s) => {
      if (!live) return
      setStale(false)
      setLogin(s)
      // doctor's answer decides: confirmed, the parent moves on; still signed out, this says so
      if (s.state === 'done')
        void Promise.resolve(onDoneRef.current()).then(() => {
          if (live) setStale(true)
        })
    })
    void window.door.claudeLogin.state().then((s) => {
      if (!live) return
      // Only a sign-in still going, or a done doctor did not confirm; an old failure or cancel is not shown again.
      const carried = s.state === 'starting' || s.state === 'waiting' || s.state === 'done'
      if (carried) setLogin((now) => (now.state === 'idle' ? s : now))
      if (s.state === 'done') setStale(true)
    })
    return () => {
      live = false
      off()
    }
  }, [])

  const start = () => {
    setStale(false)
    setCodeOpen(false)
    setCode('')
    setCodeError(null)
    setLogin({ state: 'starting' })
    void window.door.claudeLogin.start(email)
  }

  const sendCode = async () => {
    setCodeError(null)
    const r = await window.door.claudeLogin.sendCode(code)
    if (!r.ok) setCodeError(r.error ?? 'That code did not go through.')
  }

  const startButton = (label: string) => (
    <div className="actions">
      <button type="button" className="primary" onClick={start}>
        {label}
      </button>
    </div>
  )

  if (login.state === 'starting') return <Spinner message="Starting the sign-in…" />

  if (login.state === 'waiting') {
    return (
      <div className="onb-field field">
        <Spinner message="Finish signing in in your browser. The other door waits here." />
        <div className="actions">
          <button type="button" className="secondary" disabled={!login.canOpen} onClick={() => void window.door.claudeLogin.openPage()}>
            Open the sign-in page again
          </button>
          <button type="button" className="quiet" onClick={() => void window.door.claudeLogin.cancel()}>
            Cancel
          </button>
        </div>
        {!codeOpen ? (
          <button type="button" className="quiet signin-code-link" onClick={() => setCodeOpen(true)}>
            The page showed a code?
          </button>
        ) : (
          <form
            className="onb-field field"
            onSubmit={(e) => {
              e.preventDefault()
              void sendCode()
            }}
          >
            <label htmlFor="signin-code" className="small">
              Sign-in code
            </label>
            <input id="signin-code" className="onb-input" autoComplete="off" spellCheck={false} value={code} onChange={(e) => setCode(e.target.value)} />
            {codeError && (
              <p role="alert" className="small error">
                {named(codeError)}
              </p>
            )}
            <div className="actions">
              <button type="submit" className="secondary" disabled={!code.trim()}>
                Send code
              </button>
            </div>
          </form>
        )}
      </div>
    )
  }

  const problem =
    login.state === 'failed'
      ? `The sign-in didn't go through: ${login.message}`
      : login.state === 'timeout'
        ? 'The sign-in waited five minutes for the browser and stopped.'
        : login.state === 'done' && stale
          ? "claude said the sign-in worked, but The other door still can't see the sign-in."
          : null
  if (login.state === 'done' && !stale) return <Spinner message="Checking the sign-in…" />
  if (problem) {
    return (
      <div className="onb-field field">
        <p role="alert" className="body error">
          {named(problem)}
        </p>
        {startButton('Try again')}
      </div>
    )
  }
  return startButton('Sign in with Claude')
}
