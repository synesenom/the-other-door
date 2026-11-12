import { legalDisclaimer } from './scripts/legal-disclaimer'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'
import { cspHeader } from './src/main/security'
import { FONT_PACKAGES } from './scripts/font-licenses'

// The packaged page carries its policy in a <meta> too (the dev server's page
// gets the header only: Vite's dev client needs inline scripts).
const cspMeta = {
  name: 'csp-meta',
  apply: 'build' as const,
  transformIndexHtml: () => [
    { tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: cspHeader().replace(/; frame-ancestors[^;]*/, '') }, injectTo: 'head-prepend' as const },
  ],
}

// Ship each bundled font's licence next to the page (SIL OFL asks for it).
const fontLicenses = {
  name: 'font-licenses',
  apply: 'build' as const,
  generateBundle(this: { emitFile(f: { type: 'asset'; fileName: string; source: string }): void }) {
    for (const f of FONT_PACKAGES) {
      this.emitFile({
        type: 'asset',
        fileName: `licenses/${f.family}-OFL.txt`,
        source: readFileSync(resolve(__dirname, 'node_modules', f.package, 'LICENSE'), 'utf8'),
      })
    }
  },
}

export default defineConfig({
  // The update feed (#501): set at build time; empty means the app never checks.
  main: { define: { __UPDATE_FEED__: JSON.stringify(process.env['DOOR_UPDATE_FEED'] ?? '') }, build: { rollupOptions: { input: { index: resolve(__dirname, 'src/main/index.ts') } } } },
  preload: { build: { rollupOptions: { input: { index: resolve(__dirname, 'src/preload/index.ts') } } } },
  renderer: {
    root: resolve(__dirname, 'src/renderer'),
    build: { rollupOptions: { input: { index: resolve(__dirname, 'src/renderer/index.html') } } },
    plugins: [react(), cspMeta, fontLicenses, legalDisclaimer()],
  },
})
