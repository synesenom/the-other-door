// The phone app's entry (#303): the desktop renderer's fonts, theme and styles, then the pair screen or
// the app (Web.tsx), and the service worker that keeps the app's own code for offline starts.
import { StrictMode } from 'react'
import { keepSplashTime } from '../renderer/Splash'
import { createRoot } from 'react-dom/client'
import { applyTheme, readTheme } from '../renderer/theme'
import { Web } from './Web'
import { indexedDbStore } from './token-store'
import '@fontsource/figtree/latin-400.css'
import '@fontsource/figtree/latin-ext-400.css'
import '@fontsource/figtree/latin-500.css'
import '@fontsource/figtree/latin-ext-500.css'
import '@fontsource/figtree/latin-600.css'
import '@fontsource/figtree/latin-ext-600.css'
import '@fontsource/young-serif/latin-400.css'
import '@fontsource/young-serif/latin-ext-400.css'
import '../renderer/theme.css'
import '../renderer/styles.css'
import './web.css'

applyTheme(readTheme())
// index.html's splash bar is replaced by React's: the new one carries on where this one is.
keepSplashTime()

if ('serviceWorker' in navigator) void navigator.serviceWorker.register('/sw.js').catch(() => undefined)

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <Web store={indexedDbStore()} fetch={(input, init) => fetch(input, init)} />
  </StrictMode>,
)
