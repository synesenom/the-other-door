import { contextBridge, ipcRenderer, webUtils } from 'electron'
import { beforeCloseHandler } from './before-close'

// The renderer's whole surface: `call` (one named tool), `onProgress`, `invoke(action, ...args)` for every
// other capability of the main process, `on(event, cb)` for what main pushes, `onBeforeClose` and `dropCvFiles`.
// `invoke` goes to `door:<action>`, and main answers only the channels it registered (src/main/ipc.ts's action
// table), so `ipcRenderer` itself is never exposed. The names match ipc.ts (not imported: a sandboxed preload
// cannot load modules; the preload test compares the events). The event never reaches the page, only the payload.
// The one listener of the window closing: it answers at once when no screen has anything to write.
const writers = new Set<() => Promise<void>>()
ipcRenderer.on('door:before-close', beforeCloseHandler(writers, () => ipcRenderer.send('door:before-close-done')))

// What main pushes (ipc.ts EVENTS).
const EVENTS: readonly string[] = ['run-board', 'update-state', 'claude-login', 'open']

contextBridge.exposeInMainWorld('door', {
  // `tokens`: the files the user picked (CV files for draft_cv, enrich; the photo for save_photo, an archive for import_data, one-shot); main puts their paths into the tool's argument.
  call: (tool: string, args?: Record<string, unknown>, callId?: string, tokens?: string[]) =>
    ipcRenderer.invoke('door:call', tool, args ?? {}, callId, tokens),
  onProgress: (callId: string, cb: (p: { progress: number; total?: number; message: string }) => void) => {
    const listener = (_event: unknown, id: unknown, payload: { progress: number; total?: number; message: string }) => {
      if (id === callId) cb(payload)
    }
    ipcRenderer.on('door:progress', listener)
    return () => {
      ipcRenderer.removeListener('door:progress', listener)
    }
  },
  invoke: (action: string, ...args: unknown[]) => ipcRenderer.invoke(`door:${action}`, ...args),
  on: (event: string, cb: (payload: unknown) => void) => {
    if (!EVENTS.includes(event)) return () => undefined
    const listener = (_event: unknown, payload: unknown) => cb(payload)
    ipcRenderer.on(`door:${event}`, listener)
    return () => {
      ipcRenderer.removeListener(`door:${event}`, listener)
    }
  },
  // The window is closing: the page writes what it holds unsaved, then says so (src/main/close-flush.ts).
  onBeforeClose: (cb: () => Promise<void>) => {
    writers.add(cb)
    return () => {
      writers.delete(cb)
    }
  },
  // A drop: only Electron can turn a dropped File into a path, here, out of the page's reach.
  dropCvFiles: (files: File[]) => ipcRenderer.invoke('door:drop-cv-files', files.map((f) => webUtils.getPathForFile(f)).filter(Boolean)),
})
