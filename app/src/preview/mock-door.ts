// The screen preview's window.door: answers from fixtures.json (the real server's answers on the demo
// data), so nothing runs but the browser: no Electron, no Python, no claude, and nothing is ever written.
// A write answers as if it worked and the data stays as it was; a reload starts the scene over.
import { doctorReport } from '../renderer/screens/onboarding/testing'
import { playRun } from '../main/demo-script'
import type { RunBoard } from '../main/run-board'
import type { Envelope } from '../main/ipc'
import fixtures from './fixtures.json'
import cvPage1 from '../../test/fixtures/prepared/cv_page_1.png'
import cvPage2 from '../../test/fixtures/prepared/cv_page_2.png'
import letterPage1 from '../../test/fixtures/prepared/cover_letter_page_1.png'
import { SAMPLE_RUN, type DataState, type Scene } from './scenes'
import pairQr from './pair-qr.svg?raw'

type Answer = { data: unknown } | { error: string }

/** The sidebar's own reads: they answer in every state, so a state shows on the screen under test. */
const SHELL_TOOLS = new Set(['doctor', 'status_summary', 'phone_status'])
const LONG_TITLE = ' — Regional Transformation Lead for Finance, Risk and Compliance across the Nordics and the Baltics'
const LONG_COMPANY = ' Holding, Shipping & Offshore Logistics Group A/S'
const COPIES = 8

interface Row {
  id: string
  title: string
  company: string
}
type List = { matches: Row[] }

const lengthen = <T extends { title: string; company: string }>(row: T): T => ({ ...row, title: row.title + LONG_TITLE, company: row.company + LONG_COMPANY })
const longRows = (list: List): List => ({
  ...list,
  matches: Array.from({ length: COPIES }, (_, n) => list.matches.map((m) => lengthen({ ...m, id: `${m.id}~${n}` }))).flat(),
})

function listFor(args: Record<string, unknown>): List {
  if (args['closed']) return fixtures.list_matches_closed as List
  if (args['ongoing']) return fixtures.list_matches_ongoing as List
  return fixtures.list_matches as List
}

/** The page images: the demo's (`test/fixtures/prepared/`, the example CV laid out as the templates do, rendered
 * at prepare's 150 DPI), picked by the file name the fixture asks for. */
const PAGES: Record<string, string> = { cv_page_1: cvPage1, cv_page_2: cvPage2, cover_letter_page_1: letterPage1 }
const pageUrl = (_jobId: string, pngPath: string): string => PAGES[pngPath.split('/').pop()!.replace(/\.png$/, '')] ?? cvPage1


// What a page shows and the CV lacks, as the preview's enrich proposes it.
const ENRICH_PROPOSALS = [
  { n: 1, section: 'Work Experience', text: 'Built a month-end close tracker in Power BI, used by four subsidiaries.' },
  { n: 2, section: 'Certifications', text: 'Power Query for finance (online course) — 2024' },
]

/** `- text` under `## section`, after its last bullet (or its heading), as enrich inserts it; a new section at the end. */
function addBullet(cv: string, section: string, text: string): string {
  const lines = cv.split('\n')
  const at = lines.findIndex((l) => l.trim() === `## ${section}`)
  if (at < 0) return `${cv.trimEnd()}\n\n## ${section}\n\n- ${text}\n`
  let end = lines.findIndex((l, i) => i > at && /^## /.test(l))
  if (end < 0) end = lines.length
  let last = -1
  for (let i = at + 1; i < end; i++) if (/^\s*[-*+]\s/.test(lines[i]!)) last = i
  lines.splice(last >= 0 ? last + 1 : at + 2, 0, `- ${text}`)
  return lines.join('\n')
}

export function createMockDoor(scene: Scene, state: DataState, { delayMs = 300 }: { delayMs?: number } = {}): Window['door'] {
  // Claude as a scene starts it: the install and the sign-in below change it, as the real ones would.
  let installed = !scene.claudeNotInstalled
  let signedIn = !scene.claudeSignedOut && !scene.claudeNotInstalled
  const loginListeners = new Set<(s: { state: 'done' }) => void>()
  // Google Drive as the scene starts it: connect_drive, sync_data and disconnect_drive change it.
  const ACCOUNT = 'jane.doe@example.com'
  const start = scene.drive ?? 'off'
  let drive = {
    ...fixtures.status_summary.drive,
    ...(start === 'off' ? {} : { connected: true, account: ACCOUNT, last_synced: '2026-10-29T09:00:00+00:00' }),
    ...(start === 'failed' ? { last_error: 'Google Drive did not answer (503).' } : {}),
  }
  let conflict = start === 'conflict'
  // Your phone: phone_start serves, pair_phone shows a QR code (made up: it leads nowhere), and the phone
  // "scans" it a few seconds later, as phone_status then says; unpair_phone and phone_stop undo it.
  type Device = { device: string; paired_at: string | null; last_seen: string | null }
  let phone: { running: boolean; devices: Device[] } = { running: false, devices: [] }
  const phoneStatus = () => ({
    ...phone,
    ...(phone.running ? { connection: 'cloudflare', address: 'https://preview-made-up.trycloudflare.com', lasting: false } : {}),
    web_built: true,
    tailscale_installed: false,
  })
  const phoneCall = (tool: string, args: Record<string, unknown>): Envelope | null => {
    if (tool === 'phone_start') {
      phone = { ...phone, running: true }
      return { ok: true, data: phoneStatus() }
    }
    if (tool === 'pair_phone') {
      const device = String(args['device'] ?? 'My phone')
      setTimeout(() => {
        const at = new Date().toISOString()
        phone = { ...phone, devices: [...phone.devices.filter((d) => d.device !== device), { device, paired_at: at, last_seen: at }] }
      }, 5_000)
      return { ok: true, data: { device, qr_svg: pairQr, expires_at: new Date(Date.now() + 5 * 60_000).toISOString() } }
    }
    if (tool === 'unpair_phone') {
      phone = { ...phone, devices: phone.devices.filter((d) => d.device !== args['device']) }
      return { ok: true, data: { removed: args['device'] } }
    }
    if (tool === 'phone_stop') {
      phone = { ...phone, running: false }
      return { ok: true, data: { stopped: true } }
    }
    return null
  }
  const driveCall = (tool: string, args: Record<string, unknown>): Envelope | null => {
    if (tool === 'connect_drive') {
      drive = { ...drive, connected: true, account: ACCOUNT, last_synced: null, last_error: null }
      return { ok: true, data: { account: ACCOUNT } }
    }
    if (tool === 'disconnect_drive') {
      drive = { ...drive, connected: false, account: null, last_synced: null, last_error: null }
      return { ok: true, data: {} }
    }
    if (tool !== 'sync_data') return null
    const keep = args['keep_local'] ? 'push' : args['keep_drive'] ? 'pull' : null
    if (conflict && !keep) return { ok: false, error: 'This computer and Drive both changed since the last sync.', conflict: true }
    // still unreachable: the sync on opening fails as the last one did, and the row keeps saying so
    if (start === 'failed') return { ok: false, error: drive.last_error ?? 'Google Drive did not answer (503).' }
    conflict = false
    drive = { ...drive, last_synced: new Date().toISOString(), last_error: null }
    return { ok: true, data: { action: keep ?? 'push' } }
  }
  const freshProfile = () => ({ ...fixtures.show_profile, config: null, errors: ['config.json not found'], cv: { ...fixtures.show_profile.cv, exists: false, text: null, headline: null, sections: [] }, discovery_unchosen: [] })
  // The CV as "Add … to my CV" left it: each added line a bullet under its section, as enrich writes it.
  let cvText = fixtures.show_profile.cv.text
  const withCv = <T extends { cv: object }>(p: T): T => ({ ...p, cv: { ...p.cv, text: cvText } })
  const profile = () =>
    scene.fresh ? freshProfile() : withCv(scene.discoveryUnchosen !== undefined ? { ...fixtures.show_profile, discovery_unchosen: scene.discoveryUnchosen } : fixtures.show_profile)

  // The matches opened so far (`mark_seen`): no longer new, as the server would answer.
  const seen = new Set<string>()
  // The jobs prepared so far (`prepare`): `show` then has their CV and letter, borrowed from the prepared
  // fixture, as the server's would after a real prepare.
  const prepared = new Set<string>()
  const unseen = (l: List, newOnly = false): List => {
    const rows = l.matches.map((m) => (seen.has(m.id) ? { ...m, is_new: false } : m))
    return { ...l, matches: newOnly ? rows.filter((m) => (m as { is_new?: boolean }).is_new) : rows }
  }
  const newCount = () => fixtures.list_matches.matches.filter((m) => m.is_new && !seen.has(m.id)).length
  /** Answers for `state === 'ok'`, and the base the other states change. */
  const answer = (tool: string, args: Record<string, unknown>): unknown => {
    switch (tool) {
      case 'show_profile':
        return profile()
      case 'status_summary':
        return {
          ...fixtures.status_summary,
          drive,
          since_last_review: { ...fixtures.status_summary.since_last_review, new_matches: state === 'empty' ? 0 : newCount() },
          ...(state === 'empty' ? { plan: null, cost: null } : {}),
          // the plan's window nearly full: the sidebar's foot says so
          ...(state === 'plan-low' ? { plan: { ...fixtures.status_summary.plan, five_hour: { used: 0.9, resets_at: new Date(Date.now() + 90 * 60_000).toISOString() }, room: { find: 1, prepare: 2 } } } : {}),
        }
      case 'doctor':
        if (!installed) return { ok: false, checks: [{ name: 'claude CLI', status: 'missing', required: true, detail: 'no claude found' }] }
        return doctorReport(signedIn ? 'ok' : 'out')
      case 'setup':
        if (scene.installFails) return { outcome: 'incomplete', results: [{ tool: 'claude', ok: false, error: 'The installer could not reach the network.' }], todo: ['create your profile: run onboarding'] }
        installed = true
        return { outcome: 'ok', results: [{ tool: 'claude', ok: true }] }
      case 'list_matches':
        return state === 'empty' ? { ...listFor(args), matches: [] } : state === 'long' ? longRows(unseen(listFor(args), Boolean(args['new_only']))) : unseen(listFor(args), Boolean(args['new_only']))
      case 'mark_seen':
        seen.add(String(args['job_id']))
        return { job_id: args['job_id'] }
      case 'list_companies':
        return state === 'empty' ? { companies: [] } : fixtures.list_companies
      case 'show': {
        const id = String(args['job_id']).replace(/~\d+$/, '')
        const job = (fixtures.show as Record<string, Row>)[id]
        if (!job) throw new Error(`No job matches "${id}".`)
        const shown = fixtures.show as Record<string, Row & { materials?: unknown }>
        const ready = prepared.has(id) && !shown[id]!.materials ? { ...job, status: 'prepared', materials: shown['successfactors.demo-6']!.materials } : job
        return state === 'long' ? lengthen({ ...ready, id: String(args['job_id']) }) : ready
      }
      case 'prepare': {
        const id = String(args['job_id']).replace(/~\d+$/, '')
        prepared.add(id)
        return { job_id: id, outcome: 'prepared' }
      }
      case 'set_status': {
        // what the server answers: the status recorded, which the notice names
        const status = String(args['status'])
        return { job_id: String(args['job_id']).replace(/~\d+$/, ''), status, current: status }
      }
      case 'why_company':
        return { company: fixtures.list_companies.companies[0], postings: 3 }
      case 'find_jobs':
        return SAMPLE_RUN
      case 'ask':
        return { answer: 'Two of your new matches are in shipping; Oceanic Shipping scores highest.', go_to: { screen: 'matches' }, sources: [] }
      case 'infer_basics':
        return {
          name: 'Jane Doe',
          email: 'jane@example.com',
          location: 'Copenhagen',
          languages: ['English', 'Danish'],
          remote: 'hybrid',
          missing: [],
        }
      case 'suggest_titles':
        return { titles: [{ title: 'Financial Controller', reason: 'Five years of month-end close and group reporting.', recommended: true }, { title: 'Head of Finance', reason: 'A step up: you have led a small team.', recommended: false }] }
      case 'keywords':
        return { keywords: ['financial controller', 'controller', 'økonomimedarbejder'], topic_terms: ['controller', 'økonomi*'] }
      case 'market':
        return { counts: { scraped: 412, scored: 96, above_min_score: 23 }, skills: [{ name: 'IFRS', count: 44, share: 0.46, have: true }, { name: 'SAP', count: 31, share: 0.32, have: false }, { name: 'Power BI', count: 22, share: 0.23, have: false }], near_misses: { n: 7, rows: [{ skill: 'SAP', count: 5 }] }, uncovered_titles: [{ title: 'Finance Manager', count: 6 }], warning: null }
      case 'skill_gaps':
        return { report: '# Skill gaps\n\n## SAP\n\nAsked for by a third of the ads you nearly match.', report_path: '/demo/upskill/report.md' }
      case 'enrich':
        // what a page shows and the CV lacks; adding answers what was added
        if (args['apply']) {
          const added = ENRICH_PROPOSALS.filter((p) => (args['apply'] as number[]).includes(p.n))
          for (const p of added) cvText = addBullet(cvText, p.section, p.text)
          return { outcome: 'applied', added }
        }
        return {
          outcome: 'proposed',
          urls: args['urls'],
          unreachable: [],
          proposals: ENRICH_PROPOSALS.map((p) => ({ ...p, source: (args['urls'] as string[] | undefined)?.[0] ?? fixtures.show_profile.enrich_sources[0] })),
        }
      case 'list_stories':
        return { ...fixtures.list_stories, stories: state === 'empty' ? [] : fixtures.list_stories.stories }
      case 'draft_stories':
        return {
          outcome: 'proposed',
          stories: [
            { ...fixtures.list_stories.stories[0], title: 'Moved the budget to a rolling forecast', missing: [], conflicts: [] },
            { ...fixtures.list_stories.stories[1], title: 'Introduced a shared close calendar', learning: '', missing: ['learning'], conflicts: ['You wrote 12 days; your CV says 10.'] },
          ],
        }
      case 'phone_status':
        return phoneStatus()
      default:
        return {} // a write: it "worked", and nothing changed
    }
  }

  // Each `info()` is the app starting: it reads the profile once to choose the wizard or the shell, and
  // that read answers in every state, or the error and loading states would never reach a screen.
  let gateReads = 0
  // The whole run (`scene.play`): the demo's timeline pushes the boards a real run does, then answers.
  const boardListeners = new Set<(b: RunBoard) => void>()
  const pushBoard = (b: RunBoard) => boardListeners.forEach((l) => l(b))
  let stopPlay: (() => void) | null = null
  const playFind = (args: Record<string, unknown>): Promise<Envelope> =>
    new Promise((resolve) => {
      const startedAt = new Date().toISOString()
      const skip = Array.isArray(args['skip']) ? (args['skip'] as unknown[]).map(String) : []
      const play = playRun({ startedAt, skip, onBoard: pushBoard })
      stopPlay = () => {
        play.stop()
        pushBoard({ active: false })
        resolve({ ok: false, error: 'stopped', stopped: true })
      }
      void play.ended.then(() => {
        stopPlay = null
        pushBoard({ active: false })
        resolve({ ok: true, data: { ...SAMPLE_RUN, started_at: startedAt } })
      })
    })
  const respond = async (tool: string, args: Record<string, unknown>): Promise<Envelope> => {
    if (tool === 'find_jobs' && scene.play) return playFind(args)
    const free = SHELL_TOOLS.has(tool) || (tool === 'show_profile' && gateReads > 0)
    if (tool === 'show_profile' && gateReads > 0) gateReads -= 1
    if (scene.hold === tool) return new Promise(() => undefined)
    if (!free && state === 'loading') return new Promise(() => undefined)
    if (delayMs > 0) await new Promise((r) => setTimeout(r, scene.slow?.[tool] ?? delayMs))
    if (!free && state === 'error') return { ok: false, error: 'The other door did not answer (the preview\'s error state).' }
    const handled = driveCall(tool, args) ?? phoneCall(tool, args)
    if (handled) return handled
    try {
      return { ok: true, data: answer(tool, args) }
    } catch (e) {
      return { ok: false, error: (e as Error).message }
    }
  }

  const done = async () => ({ ok: true })
  const never = () => () => undefined
  return {
    call: (tool, args = {}) => respond(tool, args),
    onProgress: never,
    openExternal: done,
    saveMaterial: async (_j: string, _w: string, _s: boolean, name: string) => ({ ok: true, path: `/Users/jane/Downloads/${name}` }),
    pickCvFiles: async () => ({ files: [{ token: 'preview-1', name: 'jane-doe-cv.pdf', size: 184_000 }], refused: [] }),
    dropCvFiles: async (files) => ({ files: files.map((f, i) => ({ token: `preview-drop-${i}`, name: f.name, size: f.size })), refused: [] }),
    draftCv: async () => {
      const r = await respond('draft_cv', {})
      if (!r.ok) return r
      return { ok: true, data: { markdown: fixtures.show_profile.cv.text, provenance: [], todos: [], sources: [{ source: 'jane-doe-cv.pdf', kind: 'file', chars: 5400 }] } }
    },
    clearCvSources: async () => undefined,
    pickPhoto: async () => ({ token: 'preview-photo', name: 'portrait.jpg' }),
    savePhoto: async () => ({ ok: true, data: { photo_path: '/demo/profile/photo.jpg' } }),
    claudeLogin: {
      start: async () => {
        // A moment for the "Starting the sign-in" line, then signed in, with no browser.
        setTimeout(() => {
          signedIn = true
          loginListeners.forEach((listener) => listener({ state: 'done' }))
        }, 1500)
        return { ok: true }
      },
      sendCode: done,
      openPage: done,
      cancel: done,
      state: async () => ({ state: 'idle' }),
      onState: (cb: (s: { state: 'done' }) => void) => {
        loginListeners.add(cb)
        return () => loginListeners.delete(cb)
      },
    },
    info: async () => {
      gateReads = 1
      return { demo: false, home: '/demo' }
    },
    pageUrl,
    exportData: async () => ({ ok: false, canceled: true }),
    pickArchive: async () => ({ canceled: true }),
    importData: async () => ({ ok: false, error: 'Nothing is imported in the preview.' }),
    reportProblem: async () => ({ ok: false, canceled: true }),
    showHome: done,
    checkUpdate: async () => ({ enabled: false as const }),
    stopRun: async () => {
      stopPlay?.()
      stopPlay = null
      return { ok: true }
    },
    showRun: done,
    runBoard: async () => scene.board ?? { active: false },
    onRunBoard: (cb: (b: RunBoard) => void) => {
      boardListeners.add(cb)
      return () => boardListeners.delete(cb)
    },
    onOpen: (cb) => {
      // After the app has subscribed, as a click on a notification would be.
      const timer = scene.open ? setTimeout(() => cb(scene.open!), 0) : undefined
      return () => clearTimeout(timer)
    },
  } as Window['door']
}
