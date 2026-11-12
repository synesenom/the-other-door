import { defineConfig } from '@playwright/test'

// Records the README's app GIF (`npm run record:gif`); not a test, never run by CI.
export default defineConfig({
  testDir: 'demo-record',
  testMatch: '**/*.record.ts',
  workers: 1,
  timeout: 240_000,
  reporter: [['list']],
})
