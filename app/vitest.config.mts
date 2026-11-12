import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { legalDisclaimer } from './scripts/legal-disclaimer'

// Unit tests only; the real-server test is vitest.integration.config.ts.
// Renderer tests opt into jsdom with a `// @vitest-environment jsdom` docblock.
export default defineConfig({
  plugins: [react(), legalDisclaimer()],
  test: {
    globals: true,
    environment: 'node',
    setupFiles: ['test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'scripts/**/*.test.ts', 'e2e-install/**/*.test.ts'],
    exclude: ['**/*.integration.test.ts', 'node_modules/**'],
  },
})
