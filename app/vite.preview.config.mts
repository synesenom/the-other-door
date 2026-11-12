// The screen preview (`npm run dev:preview`): the renderer in a browser tab on made-up data, for working
// on one screen. A dev server only; nothing here is ever built into the app.
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import { legalDisclaimer } from './scripts/legal-disclaimer'
import react from '@vitejs/plugin-react'

export default defineConfig({
  root: resolve(__dirname, 'src/preview'),
  plugins: [react(), legalDisclaimer()],
  server: { port: 5199, fs: { allow: [resolve(__dirname)] } },
})
