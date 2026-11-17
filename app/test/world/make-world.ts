// Builds a test world for a process outside the journeys (the skill journeys, tests/model/) and prints
// what it needs as JSON: `npx tsx test/world/make-world.ts <persona> [--empty]`. The persona's own CV, as
// they would hand it over, is in the data folder as `sources/<persona>-cv.md`, where a user copies it first
// (a tool reads no local path outside the data folder or the checkout).
import { mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { buildWorld } from './build'

const [persona = 'mette', ...flags] = process.argv.slice(2)
const world = buildWorld({ persona, empty: flags.includes('--empty') })
const sources = join(world.home, 'sources')
mkdirSync(sources, { recursive: true })
const cvFile = join(sources, `${persona}-cv.md`)
writeFileSync(cvFile, world.persona.rawSource)
process.stdout.write(
  JSON.stringify({ scratch: world.scratch, bin: join(world.scratch, 'bin'), hook: resolve(__dirname, 'hook'), jobs: Object.fromEntries(Object.keys(world.ads).map((k) => [k, { id: world.jobId(k), title: world.ads[k].title, company: world.ads[k].company }])), home: world.home, dir: world.dir, env: world.env, cvFile, persona: { name: world.persona.name, email: world.persona.email, city: world.persona.city, languages: world.persona.languages, roleTargets: world.persona.roleTargets, cv: world.persona.cv } }),
)
