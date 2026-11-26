// The phone app's own two screens, around the desktop screens it shows (the visual guide shows them too):
// a computer it cannot reach, and a pairing link opened in another Android browser.
import { AppName } from '../renderer/screens/AppName'

/** The words for a computer the phone cannot reach, on its own screen and under any call that fails so. */
export const UNREACHABLE_HELP = 'Make sure it is on and The other door is open on it. If you set up your phone again there, scan the new code.'

export function UnreachableView({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="onb pair">
      <h1 className="display-l">Can't reach your computer</h1>
      <p className="body">
        Make sure it is on and <AppName /> is open on it. If you set up your phone again there, scan the new code.
      </p>
      <div className="actions">
        <button type="button" className="primary" onClick={onRetry}>
          Try again
        </button>
      </div>
    </main>
  )
}

export function OpenInChromeView({ href, onHere }: { href: string; onHere: () => void }) {
  return (
    <main className="onb pair">
      <h1 className="display-l">Open in Chrome</h1>
      <p className="body">
        Chrome puts <AppName /> on your home screen as an app. Other browsers add their own badge to its icon.
      </p>
      <div className="actions">
        <button type="button" className="quiet" onClick={onHere}>
          Continue here
        </button>
        <a className="primary go" href={href}>
          Open in Chrome
        </a>
      </div>
    </main>
  )
}
