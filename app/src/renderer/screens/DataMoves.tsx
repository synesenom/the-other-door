import { useState } from 'react'
import { named } from './AppName'
import { Dialog } from './Dialog'
import { Spinner } from './Spinner'

const basename = (p: string) => p.split(/[\\/]/).pop() ?? p
/** What clicking the data folder's path does, said where the system says it. */
const SHOW_IN_FOLDER = /Mac/.test(navigator.userAgent) ? 'Show in Finder' : 'Show in folder'
const size = (bytes: number) => (bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} kB`)

/**
 * Settings' Your data: where the data folder is (`home`; its path, a link, shows it in the file manager), then Export… packs profile/ and jobs/ into one archive where you say (a save dialog the
 * main process runs); Import… replaces them with one, after a yes that says what it replaces (what was here
 * is kept as a backup first). The window never names a file.
 */
export function DataMoves({ home, onImported }: { home?: string; onImported: () => void }) {
  const [busy, setBusy] = useState<null | 'export' | 'import'>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [picked, setPicked] = useState<{ token: string; name: string } | null>(null)

  const start = (what: 'export' | 'import') => {
    setBusy(what)
    setMessage(null)
    setWarnings([])
    setError(null)
  }
  const exportData = async () => {
    start('export')
    const r = await window.door.exportData()
    setBusy(null)
    if (r.ok) {
      const d = r.data as { path: string; files: number; bytes: number }
      setMessage(`Exported ${d.files} files (${size(d.bytes)}) to ${basename(d.path)}.`)
    } else if (!('canceled' in r)) setError(r.error)
  }
  const pick = async () => {
    setError(null)
    setMessage(null)
    const r = await window.door.pickArchive()
    if ('token' in r) setPicked(r)
    else if ('error' in r) setError(r.error)
  }
  const importData = async () => {
    const token = picked!.token
    setPicked(null)
    start('import')
    const r = await window.door.importData(token)
    setBusy(null)
    if (!r.ok) {
      setError(r.error)
      return
    }
    const d = r.data as { files: number; backup_dir?: string | null; warnings?: string[] }
    setMessage(`Imported ${d.files} files.${d.backup_dir ? ` What was here is kept in ${d.backup_dir}.` : ''}`)
    setWarnings(d.warnings ?? [])
    onImported()
  }

  return (
    <div className="data-moves">
      <p className="small muted settings-path">
        {home && (
          <>
            Your profile and jobs are stored in{' '}
            {/* Not a <button>: a button lays out as an inline block, so a long path would leave the sentence. */}
            <span
              role="button"
              tabIndex={0}
              className="link-inline"
              title={SHOW_IN_FOLDER}
              onClick={() => void window.door.showHome()}
              onKeyDown={(e) => {
                if (e.key !== 'Enter' && e.key !== ' ') return
                e.preventDefault()
                void window.door.showHome()
              }}>
              {home}
            </span>
            .{' '}
          </>
        )}
        Export saves them in one file, to move to another computer or keep a copy; Import replaces them with the ones in such a file.
      </p>
      <div className="actions">
        <button type="button" className="secondary" disabled={busy !== null} onClick={() => void exportData()}>
          Export…
        </button>
        <button type="button" className="secondary" disabled={busy !== null} onClick={() => void pick()}>
          Import…
        </button>
      </div>
      {busy && <Spinner message={busy === 'export' ? 'Exporting…' : 'Importing…'} />}
      {message && <p className="small">{message}</p>}
      {warnings.length > 0 && (
        <ul className="small muted" aria-label="Worth checking">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="field-error">
          {named(error)}
        </p>
      )}
      {picked && (
        <Dialog title={`Import ${picked.name}?`} onClose={() => setPicked(null)}>
          <p className="body">{`This replaces your profile and jobs on this computer with the ones in ${picked.name}. What is here now is kept as a backup first, so nothing is lost.`}</p>
          <p className="small muted">If Google Drive is connected, the next sync sends the imported data to Drive, replacing the copy there; if Drive changed meanwhile, it asks which to keep first.</p>
          <div className="actions">
            <button type="button" className="quiet" onClick={() => setPicked(null)}>
              Cancel
            </button>
            <button type="button" className="primary" onClick={() => void importData()}>
              Import
            </button>
          </div>
        </Dialog>
      )}
    </div>
  )
}
