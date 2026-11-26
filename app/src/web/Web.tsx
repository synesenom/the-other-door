// The phone app's root (#303): the pair screen until this phone has a token, then the desktop app's own
// App over the web bridge. A revoked token (401 anywhere) brings the pair screen back.
import { useCallback, useEffect, useState } from 'react'
import { AppName, ErrorBox } from '../renderer/screens/AppName'
import { App } from '../renderer/App'
import { Splash } from '../renderer/Splash'
import { NOTHING_BEHIND, createWebDoor } from './bridge'
import { InstallLine } from './InstallLine'
import { OpenInChromeView, UnreachableView } from './PhoneScreens'
import { Pair, codeFromHash } from './Pair'
import { sharedFrom, type Shared } from './share'
import type { TokenStore } from './token-store'

const UNPAIRED = 'This phone is no longer paired with The other door. Make a new code on the computer running The other door.'

type State = { kind: 'loading' } | { kind: 'pair'; notice?: string } | { kind: 'sharing'; error?: string } | { kind: 'app' } | { kind: 'unreachable'; token: string }

/** Android, in a browser other than Chrome: only Chrome installs the app without its own badge on the icon. */
function otherAndroidBrowser(): boolean {
  const ua = navigator.userAgent
  return /Android/.test(ua) && ('brave' in navigator || /Firefox|EdgA|OPR|SamsungBrowser|DuckDuckGo|YaBrowser|UCBrowser/.test(ua))
}

/** The same page in Chrome, the pairing code carried along (Android opens an intent: link in the app it names). */
function inChrome(): string {
  const { host, pathname, hash } = window.location
  return `intent://${host}${pathname}${hash}#Intent;scheme=https;package=com.android.chrome;end`
}

function whenVisible(): Promise<void> {
  return new Promise((resolve) => {
    if (document.visibilityState === 'visible') return resolve()
    const on = () => {
      if (document.visibilityState !== 'visible') return
      document.removeEventListener('visibilitychange', on)
      resolve()
    }
    document.addEventListener('visibilitychange', on)
  })
}

export function Web({ store, fetch }: { store: TokenStore; fetch: typeof globalThis.fetch }) {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [code] = useState(() => codeFromHash(window.location.hash))
  const [here, setHere] = useState(() => !otherAndroidBrowser())
  // Something shared to the installed app (Android's share sheet opens /share): imported once paired.
  const [shared] = useState<Shared | null>(() => (window.location.pathname === '/share' ? sharedFrom(window.location.search) : null))

  const unpaired = useCallback(() => {
    void store.clear()
    setState({ kind: 'pair', notice: UNPAIRED })
  }, [store])

  /** Opens the /files cookie for this token, installs the bridge and shows the app; false when the token is refused.
   * A computer it cannot reach (no network, or the tunnel's own error page) gets a screen of its own. */
  const enter = useCallback(
    async (token: string): Promise<boolean> => {
      try {
        const r = await fetch('/session', { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
        if (r.status === 401) return false
        if (NOTHING_BEHIND(r.status)) {
          setState({ kind: 'unreachable', token })
          return true
        }
      } catch {
        setState({ kind: 'unreachable', token })
        return true
      }
      window.door = createWebDoor({
        fetch: (input, init) => fetch(input, init),
        token: () => store.get(),
        onUnpaired: unpaired,
        visible: () => document.visibilityState === 'visible',
        whenVisible,
        open: (url) => void window.open(url, '_blank', 'noopener'),
        download: (url, name) => {
          const a = Object.assign(document.createElement('a'), { href: url, download: name })
          a.click()
        },
      }) as unknown as Window['door']
      setState({ kind: shared ? 'sharing' : 'app' })
      return true
    },
    [fetch, store, shared, unpaired],
  )

  // The shared ad: imported and scored, then its posting opens over the app.
  useEffect(() => {
    if (state.kind !== 'sharing' || state.error || !shared) return
    let live = true
    void (async () => {
      const r = await window.door.call('import_posting', { ...shared })
      if (!live) return
      if (!r.ok) return setState({ kind: 'sharing', error: r.error })
      const id = (r.data as { job_id?: string }).job_id
      if (id) (window.door as unknown as { openTarget(t: unknown): void }).openTarget({ screen: 'posting', jobId: id, inPlay: false })
      history.replaceState(null, '', '/')
      setState({ kind: 'app' })
    })()
    return () => {
      live = false
    }
  }, [state, shared])

  useEffect(() => {
    void (async () => {
      // A phone already paired keeps its pairing: a code left in the link (a reopened tab) is already used.
      const token = await store.get()
      if (!token) return setState({ kind: 'pair' })
      if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search)
      if (!(await enter(token))) unpaired()
    })()
  }, [code, enter, store, unpaired])

  if (state.kind === 'loading') return <Splash />
  if (state.kind === 'unreachable') {
    const token = state.token
    return (
      <UnreachableView
        onRetry={() => {
          setState({ kind: 'loading' })
          void enter(token).then((ok) => ok || unpaired())
        }}
      />
    )
  }
  if (state.kind === 'pair' && code && !here) return <OpenInChromeView href={inChrome()} onHere={() => setHere(true)} />
  if (state.kind === 'pair') {
    return (
      <Pair
        fetch={fetch}
        notice={state.notice}
        initialCode={code}
        onPaired={async ({ token }) => {
          await store.set(token)
          if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search)
          await enter(token)
        }}
      />
    )
  }
  if (state.kind === 'sharing') {
    return (
      <main className="onb pair">
        <h1 className="display-l">Adding the ad you shared</h1>
        {state.error ? (
          <>
            <ErrorBox className="body" text={state.error} />
            <div className="actions">
              <button
                type="button"
                className="primary"
                onClick={() => {
                  history.replaceState(null, '', '/')
                  setState({ kind: 'app' })
                }}
              >
                Go to <AppName />
              </button>
            </div>
          </>
        ) : (
          <p role="status" className="body muted">
            Reading it and scoring it against your CV…
          </p>
        )}
      </main>
    )
  }
  return (
    <div className="web-app">
      <InstallLine />
      <App />
    </div>
  )
}
