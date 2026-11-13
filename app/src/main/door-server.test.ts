import { mkdtempSync, readFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { APP_ID, DoorError, DoorServer, resolvePackagedSpawn, resolveSpawn } from './door-server'

const FAKE = join(__dirname, '..', '..', 'test', 'fake-mcp-server.mjs')
const servers: DoorServer[] = []

function make(env: Record<string, string> = {}, opts = {}) {
  const s = new DoorServer({ command: process.execPath, args: [FAKE], env: { ...env } }, opts)
  servers.push(s)
  return s
}

afterEach(async () => {
  await Promise.all(servers.splice(0).map((s) => s.close()))
})

async function until(cond: () => boolean, ms = 5000) {
  const end = Date.now() + ms
  while (!cond()) {
    if (Date.now() > end) throw new Error('timed out waiting')
    await new Promise((r) => setTimeout(r, 20))
  }
}

describe('DoorServer', () => {
  it('(a) parses the JSON text block into an object', async () => {
    const r = await make().call<{ ok: boolean; args: unknown }>('json', { x: 1 })
    expect(r.ok).toBe(true)
    expect(r.args).toEqual({ x: 1 })
  })

  it('(b) an {error} result becomes a DoorError, with its candidates', async () => {
    const s = make()
    await expect(s.call('err')).rejects.toMatchObject({ name: 'DoorError', message: 'no such job' })
    const e: any = await s.call("ambiguous").catch((x) => x)
    expect(e).toBeInstanceOf(DoorError)
    expect(e.message).toBe('several jobs match')
    expect(e.candidates).toEqual([{ job_id: 'a.1', title: 'T', company: 'C', status: 'unapplied' }])
  })

  it('(b2) a sync conflict keeps its flag', async () => {
    const e: any = await make().call('conflict').catch((x) => x)
    expect(e).toBeInstanceOf(DoorError)
    expect(e.conflict).toBe(true)
  })

  it('(c) an isError result becomes a DoorError', async () => {
    await expect(make().call('iserror')).rejects.toThrow(/boom/)
  })

  it('(d) lists the tools', async () => {
    const tools = await make().listTools()
    expect(tools.map((t) => t.name)).toContain('json')
    expect(tools[0]).toHaveProperty('inputSchema')
  })

  it('(e) a killed child is replaced by the next call', async () => {
    const s = make()
    const first = await s.call<{ pid: number }>('json')
    expect(s.pid).toBe(first.pid)
    process.kill(first.pid)
    await until(() => s.pid === null)
    const second = await s.call<{ pid: number }>('json')
    expect(second.pid).not.toBe(first.pid)
  })

  it('(f) a call in flight when the child dies rejects, and the next call restarts it', async () => {
    const s = make()
    await s.call('json')
    await expect(s.call('exit')).rejects.toMatchObject({ name: 'DoorError', message: expect.stringMatching(/stopped; try again/) })
    const r = await s.call<{ ok: boolean }>('json')
    expect(r.ok).toBe(true)
  })

  it('(g) a child that dies on every start: each call fails, one spawn per call', async () => {
    const log = join(mkdtempSync(join(tmpdir(), 'fake-')), 'starts.log')
    const s = make({ FAKE_DIE_ON_START: '1', FAKE_START_LOG: log })
    await expect(s.call('json')).rejects.toBeInstanceOf(DoorError)
    await expect(s.call('json')).rejects.toBeInstanceOf(DoorError)
    expect(readFileSync(log, 'utf8').trim().split('\n')).toHaveLength(2)
  })

  it('(h) the child gets only the env it is passed (plus the SDK safe defaults)', async () => {
    process.env.LEAK_ME_INTO_CHILD = 'yes'
    try {
      const r = await make({ DOOR_HOME: '/x/y', PYTHONPATH: '/p' }).call<{ env: Record<string, string> }>('env')
      expect(r.env.DOOR_HOME).toBe('/x/y')
      expect(r.env.PYTHONPATH).toBe('/p')
      expect(r.env.LEAK_ME_INTO_CHILD).toBeUndefined()
    } finally {
      delete process.env.LEAK_ME_INTO_CHILD
    }
  })

  it('a per-call timeout rejects with a DoorError', async () => {
    await expect(make().call('slow', { ms: 3000 }, { timeout: 200 })).rejects.toBeInstanceOf(DoorError)
  })

  it('passes progress notifications to onProgress', async () => {
    const seen: unknown[] = []
    const r = await make().call<{ withToken: boolean }>('slow_progress', {}, { onProgress: (p) => seen.push(p) })
    expect(r.withToken).toBe(true)
    expect(seen).toEqual([
      { progress: 1, total: 2, message: 'step 1' },
      { progress: 2, total: 2, message: 'step 2' },
    ])
  })

  it('sends no progress token without onProgress, and does not fail', async () => {
    const r = await make().call<{ done: boolean; withToken: boolean }>('slow_progress')
    expect(r).toEqual({ done: true, withToken: false })
  })

  it('close() does not restart the child', async () => {
    const log = join(mkdtempSync(join(tmpdir(), 'fake-')), 'starts.log')
    const s = make({ FAKE_START_LOG: log })
    await s.call('json')
    await s.close()
    await new Promise((r) => setTimeout(r, 300))
    expect(s.pid).toBeNull()
    expect(readFileSync(log, 'utf8').trim().split('\n')).toHaveLength(1)
    expect(existsSync(log)).toBe(true)
  })
})

describe('what goes wrong, for the problem log', () => {
  const recorder = () => {
    const seen: [string, string][] = []
    return { seen, onProblem: (where: string, message: string) => void seen.push([where, message]) }
  }

  it('a child that dies in a call: its stderr', async () => {
    const r = recorder()
    const s = make({}, { onProblem: r.onProblem })
    await s.call('json')
    await s.call('exit').catch(() => undefined)
    expect(r.seen).toEqual([['server stopped', expect.stringContaining('RuntimeError: the fake fell over')]])
  })

  it('a child that will not start: why, with its stderr', async () => {
    const r = recorder()
    await make({ FAKE_DIE_ON_START: '1' }, { onProblem: r.onProblem }).call('json').catch(() => undefined)
    expect(r.seen).toEqual([['server would not start', expect.stringContaining('no module named door')]])
  })

  it('a call that timed out names its tool', async () => {
    const r = recorder()
    await make({}, { onProblem: r.onProblem }).call('slow', { ms: 3000 }, { timeout: 200 }).catch(() => undefined)
    expect(r.seen).toEqual([['slow timed out', 'no answer in 0.2 s']])
  })

  it('an {error} answer is the server\'s own to log, and a stop is not a problem', async () => {
    const r = recorder()
    const s = make({}, { onProblem: r.onProblem })
    await s.call('err').catch(() => undefined)
    const slow = s.call('slow', { ms: 30_000 }).catch(() => undefined)
    await until(() => s.pid !== null)
    await new Promise((res) => setTimeout(res, 300))
    await s.stop()
    await slow
    expect(r.seen).toEqual([])
  }, 20_000)
})

describe('the server\'s version', () => {
  it('a server of another version is refused, in words', async () => {
    const s = make({}, { expectedVersion: '9.9.9' })
    await expect(s.call('json')).rejects.toThrow('This app is version 9.9.9, but the door inside it is 0.0.0. Install the app again.')
    await s.close()
  })

  it('the same version, or none expected, goes through', async () => {
    const same = make({}, { expectedVersion: '0.0.0' })
    await expect(same.call('json')).resolves.toMatchObject({ ok: true })
    await same.close()
    const any = make()
    await expect(any.call('json')).resolves.toMatchObject({ ok: true })
    await any.close()
  })
})

describe('DoorServer.stop', () => {
  it('rejects the call in flight as stopped, and the next call starts a new child', async () => {
    const log = join(mkdtempSync(join(tmpdir(), 'fake-')), 'starts.log')
    const s = make({ FAKE_START_LOG: log })
    const first = s.call('slow', { ms: 30_000 })
    const caught = first.catch((e) => e)
    await until(() => s.pid !== null)
    await new Promise((r) => setTimeout(r, 300)) // the call reached the child
    await s.stop()
    const e: any = await caught
    expect(e).toBeInstanceOf(DoorError)
    expect(e.stopped).toBe(true)
    expect(e.message).toBe('stopped')
    expect(s.pid).toBeNull()
    const r = await s.call<{ ok: boolean }>('json')
    expect(r.ok).toBe(true)
    expect(readFileSync(log, 'utf8').trim().split('\n')).toHaveLength(2)
  }, 20_000)

  it('is a no-op without a child, and a later death is an ordinary failure', async () => {
    const s = make()
    await s.stop()
    await s.call('json')
    await expect(s.call('exit')).rejects.toMatchObject({ message: expect.stringMatching(/stopped; try again/) })
    const e: any = await s.call('exit').catch((x) => x)
    expect(e.stopped).toBeUndefined()
  })
})

describe('resolveSpawn', () => {
  const env = { HOME: '/h', XDG_CONFIG_HOME: '/xdg', APPDATA: '/ad', DOOR_HOME: '/hh', PATH: '/bin', SECRET: 'no' }

  it('uses the checkout venv, the server module, the repo root and an explicit env', () => {
    const s = resolveSpawn('/repo', env, 'linux')
    expect(s.command).toBe('/repo/.venv/bin/python')
    expect(s.args).toEqual(['-m', 'door.mcp_server'])
    expect(s.cwd).toBe('/repo')
    expect(s.env).toMatchObject({ PYTHONPATH: '/repo/src', HOME: '/h', XDG_CONFIG_HOME: '/xdg', APPDATA: '/ad', DOOR_HOME: '/hh', PATH: '/bin', DOOR_PATHS_FROM_DIALOGS: '1' })
    expect(s.env).not.toHaveProperty('SECRET')
  })

  it('forwards CLAUDE_CONFIG_DIR when set and leaves it out when not', () => {
    expect(resolveSpawn('/repo', { ...env, CLAUDE_CONFIG_DIR: '/sandbox/.claude' }, 'linux').env).toMatchObject({ CLAUDE_CONFIG_DIR: '/sandbox/.claude' })
    expect(resolveSpawn('/repo', env, 'linux').env).not.toHaveProperty('CLAUDE_CONFIG_DIR')
  })

  it('uses Scripts/python.exe on Windows', () => {
    expect(resolveSpawn('C:/repo', env, 'win32').command).toMatch(/\.venv[\\/]Scripts[\\/]python\.exe$/)
  })

  it('DOOR_PYTHON overrides the interpreter; unset variables are left out', () => {
    const s = resolveSpawn('/repo', { DOOR_PYTHON: '/usr/bin/py3' }, 'linux')
    expect(s.command).toBe('/usr/bin/py3')
    expect(s.env).not.toHaveProperty('DOOR_HOME')
    expect(s.env).not.toHaveProperty('HOME')
  })
})

describe('resolvePackagedSpawn', () => {
  const env = { PATH: '/usr/bin', HOME: '/Users/ada', CLAUDE_CONFIG_DIR: '/Users/ada/.claude-work', SECRET: 'no' }

  it('runs the bundled Python on the bundled src, with the data in the user folder (macOS and Linux)', () => {
    const s = resolvePackagedSpawn({ resourcesPath: '/Applications/door.app/Contents/Resources', home: '/Users/ada/Library/Application Support/door', platform: 'darwin', env })
    expect(s.command).toBe('/Applications/door.app/Contents/Resources/python/bin/python3')
    expect(s.args).toEqual(['-s', '-m', 'door.mcp_server'])
    expect(s.cwd).toBe('/Applications/door.app/Contents/Resources/door')
    expect(s.env).toEqual({
      PYTHONPATH: '/Applications/door.app/Contents/Resources/door/src',
      DOOR_HOME: '/Users/ada/Library/Application Support/door',
      DOOR_BIN: '/Applications/door.app/Contents/Resources/bin',
      DOOR_WEB_DIR: '/Applications/door.app/Contents/Resources/web',
      PYTHONNOUSERSITE: '1',
      PYTHONDONTWRITEBYTECODE: '1',
      DOOR_PATHS_FROM_DIALOGS: '1',
      PATH: '/Applications/door.app/Contents/Resources/bin:/Users/ada/.local/bin:/usr/bin',
      HOME: '/Users/ada',
      CLAUDE_CONFIG_DIR: '/Users/ada/.claude-work',
    })
  })

  it('on Windows: python.exe at the runtime root, ; between PATH entries', () => {
    const s = resolvePackagedSpawn({ resourcesPath: 'C:\\Program Files\\door\\resources', home: 'C:\\Users\\ada\\AppData\\Roaming\\door', platform: 'win32', env: { PATH: 'C:\\Windows', USERPROFILE: 'C:\\Users\\ada', APPDATA: 'C:\\Users\\ada\\AppData\\Roaming' } })
    expect(s.command).toBe('C:\\Program Files\\door\\resources\\python\\python.exe')
    expect(s.env!['PATH']).toBe('C:\\Program Files\\door\\resources\\bin;C:\\Users\\ada\\.local\\bin;C:\\Windows')
    expect(s.env!['APPDATA']).toBe('C:\\Users\\ada\\AppData\\Roaming')
  })

  it('on Windows: keeps what Windows needs to run a .cmd (an npm-installed claude.cmd), whatever its case', () => {
    const s = resolvePackagedSpawn({ resourcesPath: 'C:\\r', home: 'C:\\h', platform: 'win32', env: {
      PATH: 'C:\\Windows', ComSpec: 'C:\\Windows\\system32\\cmd.exe', PATHEXT: '.COM;.EXE;.BAT;.CMD', SystemRoot: 'C:\\Windows',
      windir: 'C:\\Windows', TEMP: 'C:\\t', TMP: 'C:\\t', SECRET: 'no' } })
    expect(s.env).toMatchObject({ ComSpec: 'C:\\Windows\\system32\\cmd.exe', PATHEXT: '.COM;.EXE;.BAT;.CMD', SystemRoot: 'C:\\Windows',
      windir: 'C:\\Windows', TEMP: 'C:\\t', TMP: 'C:\\t' })
    expect(s.env!['SECRET']).toBeUndefined()
  })

  it('elsewhere: no Windows variables', () => {
    const s = resolvePackagedSpawn({ resourcesPath: '/r', home: '/h', platform: 'linux', env: { ComSpec: 'x', PATH: '/usr/bin' } })
    expect(s.env!['ComSpec']).toBeUndefined()
  })

  it('never puts the data, or anything it writes, inside the app', () => {
    const res = '/Applications/door.app/Contents/Resources'
    const s = resolvePackagedSpawn({ resourcesPath: res, home: '/Users/ada/Library/Application Support/door', platform: 'darwin', env })
    expect(s.env!['DOOR_HOME']!.startsWith(res)).toBe(false)
    expect(() => resolvePackagedSpawn({ resourcesPath: res, home: `${res}/data`, platform: 'darwin', env })).toThrow(/inside the app/)
  })

  it('ignores a DOOR_PYTHON from the environment: the bundle runs its own', () => {
    expect(resolvePackagedSpawn({ resourcesPath: '/r', home: '/h', platform: 'linux', env: { DOOR_PYTHON: '/tmp/evil' } }).command).toBe('/r/python/bin/python3')
  })

  it('has one app id', () => {
    expect(APP_ID).toBe('dev.door.app')
  })
})
