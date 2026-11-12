import { describe, expect, it, vi } from 'vitest'
import { createWebDoor, type WebDeps } from './bridge'

type Handler = (tool: string, args: Record<string, unknown>) => unknown

/** A fake `door serve`: answers tools/call with the handler's value as MCP text content. */
function fakeServer(handler: Handler, opts: { status?: number } = {}) {
  const calls: { tool: string; args: Record<string, unknown>; auth: string | null }[] = []
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const headers = new Headers(init?.headers)
    if (url === '/session') return new Response('{}', { status: opts.status ?? 200 })
    const body = JSON.parse(String(init?.body))
    const { name, arguments: args } = body.params
    calls.push({ tool: name, args, auth: headers.get('Authorization') })
    if (opts.status) return new Response('{"error":"x"}', { status: opts.status })
    const value = handler(name, args)
    if (value instanceof Error) throw value
    return new Response(JSON.stringify({ jsonrpc: '2.0', id: body.id, result: { content: [{ type: 'text', text: JSON.stringify(value) }] } }))
  })
  return { fetch, calls }
}

function setup(handler: Handler, opts: { status?: number } = {}) {
  const server = fakeServer(handler, opts)
  const onUnpaired = vi.fn()
  const deps: WebDeps = {
    fetch: server.fetch as unknown as typeof fetch,
    token: async () => 'tok',
    onUnpaired,
    pollMs: 1,
    visible: () => true,
    whenVisible: async () => undefined,
    open: vi.fn(),
    download: vi.fn(),
  }
  return { door: createWebDoor(deps), server, onUnpaired, deps }
}

describe('createWebDoor', () => {
  it('a tool call goes to /mcp with the device token and comes back as the desktop envelope', async () => {
    const { door, server } = setup(() => ({ matches: [1] }))
    expect(await door.call('list_matches', { new_only: true })).toEqual({ ok: true, data: { matches: [1] } })
    expect(server.calls[0]).toEqual({ tool: 'list_matches', args: { new_only: true }, auth: 'Bearer tok' })
  })

  it("a tool's {error} is a failed envelope with its candidates", async () => {
    const { door } = setup(() => ({ error: 'which one?', candidates: [{ job_id: 'a' }] }))
    expect(await door.call('show', { job_id: 'x' })).toEqual({ ok: false, error: 'which one?', candidates: [{ job_id: 'a' }] })
  })

  it('401 means this phone is no longer paired', async () => {
    const { door, onUnpaired } = setup(() => ({}), { status: 401 })
    const r = await door.call('list_matches')
    expect(r.ok).toBe(false)
    expect(onUnpaired).toHaveBeenCalled()
  })

  it('an unreachable server is said in words', async () => {
    const { door } = setup(() => new TypeError('Failed to fetch'))
    expect(await door.call('list_matches')).toEqual({ ok: false, error: "Can't reach The other door. Is the computer on? If it restarted, set your phone up again on it and scan the new code." })
  })

  it('a long tool that started is followed to its result, with progress from status_summary', async () => {
    let polls = 0
    const { door } = setup((tool) => {
      if (tool === 'find_jobs') return { started: true, tool: 'find_jobs', started_at: 't' }
      if (tool === 'status_summary') return { in_progress: { message: 'collect: Nordlys', steps: [] } }
      if (tool === 'job_result') return ++polls < 3 ? { tool: 'find_jobs', running: true } : { tool: 'find_jobs', running: false, result: { top: ['x'] } }
      return {}
    })
    const progress = vi.fn()
    door.onProgress('c1', progress)
    expect(await door.call('find_jobs', {}, 'c1')).toEqual({ ok: true, data: { top: ['x'] } })
    expect(progress).toHaveBeenCalledWith(expect.objectContaining({ message: 'collect: Nordlys' }))
  })

  it('a stopped run ends as stopped, a failed one with its error', async () => {
    const stopped = setup((tool) => (tool === 'prepare' ? { started: true } : tool === 'job_result' ? { running: false, cancelled: true } : {}))
    expect(await stopped.door.call('prepare', { job_id: 'a' })).toEqual({ ok: false, error: 'Stopped.', stopped: true })
    const failed = setup((tool) => (tool === 'prepare' ? { started: true } : tool === 'job_result' ? { running: false, error: 'no claude' } : {}))
    expect(await failed.door.call('prepare', { job_id: 'a' })).toEqual({ ok: false, error: 'no claude' })
  })

  it("the run board is status_summary's in_progress; Stop is cancel_job", async () => {
    const { door, server } = setup((tool) => {
      if (tool === 'status_summary') return { in_progress: { purpose: 'find', started_at: 's', message: 'm', steps: [{ name: 'search', status: 'done' }] } }
      if (tool === 'job_result') return { running: true }
      if (tool === 'cancel_job') return { cancelling: 'find_jobs' }
      return {}
    })
    expect(await door.runBoard()).toEqual({ active: true, own: true, started_at: 's', purpose: 'find', message: 'm', steps: [{ name: 'search', status: 'done' }] })
    expect(await door.stopRun()).toEqual({ ok: true })
    expect(server.calls.some((c) => c.tool === 'cancel_job')).toBe(true)
  })

  it('no run is an inactive board', async () => {
    const { door } = setup(() => ({ in_progress: null }))
    expect(await door.runBoard()).toEqual({ active: false })
  })

  it('a tunnel with no computer behind it counts as not reaching it, and says what to do after a restart', async () => {
    for (const status of [502, 530]) {
      const door = createWebDoor({ fetch: vi.fn(async () => new Response('<html>', { status })) as never, token: async () => 't', onUnpaired: vi.fn(), visible: () => true, whenVisible: async () => undefined, open: vi.fn(), download: vi.fn() })
      const r = await door.call('list_matches')
      expect(r).toMatchObject({ ok: false })
      expect((r as { error: string }).error).toMatch(/Can't reach The other door.*scan the new code/)
    }
  })

  it('page images are same-origin /files addresses, a PDF is saved from one; links open in the browser', async () => {
    const { door, deps } = setup(() => ({}))
    expect(door.pageUrl('jobindex.1', '/home/x/jobs/output/jobindex.1/cv-1.png', 3)).toBe('/files/jobs/output/jobindex.1/cv-1.png?v=3')
    expect(door.pageUrl('jobindex.1', '/home/x/jobs/output/jobindex.1/sent/cv-1.png', 3, true)).toBe('/files/jobs/output/jobindex.1/sent/cv-1.png?v=3')
    expect(await door.saveMaterial('jobindex.1', 'cv', false, 'Jane Doe - CV.pdf')).toEqual({ ok: true })
    expect(deps.download).toHaveBeenCalledWith('/files/jobs/output/jobindex.1/cv.pdf', 'Jane Doe - CV.pdf')
    await door.saveMaterial('jobindex.1', 'cover_letter', true, 'Cover letter.pdf')
    expect(deps.download).toHaveBeenLastCalledWith('/files/jobs/output/jobindex.1/sent/cover_letter.pdf', 'Cover letter.pdf')
    await door.openExternal('https://example.com/job')
    expect(deps.open).toHaveBeenCalledWith('https://example.com/job')
  })

  it("what belongs to the computer running The other door says so; info says it's remote", async () => {
    const { door } = setup(() => ({}))
    expect(await door.info()).toEqual({ demo: false, remote: true })
    expect(await door.pickCvFiles()).toEqual({ files: [], refused: [] })
    expect(await door.exportData()).toEqual({ ok: false, error: expect.stringMatching(/computer running The other door/) })
  })

  it('a target opened before the app listens is held until it does', async () => {
    const { door } = setup(() => ({}))
    door.openTarget({ screen: 'posting', jobId: 'manual.1', inPlay: false })
    const seen: unknown[] = []
    door.onOpen((t) => seen.push(t))
    expect(seen).toEqual([{ screen: 'posting', jobId: 'manual.1', inPlay: false }])
    door.openTarget({ screen: 'matches' })
    expect(seen).toHaveLength(2)
  })

  it('while a run is followed, the board does not go blank before its result arrives', async () => {
    let finished = false
    let resultPolls = 0
    const { door } = setup((tool) => {
      if (tool === 'find_jobs') return { started: true }
      if (tool === 'status_summary') return { in_progress: finished ? null : { purpose: 'find', started_at: 's', message: 'm', steps: [{ name: 'search', status: 'done' }] } }
      if (tool === 'job_result') {
        resultPolls += 1
        if (resultPolls > 80) return { running: false, result: { top: [] } }
        return { running: true }
      }
      return {}
    })
    const boards: unknown[] = []
    const stop = door.onRunBoard((b) => boards.push(b))
    const run = door.call('find_jobs', {})
    await vi.waitFor(() => expect(boards).toContainEqual(expect.objectContaining({ active: true })))
    finished = true // the lock is gone: in_progress is null, but the result is not collected yet
    await run
    stop()
    const firstInactive = boards.findIndex((b) => (b as { active: boolean }).active === false)
    expect(firstInactive).toBe(-1)
  })

  it('opens only web links (a posting could carry anything)', async () => {
    const { door, deps } = setup(() => ({}))
    expect(await door.openExternal('javascript:alert(1)')).toEqual({ ok: false, error: 'Only web links open from The other door.' })
    expect(deps.open).not.toHaveBeenCalled()
  })
})
