// The screen preview's entry (`npm run dev:preview`): the real App, with the desktop renderer's fonts and
// styles, on a made-up window.door. A development tool, in no build of the app.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from '../renderer/App'
import { applyTheme, readTheme, type Theme } from '../renderer/theme'
import { createMockDoor } from './mock-door'
import { Guide } from './Guide'
import { Picker } from './Picker'
import { readSelection } from './scenes'
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

const query = new URLSearchParams(location.search)
// `?theme=` for this tab only, so light and dark can stand side by side.
const asked = query.get('theme')
applyTheme(asked === 'light' || asked === 'dark' ? (asked as Theme) : readTheme())

const selection = readSelection(query)
if (selection) window.door = createMockDoor(selection.scene, selection.state)

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>{!selection ? <Picker /> : selection.scene.guide ? <Guide /> : <App start={selection.scene.start} />}</StrictMode>,
)
