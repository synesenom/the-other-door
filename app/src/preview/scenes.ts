// The screen preview's scenes (`npm run dev:preview`): each opens one screen of the real app, on made-up
// data, in a plain browser tab. A scene's address survives a reload, so a change that Fast Refresh cannot
// keep (the reducer, App.tsx) comes back to the same screen.
import type { AppStart } from '../renderer/App'
import type { NoticeTarget, RunRecord } from '../renderer/api'
import type { WizardState } from '../renderer/screens/onboarding/reducer'
import type { RunBoard, StepRow } from '../main/run-board'
import fixtures from './fixtures.json'

/** What the data tools answer: `ok` the fixtures, then the states every screen has to hold up in. */
export const DATA_STATES = ['ok', 'empty', 'loading', 'error', 'long', 'plan-low'] as const
export type DataState = (typeof DATA_STATES)[number]

export interface Scene {
  id: string
  group: string
  title: string
  start?: AppStart
  /** A clicked notification, fired once the app listens: how a posting or the materials open. */
  open?: NoticeTarget
  board?: RunBoard
  /** A home with no profile: the wizard opens. */
  fresh?: boolean
  claudeSignedOut?: boolean
  claudeNotInstalled?: boolean
  /** The install answers that it did not finish. */
  installFails?: boolean
  /** How long a tool takes here, in ms, for a screen meant to be watched at its real pace. */
  slow?: Record<string, number>
  /** A tool that never answers, so a passing step stays on screen. */
  hold?: string
  /** The visual guide (`Guide.tsx`) in place of the app: every control on one page. */
  guide?: boolean
  /** A run starts on opening and plays the desktop demo's scripted run (demo-script.ts) through to its summary; Stop ends it. */
  play?: boolean
  /** The discovery sources never chosen, in place of the fixtures' (`show_profile`). */
  discoveryUnchosen?: { key: string; label: string }[]
  /** Google Drive as the scene starts it (default off): Connect and Disconnect, and the sync on opening, change it
   * as the real tools would. `failed`: connected, the last sync failed; `conflict`: the next sync finds both sides changed. */
  drive?: 'off' | 'connected' | 'failed' | 'conflict'
}

export const SAMPLE_RUN: RunRecord = {
  started_at: '2026-10-30T07:00:00+00:00',
  finished_at: '2026-10-30T07:41:00+00:00',
  elapsed_s: 2460,
  steps: ['search', 'follow', 'collect', 'match'],
  skipped: { discover: '--skip' },
  search: { sites: [{ site: 'jobindex', outcome: 'ok', count: 34 }, { site: 'thehub', outcome: 'failed', count: 0, errors: ['thehub: 503 Service Unavailable'] }] },
  collect: { sites: [{ site: 'greenhouse', outcome: 'ok', count: 12 }, { site: 'teamtailor', outcome: 'empty', count: 0, warning: 'no records' }] },
  match: { scored: 8, above_threshold: 2, min_score: 0.65 },
  new_above_threshold: ['greenhouse.demo-3', 'jobindex.demo-1'],
  top: [
    { id: 'jobindex.demo-1', score: 0.88, title: 'Senior Financial Controller', company: 'Oceanic Shipping' },
    { id: 'greenhouse.demo-3', score: 0.76, title: 'Group Controller', company: 'Globex Energy' },
  ],
  failures: ['thehub'],
}

/** A run that found jobs but none reached the bar. */
export const SAMPLE_RUN_NONE: RunRecord = {
  ...SAMPLE_RUN,
  match: { scored: 40, above_threshold: 0, min_score: 0.65 },
  new_above_threshold: [],
  top: [],
}

// A run caught in each of its five steps, as the server folds it: the steps before are done,
// the ones after wait. Times count back from when the preview loads, so the clocks read sensibly.
const RUN_STEPS = ['search', 'discover', 'follow', 'collect', 'match'] as const
type RunStep = (typeof RUN_STEPS)[number]
const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString()
// [started, finished] in minutes before now, for a step that is done
const DONE_AT: Record<RunStep, [number, number]> = { search: [24, 20], discover: [20, 12], follow: [12, 9], collect: [9, 3], match: [3, 0] }
const DONE: Record<RunStep, string> = {
  search: '34 postings from 5 boards',
  discover: '6 employers found',
  follow: '4 followed, 1 unfollowable',
  collect: '5 employers, 25 postings',
  match: '8 scored, 2 new >= 0.65',
}
const RUNNING: Record<RunStep, Omit<StepRow, 'name' | 'status' | 'detail' | 'started_at'>> = {
  search: {
    done: 3,
    total: 8,
    items: [
      { id: 'jobindex', name: 'Jobindex', state: 'running' },
      { id: 'thehub', name: 'The Hub', state: 'done' },
      { id: 'euraxess', name: 'EURAXESS', state: 'running' },
      { id: 'globalnyt', name: 'Globalnyt', state: 'done' },
      { id: 'jobbank', name: 'Akademikernes Jobbank', state: 'running' },
      { id: 'jobmaskinen', name: 'Jobmaskinen', state: 'running' },
      { id: 'workable', name: 'Workable', state: 'done' },
      { id: 'reliefweb', name: 'ReliefWeb', state: 'failed' },
    ],
    sites: { jobindex: 14, thehub: 6, globalnyt: 2, workable: 1 }, // keyed by the board's id, as the server folds them
  },
  // LinkedIn reading
  discover: {
    request: 'page 3/15',
    requests: [3, 15],
    items: [{ id: 'linkedin', name: 'LinkedIn', state: 'running' }],
  },
  follow: { done: 4, total: 6 },
  collect: { done: 2, total: 5, hosts: ['Globex Energy'], sites: { 'Oceanic Shipping': 3, 'Acme Foods': 4 } },
  match: { done: 5, total: 8 },
}

function runningBoard(at: RunStep): RunBoard {
  const here = RUN_STEPS.indexOf(at)
  const steps: StepRow[] = RUN_STEPS.map((name, i) => {
    if (i < here) return { name, status: 'done', detail: DONE[name], started_at: minutesAgo(DONE_AT[name][0] - DONE_AT[at][0]), finished_at: minutesAgo(DONE_AT[name][1] - DONE_AT[at][0]) }
    if (i > here) return { name, status: 'waiting', detail: '' }
    return { name, status: 'running', detail: '', started_at: minutesAgo(2), ...RUNNING[name] }
  })
  return { active: true, own: true, started_at: steps[0].started_at ?? minutesAgo(2), purpose: 'run', message: '', steps }
}

const RUNNING_SCENES: Scene[] = RUN_STEPS.map((step, i) => ({
  id: `finding-running-${step}`,
  group: 'Finding jobs',
  title: `Running, ${i + 1}. ${step[0].toUpperCase()}${step.slice(1)}`,
  start: { run: { kind: 'running' } },
  board: runningBoard(step),
  ...(step === 'discover' ? { discoveryUnchosen: [] } : {}),
}))

const CV = fixtures.show_profile.cv.text ?? ''
const FILE = { token: 'preview-1', name: 'jane-doe-cv.pdf', size: 184_000 }

/** Every answer in the wizard, as the reading step leaves them. */
const ANSWERED: Partial<WizardState> = {
  files: [FILE],
  name: 'Jane Doe',
  email: 'jane@example.com',
  location: 'Copenhagen',
  languages: ['English', 'Danish'],
  remote: 'hybrid',
  titles: [
    { title: 'Financial Controller', reason: 'Five years of month-end close and group reporting.', recommended: true },
    { title: 'Finance Business Partner', reason: 'The forecasting work with the business units.', recommended: true },
    { title: 'Head of Finance', reason: 'A step up: you have led a small team.', recommended: false },
  ],
  roleTargets: ['Financial Controller', 'Finance Business Partner'],
  keywords: ['financial controller', 'controller', 'økonomimedarbejder', 'business partner'],
  topicTerms: ['controller', 'finance', 'økonomi*', 'regnskab*'],
  keywordsState: 'proposed',
  cvText: CV,
  cvDraft: {
    sources: [{ source: 'jane-doe-cv.pdf', kind: 'file', chars: 5400 }],
  },
}

export const SCENES: readonly Scene[] = [
  { id: 'guide', group: 'Visual guide', title: 'Buttons, fields, marks, type and colours', guide: true },
  { id: 'splash', group: 'Start', title: 'Splash', hold: 'show_profile' },
  { id: 'matches', group: 'Matches', title: 'Matches' },
  { id: 'posting', group: 'Matches', title: 'Posting', open: { screen: 'posting', jobId: 'jobindex.demo-1', inPlay: false } },
  { id: 'applications', group: 'Applications', title: 'Applications board', start: { destination: 'Applications' } },
  { id: 'posting-prepared', group: 'Applications', title: 'Posting, prepared', open: { screen: 'posting', jobId: 'successfactors.demo-6', inPlay: true } },
  { id: 'materials', group: 'Applications', title: 'Ready to send (Revise)', open: { screen: 'materials', jobId: 'successfactors.demo-6', inPlay: true } },
  { id: 'sent', group: 'Applications', title: 'What you sent', open: { screen: 'materials', jobId: 'jobindex.demo-7', inPlay: true } },
  { id: 'profile', group: 'Profile', title: 'Profile form', start: { destination: 'Profile' } },
  { id: 'profile-cv', group: 'Profile', title: 'CV', start: { destination: 'Profile', cv: true } },
  { id: 'profile-stories', group: 'Profile', title: 'Stories', start: { destination: 'Profile', stories: true } },
  { id: 'settings', group: 'Settings', title: 'Settings', start: { destination: 'Settings' } },
  { id: 'analytics', group: 'Analytics', title: 'Analytics: Claude usage', start: { destination: 'Analytics' } },
  { id: 'settings-signed-out', group: 'Settings', title: 'Settings, Claude signed out', start: { destination: 'Settings' }, claudeSignedOut: true },
  { id: 'settings-drive', group: 'Settings', title: 'Google Drive: Connect (it syncs at once), Disconnect', start: { destination: 'Settings' }, drive: 'off', slow: { connect_drive: 2_500, sync_data: 1_500 } },
  { id: 'settings-drive-failed', group: 'Settings', title: 'Google Drive: the last sync failed', start: { destination: 'Settings' }, drive: 'failed' },
  { id: 'settings-drive-conflict', group: 'Settings', title: 'Google Drive: both sides changed, found on opening', start: { destination: 'Settings' }, drive: 'conflict' },
  ...RUNNING_SCENES,
  // LinkedIn chosen and read
  { id: 'finding-flow', group: 'Finding jobs', title: 'The whole run', play: true, start: { findOnOpen: true }, discoveryUnchosen: [] },
  { id: 'finding-summary', group: 'Finding jobs', title: 'Summary', start: { run: { kind: 'summary', record: SAMPLE_RUN } } },
  { id: 'finding-summary-none', group: 'Finding jobs', title: 'Summary, nothing reached the bar', start: { run: { kind: 'summary', record: SAMPLE_RUN_NONE } } },
  {
    id: 'finding-first-run',
    group: 'Finding jobs',
    title: 'First run, few matches',
    start: { run: { kind: 'summary', record: { ...SAMPLE_RUN, new_above_threshold: ['jobindex.demo-1'], top: SAMPLE_RUN.top.slice(0, 1) }, firstRun: true } },
  },
  { id: 'finding-error', group: 'Finding jobs', title: 'Failed', start: { run: { kind: 'error', message: 'The server stopped answering.' } } },
  { id: 'onboarding-signed-out', group: 'Onboarding', title: 'Connect Claude, signed out', fresh: true, claudeSignedOut: true },
  { id: 'onboarding-no-claude', group: 'Onboarding', title: 'Connect Claude, not installed', fresh: true, claudeNotInstalled: true },
  { id: 'onboarding-install-fails', group: 'Onboarding', title: 'Connect Claude, the install fails', fresh: true, claudeNotInstalled: true, installFails: true },
  { id: 'onboarding-sources', group: 'Onboarding', title: '1. Sources', fresh: true },
  { id: 'onboarding-reading', group: 'Onboarding', title: '2. Reading, slowed down (reload to watch again)', fresh: true, start: { wizard: { step: 'reading', files: [FILE] } }, slow: { draft_cv: 8_000, infer_basics: 2_000, suggest_titles: 3_000, keywords: 3_000 } },
  { id: 'onboarding-reading-last', group: 'Onboarding', title: '2. Reading, stays on the last step', fresh: true, start: { wizard: { step: 'reading', files: [FILE] } }, hold: 'keywords' },
  { id: 'onboarding-review', group: 'Onboarding', title: '3. Review', fresh: true, start: { wizard: { ...ANSWERED, step: 'review' } } },
  { id: 'onboarding-review-unfound', group: 'Onboarding', title: '3. Review, details not found', fresh: true, start: { wizard: { ...ANSWERED, step: 'review', name: '', email: '', location: '', titles: [], roleTargets: [], keywords: [], topicTerms: [], keywordsState: 'none', missing: ['name', 'email', 'location', 'titles'] } } },
  { id: 'onboarding-review-gaps', group: 'Onboarding', title: '3. Review, the CV has gaps', fresh: true, start: { wizard: { ...ANSWERED, step: 'review', cvText: CV.replace('+45 00 00 00 00', 'TODO').replace(/(BSc in Business Administration.*— ).*/, '$1TODO') } } },
  { id: 'onboarding-review-no-cv', group: 'Onboarding', title: '3. Review, the draft failed', fresh: true, start: { wizard: { ...ANSWERED, cvText: null, cvDraft: null, step: 'review' } } },
]

export function sceneById(id: string): Scene | undefined {
  return SCENES.find((s) => s.id === id)
}

/** The scene and state a page's address names; null opens the list of scenes. */
export function readSelection(query: URLSearchParams): { scene: Scene; state: DataState } | null {
  const scene = sceneById(query.get('scene') ?? '')
  if (!scene) return null
  const asked = query.get('state') as DataState
  return { scene, state: DATA_STATES.includes(asked) ? asked : 'ok' }
}
