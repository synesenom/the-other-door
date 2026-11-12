import { useEffect, useState } from 'react'

// size.sidebar-breakpoint (docs/design/tokens.json) is 900; below it the
// sidebar becomes a tab bar. styles.css carries the same literal, and
// styles.test.ts ties both to the token.
const QUERY = '(max-width: 899px)'

const query = () => (typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(QUERY) : null)

/** True while the window is narrower than the sidebar breakpoint. */
export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => query()?.matches ?? false)
  useEffect(() => {
    const mql = query()
    if (!mql) return
    const onChange = (e: { matches: boolean }) => setNarrow(e.matches)
    setNarrow(mql.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])
  return narrow
}
