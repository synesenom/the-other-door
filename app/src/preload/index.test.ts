import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EVENTS } from '../main/ipc'

// The sandboxed preload cannot import modules, so it holds its own list of pushed events: it must equal ipc.ts's.
const exposed: Record<string, any> = {}
const listeners = new Map<string, (...a: any[]) => void>()
const ipcRenderer = {
  invoke: vi.fn(async (..._a: unknown[]) => 'answer'),
  send: vi.fn(),
  on: vi.fn((channel: string, fn: (...a: any[]) => void) => void listeners.set(channel, fn)),
  removeListener: vi.fn(),
}
vi.mock('electron', () => ({
  contextBridge: { exposeInMainWorld: (_name: string, api: Record<string, unknown>) => Object.assign(exposed, api) },
  ipcRenderer,
  webUtils: { getPathForFile: (f: { path: string }) => f.path },
}))

beforeEach(async () => {
  vi.resetModules()
  for (const k of Object.keys(exposed)) delete exposed[k]
  listeners.clear()
  ipcRenderer.invoke.mockClear()
  ipcRenderer.on.mockClear()
  ipcRenderer.removeListener.mockClear()
  await import('./index')
})

describe('the preload', () => {
  it('exposes exactly call, onProgress, invoke, on, onBeforeClose and dropCvFiles', () => {
    expect(Object.keys(exposed).sort()).toEqual(['call', 'dropCvFiles', 'invoke', 'on', 'onBeforeClose', 'onProgress'])
  })

  it('invoke sends door:<action> with its arguments', async () => {
    expect(await exposed.invoke('save-material', 'a.1', 'cv', false, 'x')).toBe('answer')
    expect(ipcRenderer.invoke).toHaveBeenCalledWith('door:save-material', 'a.1', 'cv', false, 'x')
    await exposed.invoke('pick-photo')
    expect(ipcRenderer.invoke).toHaveBeenLastCalledWith('door:pick-photo')
  })

  it('on subscribes each pushed event, hands the callback the payload only, and returns the remover', () => {
    for (const event of EVENTS) {
      const cb = vi.fn()
      const off = exposed.on(event, cb)
      listeners.get(`door:${event}`)!({}, { x: 1 })
      expect(cb).toHaveBeenCalledWith({ x: 1 })
      off()
      expect(ipcRenderer.removeListener).toHaveBeenLastCalledWith(`door:${event}`, listeners.get(`door:${event}`))
    }
  })

  it('on subscribes nothing for an event that is not pushed', () => {
    const before = ipcRenderer.on.mock.calls.length
    const off = exposed.on('call', vi.fn())
    expect(ipcRenderer.on.mock.calls.length).toBe(before)
    expect(typeof off).toBe('function')
  })

  it('dropCvFiles sends the paths of the dropped files', async () => {
    await exposed.dropCvFiles([{ path: '/a.pdf' }, { path: '' }])
    expect(ipcRenderer.invoke).toHaveBeenCalledWith('door:drop-cv-files', ['/a.pdf'])
  })
})
