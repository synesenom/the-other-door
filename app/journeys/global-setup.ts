import { electronBinary } from './electron-binary'
import { startRun } from './teardown'

export default function globalSetup(): void {
  // before the workers start: they would otherwise race to download Electron's binary (#126)
  electronBinary()
  startRun()
}
