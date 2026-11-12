// A phone-sized Chromium for the phone app's end-to-end test (#303): Electron's own, so no browser is
// downloaded. It opens DOOR_WEB_URL in a 412 x 915 window with a Pixel's user agent and nothing else:
// no preload, no Node in the page; the page is the web build served by `door serve`.
const { app, BrowserWindow } = require('electron')

// Its own storage per test (IndexedDB, the service worker, the theme), never the shared Electron folder.
if (process.env.DOOR_WEB_PROFILE) app.setPath('userData', process.env.DOOR_WEB_PROFILE)

app.whenReady().then(() => {
  const win = new BrowserWindow({ width: 412, height: 915, webPreferences: { contextIsolation: true, sandbox: true } })
  win.webContents.setUserAgent(
    'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36',
  )
  void win.loadURL(process.env.DOOR_WEB_URL || 'about:blank')
})
app.on('window-all-closed', () => app.quit())
