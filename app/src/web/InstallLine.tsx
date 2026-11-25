// One quiet, dismissable line on the phone app once paired (#576): the browser's install button on
// Android, the Share words on iOS Safari; nothing once installed or waved away.
import { dismiss, install, useInstallOffer, type InstallOffer } from './install'

export function InstallLineView({ what, onInstall, onDismiss }: { what: InstallOffer; onInstall(): void; onDismiss(): void }) {
  if (!what) return null
  return (
    <div className="install-line notice" role="region" aria-label="Install the app">
      {what === 'prompt' ? (
        <button type="button" className="quiet" onClick={onInstall}>
          Install the app
        </button>
      ) : (
        <small>To install, tap Share, then Add to Home Screen.</small>
      )}
      <button type="button" className="quiet" onClick={onDismiss}>
        Not now
      </button>
    </div>
  )
}

export function InstallLine() {
  return <InstallLineView what={useInstallOffer()} onInstall={() => void install()} onDismiss={dismiss} />
}
