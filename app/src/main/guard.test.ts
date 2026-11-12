// Nothing under app/ may run the door CLI, call a model, or spawn processes
// outside the module that starts the MCP server (#219) and the one that runs
// `claude auth login` (#221), and that one runs nothing else. The patterns are
// built from fragments so this file does not match itself.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const APP = join(__dirname, '..', '..')
const SERVER = join('src', 'main', 'door-server.ts')
const LOGIN = join('src', 'main', 'claude-login.ts')
// The packaging hook runs at build time, never in the app: it signs the packed app ad hoc (#223).
const AFTER_PACK = join('scripts', 'after-pack.cjs')
// The phone app's end-to-end test starts the real `door serve` a phone talks to (#303): a test, not the app.
const SERVE_FIXTURE = join('e2e-web', 'serve-fixture.ts')
// The journeys' world compiles its prepared materials with door's own compile while it builds a test home: a test, not the app.
const JOURNEYS_WORLD = join('test', 'world', 'build.ts')
const SPAWN_ALLOWED = [SERVER, LOGIN, AFTER_PACK, SERVE_FIXTURE, JOURNEYS_WORLD]

function walk(dir: string, out: string[] = []): string[] {
  if (!existsSync(dir)) return out
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === 'out' || name === 'dist') continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(ts|mts|tsx|mjs|cjs|js|json|css|html)$/.test(name)) out.push(p)
  }
  return out
}

const dot = '\\.'
const FORBIDDEN: Record<string, RegExp> = {
  'the CLI script': new RegExp(`${dot}/do` + 'or(?=["\'`\\s]|$)'),
  'the CLI module': new RegExp('-m\\s+do' + 'or(?!\\.mcp_server)|"-m"\\s*,\\s*"do' + 'or(?!\\.mcp_server)'),
  'an API key': new RegExp('ANTHROPIC' + '_API_KEY'),
  'the Anthropic SDK': new RegExp('@anthropic-ai' + '/sdk'),
  'claude print mode': new RegExp('claude\\s+-' + 'p\\b'),
}
// Process spawning: Node's own module and the common wrappers around it.
const SPAWN = new RegExp(`["'](node:)?child` + '_process["\']|["\'](exe' + 'ca|cross-' + 'spawn|shell' + 'js|z' + 'x)["\'/]')
const MCP_MODULE = new RegExp('do' + 'or\\.mcp_server')

function scan(files: string[], root: string): string[] {
  const offenders: string[] = []
  for (const file of files) {
    const rel = relative(root, file)
    if (rel === join('src', 'main', 'guard.test.ts')) continue
    if (rel === 'package-lock.json') continue
    // The tool descriptions are prose written for the model, which name the CLI.
    if (rel === join('src', 'generated', 'tools.json')) continue
    const text = readFileSync(file, 'utf8')
    for (const [what, re] of Object.entries(FORBIDDEN)) {
      if (rel === SERVE_FIXTURE && what === 'the CLI module') continue // it runs `serve`, see above
      if (re.test(text)) offenders.push(`${rel}: ${what}`)
    }
    if (!SPAWN_ALLOWED.includes(rel) && SPAWN.test(text)) offenders.push(`${rel}: process spawning`)
    if (rel !== SERVER && MCP_MODULE.test(text) && !rel.endsWith('.md') && !rel.includes('test'))
      offenders.push(`${rel}: starts the server outside door-server.ts`)
  }
  return offenders
}

describe('app guard', () => {
  it('no CLI, model or process spawning outside door-server.ts', () => {
    const rootFiles = readdirSync(APP)
      .filter((name) => /\.(ts|mts|js|mjs|json)$/.test(name))
      .map((name) => join(APP, name))
    const files = [...walk(join(APP, 'src')), ...walk(join(APP, 'scripts')), ...walk(join(APP, 'e2e')), ...walk(join(APP, 'e2e-package')), ...walk(join(APP, 'e2e-web')), ...walk(join(APP, 'test')), ...rootFiles]
    expect(files.length).toBeGreaterThan(0)
    expect(scan(files, APP)).toEqual([])
  })

  it('the e2e tests and the shared fixture are scanned and spawn nothing themselves', () => {
    const scanned = [...walk(join(APP, 'e2e')), ...walk(join(APP, 'test'))].map((f) => relative(APP, f))
    expect(scanned).toContain(join('test', 'home-fixture.ts'))
    expect(scanned).toContain(join('e2e', 'matches.e2e.ts'))
  })

  it('positive control: the patterns catch each forbidden thing', () => {
    const samples = [
      'spawn("./do' + 'or", ["find"])',
      'a = "python -m do' + 'or find"',
      'args = ["-m", "do' + 'or", "find"]',
      'process.env.ANTHROPIC' + '_API_KEY',
      'import x from "@anthropic-ai' + '/sdk"',
      'run("claude -' + 'p")',
    ]
    for (const body of samples) {
      expect(Object.values(FORBIDDEN).some((re) => re.test(body)), body).toBe(true)
    }
    expect(SPAWN.test('import cp from "node:child' + '_process"')).toBe(true)
    for (const lib of ['exe' + 'ca', 'cross-' + 'spawn', 'shell' + 'js', 'z' + 'x']) {
      expect(SPAWN.test(`import run from "${lib}"`), lib).toBe(true)
    }
  })

  it('the server module may name door.mcp_server, and nothing else is let through', () => {
    const ok = 'args = ["-m", "do' + 'or.mcp_server"]'
    expect(Object.values(FORBIDDEN).some((re) => re.test(ok))).toBe(false)
    expect(MCP_MODULE.test(ok)).toBe(true)
  })

  it('the sign-in module runs only `claude auth login`, with no shell', () => {
    const text = readFileSync(join(APP, LOGIN), 'utf8')
    // One spawn call, its arguments from loginArgs, whose literals are the login and nothing else.
    expect(text.match(/\bspawn\(/g)).toHaveLength(1)
    expect(text).toMatch(/spawn\(found\.path, loginArgs\(email\), \{[^}]*shell: false/)
    const args = /const args = \[([^\]]*)\]/.exec(text)?.[1]
    expect(args).toBe("'auth', 'login', '--claudeai'")
    expect(text).not.toMatch(/shell:\s*true|(?<![.\w])exec(Sync|File)?\(|'--console'|'-p'|setup-token/)
    // The real login's tests run a fake spawn.
    expect(readFileSync(join(APP, 'src', 'main', 'claude-login.test.ts'), 'utf8')).toMatch(/spawn: spawn as never/)
  })

  it('the phone test fixture runs `serve` and nothing else of the CLI', () => {
    const text = readFileSync(join(APP, SERVE_FIXTURE), 'utf8')
    expect(text).toMatch(/cliArgs = \(\.\.\.rest: string\[\]\) => \['-m', 'door', 'serve', \.\.\.rest\]/)
    expect(text.match(/spawn(Sync)?\(/g)).toHaveLength(2)
    expect(text).not.toMatch(/shell:\s*true/)
  })

  it('the packaging hook runs codesign and nothing else', () => {
    const text = readFileSync(join(APP, AFTER_PACK), 'utf8')
    expect(text.match(/execFileSync\(/g)).toHaveLength(1)
    expect(text).toMatch(/execFileSync\('codesign', \['--force', '--deep', '--sign', '-', app\]/)
    expect(text).not.toMatch(/\bexec\(|spawn\(|shell:\s*true/)
  })

  it('package.json depends on no model SDK', () => {
    const pkg = readFileSync(join(APP, 'package.json'), 'utf8')
    expect(pkg).not.toMatch(new RegExp('@anthropic-ai' + '/sdk'))
    expect(pkg).not.toMatch(new RegExp('"(exe' + 'ca|cross-' + 'spawn|shell' + 'js|z' + 'x)"\\s*:'))
  })
})
