// Test helper: a stand-in for the preload's window.door. A tool handler is a value
// (the tool's result) or a function of the arguments; throwing { message,
// candidates? } answers the way a failed tool does. Every other capability is an action
// (src/main/ipc.ts's `buildActions`): `m.actions[name]` is its `vi.fn`, answering a default until a
// test gives it another answer (`mockDoor(handlers, { actions: { 'save-material': fn } })` or
// `m.actions['save-material'].mockResolvedValueOnce(...)`). A new action needs no entry here:
// a test that reaches it gives it its answer; an action with no answer is refused.
import { vi, type Mock } from 'vitest'
import { EVENTS, type ActionArgs, type ActionName, type ActionResult, type Events } from '../main/ipc'
import { unknownAction } from './unknown-action'

type Handler = unknown | ((args: Record<string, unknown>) => unknown)

/** What `show_profile` answers unless a test says otherwise: a saved profile with the user's own CV, so the app opens as usual. */
const SAVED_PROFILE = {
  path: '/p',
  config: { name: 'Ada Lovelace', email: 'ada@example.com', location: 'Aarhus', languages: ['English'], role_targets: ['Data Scientist'], search_keywords: ['data scientist'], remote: 'hybrid', min_score: 0.65, exclude: { companies: [], keywords: [] } },
  errors: [],
  cv: { path: '/p/cv.md', exists: true, is_example: false, text: '# Ada\n', headline: 'Ada', sections: [] },
  options: { cities: [{ name: 'Aarhus', country: 'Denmark', boards: ['jobindex'] }], languages: ['English', 'Danish'], worldwide_boards: ['workable'] },
  enrich_sources: [],
}

type Answers = { [A in ActionName]: (...args: ActionArgs<A>) => ActionResult<A> | Promise<ActionResult<A>> }
type ActionMocks = { [A in ActionName]: Mock<(...args: ActionArgs<A>) => Promise<ActionResult<A>>> }
type Progress = { progress: number; total?: number; message: string }
type Listeners = { [E in keyof Events]: Set<(payload: Events[E]) => void> }

export function mockDoor(given: Record<string, Handler>, options: { actions?: Partial<Answers> } = {}) {
  const handlers: Record<string, Handler> = { show_profile: SAVED_PROFILE, ...given }
  // `tokens`: the picked files of draft_cv, enrich, save_photo, import_data (their handler gets them as `tokens`)
  const call = vi.fn(async (tool: string, args: Record<string, unknown> = {}, _callId?: string, tokens?: string[]) => {
    if (!(tool in handlers)) return { ok: false, error: `unexpected tool ${tool}` }
    const h = handlers[tool]
    try {
      const data = typeof h === 'function' ? await (h as (a: Record<string, unknown>) => unknown)(tokens ? { ...args, tokens } : args) : h
      return { ok: true, data }
    } catch (e) {
      const err = e as { message: string; candidates?: unknown; conflict?: boolean }
      return { ok: false, error: err.message, ...(err.candidates ? { candidates: err.candidates } : {}), ...(err.conflict ? { conflict: true } : {}) }
    }
  })

  // The state main holds and pushes: a test pushes a new one with `pushBoard`, `pushLogin`.
  let board: Events['run-board'] = { active: false }
  let loginState: Events['claude-login'] = { state: 'idle' }
  // What the shell reads on its own when a screen mounts. Any other action answers only what a test gives it
  // (`options.actions`, or `m.actions[name].mockResolvedValue...`); with no answer it is refused, so a new action needs no entry here.
  const defaults: Partial<Answers> = {
    info: async () => ({ environment: 'production' }),
    'current-board': async () => board,
    'check-update': async () => ({ enabled: false }),
    'claude-login-state': async () => loginState,
  }
  const answers: Partial<Answers> = { ...defaults, ...options.actions }
  // One `vi.fn` per action, made on first use.
  const made = new Map<string, Mock<(...args: never[]) => unknown>>()
  const actions = new Proxy({} as ActionMocks, {
    get(_target, name) {
      if (typeof name !== 'string') return undefined
      let mock = made.get(name)
      if (!mock) {
        mock = vi.fn((answers as Record<string, ((...a: never[]) => unknown) | undefined>)[name] ?? (async () => { throw new Error(unknownAction(name)) }))
        made.set(name, mock)
      }
      return mock
    },
  })
  const invoke = vi.fn(async (action: string, ...args: unknown[]) => (actions as unknown as Record<string, (...a: unknown[]) => unknown>)[action]!(...args))

  // One listener set per event main pushes; a test pushes with `pushBoard`, `pushOpen`, `pushLogin`, `pushUpdate`.
  const listeners = Object.fromEntries(EVENTS.map((e) => [e, new Set()])) as unknown as Listeners
  const emit = <E extends keyof Events>(event: E, payload: Events[E]) => listeners[event].forEach((cb) => cb(payload))
  const on = vi.fn((event: string, cb: (payload: never) => void) => {
    const set = (listeners as Record<string, Set<(p: never) => void> | undefined>)[event]
    if (!set) return () => undefined
    set.add(cb)
    return () => {
      set.delete(cb)
    }
  })
  const pushBoard = (b: Events['run-board']) => {
    board = b
    emit('run-board', b)
  }
  const pushOpen = (t: Events['open']) => emit('open', t)
  const pushLogin = (s: Events['claude-login']) => {
    loginState = s
    emit('claude-login', s)
  }
  const pushUpdate = (u: Events['update-state']) => emit('update-state', u)

  const beforeCloseListeners = new Set<() => Promise<void>>()
  const onBeforeClose = vi.fn((cb: () => Promise<void>) => {
    beforeCloseListeners.add(cb)
    return () => {
      beforeCloseListeners.delete(cb)
    }
  })
  const pushBeforeClose = () => Promise.all([...beforeCloseListeners].map((cb) => cb()))
  // Progress callbacks are kept by call id so a test can fire them (`emitProgress`).
  const progressCallbacks = new Map<string, (p: Progress) => void>()
  const onProgress = vi.fn((id: string, cb: (p: Progress) => void) => {
    progressCallbacks.set(id, cb)
    return () => {
      progressCallbacks.delete(id)
    }
  })
  const emitProgress = (p: Progress) => progressCallbacks.forEach((cb) => cb(p))
  // A drop reaches main as paths; the stand-in hands the files themselves to the action.
  const dropCvFiles = (files: File[]) => actions['drop-cv-files'](files as never)
  ;(window as unknown as { door: unknown }).door = { call, onProgress, invoke, on, onBeforeClose, dropCvFiles }
  return { call, onProgress, emitProgress, invoke, on, actions, listeners, pushBoard, pushOpen, pushLogin, pushUpdate, onBeforeClose, pushBeforeClose }
}

export const summary = (over: Record<string, unknown> = {}) => ({
  min_score: 0.65,
  pipeline: {},
  ledger: {},
  since_last_review: { last_reviewed_at: null, runs: 1, last_run: null, new_matches: 1, site_failures: [] },
  interviews: {},
  application: {},
  pass_rates: {},
  pass_rates_by_score: null,
  in_progress: null,
  employers: {},
  drive: {},
  ...over,
})

export const match = (over: Record<string, unknown> = {}) => ({
  id: 'jobindex.1',
  score: 0.91,
  title: 'Data Analyst',
  title_en: null,
  company: 'Acme',
  location: 'Copenhagen',
  status: 'unapplied',
  is_new: false,
  ...over,
})

export const matchesResult = (matches: unknown[], extra: Record<string, unknown> = {}) => ({ min_score: 0.65, last_reviewed_at: null, matches, ...extra })

/** Makes window.matchMedia answer `narrow` for every query (the window is narrower than the breakpoint). */
export function stubNarrow(narrow: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: narrow,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia
}
