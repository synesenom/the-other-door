import { Documentation } from './Documentation'
import { AppName } from './AppName'
import { useRemote } from '../remote'
import { useEffect, useRef, useState } from 'react'
import type { UpdateResult } from '../../main/updates'
import { readTheme, saveTheme, type Theme } from '../theme'
import { Connections } from './Connections'
import { DataMoves } from './DataMoves'
import { ReportProblem } from './ReportProblem'
import { SettingsFields } from './SettingsFields'
import type { DriveStatus, Environment } from './connection-rows'
import type { DoctorReport } from './onboarding/reducer'

/**
 * Settings: how The other door works for you (Profile is who you are and what you want). One reading-width
 * column. Connections (Claude, Google Drive, the phone), Risky sources (where it looks), Your data (the data folder, export,
 * import), Appearance (the theme) and, last, Help (the version, the documents and Report a problem). Opening it reads doctor again (Claude's sign-in may have changed); nothing else
 * runs by itself. On the phone it is Appearance and where the data is, and it reads nothing.
 */
export function Settings({
  doctor,
  drive,
  where,
  home,
  email,
  onRecheck,
  driveConflict,
  onDriveConflict,
  onDriveChanged,
  onDataChanged,
  at,
  onReported,
}: {
  doctor: DoctorReport | null
  drive: DriveStatus | null
  where: Environment
  home?: string
  email?: string
  onRecheck: () => void | Promise<void>
  /** Both sides changed since they last synced: the Drive row asks which to keep. */
  driveConflict?: boolean
  onDriveConflict?: (conflict: boolean) => void
  onDriveChanged: () => void
  onDataChanged: () => void
  /** Where it opens: at Help's report button (the sidebar's "Something keeps going wrong"), or at Risky sources (sources never chosen). */
  at?: 'report' | 'risky'
  /** A problem report was saved. */
  onReported?: () => void
}) {
  const remote = useRemote()
  const [theme, setTheme] = useState<Theme>(readTheme)
  const reportPart = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!at) return
    const part = at === 'report' ? reportPart.current : document.getElementById('settings-risky')
    part?.scrollIntoView?.({ block: 'start' })
    // once, on opening
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    if (!remote) onRecheck() // the phone has no connections to read
    // once, on opening
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const [update, setUpdate] = useState<UpdateResult | { enabled: false } | null>(null)
  useEffect(() => {
    if (remote) return
    let live = true
    void window.door.invoke('check-update').then((r) => live && setUpdate(r))
    const stop = window.door.on('update-state', (r) => live && setUpdate(r))
    return () => {
      live = false
      stop()
    }
    // once, on opening
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return (
    <div className="settings">
      <h1 className="display-l">Settings</h1>
      {!remote && (
        <>
          <section className="part" aria-labelledby="settings-connections">
            <h2 className="display-s" id="settings-connections">
              Connections
            </h2>
            <Connections doctor={doctor} drive={drive} where={where} email={email} onRecheck={onRecheck} driveConflict={driveConflict} onDriveConflict={onDriveConflict} onDriveChanged={onDriveChanged} onDataChanged={onDataChanged} />
          </section>
          <section className="part" aria-labelledby="settings-risky">
            <h2 className="display-s" id="settings-risky">
              Risky sources
            </h2>
            <div className="data-moves">
              <p className="small muted">
                These sites forbid automated reading in their terms. Ticked, <AppName /> reads their public job ads, logged out, for employers hiring
                for your keywords, then follows those employers' own job pages. For personal use only, at your own risk.
              </p>
              <SettingsFields section="risky" />
            </div>
          </section>
          <section className="part" aria-labelledby="settings-data">
            <h2 className="display-s" id="settings-data">
              Your data
            </h2>
            <DataMoves home={home} onImported={onDataChanged} />
          </section>
        </>
      )}
      <section className="part" aria-labelledby="settings-appearance">
        <h2 className="display-s" id="settings-appearance">
          Appearance
        </h2>
        <fieldset className="choices onb-field" aria-labelledby="settings-appearance">
          {(
            [
              ['system', 'Same as the system'],
              ['light', 'Light'],
              ['dark', 'Dark'],
            ] as [Theme, string][]
          ).map(([value, word]) => (
            <label key={value} className="choice">
              <input
                type="radio"
                name="theme"
                checked={theme === value}
                onChange={() => {
                  setTheme(value)
                  saveTheme(value)
                }}
              />
              <span>{word}</span>
            </label>
          ))}
        </fieldset>
      </section>
      {remote ? (
        // The phone: where the data is, and that everything else is done on that computer.
        <section className="settings-section" aria-labelledby="settings-computer">
          <h2 className="label" id="settings-computer">
            This computer
          </h2>
          <p className="small muted">Your profile and jobs are on the computer running <AppName />, in</p>
          {home && <p className="body settings-path">{home}</p>}
          <p className="small muted">The phone finds, prepares and keeps your applications. Setting up, your profile and CV, connections and moving your data are done on the computer where it is installed.</p>
        </section>
      ) : (
        <section className="part" aria-labelledby="settings-help">
          <h2 className="display-s" id="settings-help">
            Help
          </h2>
          {update?.enabled && (
            <>
              <p className="body">Version {update.current}</p>
              {update.checked && update.available && update.mode === 'link' && (
                <p className="body">
                  Version {update.version} is available{' '}
                  <button type="button" className="secondary go" onClick={() => void window.door.invoke('open-external', update.url)}>
                    Download
                  </button>
                </p>
              )}
              {update.checked && update.available && update.mode === 'install' && update.state === 'downloading' && <p className="body">Downloading {update.version}</p>}
              {update.checked && update.available && update.mode === 'install' && update.state === 'downloaded' && (
                <p>
                  <button type="button" className="primary" onClick={() => void window.door.invoke('install-update')}>
                    Restart to update to {update.version}
                  </button>
                </p>
              )}
            </>
          )}
          <Documentation />
          <div ref={reportPart}>
            <ReportProblem onSaved={onReported} />
          </div>
        </section>
      )}
    </div>
  )
}
