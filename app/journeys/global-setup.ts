import { ensureElectron } from './electron-binary'
import { startRun } from './teardown'

/** Fetches Electron's binary before the workers start (they would otherwise race to download it, #126), then the run. */
export function makeGlobalSetup(fetch: () => string = () => ensureElectron(), start: () => void = startRun): () => void {
  return () => {
    fetch()
    start()
  }
}

export default makeGlobalSetup()
