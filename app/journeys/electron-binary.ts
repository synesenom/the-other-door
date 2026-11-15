// Electron (43) has no postinstall: its binary is downloaded and unpacked on the first require('electron'), with no
// lock between processes. Two workers launching their first app at once both found it missing, both unpacked it, and
// one spawned the binary while the other was still writing it: `spawn ETXTBSY` on Linux, the first test of a CI shard
// (#126). The journeys' global setup fetches it here, once, before any worker starts.
import { existsSync } from 'node:fs'

const loadElectron = (): string => require('electron') as string

/** The Electron binary's path, fetched now if it is not there yet; throws when it is still missing after. */
export function electronBinary(load: () => string = loadElectron): string {
  const binary = load()
  if (!existsSync(binary)) throw new Error(`Electron's binary is missing after its download: ${binary}`)
  return binary
}
