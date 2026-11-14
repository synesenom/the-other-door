import { defineConfig } from '@playwright/test'

// The Electron smoke tests against the built app (`npm run test:e2e` builds first): only the demo
// and onboarding-sandbox modes, which the journeys (`playwright.journeys.config.ts`) never start.
export default defineConfig({
  testDir: 'e2e',
  testMatch: '**/*.e2e.ts',
  workers: 1,
  timeout: 90_000,
  reporter: [['list']],
})
