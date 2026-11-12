import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DoorError } from './door-server'
import { registerIpc, CHANNELS, PATH_ARGS, type Envelope } from './ipc'
import { cspHeader, isAllowedNavigation } from './security'
import tools from '../generated/tools.json'
import type { Notice } from './notices'

type Handler = (event: unknown, ...args: any[]) => Promise<any>

function setup(callImpl: (tool: string, args: unknown, opts?: any) => Promise<unknown> = async () => ({ ok: 1 }), demoRun?: (args: any, onProgress: any) => any, notifyThrows = false, info: { demo: boolean; sandbox?: 'onboard'; home?: string } = { demo: true }) {
  const cvSources = {
    pick: vi.fn(async () => ({ files: [{ token: 'tok1', name: 'cv.pdf', size: 10 }], refused: [] })),
    add: vi.fn(async (_paths: string[]) => ({ files: [{ token: 'tok2', name: 'dropped.pdf', size: 10 }], refused: [] })),
    resolve: vi.fn(async (tokens: string[]) => (tokens.every((t) => t === 'tok1') ? { ok: true as const, paths: tokens.map(() => '/Users/ada/cv.pdf') } : { ok: false as const, error: 'A chosen file is no longer available; add it again.' })),
    clear: vi.fn(),
  }

  const archiveFiles = {
    exportTarget: vi.fn(async (): Promise<{ path: string } | { canceled: true } | { error: string }> => ({ path: '/Users/ada/door-export.tar.gz' })),
    pick: vi.fn(async (): Promise<{ token: string; name: string } | { canceled: true } | { error: string }> => ({ token: 'arch1', name: 'door-export.tar.gz' })),
    take: vi.fn((t: string) => (t === 'arch1' ? '/Volumes/usb/door-export.tar.gz' : null)),
    reportTarget: vi.fn(async (): Promise<{ path: string } | { canceled: true } | { error: string }> => ({ path: '/Users/ada/door-report-2026-10-30.zip' })),
  }
  const photoFile = {
    pick: vi.fn(async (): Promise<{ token: string; name: string } | { canceled: true } | { error: string }> => ({ token: 'ph1', name: 'me.jpg' })),
    take: vi.fn((t: string) => (t === 'ph1' ? '/Users/ada/Pictures/me.jpg' : null)),
  }
  const problemLog = { write: vi.fn((_where: string, _message: string) => undefined) }
  const claudeLogin = {
    start: vi.fn(async (_email?: string) => undefined),
    sendCode: vi.fn((code: string) => code === 'good#code'),
    openPage: vi.fn(async () => true),
    cancel: vi.fn(),
    state: vi.fn(() => ({ state: 'idle' }) as const),
  }
  const handlers = new Map<string, Handler>()
  const ipcMain = { handle: (channel: string, fn: Handler) => void handlers.set(channel, fn) }
  const server = { call: vi.fn(callImpl), stop: vi.fn(async () => undefined) }
  const openExternal = vi.fn(async () => undefined)
  const home = realpathSync(mkdtempSync(join(tmpdir(), 'ipc-')))
  const dir = join(home, 'jobs', 'output', 'jobindex.123')
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'cv.pdf'), 'x')
  writeFileSync(join(dir, 'cover_letter.pdf'), 'x')
  mkdirSync(join(home, 'jobs', 'runs'), { recursive: true })
  writeFileSync(join(home, 'jobs', 'runs', '2026-10-29T08-00-00-00-00.json'), '{}')
  const saveDir = realpathSync(mkdtempSync(join(tmpdir(), 'ipc-save-')))
  const showSaveDialog = vi.fn(async (_o: Record<string, unknown>): Promise<{ canceled: boolean; filePath?: string }> => ({ canceled: false, filePath: join(saveDir, 'chosen.pdf') }))
  const showItemInFolder = vi.fn((_p: string) => undefined)
  const currentBoard = vi.fn(() => ({ active: false }) as { active: false })
  const notify = vi.fn((_n: Notice) => {
    if (notifyThrows) throw new Error('notify broke')
  })
  registerIpc(ipcMain, server, { openExternal, home, savePdf: { showSaveDialog, downloads: '/Users/ada/Downloads' }, showItemInFolder, info, currentBoard, demoRun, notify, cvSources, claudeLogin, archiveFiles, photoFile, problemLog })
  const send = vi.fn()
  const invoke = (channel: string, ...args: unknown[]) => handlers.get(channel)!({ sender: { send } }, ...args)
  return { server, openExternal, invoke, send, dir, showSaveDialog, saveDir, showItemInFolder, currentBoard, home, notify, cvSources, claudeLogin, archiveFiles, photoFile, problemLog }
}

describe('registerIpc', () => {
  it('answers the current run board, and names the push channel', async () => {
    const { invoke, currentBoard } = setup()
    expect(CHANNELS.runBoard).toBe('door:run-board')
    expect(CHANNELS.currentBoard).toBe('door:current-board')
    expect(await invoke(CHANNELS.currentBoard)).toEqual({ active: false })
    currentBoard.mockReturnValue({ active: true } as never)
    expect(await invoke(CHANNELS.currentBoard)).toEqual({ active: true })
  })

  it('tells the window whether it runs on the demo data', async () => {
    const { invoke } = setup()
    expect(await invoke('door:info')).toEqual({ demo: true })
  })

  it('forwards a call to the server and wraps the result', async () => {
    const { server, invoke } = setup(async () => ({ matches: [] }))
    const r: Envelope = await invoke(CHANNELS.call, 'list_matches', { new_only: true })
    expect(server.call).toHaveBeenCalledWith('list_matches', { new_only: true }, expect.anything())
    expect(r).toEqual({ ok: true, data: { matches: [] } })
  })

  it('serialises a sync conflict with its flag', async () => {
    const { invoke } = setup(async () => {
      const e = new DoorError('both changed')
      e.conflict = true
      throw e
    }, undefined, false, { demo: false })
    expect(await invoke(CHANNELS.call, 'sync_data', {})).toEqual({ ok: false, error: 'both changed', conflict: true })
  })

  it('serialises a DoorError with its candidates', async () => {
    const candidates = [{ job_id: 'a.1', title: 'T', company: 'C', status: 'unapplied' }]
    const { invoke } = setup(async () => {
      throw new DoorError('several jobs match', candidates)
    })
    expect(await invoke(CHANNELS.call, 'show', { job_id: 'x' })).toEqual({ ok: false, error: 'several jobs match', candidates })
  })

  it('refuses a tool that is not in the generated list, without calling the server', async () => {
    const { server, invoke } = setup()
    const r = await invoke(CHANNELS.call, 'rm_rf', {})
    expect(r.ok).toBe(false)
    expect(server.call).not.toHaveBeenCalled()
    expect((await invoke(CHANNELS.call, 42, {})).ok).toBe(false)
    expect(tools.map((t) => t.name)).toContain('list_matches')
  })

  it('treats missing or odd arguments as an empty object', async () => {
    const { server, invoke } = setup()
    await invoke(CHANNELS.call, 'status_summary')
    await invoke(CHANNELS.call, 'status_summary', 'nope')
    expect(server.call).toHaveBeenNthCalledWith(1, 'status_summary', {}, expect.anything())
    expect(server.call).toHaveBeenNthCalledWith(2, 'status_summary', {}, expect.anything())
  })

  it('gives import_posting a longer timeout, and no other tool one', async () => {
    const { server, invoke } = setup()
    await invoke(CHANNELS.call, 'import_posting', { text: 'x', title: 't', company: 'c' })
    await invoke(CHANNELS.call, 'list_matches', {})
    expect(server.call.mock.calls[0][2].timeout).toBe(180_000)
    expect(server.call.mock.calls[1][2].timeout).toBeUndefined()
  })

  it('gives draft_stories longer than its own 300 s limit on the server', async () => {
    const { server, invoke } = setup()
    await invoke(CHANNELS.call, 'draft_stories', { from_cv: true })
    expect(server.call.mock.calls[0][2].timeout).toBeGreaterThan(300_000)
  })

  it('gives the Drive calls the time a browser and an upload need', async () => {
    const { server, invoke } = setup(undefined, undefined, false, { demo: false })
    await invoke(CHANNELS.call, 'connect_drive', {})
    await invoke(CHANNELS.call, 'sync_data', {})
    expect(server.call.mock.calls[0][2].timeout).toBe(330_000)
    expect(server.call.mock.calls[1][2].timeout).toBe(120_000)
  })

  it('never lets the demo or the onboarding sandbox reach Drive', async () => {
    for (const info of [{ demo: true }, { demo: true, sandbox: 'onboard' as const }]) {
      const { server, invoke } = setup(undefined, undefined, false, info)
      for (const tool of ['connect_drive', 'sync_data', 'disconnect_drive']) {
        expect(await invoke(CHANNELS.call, tool, {})).toEqual({ ok: false, error: 'Google Drive is not available on made-up data.' })
      }
      expect(server.call).not.toHaveBeenCalled()
    }
  })

  it('gives enrich and skill_gaps the time their claude call may take', async () => {
    const { server, invoke } = setup()
    await invoke(CHANNELS.call, 'enrich', { urls: ['https://ada.dev'] })
    await invoke(CHANNELS.call, 'skill_gaps', { targets: ['Analyst'] })
    expect(server.call.mock.calls[0][2].timeout).toBe(660_000)
    expect(server.call.mock.calls[1][2].timeout).toBe(960_000)
  })

  it('gives market the time of its one short claude call, and add_company the time to probe', async () => {
    const { server, invoke } = setup()
    await invoke(CHANNELS.call, 'market', { save: false })
    await invoke(CHANNELS.call, 'add_company', { inputs: ['Acme'] })
    expect(server.call.mock.calls[0][2].timeout).toBe(180_000)
    expect(server.call.mock.calls[1][2].timeout).toBe(180_000)
  })

  it('gives ask the time of its one call with the read tools', async () => {
    const { server, invoke } = setup()
    await invoke(CHANNELS.call, 'ask', { question: 'q' })
    expect(server.call.mock.calls[0][2].timeout).toBe(240_000)
  })

  it('does not let the renderer choose the timeout', async () => {
    const { server, invoke } = setup()
    await invoke(CHANNELS.call, 'import_posting', { text: 'x', timeout: 1 })
    await invoke(CHANNELS.call, 'list_matches', { timeout: 999_999 })
    expect(server.call.mock.calls[0][2].timeout).toBe(180_000)
    expect(server.call.mock.calls[1][2].timeout).toBeUndefined()
  })

  it('forwards progress to the sender under the call id, and nothing else', async () => {
    const { invoke, send } = setup(async (_t, _a, opts) => {
      opts.onProgress({ progress: 1, total: 4, message: 'reading' })
      return {}
    })
    await invoke(CHANNELS.call, 'status_summary', {}, 'call-1')
    expect(CHANNELS.progress).toBe('door:progress')
    expect(send).toHaveBeenCalledWith('door:progress', 'call-1', { progress: 1, total: 4, message: 'reading' })
  })

  it('forwards nothing for an invalid call id', async () => {
    const { invoke, send, server } = setup(async (_t, _a, opts) => {
      opts?.onProgress?.({ progress: 1, message: 'x' })
      return {}
    })
    for (const bad of [undefined, 7, '', 'x'.repeat(65), {}]) await invoke(CHANNELS.call, 'status_summary', {}, bad)
    expect(send).not.toHaveBeenCalled()
    expect(server.call).toHaveBeenCalledTimes(5)
  })

  it('truncates a long progress message to 500 characters', async () => {
    const { invoke, send } = setup(async (_t, _a, opts) => {
      opts.onProgress({ progress: 1, message: 'y'.repeat(900) })
      return {}
    })
    await invoke(CHANNELS.call, 'status_summary', {}, 'c')
    expect(send.mock.calls[0][2].message).toHaveLength(500)
  })

  it('gives the onboarding tools their long timeouts', async () => {
    const { server, invoke } = setup()
    await invoke(CHANNELS.call, 'draft_cv', { sources: ['https://example.com'] })
    await invoke(CHANNELS.call, 'keywords', { role_targets: ['x'] })
    await invoke(CHANNELS.call, 'setup', { install: ['latex'], yes: true })
    expect(server.call.mock.calls.map((c) => c[2].timeout)).toEqual([960_000, 150_000, 1_800_000])
  })

  it('gives prepare and revise their long timeouts', async () => {
    const { server, invoke } = setup()
    await invoke(CHANNELS.call, 'prepare', { job_id: 'a.1' }, 'c1')
    await invoke(CHANNELS.call, 'revise', { job_id: 'a.1', instruction: 'x' })
    expect(server.call.mock.calls[0][2].timeout).toBe(180_000)
    expect(server.call.mock.calls[1][2].timeout).toBe(420_000)
  })

  it('saves a PDF where the user chooses, offered in Downloads under its name, by job id and document', async () => {
    const { invoke, showSaveDialog, saveDir, dir } = setup()
    writeFileSync(join(dir, 'cv.pdf'), 'the cv')
    const r = await invoke(CHANNELS.saveMaterial, 'jobindex.123', 'cv', false, 'Jane Doe - CV.pdf')
    expect(showSaveDialog).toHaveBeenCalledWith(expect.objectContaining({ defaultPath: join('/Users/ada/Downloads', 'Jane Doe - CV.pdf') }))
    expect(r).toEqual({ ok: true, path: join(saveDir, 'chosen.pdf') })
    expect(readFileSync(join(saveDir, 'chosen.pdf'), 'utf8')).toBe('the cv')
  })

  it('saves the copy that was sent', async () => {
    const { invoke, saveDir, dir } = setup()
    mkdirSync(join(dir, 'sent'))
    writeFileSync(join(dir, 'sent', 'cover_letter.pdf'), 'as sent')
    await invoke(CHANNELS.saveMaterial, 'jobindex.123', 'cover_letter', true, 'Cover letter.pdf')
    expect(readFileSync(join(saveDir, 'chosen.pdf'), 'utf8')).toBe('as sent')
  })

  it('a cancelled dialog saves nothing', async () => {
    const { invoke, showSaveDialog, saveDir } = setup()
    showSaveDialog.mockResolvedValueOnce({ canceled: true })
    expect(await invoke(CHANNELS.saveMaterial, 'jobindex.123', 'cv', false, 'CV.pdf')).toEqual({ ok: false, canceled: true })
    expect(existsSync(join(saveDir, 'chosen.pdf'))).toBe(false)
  })

  it('offers only a plain file name, and refuses a bad id, document or missing file before any dialog', async () => {
    const { invoke, showSaveDialog } = setup()
    await invoke(CHANNELS.saveMaterial, 'jobindex.123', 'cv', false, '../../etc/x')
    expect(showSaveDialog).toHaveBeenLastCalledWith(expect.objectContaining({ defaultPath: join('/Users/ada/Downloads', 'x.pdf') }))
    showSaveDialog.mockClear()
    for (const [id, which, sent] of [['../x', 'cv', false], ['jobindex.123', 'cv.tex', false], ['nope.1', 'cv', false], [7, 'cv', false], ['jobindex.123', 'cv', 'yes'], ['jobindex.123', 'cv', true]]) {
      expect((await invoke(CHANNELS.saveMaterial, id, which, sent, 'CV.pdf')).ok).toBe(false)
    }
    expect(showSaveDialog).not.toHaveBeenCalled()
  })

  it('opens only http(s) links externally', async () => {
    const { openExternal, invoke } = setup()
    expect(await invoke(CHANNELS.openExternal, 'https://example.com/job')).toEqual({ ok: true })
    expect(await invoke(CHANNELS.openExternal, 'http://example.com/job')).toEqual({ ok: true })
    for (const bad of ['file:///etc/passwd', 'javascript:alert(1)', 'vscode://x', 'not a url', 7]) {
      expect((await invoke(CHANNELS.openExternal, bad)).ok).toBe(false)
    }
    expect(openExternal).toHaveBeenCalledTimes(2)
  })
})

describe('a run (find_jobs)', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('has a 15 minute idle limit the renderer cannot override', async () => {
    const { server, invoke } = setup()
    await invoke(CHANNELS.call, 'find_jobs', { timeout: 1 }, 'c1')
    expect(server.call.mock.calls[0][2].timeout).toBe(900_000)
  })

  it('stops the child when The other door heard nothing for the whole idle limit', async () => {
    const { server, invoke } = setup(async () => {
      const e = new DoorError('The other door took too long to answer')
      e.timedOut = true
      throw e
    })
    const r = await invoke(CHANNELS.call, 'find_jobs', {}, 'c1')
    expect(server.stop).toHaveBeenCalledTimes(1)
    expect(r).toEqual({ ok: false, error: 'The run stopped: The other door heard nothing for 15 minutes.' })
  })

  it('does not stop the child for a timeout of another tool', async () => {
    const { server, invoke } = setup(async () => {
      const e = new DoorError('The other door took too long to answer')
      e.timedOut = true
      throw e
    })
    const r = await invoke(CHANNELS.call, 'revise', {})
    expect(server.stop).not.toHaveBeenCalled()
    expect(r.error).toBe('The other door took too long to answer')
  })

  it('sends at most one progress message per 200 ms, the latest, and flushes when the call ends', async () => {
    vi.useFakeTimers()
    let finish!: () => void
    const { invoke, send } = setup(async (_t, _a, opts) => {
      for (let i = 1; i <= 50; i++) opts.onProgress({ progress: i, message: `m${i}` })
      await new Promise<void>((r) => (finish = r))
      opts.onProgress({ progress: 51, message: 'last' })
      return {}
    })
    const done = invoke(CHANNELS.call, 'find_jobs', {}, 'c1')
    await vi.advanceTimersByTimeAsync(10)
    expect(send).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(250)
    expect(send).toHaveBeenCalledTimes(1)
    expect(send.mock.calls[0][2]).toEqual({ progress: 50, message: 'm50' })
    finish()
    await done
    expect(send).toHaveBeenCalledTimes(2)
    expect(send.mock.calls[1][2].message).toBe('last')
  })

  it('answers a stopped call as stopped', async () => {
    const { invoke } = setup(async () => {
      const e = new DoorError('stopped')
      e.stopped = true
      throw e
    })
    expect(await invoke(CHANNELS.call, 'find_jobs', {}, 'c1')).toEqual({ ok: false, error: 'stopped', stopped: true })
  })

  it('door:stop-run stops the child of a run in progress, and does nothing without one', async () => {
    let reject!: (e: Error) => void
    const { server, invoke } = setup(async (tool) => {
      if (tool === 'find_jobs') await new Promise((_r, rej) => (reject = rej))
      return {}
    })
    expect(await invoke(CHANNELS.stopRun)).toEqual({ ok: true })
    expect(server.stop).not.toHaveBeenCalled()
    const run = invoke(CHANNELS.call, 'find_jobs', {}, 'c1')
    await Promise.resolve()
    server.stop.mockImplementation(async () => {
      const e = new DoorError('stopped')
      e.stopped = true
      reject(e)
    })
    expect(await invoke(CHANNELS.stopRun)).toEqual({ ok: true })
    expect(server.stop).toHaveBeenCalledTimes(1)
    expect(await run).toMatchObject({ ok: false, stopped: true })
    expect(await invoke(CHANNELS.stopRun)).toEqual({ ok: true })
    expect(server.stop).toHaveBeenCalledTimes(1)
  })
})

describe('the demo\'s run', () => {
  it('never reaches the server: find_jobs goes to the simulation, with its arguments and progress', async () => {
    const record = { started_at: 'x' }
    const demoRun = vi.fn((_args: unknown, onProgress: (p: unknown) => void) => {
      onProgress({ progress: 1, message: 'search: started' })
      return { result: Promise.resolve(record), stop: vi.fn() }
    })
    const { server, invoke, send } = setup(async () => ({}), demoRun)
    const r = await invoke(CHANNELS.call, 'find_jobs', { skip: ['discover'] }, 'c1')
    expect(r).toEqual({ ok: true, data: record })
    expect(demoRun.mock.calls[0][0]).toEqual({ skip: ['discover'] })
    expect(server.call).not.toHaveBeenCalled()
    expect(send).toHaveBeenCalledWith('door:progress', 'c1', { progress: 1, message: 'search: started' })
  })

  it('other tools still go to the server', async () => {
    const { server, invoke } = setup(async () => ({ ok: 1 }), vi.fn())
    await invoke(CHANNELS.call, 'status_summary', {})
    expect(server.call).toHaveBeenCalledTimes(1)
  })

  it('door:stop-run cancels the simulation and leaves the server alone', async () => {
    let reject!: (e: Error) => void
    const stop = vi.fn(() => reject(Object.assign(new DoorError('stopped'), { stopped: true })))
    const demoRun = vi.fn(() => ({ result: new Promise((_r, rej) => (reject = rej)), stop }))
    const { server, invoke } = setup(async () => ({}), demoRun)
    const run = invoke(CHANNELS.call, 'find_jobs', {}, 'c1')
    await Promise.resolve()
    expect(await invoke(CHANNELS.stopRun)).toEqual({ ok: true })
    expect(stop).toHaveBeenCalledTimes(1)
    expect(server.stop).not.toHaveBeenCalled()
    expect(await run).toEqual({ ok: false, error: 'stopped', stopped: true })
  })
})

describe('door:show-run', () => {
  it('reveals the run record named by its started_at, when it exists', async () => {
    const { invoke, showItemInFolder, home } = setup()
    expect(await invoke(CHANNELS.showRun, '2026-10-29T08:00:00+00:00')).toEqual({ ok: true })
    expect(showItemInFolder).toHaveBeenCalledWith(join(home, 'jobs', 'runs', '2026-10-29T08-00-00-00-00.json'))
  })

  it('refuses a missing record, a path and anything that is not a string', async () => {
    const { invoke, showItemInFolder } = setup()
    for (const bad of ['2030-01-01T00:00:00+00:00', '../../etc/passwd', '', 7, null, 'x'.repeat(200)]) {
      expect((await invoke(CHANNELS.showRun, bad)).ok).toBe(false)
    }
    expect(showItemInFolder).not.toHaveBeenCalled()
  })
})

describe('security helpers', () => {
  it('allows navigation only within the app itself', () => {
    expect(isAllowedNavigation('http://localhost:5173/', 'http://localhost:5173/')).toBe(true)
    expect(isAllowedNavigation('http://localhost:5173/#/matches', 'http://localhost:5173/')).toBe(true)
    expect(isAllowedNavigation('https://evil.example/', 'http://localhost:5173/')).toBe(false)
    expect(isAllowedNavigation('file:///etc/passwd', 'http://localhost:5173/')).toBe(false)
    expect(isAllowedNavigation('file:///app/out/renderer/index.html', 'file:///app/out/renderer/index.html')).toBe(true)
    expect(isAllowedNavigation('file:///other/index.html', 'file:///app/out/renderer/index.html')).toBe(false)
  })

  it('the CSP is self-only without eval', () => {
    const csp = cspHeader()
    expect(csp).toContain("default-src 'self'")
    expect(csp).not.toContain('unsafe-eval')
    expect(csp).toContain("object-src 'none'")
  })

  it('the CSP lets the door-file scheme load images and nothing else', () => {
    const csp = cspHeader()
    expect(csp).toContain("img-src 'self' data: door-file:")
    expect(csp.split('door-file:')).toHaveLength(2)
    expect(cspHeader({ dev: true }).split('door-file:')).toHaveLength(2)
  })

  it('the dev CSP lets the dev server in, the packaged one does not', () => {
    expect(cspHeader({ dev: true })).toContain('ws://localhost')
    expect(cspHeader()).not.toContain('ws:')
  })

  it("the dev CSP runs the React refresh preamble (an inline script), the packaged one runs no inline script", () => {
    const scriptSrc = (csp: string) => csp.split('; ').find((d) => d.startsWith('script-src'))
    expect(scriptSrc(cspHeader({ dev: true }))).toContain("'unsafe-inline'")
    expect(scriptSrc(cspHeader())).toBe("script-src 'self'")
  })
})

describe('notifications', () => {
  const posting = { title: 'Data Analyst', company: 'Acme', status: 'prepared' }
  const impl = (results: Record<string, unknown>, show: unknown = posting) => async (tool: string) => {
    if (tool === 'show') {
      if (show instanceof Error) throw show
      return show
    }
    const r = results[tool]
    if (r instanceof Error) throw r
    return r
  }
  const record = { new_above_threshold: ['a.1', 'a.2'], search: null, collect: null }

  it('announces a finished search', async () => {
    const { invoke, notify } = setup(impl({ find_jobs: record }))
    expect(await invoke(CHANNELS.call, 'find_jobs', {}, 'c1')).toEqual({ ok: true, data: record })
    expect(notify).toHaveBeenCalledTimes(1)
    expect(notify.mock.calls[0][0]).toMatchObject({ title: 'New jobs found', target: { screen: 'matches', newOnly: true } })
  })

  it('announces the demo run through the same path', async () => {
    const demoRun = () => ({ result: Promise.resolve(record), stop: () => undefined })
    const { invoke, notify } = setup(async () => ({}), demoRun)
    await invoke(CHANNELS.call, 'find_jobs', {}, 'c1')
    expect(notify).toHaveBeenCalledTimes(1)
    expect(notify.mock.calls[0][0].title).toBe('New jobs found')
  })

  it('announces a prepared application with the job in words', async () => {
    const { server, invoke, notify } = setup(impl({ prepare: { outcome: 'prepared', job_id: 'jobindex.1' } }))
    await invoke(CHANNELS.call, 'prepare', { job_id: 'jobindex.1' })
    expect(server.call).toHaveBeenCalledWith('show', { job_id: 'jobindex.1' })
    expect(notify.mock.calls[0][0]).toEqual({
      title: 'Application ready',
      body: 'Data Analyst · Acme: the CV and letter are ready to send.',
      target: { screen: 'materials', jobId: 'jobindex.1', inPlay: true },
    })
  })

  it('announces a revision and an import', async () => {
    const a = setup(impl({ revise: { outcome: 'revised', job_id: 'jobindex.1', file: 'cover_letter.tex' } }, { ...posting, status: 'unapplied' }))
    await a.invoke(CHANNELS.call, 'revise', { job_id: 'jobindex.1' })
    expect(a.notify.mock.calls[0][0]).toMatchObject({ title: 'Revision done', target: { document: 'cover_letter', inPlay: false } })
    const b = setup(impl({ import_posting: { job_id: 'jobindex.9', score: 0.81 } }, { ...posting, status: 'unapplied' }))
    await b.invoke(CHANNELS.call, 'import_posting', { url: 'https://x.test/1' })
    expect(b.notify.mock.calls[0][0]).toMatchObject({ title: 'Ad imported', body: 'Data Analyst · Acme: scored 0.81' })
  })

  it('announces the failures: an idle timeout and another error', async () => {
    const timedOut = Object.assign(new DoorError('idle'), { timedOut: true })
    const a = setup(impl({ find_jobs: timedOut }))
    await a.invoke(CHANNELS.call, 'find_jobs', {}, 'c1')
    expect(a.notify.mock.calls[0][0].title).toBe('The search stopped')
    const b = setup(impl({ find_jobs: new DoorError('no network\nmore') }))
    await b.invoke(CHANNELS.call, 'find_jobs', {}, 'c1')
    expect(b.notify.mock.calls[0][0]).toMatchObject({ title: "The search didn't finish", body: 'no network' })
    const c = setup(impl({ prepare: new DoorError('LaTeX failed') }))
    await c.invoke(CHANNELS.call, 'prepare', { job_id: 'jobindex.1' })
    expect(c.notify.mock.calls[0][0]).toMatchObject({ title: "Preparing didn't finish", body: 'Data Analyst · Acme: LaTeX failed' })
  })

  it('a failing show still announces, without the job words', async () => {
    const { invoke, notify } = setup(impl({ prepare: { outcome: 'prepared', job_id: 'jobindex.1' } }, new Error('gone')))
    await invoke(CHANNELS.call, 'prepare', { job_id: 'jobindex.1' })
    expect(notify.mock.calls[0][0].body).toBe('The CV and letter are ready to send.')
  })

  it('never announces quick tools, a Stop or a refusal', async () => {
    for (const tool of ['show', 'list_matches', 'set_status', 'mark_reviewed']) {
      const { invoke, notify } = setup(async () => ({ job_id: 'jobindex.1', title: 'T', company: 'C', status: 'applied' }))
      await invoke(CHANNELS.call, tool, { job_id: 'jobindex.1' })
      expect(notify).not.toHaveBeenCalled()
    }
    const stopped = Object.assign(new DoorError('stopped'), { stopped: true })
    const a = setup(impl({ find_jobs: stopped }))
    await a.invoke(CHANNELS.call, 'find_jobs', {}, 'c1')
    const b = setup(impl({ find_jobs: new DoorError('A run is in progress (started 09:12)') }))
    await b.invoke(CHANNELS.call, 'find_jobs', {}, 'c1')
    const c = setup(impl({ prepare: new DoorError('another long-running tool is running') }))
    await c.invoke(CHANNELS.call, 'prepare', { job_id: 'jobindex.1' })
    expect([a.notify, b.notify, c.notify].map((n) => n.mock.calls.length)).toEqual([0, 0, 0])
  })

  it('a notify that throws leaves the envelope as it was', async () => {
    const { invoke } = setup(impl({ find_jobs: record }), undefined, true)
    expect(await invoke(CHANNELS.call, 'find_jobs', {}, 'c1')).toEqual({ ok: true, data: record })
  })
})

describe('the preload and the channels', () => {
  it('uses every channel name as written in ipc.ts (a sandboxed preload cannot import them)', () => {
    const preload = readFileSync(join(__dirname, '..', 'preload', 'index.ts'), 'utf8')
    for (const channel of Object.values(CHANNELS)) expect(preload).toContain(`'${channel}'`)
    expect(CHANNELS.open).toBe('door:open')
  })
})

describe('moving the data', () => {
  it('names the channels', () => {
    expect(CHANNELS.exportData).toBe('door:export-data')
    expect(CHANNELS.pickArchive).toBe('door:pick-archive')
    expect(CHANNELS.importData).toBe('door:import-data')
  })

  it('exports to where the save dialog said, with time for a big archive', async () => {
    const { invoke, server } = setup(async () => ({ path: '/Users/ada/door-export.tar.gz', files: 12, bytes: 3456 }))
    expect(await invoke(CHANNELS.exportData, '/etc/evil.tar.gz')).toEqual({ ok: true, data: { path: '/Users/ada/door-export.tar.gz', files: 12, bytes: 3456 } })
    expect(server.call).toHaveBeenCalledWith('export_data', { path: '/Users/ada/door-export.tar.gz' }, { timeout: 180_000 })
  })

  it('a cancelled save dialog exports nothing; a refused name says why', async () => {
    const one = setup()
    one.archiveFiles.exportTarget.mockResolvedValueOnce({ canceled: true })
    expect(await one.invoke(CHANNELS.exportData)).toEqual({ ok: false, canceled: true })
    one.archiveFiles.exportTarget.mockResolvedValueOnce({ error: 'there already' })
    expect(await one.invoke(CHANNELS.exportData)).toEqual({ ok: false, error: 'there already' })
    expect(one.server.call).not.toHaveBeenCalled()
  })

  it('the archive is picked in main and goes by token', async () => {
    const { invoke, server } = setup(async () => ({ files: 3, backup_dir: '/b', warnings: [] }))
    expect(await invoke(CHANNELS.pickArchive)).toEqual({ token: 'arch1', name: 'door-export.tar.gz' })
    expect(await invoke(CHANNELS.importData, 'arch1')).toEqual({ ok: true, data: { files: 3, backup_dir: '/b', warnings: [] } })
    expect(server.call).toHaveBeenCalledWith('import_data', { archive: '/Volumes/usb/door-export.tar.gz' }, { timeout: 180_000 })
  })

  it('an unknown token, or a path from the window, imports nothing', async () => {
    const { invoke, server } = setup()
    for (const t of ['nope', '/Users/ada/x.tar.gz', 42]) {
      expect(await invoke(CHANNELS.importData, t)).toEqual({ ok: false, error: 'Choose the archive again.' })
    }
    expect(server.call).not.toHaveBeenCalled()
  })
})

describe('the CV photo (#605)', () => {
  it('names the channels', () => {
    expect(CHANNELS.pickPhoto).toBe('door:pick-photo')
    expect(CHANNELS.savePhoto).toBe('door:save-photo')
  })

  it('the picture is picked in main and saved by token: the tool gets the real path', async () => {
    const { invoke, server } = setup(async () => ({ photo_path: '/home/profile/photo.jpg' }))
    expect(await invoke(CHANNELS.pickPhoto)).toEqual({ token: 'ph1', name: 'me.jpg' })
    expect(await invoke(CHANNELS.savePhoto, 'ph1')).toEqual({ ok: true, data: { photo_path: '/home/profile/photo.jpg' } })
    expect(server.call).toHaveBeenCalledWith('save_photo', { path: '/Users/ada/Pictures/me.jpg' })
  })

  it('a refusal by the tool reaches the window as the reason', async () => {
    const { invoke } = setup(async () => {
      throw new DoorError('the picture is too small (50 x 50 px)')
    })
    expect(await invoke(CHANNELS.savePhoto, 'ph1')).toEqual({ ok: false, error: 'the picture is too small (50 x 50 px)' })
  })

  it('an unknown token, or a path from the window, saves nothing', async () => {
    const { invoke, server } = setup()
    for (const t of ['nope', '/Users/ada/me.jpg', 42]) {
      expect(await invoke(CHANNELS.savePhoto, t)).toEqual({ ok: false, error: 'Choose the picture again.' })
    }
    expect(server.call).not.toHaveBeenCalled()
  })

  it('save_photo cannot be called with a path through door:call', async () => {
    const { invoke, server } = setup()
    expect(PATH_ARGS['save_photo']).toEqual({ arg: 'path' })
    const r = await invoke(CHANNELS.call, 'save_photo', { path: '/etc/passwd' })
    expect(r.ok).toBe(false)
    expect(server.call).not.toHaveBeenCalled()
  })

  it('removing the photo is an ordinary tool call', async () => {
    const { invoke, server } = setup(async () => ({ removed: true }))
    expect(await invoke(CHANNELS.call, 'remove_photo', {})).toEqual({ ok: true, data: { removed: true } })
    expect(server.call).toHaveBeenCalled()
  })
})

describe('reporting a problem', () => {
  it('names the channel and writes the report where the save dialog said', async () => {
    expect(CHANNELS.reportProblem).toBe('door:report-problem')
    const answer = { path: '/Users/ada/door-report-2026-10-30.zip', files: ['README.txt'], bytes: 900 }
    const { invoke, server } = setup(async () => answer)
    expect(await invoke(CHANNELS.reportProblem, '/etc/evil.zip')).toEqual({ ok: true, data: answer })
    expect(server.call).toHaveBeenCalledWith('report_problem', { path: '/Users/ada/door-report-2026-10-30.zip' }, { timeout: 120_000 })
  })

  it('a cancelled dialog writes nothing; a refused name or a failed call says why', async () => {
    const one = setup(async () => {
      throw new DoorError('disk full')
    })
    one.archiveFiles.reportTarget.mockResolvedValueOnce({ canceled: true })
    expect(await one.invoke(CHANNELS.reportProblem)).toEqual({ ok: false, canceled: true })
    one.archiveFiles.reportTarget.mockResolvedValueOnce({ error: 'there already' })
    expect(await one.invoke(CHANNELS.reportProblem)).toEqual({ ok: false, error: 'there already' })
    expect(one.server.call).not.toHaveBeenCalled()
    expect(await one.invoke(CHANNELS.reportProblem)).toEqual({ ok: false, error: 'disk full' })
  })

  it('the window may not name the report\'s file through door:call', async () => {
    expect(PATH_ARGS['report_problem']).toEqual({ arg: 'path' })
    const { invoke, server } = setup()
    expect((await invoke(CHANNELS.call, 'report_problem', { path: '/tmp/x.zip' })).ok).toBe(false)
    expect(server.call).not.toHaveBeenCalled()
  })

  it('what the window is refused goes to the problem log, its arguments do not', async () => {
    const { invoke, problemLog } = setup()
    await invoke(CHANNELS.call, 'rm_rf', { secret: 'Ada Lovelace' })
    await invoke(CHANNELS.call, 'import_posting', { path: '/Users/ada/ad.txt' })
    await invoke(CHANNELS.call, 'sync_data', {})
    expect(problemLog.write.mock.calls).toEqual([
      ['refused rm_rf', 'unknown tool'],
      ['refused import_posting', 'import_posting cannot take a file path from the window; files are chosen with a file dialog.'],
      ['refused sync_data', 'Google Drive is not available on made-up data.'],
    ])
  })
})

describe('the data folder', () => {
  it('shows the data folder itself, whatever the window sends', async () => {
    const { invoke, showItemInFolder, home } = setup()
    expect(await invoke(CHANNELS.showHome, '/etc/passwd')).toEqual({ ok: true })
    expect(showItemInFolder).toHaveBeenCalledWith(home)
  })
})

describe('the update check channel', () => {
  const found = { enabled: true, checked: true, current: '0.1.0', available: true, version: '0.1.1', url: 'https://example.com/r' } as const
  it('answers the cached result, without fetching', async () => {
    const updates = { last: vi.fn(() => found), check: vi.fn(async () => found) }
    const handlers = new Map<string, (...a: any[]) => unknown>()
    registerIpc({ handle: (c, l) => void handlers.set(c, l) }, { call: vi.fn() } as any, { openExternal: vi.fn(), home: '/h', showItemInFolder: vi.fn(), updates })
    const h = handlers.get(CHANNELS.checkUpdate)!
    expect(await h({})).toEqual(found)
    expect(await h({}, 'yes')).toEqual(found)
    expect(updates.check).not.toHaveBeenCalled()
    expect(await h({}, true)).toEqual(found)
    expect(updates.check).toHaveBeenCalledTimes(1)
  })
  it('is disabled without a checker or a cached result', async () => {
    const handlers = new Map<string, (...a: any[]) => unknown>()
    registerIpc({ handle: (c, l) => void handlers.set(c, l) }, { call: vi.fn() } as any, { openExternal: vi.fn(), home: '/h', showItemInFolder: vi.fn() })
    expect(await handlers.get(CHANNELS.checkUpdate)!({})).toEqual({ enabled: false })
    const updates = { last: vi.fn(() => null), check: vi.fn() }
    handlers.clear()
    registerIpc({ handle: (c, l) => void handlers.set(c, l) }, { call: vi.fn() } as any, { openExternal: vi.fn(), home: '/h', showItemInFolder: vi.fn(), updates: updates as any })
    expect(await handlers.get(CHANNELS.checkUpdate)!({})).toEqual({ enabled: false })
  })
})

describe('the Claude sign-in channels', () => {
  it('names the channels', () => {
    expect(CHANNELS.claudeLoginStart).toBe('door:claude-login-start')
    expect(CHANNELS.claudeLoginCode).toBe('door:claude-login-code')
    expect(CHANNELS.claudeLoginOpen).toBe('door:claude-login-open')
    expect(CHANNELS.claudeLoginCancel).toBe('door:claude-login-cancel')
    expect(CHANNELS.claudeLoginState).toBe('door:claude-login-state')
    expect(CHANNELS.claudeLogin).toBe('door:claude-login')
  })

  it('starts with the email when it is a string, and nothing else', async () => {
    const { invoke, claudeLogin } = setup()
    expect(await invoke(CHANNELS.claudeLoginStart, 'jane@example.com')).toEqual({ ok: true })
    expect(claudeLogin.start).toHaveBeenLastCalledWith('jane@example.com')
    await invoke(CHANNELS.claudeLoginStart, { email: 'x' })
    expect(claudeLogin.start).toHaveBeenLastCalledWith(undefined)
  })

  it('passes a code on and answers whether it went', async () => {
    const { invoke, claudeLogin } = setup()
    expect(await invoke(CHANNELS.claudeLoginCode, 'good#code')).toEqual({ ok: true })
    expect(await invoke(CHANNELS.claudeLoginCode, 'bad')).toEqual({ ok: false, error: 'That is not a sign-in code.' })
    expect(await invoke(CHANNELS.claudeLoginCode, 42)).toEqual({ ok: false, error: 'That is not a sign-in code.' })
    expect(claudeLogin.sendCode).toHaveBeenCalledTimes(2)
  })

  it('opens the page claude printed, takes no address from the window, cancels, and tells the state', async () => {
    const { invoke, claudeLogin, openExternal } = setup()
    expect(await invoke(CHANNELS.claudeLoginOpen, 'https://evil.example')).toEqual({ ok: true })
    expect(claudeLogin.openPage).toHaveBeenCalledWith()
    expect(openExternal).not.toHaveBeenCalled()
    expect(await invoke(CHANNELS.claudeLoginCancel)).toEqual({ ok: true })
    expect(claudeLogin.cancel).toHaveBeenCalled()
    expect(await invoke(CHANNELS.claudeLoginState)).toEqual({ state: 'idle' })
  })
})

describe('the CV draft channels', () => {
  it('names the channels', () => {
    expect(CHANNELS.pickCvFiles).toBe('door:pick-cv-files')
    expect(CHANNELS.draftCv).toBe('door:draft-cv')
    expect(CHANNELS.clearCvSources).toBe('door:cv-sources-clear')
  })

  it('answers the picker result', async () => {
    const { invoke, cvSources } = setup()
    expect(await invoke(CHANNELS.pickCvFiles)).toEqual({ files: [{ token: 'tok1', name: 'cv.pdf', size: 10 }], refused: [] })
    expect(CHANNELS.dropCvFiles).toBe('door:drop-cv-files')
    expect(await invoke(CHANNELS.dropCvFiles, ['/x/dropped.pdf'])).toEqual({ files: [{ token: 'tok2', name: 'dropped.pdf', size: 10 }], refused: [] })
    expect(await invoke(CHANNELS.dropCvFiles, 'not a list')).toEqual({ files: [], refused: [] })
    expect(cvSources.pick).toHaveBeenCalled()
  })

  it('drafts from the resolved paths and the urls, with the long limit', async () => {
    const { invoke, server } = setup(async () => ({ markdown: '# Ada' }))
    const r = await invoke(CHANNELS.draftCv, { files: ['tok1'], urls: ['https://example.com/ada'] })
    expect(r).toEqual({ ok: true, data: { markdown: '# Ada' } })
    expect(server.call).toHaveBeenCalledWith('draft_cv', { sources: ['/Users/ada/cv.pdf', 'https://example.com/ada'] }, expect.objectContaining({ timeout: 960_000 }))
  })

  it('refuses an unknown token without calling the server', async () => {
    const { invoke, server } = setup()
    const r = await invoke(CHANNELS.draftCv, { files: ['guess'], urls: [] })
    expect(r.ok).toBe(false)
    expect(server.call).not.toHaveBeenCalled()
  })

  it('refuses a LinkedIn page with the hint, and a non-http address', async () => {
    const { invoke, server } = setup()
    const li = await invoke(CHANNELS.draftCv, { files: [], urls: ['https://www.linkedin.com/in/ada'] })
    expect(li).toMatchObject({ ok: false, error: expect.stringContaining('Save to PDF') })
    const bad = await invoke(CHANNELS.draftCv, { files: [], urls: ['file:///etc/passwd'] })
    expect(bad.ok).toBe(false)
    expect(server.call).not.toHaveBeenCalled()
  })

  it.each([
    [{ files: 'tok1', urls: [] }],
    [{ files: [], urls: 'https://a.com' }],
    [{ files: [1], urls: [] }],
    [{ files: [], urls: [2] }],
    ['text'],
    [null],
    [{ files: [], urls: [] }],
  ])('refuses the payload %j', async (payload) => {
    const { invoke, server } = setup()
    expect((await invoke(CHANNELS.draftCv, payload)).ok).toBe(false)
    expect(server.call).not.toHaveBeenCalled()
  })

  it('turns a timeout into a failed envelope', async () => {
    const { invoke } = setup(async () => {
      throw Object.assign(new DoorError('draft_cv took too long'), { timedOut: true as const })
    })
    const r = await invoke(CHANNELS.draftCv, { files: ['tok1'], urls: [] })
    expect(r).toEqual({ ok: false, error: expect.stringContaining('too long') })
  })

  it('clears the registry', async () => {
    const { invoke, cvSources } = setup()
    await invoke(CHANNELS.clearCvSources)
    expect(cvSources.clear).toHaveBeenCalled()
  })
})

describe('door:call refuses what names a local file', () => {
  it.each([
    ['draft_cv', { sources: ['/etc/passwd'] }],
    ['draft_cv', { sources: ['C:\\x.pdf'] }],
    ['draft_cv', { sources: ['file:///x'] }],
    ['draft_cv', { sources: ['https://a.com', '/etc/passwd'] }],
    ['draft_cv', { sources: '/etc/passwd' }],
    ['import_posting', { path: '/etc/passwd' }],
    ['export_data', { path: '/tmp/x.tar.gz' }],
    ['import_data', { archive: '/tmp/x.tar.gz' }],
    ['enrich', { urls: ['/Users/ada/notes.md'] }],
    ['enrich', { urls: ['https://ada.dev', 'file:///etc/passwd'] }],
  ])('%s %j', async (tool, args) => {
    const { invoke, server } = setup()
    const r = await invoke(CHANNELS.call, tool, args)
    expect(r.ok).toBe(false)
    expect(server.call).not.toHaveBeenCalled()
  })

  it.each([
    ['draft_cv', { sources: ['https://a.com'] }],
    ['draft_cv', {}],
    ['import_posting', { url: 'https://a.com/job' }],
    ['import_posting', { text: 'an ad' }],
    ['export_data', {}],
    ['enrich', { urls: ['https://ada.dev'] }],
    ['enrich', { apply: [1, 2] }],
  ])('lets %s %j through', async (tool, args) => {
    const { invoke, server } = setup()
    const r = await invoke(CHANNELS.call, tool, args)
    expect(r.ok).toBe(true)
    expect(server.call).toHaveBeenCalled()
  })

  it('knows every tool parameter that could name a file', () => {
    // A file is chosen in a main-side dialog and sent by token (cv-sources.ts; export and import in #222).
    // A tool that gains such a parameter must be in PATH_ARGS or here, with the reason.
    const allowed = new Set(['revise.file']) // an enum: cv or cover_letter
    const risky = /path|file|dir|archive|source/i
    const found: string[] = []
    for (const t of tools as { name: string; inputSchema?: { properties?: Record<string, unknown> }; input_schema?: { properties?: Record<string, unknown> }; parameters?: { properties?: Record<string, unknown> } }[]) {
      const props = (t.inputSchema ?? t.input_schema ?? t.parameters)?.properties ?? {}
      for (const name of Object.keys(props)) if (risky.test(name)) found.push(`${t.name}.${name}`)
    }
    expect(found.length).toBeGreaterThan(0)
    for (const f of found) {
      const [tool, arg] = f.split('.') as [string, string]
      expect(PATH_ARGS[tool]?.arg === arg || allowed.has(f), `${f} is neither in PATH_ARGS nor allowed`).toBe(true)
    }
  })
})
