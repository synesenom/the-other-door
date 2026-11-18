import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { prepare, sandboxRunMs, serverEnv, startFor } from './environments'
import type { Start } from './environments'

describe('startFor', () => {
  it('reads the electron-vite mode: staging and the sandbox in their folders of the checkout', () => {
    expect(startFor('staging', {}, false, '/repo')).toEqual({ environment: 'staging', folder: join('/repo', 'app', '.staging'), fresh: false })
    expect(startFor('staging-fresh', {}, false, '/repo')).toEqual({ environment: 'staging', folder: join('/repo', 'app', '.staging'), fresh: true })
    const sandbox = join('/repo', 'app', '.sandbox')
    expect(startFor('sandbox', {}, false, '/repo')).toEqual({ environment: 'sandbox', folder: sandbox, start: 'keep' })
    expect(startFor('sandbox-fresh', {}, false, '/repo')).toEqual({ environment: 'sandbox', folder: sandbox, start: 'fresh' })
    expect(startFor('sandbox-empty', {}, false, '/repo')).toEqual({ environment: 'sandbox', folder: sandbox, start: 'empty' })
  })

  it('anything else is production, and a packaged app always is', () => {
    expect(startFor('development', {}, false, '/repo')).toEqual({ environment: 'production' })
    expect(startFor(undefined, {}, false, '/repo')).toEqual({ environment: 'production' })
    for (const mode of ['staging', 'sandbox', 'sandbox-empty']) expect(startFor(mode, { DOOR_SANDBOX_DIR: '/tmp/s' }, true, '/repo')).toEqual({ environment: 'production' })
  })

  it('DOOR_SANDBOX_DIR makes a built app the sandbox in that folder, empty with DOOR_SANDBOX_EMPTY=1', () => {
    expect(startFor('production', { DOOR_SANDBOX_DIR: '/tmp/s' }, false, '/repo')).toEqual({ environment: 'sandbox', folder: '/tmp/s', start: 'keep' })
    expect(startFor(undefined, { DOOR_SANDBOX_DIR: '/tmp/s', DOOR_SANDBOX_EMPTY: '1' }, false, '/repo')).toEqual({ environment: 'sandbox', folder: '/tmp/s', start: 'empty' })
    expect(startFor('sandbox-fresh', { DOOR_SANDBOX_DIR: '/tmp/s' }, false, '/repo')).toEqual({ environment: 'sandbox', folder: '/tmp/s', start: 'fresh' })
    expect(startFor('production', { DOOR_SANDBOX_DIR: '' }, false, '/repo')).toEqual({ environment: 'production' })
  })
})

describe('prepare', () => {
  const repo = join(__dirname, '..', '..', '..')
  const folder = (name: string) => join(mkdtempSync(join(tmpdir(), 'door-env-')), name)

  it('staging keeps what is there, and fresh empties it', () => {
    const dir = folder('.staging')
    prepare({ environment: 'staging', folder: dir, fresh: false }, repo, {})
    expect(readdirSync(dir)).toEqual([])
    mkdirSync(join(dir, 'profile'))
    writeFileSync(join(dir, 'profile', 'config.json'), '{}')
    prepare({ environment: 'staging', folder: dir, fresh: false }, repo, {})
    expect(existsSync(join(dir, 'profile', 'config.json'))).toBe(true)
    prepare({ environment: 'staging', folder: dir, fresh: true }, repo, {})
    expect(readdirSync(dir)).toEqual([])
  })

  it('the sandbox is seeded with the made-up data, kept, made again when fresh, and emptied when empty', () => {
    const dir = folder('.sandbox')
    prepare({ environment: 'sandbox', folder: dir, start: 'keep' }, repo, {})
    expect(JSON.parse(readFileSync(join(dir, 'profile', 'config.json'), 'utf8')).name).toBe('Jane Doe')
    writeFileSync(join(dir, 'jobs', 'applications.json'), '{"changed": true}')
    prepare({ environment: 'sandbox', folder: dir, start: 'keep' }, repo, {})
    expect(readFileSync(join(dir, 'jobs', 'applications.json'), 'utf8')).toContain('changed')
    prepare({ environment: 'sandbox', folder: dir, start: 'fresh' }, repo, {})
    expect(readFileSync(join(dir, 'jobs', 'applications.json'), 'utf8')).not.toContain('changed')
    prepare({ environment: 'sandbox', folder: dir, start: 'empty' }, repo, {})
    expect(readdirSync(dir)).toEqual([])
  })

  it('DOOR_SANDBOX_DISCOVERY=off seeds a profile with every discovery source off (the README GIF)', () => {
    const dir = folder('.sandbox')
    prepare({ environment: 'sandbox', folder: dir, start: 'keep' }, repo, { DOOR_SANDBOX_DISCOVERY: 'off' })
    const config = JSON.parse(readFileSync(join(dir, 'profile', 'config.json'), 'utf8'))
    for (const key of ['linkedin_discovery', 'profession_discovery', 'hellowork_discovery', 'jobbsafari_discovery']) expect(config[key]).toBe(false)
  })

  it('refuses the checkout, jobs/ and profile/ before deleting anything', () => {
    const fake = mkdtempSync(join(tmpdir(), 'door-repo-'))
    for (const d of ['jobs', 'profile']) mkdirSync(join(fake, d))
    writeFileSync(join(fake, 'jobs', 'applications.json'), '{}')
    for (const bad of [fake, join(fake, 'jobs'), join(fake, 'profile'), join(fake, 'jobs', 'x')]) {
      expect(() => prepare({ environment: 'staging', folder: bad, fresh: true }, fake, {})).toThrow(/staging/)
      for (const start of ['empty', 'fresh'] as const) expect(() => prepare({ environment: 'sandbox', folder: bad, start }, fake, {})).toThrow(/sandbox/)
    }
    expect(existsSync(join(fake, 'jobs', 'applications.json'))).toBe(true)
  })

  it('production touches nothing', () => {
    expect(() => prepare({ environment: 'production' }, repo, {})).not.toThrow()
  })
})

describe('serverEnv', () => {
  const base = { HOME: '/Users/me', PATH: '/bin', DOOR_HOME: '/real' }

  it('production is your environment as it is', () => {
    expect(serverEnv({ environment: 'production' }, base)).toEqual(base)
  })

  it('staging and the sandbox point the data and the Drive state into their folder, and keep HOME and PATH for claude', () => {
    const starts: Start[] = [{ environment: 'staging', folder: '/f', fresh: false }, { environment: 'sandbox', folder: '/f', start: 'keep' }]
    for (const start of starts) {
      expect(serverEnv(start, base)).toEqual({ ...base, DOOR_HOME: '/f', XDG_CONFIG_HOME: join('/f', '.config'), APPDATA: join('/f', 'appdata') })
    }
  })

  it('DOOR_SANDBOX_SIGNED_OUT=1 gives the sandbox, and only it, a Claude config folder of its own', () => {
    const out = { ...base, DOOR_SANDBOX_SIGNED_OUT: '1' }
    expect(serverEnv({ environment: 'sandbox', folder: '/f', start: 'empty' }, out)).toMatchObject({ CLAUDE_CONFIG_DIR: join('/f', '.claude') })
    expect(serverEnv({ environment: 'staging', folder: '/f', fresh: false }, out)).not.toHaveProperty('CLAUDE_CONFIG_DIR')
    expect(serverEnv({ environment: 'sandbox', folder: '/f', start: 'empty' }, base)).not.toHaveProperty('CLAUDE_CONFIG_DIR')
  })
})

describe('sandboxRunMs', () => {
  it('reads DOOR_SANDBOX_RUN_MS as a positive number, else nothing', () => {
    expect(sandboxRunMs({ DOOR_SANDBOX_RUN_MS: '1500' })).toBe(1500)
    for (const bad of [undefined, '', 'x', '0', '-5']) expect(sandboxRunMs({ DOOR_SANDBOX_RUN_MS: bad })).toBeUndefined()
  })
})
