import { defineConfig } from '@playwright/test'

// One Electron smoke test against the built app (`npm run test:e2e` builds first).
export default defineConfig({
  testDir: 'e2e',
  testMatch: '**/*.e2e.ts',
  workers: 1,
  timeout: 90_000,
  reporter: [['list']],
})
