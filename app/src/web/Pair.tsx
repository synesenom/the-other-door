// The phone app's first screen (#303): trade the code `door serve pair` printed for this phone's
// token. A QR code opens the app at `#pair=CODE`, which pairs without typing.
import { useEffect, useRef, useState } from 'react'
import { AppName, named } from '../renderer/screens/AppName'

export function codeFromHash(hash: string): string {
  const m = /^#pair=([^&]+)$/.exec(hash)
  return m ? decodeURIComponent(m[1]) : ''
}

export function Pair({
  fetch,
  onPaired,
  initialCode = '',
  notice,
}: {
  fetch: typeof globalThis.fetch
  onPaired: (p: { device: string; token: string }) => void
  initialCode?: string
  notice?: string
}) {
  const [code, setCode] = useState(initialCode)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const tried = useRef(false)

  const pair = async (value: string) => {
    setBusy(true)
    setError(null)
    try {
      const r = await fetch('/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: value.trim() }) })
      const body = await r.json().catch(() => ({}))
      if (r.ok && typeof body.token === 'string') {
        onPaired({ device: String(body.device ?? ''), token: body.token })
        return
      }
      setError(typeof body.error === 'string' ? body.error : r.status === 429 ? 'Too many wrong tries; wait a while and try again.' : `The other door answered ${r.status}.`)
    } catch {
      setError("Can't reach The other door. Is the computer running The other door on and serving?")
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (initialCode && !tried.current) {
      tried.current = true
      void pair(initialCode)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialCode])

  return (
    <main className="onb pair">
      <span className="dash" aria-hidden="true" />
      <h1 className="display-l">Pair this phone</h1>
      {notice && <p className="notice body">{named(notice)}</p>}
      <p className="body">
        On the computer running <AppName />, in its folder, run <code>door serve pair --device "My phone"</code> and type the code it shows. It works
        once, for ten minutes.
      </p>
      <form
        className="onb-step"
        onSubmit={(e) => {
          e.preventDefault()
          if (code.trim()) void pair(code)
        }}
      >
        <div className="onb-field field">
          <label htmlFor="pair-code" className="small">
            Pairing code
          </label>
          <input
            id="pair-code"
            className="onb-input pair-code"
            autoComplete="one-time-code"
            autoCapitalize="characters"
            spellCheck={false}
            placeholder="ABCD-EFGH"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </div>
        {error && (
          <p role="alert" className="small error">
            {named(error)}
          </p>
        )}
        <div className="actions">
          <button type="submit" className="primary" disabled={busy || !code.trim()}>
            {busy ? 'Pairing…' : 'Pair'}
          </button>
        </div>
      </form>
    </main>
  )
}
