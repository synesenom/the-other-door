// The phone app's build (#303, `npm run build:web`): the desktop renderer behind src/web's entry, as a
// static site in out/web that door serve serves at /. No Electron, no Node in it.
import { legalDisclaimer } from './scripts/legal-disclaimer'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { FONT_PACKAGES } from './scripts/font-licenses'

const fontLicenses = {
  name: 'font-licenses',
  apply: 'build' as const,
  generateBundle(this: { emitFile(f: { type: 'asset'; fileName: string; source: string }): void }) {
    for (const f of FONT_PACKAGES) {
      this.emitFile({ type: 'asset', fileName: `licenses/${f.family}-OFL.txt`, source: readFileSync(resolve(__dirname, 'node_modules', f.package, 'LICENSE'), 'utf8') })
    }
  },
}

export default defineConfig({
  root: resolve(__dirname, 'src/web'),
  publicDir: resolve(__dirname, 'src/web/public'),
  base: '/',
  plugins: [react(), fontLicenses, legalDisclaimer()],
  build: { outDir: resolve(__dirname, 'out/web'), emptyOutDir: true },
})
