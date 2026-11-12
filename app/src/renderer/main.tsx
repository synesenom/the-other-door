import { StrictMode } from 'react'
import { keepSplashTime } from './Splash'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { applyTheme, readTheme } from './theme'
import '@fontsource/figtree/latin-400.css'
import '@fontsource/figtree/latin-ext-400.css'
import '@fontsource/figtree/latin-500.css'
import '@fontsource/figtree/latin-ext-500.css'
import '@fontsource/figtree/latin-600.css'
import '@fontsource/figtree/latin-ext-600.css'
import '@fontsource/young-serif/latin-400.css'
import '@fontsource/young-serif/latin-ext-400.css'
import './theme.css'
import './styles.css'

// The chosen theme before the first paint, so a dark choice never flashes light.
applyTheme(readTheme())
// index.html's splash bar is replaced by React's: the new one carries on where this one is.
keepSplashTime()

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
