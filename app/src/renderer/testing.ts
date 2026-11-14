// Test helper: a stand-in for the preload's window.door. A handler is a value
// (the tool's result) or a function of the arguments; throwing { message,
// candidates? } answers the way a failed tool does.
import { vi } from 'vitest'
import type { UpdateResult } from '../main/updates'

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

export function mockDoor(given: Record<string, Handler>) {
  const handlers: Record<string, Handler> = { show_profile: SAVED_PROFILE, ...given }
  const call = vi.fn(async (tool: string, args: Record<string, unknown> = {}, _callId?: string) => {
    if (!(tool in handlers)) return { ok: false, error: `unexpected tool ${tool}` }
    const h = handlers[tool]
    try {
      const data = typeof h === 'function' ? await (h as (a: Record<string, unknown>) => unknown)(args) : h
      return { ok: true, data }
    } catch (e) {
      const err = e as { message: string; candidates?: unknown; conflict?: boolean }
      return { ok: false, error: err.message, ...(err.candidates ? { candidates: err.candidates } : {}), ...(err.conflict ? { conflict: true } : {}) }
    }
  })
  const openExternal = vi.fn(async () => ({ ok: true }))
  // The CV draft surface: no files picked, and a draft answered from a `draft_cv` handler (given `{files, urls}`).
  const pickCvFiles = vi.fn(async (): Promise<{ files: { token: string; name: string; size: number }[]; refused: { name: string; reason: string }[] }> => ({ files: [], refused: [] }))
  const dropCvFiles = vi.fn(async (_files: File[]): Promise<{ files: { token: string; name: string; size: number }[]; refused: { name: string; reason: string }[] }> => ({ files: [], refused: [] }))
  const draftCv = vi.fn(async (payload: { files: string[]; urls: string[] }) => {
    if (!('draft_cv' in handlers)) return { ok: false, error: 'unexpected draft_cv' }
    const h = handlers['draft_cv']
    try {
      const data = typeof h === 'function' ? await (h as (a: Record<string, unknown>) => unknown)(payload) : h
      return { ok: true, data }
    } catch (e) {
      return { ok: false, error: (e as { message: string }).message }
    }
  })
  const clearCvSources = vi.fn(async () => undefined)
  // The CV photo: nothing picked; a test answers the dialog with mockResolvedValueOnce.
  const pickPhoto = vi.fn(async (): Promise<{ token: string; name: string } | { canceled: true } | { error: string }> => ({ canceled: true }))
  const savePhoto = vi.fn(async (_token: string): Promise<unknown> => ({ ok: true, data: { photo_path: '/p/photo.jpg' } }))
  // Progress callbacks are kept by call id so a test can fire them (`emitProgress`).
  const progressCallbacks = new Map<string, (p: { progress: number; total?: number; message: string }) => void>()
  const onProgress = vi.fn((id: string, cb: (p: { progress: number; total?: number; message: string }) => void) => {
    progressCallbacks.set(id, cb)
    return () => {
      progressCallbacks.delete(id)
    }
  })
  const emitProgress = (p: { progress: number; total?: number; message: string }) => progressCallbacks.forEach((cb) => cb(p))
  // The run board the main process pushes: a test pushes one with `pushBoard`.
  let board: unknown = { active: false }
  const boardListeners = new Set<(b: unknown) => void>()
  const onRunBoard = vi.fn((cb: (b: unknown) => void) => {
    boardListeners.add(cb)
    return () => {
      boardListeners.delete(cb)
    }
  })
  const pushBoard = (b: unknown) => {
    board = b
    boardListeners.forEach((cb) => cb(b))
  }
  // The target of a clicked notification: a test pushes one with `pushOpen`.
  const openListeners = new Set<(t: unknown) => void>()
  const onOpen = vi.fn((cb: (t: unknown) => void) => {
    openListeners.add(cb)
    return () => {
      openListeners.delete(cb)
    }
  })
  const pushOpen = (t: unknown) => openListeners.forEach((cb) => cb(t))
  const runBoard = vi.fn(async () => board)
  const stopRun = vi.fn(async () => ({ ok: true }))
  const showRun = vi.fn(async (_startedAt: string) => ({ ok: true }))
  const saveMaterial = vi.fn(async (_jobId: string, _which: string, _sent: boolean, name: string): Promise<{ ok: boolean; path?: string; canceled?: true; error?: string }> => ({ ok: true, path: `/Users/ada/Downloads/${name}` }))
  const info = vi.fn(async (): Promise<{ demo: boolean; sandbox?: 'onboard'; home?: string; remote?: boolean }> => ({ demo: false }))
  const showHome = vi.fn(async () => ({ ok: true }))
  const checkUpdate = vi.fn(async (): Promise<UpdateResult | { enabled: false }> => ({ enabled: false }))
  const installUpdate = vi.fn(async (): Promise<{ ok: boolean }> => ({ ok: true }))
  const updateListeners: Array<(state: UpdateResult | { enabled: false }) => void> = []
  const onUpdateState = vi.fn((cb: (state: UpdateResult | { enabled: false }) => void) => {
    updateListeners.push(cb)
    return () => {
      const i = updateListeners.indexOf(cb)
      if (i >= 0) updateListeners.splice(i, 1)
    }
  })
  const pushUpdate = (state: UpdateResult | { enabled: false }) => updateListeners.forEach((cb) => cb(state))
  // A data move: a test answers the dialogs with mockResolvedValueOnce.
  const exportData = vi.fn(async (): Promise<unknown> => ({ ok: false, canceled: true }))
  const pickArchive = vi.fn(async (): Promise<unknown> => ({ canceled: true }))
  const importData = vi.fn(async (_token: string): Promise<unknown> => ({ ok: false, error: 'Choose the archive again.' }))
  const reportProblem = vi.fn(async (): Promise<unknown> => ({ ok: false, canceled: true }))
  // Signing in to Claude: a test pushes the main process's states with `pushLogin`.
  let loginState: unknown = { state: 'idle' }
  const loginListeners = new Set<(s: unknown) => void>()
  const pushLogin = (s: unknown) => {
    loginState = s
    loginListeners.forEach((cb) => cb(s))
  }
  const claudeLogin = {
    start: vi.fn(async (_email?: string) => ({ ok: true })),
    sendCode: vi.fn(async (_code: string) => ({ ok: true })),
    openPage: vi.fn(async () => ({ ok: true })),
    cancel: vi.fn(async () => ({ ok: true })),
    state: vi.fn(async () => loginState),
    onState: vi.fn((cb: (s: unknown) => void) => {
      loginListeners.add(cb)
      return () => {
        loginListeners.delete(cb)
      }
    }),
  }
  ;(window as unknown as { door: unknown }).door = { call, onProgress, openExternal, pickCvFiles, dropCvFiles, draftCv, clearCvSources, pickPhoto, savePhoto, saveMaterial, info, onRunBoard, runBoard, stopRun, showRun, onOpen, claudeLogin, showHome, checkUpdate, installUpdate, onUpdateState, exportData, pickArchive, importData, reportProblem }
  return { call, onProgress, openExternal, pickCvFiles, dropCvFiles, draftCv, clearCvSources, pickPhoto, savePhoto, saveMaterial, info, emitProgress, onRunBoard, pushBoard, runBoard, stopRun, showRun, onOpen, pushOpen, openListeners, claudeLogin, pushLogin, showHome, checkUpdate, installUpdate, onUpdateState, pushUpdate, exportData, pickArchive, importData, reportProblem }
}

export const summary = (over: Record<string, unknown> = {}) => ({
  min_score: 0.65,
  pipeline: {},
  ledger: {},
  since_last_review: { last_reviewed_at: null, runs: 1, last_run: null, new_matches: 1, site_failures: [] },
  interviews: {},
  application: {},
  pass_rates: {},
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
