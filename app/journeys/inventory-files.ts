// The real inventories, journey titles and test files for the check in `inventory.ts` (#122).
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'
import { journeyTests, type JourneyTest } from './inventory'

const APP = resolve(__dirname, '..')
const REPO = resolve(APP, '..')

/** Every file under `dir`, skipping dependencies and build output. */
function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (['node_modules', 'out', 'dist', '.venv', '__pycache__', 'fixtures'].includes(entry.name) || entry.name.startsWith('.')) continue
    const path = join(dir, entry.name)
    if (entry.isDirectory()) walk(path, out)
    else out.push(path)
  }
  return out
}

export function realInventory(): { files: { name: string; text: string }[]; tests: JourneyTest[]; exists: (path: string) => boolean } {
  const inventory = join(APP, 'journeys', 'inventory')
  const files = readdirSync(inventory)
    .filter((f) => f.endsWith('.md'))
    .map((name) => ({ name, text: readFileSync(join(inventory, name), 'utf8') }))
  const journeys = join(APP, 'journeys')
  const tests = readdirSync(journeys)
    .filter((f) => f.endsWith('.journey.ts'))
    .flatMap((f) => journeyTests(readFileSync(join(journeys, f), 'utf8')))
  // a bare file name is any test file of that name in the app or the Python suite; a path is from the repo or the app
  const names = new Set([...walk(APP), ...walk(join(REPO, 'tests'))].map((p) => basename(p)))
  const exists = (path: string): boolean =>
    path.includes('/') ? existsSync(join(REPO, path)) || existsSync(join(APP, path)) : names.has(path)
  return { files, tests, exists }
}
