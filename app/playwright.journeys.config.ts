import { defineConfig } from '@playwright/test'

// The journeys: every user action in the built app, against the real door server in a test world
// (test/world/). `npm run test:journeys` builds first.
export default defineConfig({
  testDir: 'journeys',
  globalSetup: './journeys/global-setup.ts',
  globalTeardown: './journeys/global-teardown.ts',
  testMatch: '**/*.journey.ts',
  // Each test has its own world and its own app: they can run side by side.
  workers: process.env.CI ? 2 : 4,
  fullyParallel: true,
  timeout: 120_000,
  expect: {
    timeout: 20_000,
  },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'journeys-report' }]],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
})
