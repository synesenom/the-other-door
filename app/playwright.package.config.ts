import { defineConfig } from '@playwright/test'

// The packaged app's smoke test (#223): `npm run package:dir` (or an installed app), then `npm run test:package`.
// DOOR_PACKAGED_APP names the executable; else the one `package:dir` left in dist/.
export default defineConfig({
  testDir: 'e2e-package',
  testMatch: '**/*.e2e.ts',
  workers: 1,
  timeout: 180_000,
  reporter: [['list']],
})
