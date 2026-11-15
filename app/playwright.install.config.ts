import { defineConfig } from '@playwright/test'

// The install test (#639): install the installer a user downloads (`npm run package` builds it into dist/,
// or DOOR_INSTALLER names one), then set-up, first run and Prepare in the installed app, then uninstall.
// Run locally on each system (app/README.md, "The install test"); `npm run test:install`.
export default defineConfig({
  testDir: 'e2e-install',
  testMatch: '**/*.e2e.ts',
  globalSetup: './e2e-install/setup.ts',
  globalTeardown: './e2e-install/teardown.ts',
  workers: 1,
  // the first Prepare downloads Tectonic's LaTeX packages: minutes on a slow line
  timeout: 15 * 60_000,
  expect: { timeout: 30_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'install-report/html' }]],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
})
