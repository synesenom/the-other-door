import { defineConfig } from '@playwright/test'

// The phone app end to end (`npm run test:web`, builds first): its web build against a real `door serve`.
export default defineConfig({
  testDir: 'e2e-web',
  testMatch: '**/*.e2e.ts',
  workers: 1,
  timeout: 120_000,
  reporter: [['list']],
})
