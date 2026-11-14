import { contextBridge, ipcRenderer, webUtils } from 'electron'

// The renderer's whole surface: one call, a progress subscription, the run board, Stop and the
// run record (by its start time), a link
// opener and two openers for a prepared job's PDFs (by job id, never a path). The channel names match src/main/ipc.ts (not imported: a sandboxed
// preload cannot load modules). The event never reaches the page, only the payload.
contextBridge.exposeInMainWorld('door', {
  call: (tool: string, args?: Record<string, unknown>, callId?: string) =>
    ipcRenderer.invoke('door:call', tool, args ?? {}, callId),
  onProgress: (callId: string, cb: (p: { progress: number; total?: number; message: string }) => void) => {
    const listener = (_event: unknown, id: unknown, payload: { progress: number; total?: number; message: string }) => {
      if (id === callId) cb(payload)
    }
    ipcRenderer.on('door:progress', listener)
    return () => {
      ipcRenderer.removeListener('door:progress', listener)
    }
  },
  openExternal: (url: string) => ipcRenderer.invoke('door:open-external', url),
  saveMaterial: (jobId: string, which: string, sent: boolean, name: string) => ipcRenderer.invoke('door:save-material', jobId, which, sent, name),
  // The CV draft: files are chosen in a dialog the main process runs and come back as tokens; the page never names a path.
  pickCvFiles: () => ipcRenderer.invoke('door:pick-cv-files'),
  // A drop: only Electron can turn a dropped File into a path, here, out of the page's reach.
  dropCvFiles: (files: File[]) => ipcRenderer.invoke('door:drop-cv-files', files.map((f) => webUtils.getPathForFile(f)).filter(Boolean)),
  draftCv: (payload: { files: string[]; urls: string[] }) => ipcRenderer.invoke('door:draft-cv', payload),
  clearCvSources: () => ipcRenderer.invoke('door:cv-sources-clear'),
  // The CV photo: chosen in a dialog the main process runs, saved by the token it hands back.
  pickPhoto: () => ipcRenderer.invoke('door:pick-photo'),
  savePhoto: (token: string) => ipcRenderer.invoke('door:save-photo', token),
  // Signing in to Claude: the main process runs claude and opens only the page claude printed.
  claudeLogin: {
    start: (email?: string) => ipcRenderer.invoke('door:claude-login-start', email),
    sendCode: (code: string) => ipcRenderer.invoke('door:claude-login-code', code),
    openPage: () => ipcRenderer.invoke('door:claude-login-open'),
    cancel: () => ipcRenderer.invoke('door:claude-login-cancel'),
    state: () => ipcRenderer.invoke('door:claude-login-state'),
    onState: (cb: (state: unknown) => void) => {
      const listener = (_event: unknown, state: unknown) => cb(state)
      ipcRenderer.on('door:claude-login', listener)
      return () => {
        ipcRenderer.removeListener('door:claude-login', listener)
      }
    },
  },
  info: () => ipcRenderer.invoke('door:info'),
  showHome: () => ipcRenderer.invoke('door:show-home'),
  checkUpdate: (fresh?: boolean) => ipcRenderer.invoke('door:check-update', fresh === true),
  installUpdate: () => ipcRenderer.invoke('door:install-update'),
  // The update's state as it changes (a download finishing).
  onUpdateState: (cb: (state: unknown) => void) => {
    const listener = (_event: unknown, state: unknown) => cb(state)
    ipcRenderer.on('door:update-state', listener)
    return () => {
      ipcRenderer.removeListener('door:update-state', listener)
    }
  },
  // Moving the data: the files are chosen in dialogs the main process runs.
  exportData: () => ipcRenderer.invoke('door:export-data'),
  pickArchive: () => ipcRenderer.invoke('door:pick-archive'),
  importData: (token: string) => ipcRenderer.invoke('door:import-data', token),
  // Save logs…: the report is written where a save dialog the main process runs says.
  reportProblem: () => ipcRenderer.invoke('door:report-problem'),
  stopRun: () => ipcRenderer.invoke('door:stop-run'),
  showRun: (startedAt: string) => ipcRenderer.invoke('door:show-run', startedAt),
  runBoard: () => ipcRenderer.invoke('door:current-board'),
  // A clicked notification: where the window should go (src/main/notices.ts has the shapes).
  onOpen: (cb: (target: unknown) => void) => {
    const listener = (_event: unknown, target: unknown) => cb(target)
    ipcRenderer.on('door:open', listener)
    return () => {
      ipcRenderer.removeListener('door:open', listener)
    }
  },
  onRunBoard: (cb: (board: unknown) => void) => {
    const listener = (_event: unknown, board: unknown) => cb(board)
    ipcRenderer.on('door:run-board', listener)
    return () => {
      ipcRenderer.removeListener('door:run-board', listener)
    }
  },
})
