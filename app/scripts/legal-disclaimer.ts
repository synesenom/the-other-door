// The legal disclaimer is one file at the repo's root, outside app/. This plugin hands its text to the
// renderer as a module, so a build, a dev server and the tests all read the same words, with no dev server
// allowed to serve anything above app/ (the checkout's profile/ and jobs/ are up there).
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Plugin } from 'vite'

const ID = 'virtual:legal-disclaimer'
const RESOLVED = `\0${ID}`
const FILE = resolve(__dirname, '../../LEGAL_DISCLAIMER.md')

export function legalDisclaimer(file = FILE): Plugin {
  return {
    name: 'legal-disclaimer',
    resolveId: (id) => (id === ID ? RESOLVED : undefined),
    load(id) {
      if (id !== RESOLVED) return undefined
      this.addWatchFile(file)
      return `export default ${JSON.stringify(readFileSync(file, 'utf8'))}`
    },
  }
}
