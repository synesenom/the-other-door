// Writes src/generated/tools.json: the server's tool list as it goes over the
// wire, sorted by name. tests/commands/test_mcp_server.py compares it with the
// live server, so a changed tool fails CI until this is run and committed.
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DoorServer, resolveSpawn } from '../src/main/door-server'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '..', '..')
const scratch = mkdtempSync(join(tmpdir(), 'door-gen-tools-'))

// An empty home: listing tools reads no data and must not touch the real
// profile, jobs or Drive state.
const spec = resolveSpawn(repoRoot, {
  DOOR_PYTHON: process.env.DOOR_PYTHON,
  DOOR_HOME: join(scratch, 'home'),
  HOME: scratch,
  XDG_CONFIG_HOME: join(scratch, 'config'),
  APPDATA: join(scratch, 'appdata'),
})
const server = new DoorServer(spec)
try {
  const tools = (await server.listTools()).sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
  writeFileSync(join(repoRoot, 'app', 'src', 'generated', 'tools.json'), JSON.stringify(tools, null, 2) + '\n')
  console.log(`wrote ${tools.length} tools`)
} finally {
  await server.close()
}
