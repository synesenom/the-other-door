import { existsSync } from 'node:fs'
import { realpath, stat } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { app, BrowserWindow, dialog, ipcMain, nativeTheme, net, Notification, protocol, session, shell } from 'electron'
import { createArchiveFiles } from './archive-files'
import { createClaudeLogin } from './claude-login'
import { createCvSources } from './cv-sources'
import { demoDir, demoDiscoveryOff, demoEnv, demoModeFor, demoRunMs, onboardDir, onboardEnv, onboardModeFor, resetOnboard, seedDemo } from './demo'
import { startDemoRun } from './demo-run'
import { doorHome } from './files'
import { watchForeignEnd } from './foreign-run'
import { APP_ID, DoorServer, resolvePackagedSpawn, resolveSpawn } from './door-server'
import { CHANNELS, registerIpc, type Progress } from './ipc'
import { createNotifier } from './notifier'
import { createProblemLog } from './problem-log'
import { MATERIAL_SCHEME, resolveMaterialRequest, resolvePhotoRequest } from './protocol'
import { createPhotoFile } from './photo-file'
import { watchRunBoard, type RunBoard } from './run-board'
import { cspHeader, isAllowedNavigation } from './security'
import { createUpdateChecker } from './updates'
import { windowBackground } from './window-look'

// From a checkout the repo is one level above app/; a packaged app carries Python, The other door's src/ and
// Tectonic in its resources (#223) and keeps the data in the user's data folder.
const packaged = app.isPackaged
const repoRoot = packaged ? process.resourcesPath : resolve(app.getAppPath(), '..')
// `npm run dev:demo`: made-up data in app/.demo/, never your real profile/, jobs/ or Drive.
// DOOR_DEMO_DIR (an unpackaged app only) starts the demo in that folder: how the tests run it.
// `npm run dev:onboard` (or DOOR_ONBOARD_DIR, unpackaged): an empty folder app/.onboard/, made again on
// every start, to try the first launch; the run there is simulated like the demo's.
const onboard = onboardModeFor(import.meta.env.MODE, process.env, app.isPackaged)
const demo = onboard ? null : demoModeFor(import.meta.env.MODE, process.env, app.isPackaged)
const demoFolder = onboard ? onboardDir(process.env, repoRoot) : demoDir(process.env, repoRoot)
if (onboard) resetOnboard(demoFolder, repoRoot)
else if (demo) seedDemo(demoFolder, repoRoot, demo, new Date(), { discoveryOff: demoDiscoveryOff(process.env) })
const simulated = Boolean(demo || onboard)
const env = onboard ? onboardEnv(process.env, demoFolder) : demo ? demoEnv(process.env, demoFolder) : process.env
// The data folder: DOOR_HOME, else the checkout (from a checkout) or the user's data folder (packaged).
const home = doorHome(env, packaged ? app.getPath('userData') : repoRoot)
// What went wrong that the screens do not say (#593): the server's own failures it logs itself; these are the app's.
const problemLog = createProblemLog(home)
const server = new DoorServer(
  packaged ? resolvePackagedSpawn({ resourcesPath: process.resourcesPath, home, platform: process.platform, env }) : resolveSpawn(repoRoot, env),
  // A packaged app and the door inside it are one version (#224); from a checkout a test keeps them so.
  { ...(packaged ? { expectedVersion: app.getVersion() } : {}), onProblem: (where, message) => problemLog.write(where, message) },
)
// Is a newer version out (#501): only an installed app, never the demo, and only when the build names a feed.
const updates = createUpdateChecker({
  feed: packaged && !simulated && typeof __UPDATE_FEED__ === 'string' ? __UPDATE_FEED__ : '',
  current: app.getVersion(),
  fetch: (url, init) => net.fetch(url, init),
  log: (message) => problemLog.write('update-check', message),
})
const devUrl = process.env['ELECTRON_RENDERER_URL']

// Before ready, or Electron ignores it. Not `standard`, and the page's CSP still applies.
protocol.registerSchemesAsPrivileged([{ scheme: MATERIAL_SCHEME, privileges: { secure: true, supportFetchAPI: true } }])

// Windows shows no notification without an app id; the packaged app's bundle id is the same
// (in development macOS shows the sender as "Electron").
app.setAppUserModelId(APP_ID)

// System notifications for a finished long job (notices.ts says what, notifier.ts when): only
// while no window is in front; a click brings one forward and tells it where to go.
function focusWindow(): BrowserWindow {
  let win = BrowserWindow.getAllWindows()[0]
  if (!win) {
    createWindow()
    win = BrowserWindow.getAllWindows()[0]
  }
  if (win.isMinimized()) win.restore()
  win.show()
  win.focus()
  return win
}
const notify = createNotifier({
  Notification,
  isFocused: () => BrowserWindow.getAllWindows().some((w) => w.isFocused()),
  focusWindow: () => void focusWindow(),
  send: (channel, target) => {
    const win = BrowserWindow.getAllWindows()[0] ?? focusWindow()
    if (win.webContents.isLoading()) win.webContents.once('did-finish-load', () => win.webContents.send(channel, target))
    else win.webContents.send(channel, target)
  },
})
// A run somebody else started (a terminal, Claude Code) ends: say so once.
const foreignEnd = watchForeignEnd(server, notify)

// The run that holds the ledger lock, whoever started it, pushed to every window.
let lastBoard: RunBoard = { active: false }
const board = watchRunBoard(home, (b) => pushBoard(b), { ownPid: () => server.pid })
function pushBoard(b: RunBoard): void {
  lastBoard = b
  void foreignEnd(b)
  for (const win of BrowserWindow.getAllWindows()) win.webContents.send(CHANNELS.runBoard, b)
}

// Signing in to Claude from the app: claude's own login, in the folder doctor says The other door's claude calls use.
const claudeLogin = createClaudeLogin({
  env,
  doctor: () => server.call('doctor', {}),
  openExternal: (url) => shell.openExternal(url),
  onState: (state) => {
    for (const win of BrowserWindow.getAllWindows()) win.webContents.send(CHANNELS.claudeLogin, state)
  },
})

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 720,
    minHeight: 480,
    title: 'The other door',
    // Shown once the page has painted its splash, on the ground colour meanwhile: never a white window.
    show: false,
    backgroundColor: windowBackground(nativeTheme.shouldUseDarkColors),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  })
  const appUrl = devUrl ?? `file://${join(__dirname, '../renderer/index.html')}`
  win.webContents.on('will-navigate', (event, url) => {
    if (!isAllowedNavigation(url, appUrl)) event.preventDefault()
  })
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  win.once('ready-to-show', () => win.show())
  if (devUrl) void win.loadURL(devUrl)
  else void win.loadFile(join(__dirname, '../renderer/index.html'))
}

app.whenReady().then(() => {
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [cspHeader({ dev: Boolean(devUrl) })],
      },
    })
  })
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false))
  protocol.handle(MATERIAL_SCHEME, async (request) => {
    const path = resolveMaterialRequest(request.url, home) ?? resolvePhotoRequest(request.url, home)
    if (!path) return new Response('not found', { status: 404 })
    const response = await net.fetch(pathToFileURL(path).toString())
    const headers = new Headers(response.headers)
    headers.set('Cache-Control', 'no-store')
    return new Response(response.body, { status: response.status, headers })
  })
  registerIpc(ipcMain, server, {
    // `home` is for reading only: the window shows where the data is and never sends a path back.
    info: { ...(onboard ? { demo: true, sandbox: 'onboard' as const } : { demo: Boolean(demo) }), home },
    openExternal: (url) => shell.openExternal(url),
    home,
    savePdf: {
      showSaveDialog: (options) => {
        const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
        return win ? dialog.showSaveDialog(win, options as Electron.SaveDialogOptions) : dialog.showSaveDialog(options as Electron.SaveDialogOptions)
      },
      downloads: app.getPath('downloads'),
    },
    showItemInFolder: (path) => shell.showItemInFolder(path),
    currentBoard: () => lastBoard,
    notify,
    claudeLogin,
    problemLog,
    updates,
    // A data move's files, chosen in dialogs in front of the window.
    archiveFiles: createArchiveFiles({
      showSaveDialog: (options) => {
        const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
        return win ? dialog.showSaveDialog(win, options as Electron.SaveDialogOptions) : dialog.showSaveDialog(options as Electron.SaveDialogOptions)
      },
      showOpenDialog: (options) => {
        const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
        return win ? dialog.showOpenDialog(win, options as Electron.OpenDialogOptions) : dialog.showOpenDialog(options as Electron.OpenDialogOptions)
      },
      exists: existsSync,
      realpath,
    }),
    // The CV files of the onboarding wizard: chosen here, in front of the window, sent as tokens.
    cvSources: createCvSources({
      showOpenDialog: (options) => {
        const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
        return win ? dialog.showOpenDialog(win, options as Electron.OpenDialogOptions) : dialog.showOpenDialog(options as Electron.OpenDialogOptions)
      },
      stat,
      realpath,
    }),
    // The CV photo of the Profile screen and the wizard: chosen here, saved by token.
    photoFile: createPhotoFile({
      showOpenDialog: (options) => {
        const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
        return win ? dialog.showOpenDialog(win, options as Electron.OpenDialogOptions) : dialog.showOpenDialog(options as Electron.OpenDialogOptions)
      },
      stat,
      realpath,
    }),
    // In the demo and the onboarding sandbox "Find new jobs" is a simulation: nothing reaches the network or claude.
    ...(simulated
      ? { demoRun: (args: Record<string, unknown>, onProgress: (p: Progress) => void) => startDemoRun(demoFolder, { args, onProgress, onBoard: pushBoard, totalMs: demoRunMs(process.env) }) }
      : {}),
  })
  createWindow()
  void updates.check() // never waits, never throws
  // Start the server now so the first screen does not wait for Python.
  void server.listTools().catch(() => undefined)
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  board.stop()
  claudeLogin.cancel()
  void server.close()
})
