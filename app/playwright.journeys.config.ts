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
  // CI runs every journey (#121): one that passes only on its retry is reported flaky (a warning on the PR, a
  // "flaky" in the report), not failed, so a timing hiccup does not block a PR and still shows.
  retries: process.env.CI ? 1 : 0,
  timeout: 120_000,
  expect: {
    timeout: 20_000,
  },
  // In CI each shard writes a blob report (blob-report/), merged by app.yml into the one journeys-report.
  reporter: process.env.CI
    ? [['list'], ['github'], ['blob']]
    : [['list'], ['html', { open: 'never', outputFolder: 'journeys-report' }]],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
})
