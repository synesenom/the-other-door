import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { AppName } from './screens/AppName'
import { WarningMark } from './screens/CheckMark'
import { ApiError, call, errorText, findJobs, onOpen, onRunBoard, runBoard, statusSummary, stopRun } from './api'
import type { Opening, PlanBlock, RunBoard } from './api'
import { TabIcon } from './TabIcon'
import { Splash } from './Splash'
import { RemoteContext } from './remote'
import { useNarrow } from './useNarrow'
import { Analytics } from './screens/Analytics'
import { Applications } from './screens/Applications'
import { Finding, type FindingState } from './screens/Finding'
import { Matches } from './screens/Matches'
import type { DriveStatus } from './screens/connection-rows'
import { discoveryOff } from './screens/onboarding/reducer'
import type { DoctorReport, ShowProfile, WizardState } from './screens/onboarding/reducer'
import { Profile, type ProfileStart } from './screens/Profile'
import { Settings } from './screens/Settings'
import { planReset, problems, type Problem } from './screens/problems'
import { Wizard } from './screens/onboarding/Wizard'
import { PREPARING_TIP } from './screens/Matches'
import { usePreparing } from './screens/prepare-store'

const DESTINATIONS = ['Matches', 'Applications', 'Profile', 'Settings', 'Analytics'] as const
type Destination = (typeof DESTINATIONS)[number]
/** The phone finds new jobs, prepares them and keeps the applications: the profile, the CV and the
 * employers are changed, and Analytics read, on the computer running The other door. */
const PHONE_DESTINATIONS: readonly Destination[] = ['Matches', 'Applications', 'Settings']

/** "Oct 28, 09:30", or null when the run has no readable end. */
function lastRunText(finishedAt: string | null | undefined): string | null {
  if (!finishedAt) return null
  const d = new Date(finishedAt)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** Search and match only on the first run: following and collecting employers wait for the next one. */
const FIRST_RUN_SKIP = ['discover', 'follow', 'collect']

/** What the first launch decided: still asking, the wizard, or the app. */
type Gate = { kind: 'loading' } | { kind: 'wizard'; profile: ShowProfile } | { kind: 'shell' } | { kind: 'remote-setup' }

/** Where the window opens instead of Matches: only the screen preview (src/preview) passes it. */
export interface AppStart {
  destination?: Destination
  /** Profile on its CV part. */
  cv?: boolean
  /** Profile opens on its Stories part. */
  stories?: boolean
  /** The Finding jobs screen, in this state. */
  run?: FindingState
  /** The wizard's answers and step, when the wizard opens. */
  wizard?: Partial<WizardState>
  /** Start a run as soon as the app is open, as a click on Find new jobs would (the preview's whole run). */
  findOnOpen?: boolean
}

export function App({ start }: { start?: AppStart } = {}) {
  const [gate, setGate] = useState<Gate>({ kind: 'loading' })
  const [profile, setProfile] = useState<ShowProfile | null>(null)
  const [sandbox, setSandbox] = useState(false)
  const [current, setCurrent] = useState<Destination>(start?.destination ?? 'Matches')
  const mainRef = useRef<HTMLElement>(null)
  // Profile opened from a problem line: on the CV.
  // Where Profile opens next, counted so the same place opens it again
  const [profileStart, setProfileStart] = useState<{ n: number; at: ProfileStart } | null>(start?.cv ? { n: 1, at: { view: 'cv' } } : start?.stories ? { n: 1, at: { view: 'stories' } } : null)
  // Where Settings opens next (Report a problem, from the sidebar's line), counted the same way
  const [settingsStart, setSettingsStart] = useState<{ n: number; at: 'report' | 'risky' } | null>(null)
  const narrow = useNarrow()
  const [pushed, setPushed] = useState(false)
  const [lastRun, setLastRun] = useState<string | null>(null)
  const [demo, setDemo] = useState(false)
  const [home, setHome] = useState<string | undefined>(undefined)
  const [remote, setRemote] = useState(false)
  // The connections (Settings and the sidebar's lines): Claude from doctor, Drive from the summary.
  const [doctor, setDoctor] = useState<DoctorReport | null>(null)
  const [drive, setDrive] = useState<DriveStatus | null>(null)
  // A sync found this computer and Drive both changed: the Drive row and a sidebar line ask which to keep
  const [driveConflict, setDriveConflict] = useState(false)
  // Something keeps going wrong since the last problem report (status_summary's recurring_problem)
  const [recurring, setRecurring] = useState<boolean | null>(null)
  // The Claude plan's window (status_summary's plan): a sidebar line only when it is nearly full
  const [plan, setPlan] = useState<PlanBlock | null>(null)
  // Bumped when a Prepare ends, to read the summary again (refreshKey would remount Matches)
  const [summaryKey, setSummaryKey] = useState(0)
  // The run: what this window asked for (`run`) and what the main process says is going (`board`),
  // whoever started it. It lives here so it survives a look at another screen.
  // this window's own run, from the moment it is asked for; null until the first one
  const [run, setRun] = useState<FindingState | null>(start?.run ?? null)
  const [board, setBoard] = useState<RunBoard>({ active: false })
  const [finding, setFinding] = useState(Boolean(start?.run))
  const [refreshKey, setRefreshKey] = useState(0)
  const [newOnlyFirst, setNewOnlyFirst] = useState(false)
  const wasForeign = useRef(false)
  // A clicked notification that names a job: held until the screen that shows it has taken it.
  const [opening, setOpening] = useState<Opening | null>(null)
  const openings = useRef(0)

  const applyBoard = useCallback((b: RunBoard) => {
    setBoard(b)
    const foreign = b.active && !b.own
    if (foreign && !wasForeign.current) setFinding(true) // somebody else's run: show it, read only
    if (!foreign && wasForeign.current) {
      setFinding(false)
      setRefreshKey((k) => k + 1) // it is over: what it found is in the table now
    }
    wasForeign.current = foreign
  }, [])
  useEffect(() => {
    let live = true
    runBoard().then(
      (b) => live && applyBoard(b),
      () => undefined,
    )
    const unsubscribe = onRunBoard(applyBoard)
    return () => {
      live = false
      unsubscribe()
    }
  }, [applyBoard])

  const own = run?.kind === 'running' || (board.active && board.own)
  const preparingNow = usePreparing()
  const wasPreparing = useRef(false)
  useEffect(() => {
    if (wasPreparing.current && !preparingNow) setSummaryKey((k) => k + 1) // a prepare used some of the window
    wasPreparing.current = preparingNow
  }, [preparingNow])
  const foreign = board.active && !board.own
  const startRun = async (skip?: string[]) => {
    setRun({ kind: 'running', startedAt: new Date().toISOString() })
    setFinding(true)
    const outcome = await findJobs(skip ? { skip } : {})
    if (outcome.kind === 'stopped') {
      // Stop is "never mind": back to the screen the run was started from, nothing to say
      setRun(null)
      setFinding(false)
      setRefreshKey((k) => k + 1)
      return
    }
    if (outcome.kind === 'preparing') {
      // a Prepare began a moment before (Find new jobs is off while one runs): nothing ran
      setRun(null)
      setFinding(false)
      return
    }
    if (outcome.kind === 'busy') {
      // a run started elsewhere a moment before: show that one, read only, as soon as the board says so
      setRun(null)
      runBoard().then(applyBoard, () => undefined)
      return
    }
    setRun(outcome.kind === 'done' ? { kind: 'summary', record: outcome.record, firstRun: skip === FIRST_RUN_SKIP } : outcome.kind === 'error' ? { kind: 'error', message: outcome.message } : outcome)
    setRefreshKey((k) => k + 1)
  }
  const goToMatches = (newOnly: boolean) => {
    setFinding(false)
    setCurrent('Matches')
    setNewOnlyFirst(newOnly)
    // the run's outcome stays: a notification about it, clicked later, opens it rather than an empty screen
    setRefreshKey((k) => k + 1)
  }
  useEffect(
    () =>
      onOpen((target) => {
        // anything from the main process is checked here: a stale or odd target is ignored
        if (typeof target !== 'object' || target === null) return
        if (target.screen === 'matches') goToMatches(target.newOnly === true)
        else if (target.screen === 'finding') setFinding(true)
        else if ((target.screen === 'materials' || target.screen === 'posting') && typeof target.jobId === 'string') {
          openings.current += 1
          setFinding(false)
          setCurrent(target.inPlay ? 'Applications' : 'Matches')
          setOpening({ target, n: openings.current })
        }
      }),
    [],
  )
  const findingState: FindingState | null = board.active && board.own && run?.kind !== 'running' ? { kind: 'running' } : run
  // Finding jobs shows a run: this window's, or one started elsewhere; with neither there is nothing to show
  const showFinding = finding && (findingState !== null || foreign)
  // Every screen opens at its top: the one scrolling column is shared, so it would keep the last screen's place.
  // A layout effect, before the screens' own effects, so Settings can still scroll to the part it was opened at.
  useLayoutEffect(() => {
    mainRef.current?.scrollTo?.({ top: 0 })
  }, [current, showFinding])

  // The first launch: where the data is (the demo never gets the wizard; the onboarding sandbox,
  // empty by design, does) and what `show_profile` says. No config means the wizard; anything
  // odd (the server not answering) means the app, whose screens say what is wrong.
  useEffect(() => {
    let live = true
    ;(async () => {
      const info = await window.door.info?.().catch(() => undefined)
      if (!live) return
      setDemo(Boolean(info?.demo))
      setSandbox(info?.sandbox === 'onboard')
      setHome(info?.home)
      setRemote(Boolean(info?.remote))
      const wizardAllowed = !info?.demo || info.sandbox === 'onboard'
      try {
        const p = await call<ShowProfile>('show_profile')
        if (!live) return
        setProfile(p)
        if (p.config === null && info?.remote) setGate({ kind: 'remote-setup' })
        else setGate(p.config === null && wizardAllowed ? { kind: 'wizard', profile: p } : { kind: 'shell' })
      } catch {
        if (live) setGate({ kind: 'shell' })
      }
    })()
    return () => {
      live = false
    }
  }, [])
  useEffect(() => {
    document.title = sandbox ? 'The other door (onboarding sandbox)' : demo ? 'The other door (demo)' : 'The other door'
  }, [demo, sandbox])

  /** Opens the wizard on what is saved now (a fresh read): Profile's "Draft it from your CV file or pages",
   * offered while the CV is the example one or missing. A profile that cannot
   * be read throws; Profile already says so where it reads it. */
  const setUpAgain = async () => {
    const p = await call<ShowProfile>('show_profile')
    setProfile(p)
    setGate({ kind: 'wizard', profile: p })
  }
  const finishWizard = async (firstRun: boolean) => {
    try {
      setProfile(await call<ShowProfile>('show_profile'))
    } catch {
      // the old profile stays; the CV line may be out of date until the next launch
    }
    setGate({ kind: 'shell' })
    if (firstRun) void startRun(FIRST_RUN_SKIP)
    else goToMatches(true)
  }

  const inShell = gate.kind === 'shell'
  const foundOnOpen = useRef(false)
  useEffect(() => {
    if (!inShell || !start?.findOnOpen || foundOnOpen.current) return
    foundOnOpen.current = true
    void startRun()
  }, [inShell])
  useEffect(() => {
    if (!inShell) return // the caption is the sidebar's; the wizard has none
    let live = true
    statusSummary().then(
      (s) => {
        if (!live) return
        setLastRun(lastRunText(s.since_last_review?.last_run?.finished_at))
        setDrive(s.drive && typeof s.drive.connected === 'boolean' ? s.drive : null)
        setRecurring(typeof s.recurring_problem === 'boolean' ? s.recurring_problem : null)
        setPlan(s.plan ?? null)
      },
      () => undefined, // the caption is optional; Matches shows the failure
    )
    return () => {
      live = false
    }
  }, [refreshKey, summaryKey, inShell])

  // The window resets at a known time: read the summary once then, so a line that has run out goes by itself (no polling)
  useEffect(() => {
    const at = planReset(plan)?.getTime()
    if (at === undefined) return
    const wait = at - Date.now()
    if (wait <= 0) return
    const timer = setTimeout(() => setSummaryKey((k) => k + 1), Math.min(wait + 1000, 2 ** 31 - 1))
    return () => clearTimeout(timer)
  }, [plan])

  /** A pull or an import replaced profile/ and jobs/: read them again. */
  const dataChanged = () => {
    void call<ShowProfile>('show_profile').then(setProfile, () => undefined)
    recheck()
    setRefreshKey((k) => k + 1)
  }
  // Drive syncs once when the app opens, so this computer starts with what the other one did (the server
  // syncs around every change of the data, but opening and reading change nothing). Only on the user's own
  // data and never on the phone; a failure is kept by the server (the row and the sidebar say it), a
  // conflict asks.
  const syncedOnOpen = useRef(false)
  useEffect(() => {
    // decided on the first Drive status read: a Drive connected later syncs as it connects (Settings)
    if (!inShell || drive === null || syncedOnOpen.current) return
    syncedOnOpen.current = true
    if (remote || demo || sandbox || !drive.connected) return
    call<{ action: string }>('sync_data', {}).then(
      (r) => (r.action === 'pull' ? dataChanged() : setRefreshKey((k) => k + 1)),
      (e) => {
        if (e instanceof ApiError && e.conflict) setDriveConflict(true)
        setRefreshKey((k) => k + 1)
      },
    )
  }, [inShell, remote, demo, sandbox, drive])

  /** Reads doctor again: Claude's sign-in, for Settings and the sidebar's lines. The last answer stays
   * until the new one comes, and only the latest check's answer counts. A doctor that fails keeps its error.
   * Resolves once this check has answered (a sign-in waits for it before saying doctor cannot see it). */
  const doctorCalls = useRef(0)
  const recheck = useCallback((): Promise<void> => {
    const mine = ++doctorCalls.current
    const keep = (r: DoctorReport) => {
      if (mine === doctorCalls.current) setDoctor(r)
    }
    return call<DoctorReport>('doctor').then(keep, (e) => keep({ ok: false, checks: [], error: errorText(e) }))
  }, [])
  useEffect(() => {
    if (inShell && !remote) recheck() // the phone has no Claude sign-in to show: that is the computer's
  }, [inShell, remote, recheck])

  if (gate.kind === 'loading') return <Splash />
  if (gate.kind === 'remote-setup') {
    // The phone app cannot run the wizard: it needs that computer's files and its Claude sign-in.
    return (
      <main className="onb">
        <span className="dash" aria-hidden="true" />
        <h1 className="display-l">Set up The other door first</h1>
        <p className="body"><AppName /> has no profile yet. Set it up on the computer where it is installed (open the desktop app there, or run its setup), then come back here.</p>
      </main>
    )
  }
  if (gate.kind === 'wizard') {
    return (
      <div className="shell-bare">
        <main className="main">
          <Wizard profile={gate.profile} sandbox={sandbox} start={start?.wizard} onFinish={(firstRun) => void finishWizard(firstRun)} onCancel={gate.profile.config ? () => setGate({ kind: 'shell' }) : undefined} />
        </main>
      </div>
    )
  }
  const where = sandbox ? 'sandbox' : demo ? 'demo' : 'real'
  // What is wrong and needs you (Claude, the Claude plan's window, the CV, Drive, something that keeps going wrong):
  // a short line each at the sidebar's foot (the plan's opens nothing). On the phone they are said, not buttons: what fixes them is on the computer running
  // The other door; a problem report is made there too, so the phone does not say that one.
  const lines = problems({ doctor, drive, driveConflict, cv: demo ? null : profile?.config ? profile.cv : null, recurring: remote ? null : recurring, plan })
  const destinations = remote ? PHONE_DESTINATIONS : DESTINATIONS
  /** Opens Profile at one of its sections (the same way for every link into it). */
  const openProfile = (section: string) => {
    setFinding(false)
    setProfileStart((s) => ({ n: (s?.n ?? 0) + 1, at: { section } }))
    setCurrent('Profile')
  }
  /** Opens Settings at Risky sources, where the discovery sources are turned on. */
  const openRisky = () => {
    setFinding(false)
    setSettingsStart((s) => ({ n: (s?.n ?? 0) + 1, at: 'risky' }))
    setCurrent('Settings')
  }
  const fix = (p: Problem) => {
    setFinding(false)
    if (p.target === 'profile-cv') {
      setProfileStart((s) => ({ n: (s?.n ?? 0) + 1, at: { view: 'cv' } }))
      setCurrent('Profile')
    } else if (p.target === 'profile') setCurrent('Profile')
    else {
      if (p.target === 'settings-report') setSettingsStart((s) => ({ n: (s?.n ?? 0) + 1, at: 'report' }))
      setCurrent('Settings')
    }
  }
  const problemLines = (
    <div className="sidebar-problems" role="group" aria-label="Needs you">
      {lines.map((p) =>
        remote || p.target === 'none' ? (
          <p key={p.key} className="small sidebar-problem marked">
            <span className="mark"><WarningMark /></span>
            <span>{p.text}</span>
          </p>
        ) : (
          <button key={p.key} type="button" className="quiet sidebar-problem marked" onClick={() => fix(p)}>
            <span className="mark"><WarningMark /></span>
            <span>{p.text}</span>
          </button>
        ),
      )}
    </div>
  )

  return (
    <RemoteContext.Provider value={remote}>
    <div className={narrow && pushed ? 'shell pushed' : 'shell'}>
      {!(narrow && pushed) && (
      <aside className="sidebar">
        {demo && (
          // A small tag; the sentence is its tooltip.
          <p
            role="note"
            aria-label={sandbox ? 'Onboarding sandbox' : 'Demo data'}
            className="demo-tag small"
            title={sandbox ? 'Onboarding sandbox (app/.onboard). Nothing here changes your real data or Drive.' : 'Made-up jobs (app/.demo). Nothing here changes your real data or Drive.'}
          >
            {sandbox ? 'Sandbox' : 'Demo'}
          </p>
        )}
        <nav aria-label="Main">
          {destinations.map((name) => (
            <button key={name} type="button" className="nav-item" aria-current={name === current && !finding ? 'page' : undefined} onClick={() => {
                setCurrent(name)
                setFinding(false)
              }}>
              <TabIcon name={name} />
              {name}
              {narrow && name === current && !finding && <span className="tab-dash" aria-hidden="true" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          {lines.length > 0 && problemLines}
          <button type="button" className="secondary" disabled={foreign || (own && finding) || (!own && preparingNow)} title={!own && preparingNow ? PREPARING_TIP : undefined} onClick={() => (own ? setFinding(true) : void startRun())}>
            {own || foreign ? 'Finding jobs…' : 'Find new jobs'}
          </button>
          {lastRun && <p className="small muted">Last run {lastRun}</p>}
        </div>
      </aside>
      )}
      <main className="main" ref={mainRef}>
        {showFinding ? (
          <Finding
            state={findingState}
            board={board}
            onStart={() => void startRun()}
            onStop={() => void stopRun()}
            onViewMatches={() => goToMatches(true)}
            discoveryUnchosen={demo || remote ? [] : (profile?.discovery_unchosen ?? [])}
            discoveryOff={demo || remote || !profile ? [] : discoveryOff(profile)}
            onChooseDiscovery={openRisky}
            onFollowEmployers={remote ? undefined : () => openProfile('employers')}
            onLowerBar={remote ? undefined : () => openProfile('search')}
            onCheckSearch={remote ? undefined : () => openProfile('search')}
          />
        ) : current === 'Matches' ? (
          <>
          {narrow && !pushed && lines.length > 0 && (
            // The phone has no sidebar foot: what needs the user sits on top of Matches instead.
            <div className="narrow-top">{problemLines}</div>
          )}
          <Matches
            key={`${refreshKey}-${newOnlyFirst}`}
            onPushed={setPushed}
            newOnlyFirst={newOnlyFirst}
            finding={own ? 'own' : foreign ? 'elsewhere' : undefined}
            onFindJobs={() => (own ? setFinding(true) : void startRun())}
            preparing={!own && preparingNow}
            opening={opening}
            onOpened={() => setOpening(null)}
            onLowerBar={remote ? undefined : () => openProfile('search')}
            onChooseDiscovery={remote ? undefined : openRisky}
            onCheckSearch={remote ? undefined : () => openProfile('search')}
          />
          </>
        ) : current === 'Applications' ? (
          <Applications onPushed={setPushed} opening={opening} onOpened={() => setOpening(null)} />
        ) : current === 'Profile' && !remote ? (
          <Profile
            key={profileStart?.n ?? 0}
            start={profileStart?.at}
            onDraft={() => void setUpAgain().catch(() => undefined)}
            onSaved={() => {
              void call<ShowProfile>('show_profile').then(setProfile, () => undefined)
              setRefreshKey((k) => k + 1) // the matches may change with the minimum score or the age limit
            }}
          />
        ) : current === 'Settings' ? (
          <Settings
            key={settingsStart?.n ?? 0}
            at={settingsStart?.at}
            onReported={() => setRefreshKey((k) => k + 1)}
            doctor={doctor}
            drive={drive}
            where={where}
            home={home}
            email={profile?.config?.email}
            onRecheck={recheck}
            driveConflict={driveConflict}
            onDriveConflict={setDriveConflict}
            onDriveChanged={() => setRefreshKey((k) => k + 1)}
            onDataChanged={dataChanged}
          />
        ) : current === 'Analytics' && !remote ? (
          <Analytics />
        ) : null}
      </main>
    </div>
    </RemoteContext.Provider>
  )
}
