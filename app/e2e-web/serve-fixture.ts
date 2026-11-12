// The server the phone app's end-to-end test talks to (#303): `door serve` on the demo's made-up data
// in a temp folder (never app/.demo, profile/ or jobs/), with the stand-in claude and an isolated user
// home from the shared fixture. The one file under app/ allowed to start The other door's CLI (guard.test.ts):
// a test needs the real server a phone talks to.
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:net'
import { join } from 'node:path'
import { seedDemo } from '../src/main/demo'
import { buildEmptyHome, repoRoot, type Home } from '../test/home-fixture'

/** A fresh storage folder for one phone window (browser.cjs's DOOR_WEB_PROFILE). */
export function phoneProfile(fixture: Home): string {
  return mkdtempSync(join(fixture.scratch, 'phone-'))
}

export interface Served {
  fixture: Home
  url: string
  code: string
  stop(): void
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const s = createServer()
    s.listen(0, '127.0.0.1', () => {
      const port = (s.address() as { port: number }).port
      s.close(() => resolve(port))
    })
    s.on('error', reject)
  })
}

const cliArgs = (...rest: string[]) => ['-m', 'door', 'serve', ...rest]
// The demo GIFs' shim (scripts/demo/shim.py): the real CLI with the job boards, scoring and tailoring
// stubbed, so Find new jobs and Prepare play out without the network or claude.
const SHIM = join(repoRoot, 'scripts', 'demo', 'shim.py')

/** The demo profile set up for the shim, as scripts/demo/record.sh does: no LinkedIn, no AI fallback, no real employers. */
function forTheShim(home: string): void {
  const path = join(home, 'profile', 'config.json')
  const config = JSON.parse(readFileSync(path, 'utf8'))
  for (const key of ['hr_manager_aliases', 'ashby_companies', 'recruitee_companies', 'career_sites', 'sites']) delete config[key]
  config.linkedin_discovery = false
  config.follow_ai_fallback = false
  writeFileSync(path, JSON.stringify(config, null, 2))
  rmSync(join(home, 'profile', 'companies.json'), { force: true })
}

export async function serveDemo(options: { stubbed?: boolean } = {}): Promise<Served> {
  const fixture = buildEmptyHome()
  seedDemo(fixture.home, repoRoot, 'fresh')
  if (options.stubbed) forTheShim(fixture.home)
  const env = { ...process.env, ...fixture.env, PYTHONPATH: `${repoRoot}/src`, ...(options.stubbed ? { DOOR_DEMO_DIR: fixture.home } : {}) }
  const argv = (...rest: string[]) => (options.stubbed ? [SHIM, 'serve', ...rest] : cliArgs(...rest))
  const pair = spawnSync(fixture.python, argv('pair', '--device', 'Test phone'), { env, encoding: 'utf8', cwd: repoRoot })
  const code = /([A-Z0-9]{4}-[A-Z0-9]{4})/.exec(pair.stdout)?.[1]
  if (!code) throw new Error(`no pairing code: ${pair.stdout}${pair.stderr}`)
  const port = await freePort()
  const child: ChildProcess = spawn(fixture.python, argv('start', '--port', String(port), '--web', `${repoRoot}/app/out/web`, '--name', 'Jane'), {
    env,
    cwd: repoRoot,
    stdio: 'ignore',
  })
  const url = `http://127.0.0.1:${port}`
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${url}/manifest.webmanifest`)).ok) break
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 200))
  }
  return { fixture, url, code, stop: () => child.kill() }
}
