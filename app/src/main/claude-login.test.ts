import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'
import { describe, expect, it, vi } from 'vitest'
import { createClaudeLogin, loginArgs, loginEnv, readLogin, type LoginState } from './claude-login'

// What claude 2.1.310 printed over plain pipes (the probe in thoughts/plan/221-pr3.md), state scrubbed.
const URL_LINE =
  "If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true&client_id=x&response_type=code&state=STATE"
const OPENING = 'Opening browser to sign in…\n' + URL_LINE + '\nPaste code here if prompted > '

class FakeChild extends EventEmitter {
  stdout = new PassThrough()
  stderr = new PassThrough()
  written: string[] = []
  stdin = { write: (s: string) => this.written.push(s), end: vi.fn(), on: vi.fn() }
  kill = vi.fn(() => true)
  exit(code: number | null) {
    this.emit('exit', code, null)
  }
}

const DOCTOR = {
  checks: [
    { name: 'claude CLI', status: 'ok', details: { path: '/home/j/.local/bin/claude' } },
    { name: 'claude login', status: 'missing', details: { loggedIn: false, doorConfigDir: '/home/j/.claude-work' } },
  ],
}

function setup(doctor: unknown = DOCTOR, ask?: () => Promise<unknown>) {
  const child = new FakeChild()
  const spawn = vi.fn((_cmd: string, _args: string[], _opts: unknown) => child)
  const states: LoginState[] = []
  const openExternal = vi.fn(async () => undefined)
  let fire: (() => void) | null = null
  const login = createClaudeLogin({
    spawn: spawn as never,
    env: { PATH: '/bin', HOME: '/home/j', CLAUDECODE: '1', CLAUDE_CODE_ENTRYPOINT: 'cli', CLAUDE_CONFIG_DIR: '/elsewhere' },
    doctor: ask ?? (async () => doctor),
    openExternal,
    onState: (s) => states.push(s),
    setTimer: (cb) => {
      fire = cb
      return 1
    },
    clearTimer: () => {
      fire = null
    },
  })
  return { child, spawn, states, openExternal, login, timeout: () => fire?.(), last: () => states[states.length - 1] }
}

describe('readLogin', () => {
  it('finds the sign-in page and nothing else in what claude printed first', () => {
    expect(readLogin(OPENING)).toEqual({ url: 'https://claude.com/cai/oauth/authorize?code=true&client_id=x&response_type=code&state=STATE', done: false, failure: null })
  })

  it('sees the success line, colours and all', () => {
    expect(readLogin(OPENING + '\u001b[32mLogin successful.\u001b[39m\n').done).toBe(true)
  })

  it('reads a failure line', () => {
    expect(readLogin('Login failed: Request failed with status code 400\n').failure).toBe('Request failed with status code 400')
  })

  it('keeps only a claude.ai or claude.com page over https', () => {
    for (const bad of ['http://claude.com/x', 'https://claude.com.evil.io/x', 'https://evilclaude.ai/x', 'https://example.com/claude.ai']) {
      expect(readLogin(`visit: ${bad}\n`).url, bad).toBeNull()
    }
    expect(readLogin('visit: https://platform.claude.com/oauth\n').url).toBe('https://platform.claude.com/oauth')
    expect(readLogin('visit: https://claude.ai/oauth/authorize?a=1\n').url).toBe('https://claude.ai/oauth/authorize?a=1')
  })
})

describe('loginArgs and loginEnv', () => {
  it('signs in to the plan, with a plain email pre-filled', () => {
    expect(loginArgs()).toEqual(['auth', 'login', '--claudeai'])
    expect(loginArgs('jane@example.com')).toEqual(['auth', 'login', '--claudeai', '--email', 'jane@example.com'])
  })

  it('leaves out anything that is not a plain email', () => {
    for (const bad of ['-p', '--console', 'jane', 'a b@c.d', '-x@y.z', `${'a'.repeat(250)}@example.com`]) {
      expect(loginArgs(bad), bad).toEqual(['auth', 'login', '--claudeai'])
    }
  })

  it("runs in The other door's config folder, or claude's default when door names none", () => {
    const base = { PATH: '/bin', CLAUDECODE: '1', CLAUDE_CODE_SSE_PORT: '1', CLAUDE_CONFIG_DIR: '/inherited' }
    expect(loginEnv(base, '/work')).toEqual({ PATH: '/bin', CLAUDE_CONFIG_DIR: '/work' })
    expect(loginEnv(base, undefined)).toEqual({ PATH: '/bin' })
  })
})

describe('createClaudeLogin', () => {
  it("starts claude from doctor's path, in doctor's config folder, without a shell", async () => {
    const { login, spawn } = setup()
    await login.start('jane@example.com')
    const [cmd, args, opts] = spawn.mock.calls[0]!
    expect(cmd).toBe('/home/j/.local/bin/claude')
    expect(args).toEqual(['auth', 'login', '--claudeai', '--email', 'jane@example.com'])
    expect(opts).toMatchObject({ shell: false, env: { PATH: '/bin', HOME: '/home/j', CLAUDE_CONFIG_DIR: '/home/j/.claude-work' } })
    expect((opts as { env: Record<string, string> }).env).not.toHaveProperty('CLAUDECODE')
  })

  it('waits for the browser, and then says the page can be opened again', async () => {
    const { login, child, last } = setup()
    await login.start()
    expect(last()).toEqual({ state: 'waiting', canOpen: false })
    child.stdout.write(OPENING.slice(0, 40))
    child.stdout.write(OPENING.slice(40))
    await Promise.resolve()
    expect(last()).toEqual({ state: 'waiting', canOpen: true })
  })

  it('opens only the page claude printed', async () => {
    const { login, child, openExternal } = setup()
    await login.start()
    expect(await login.openPage()).toBe(false)
    child.stdout.write(OPENING)
    await Promise.resolve()
    expect(await login.openPage()).toBe(true)
    expect(openExternal).toHaveBeenCalledWith(expect.stringMatching(/^https:\/\/claude\.com\/cai\/oauth\/authorize/))
  })

  it('is done when claude exits 0', async () => {
    const { login, child, last } = setup()
    await login.start()
    child.stdout.write(OPENING + 'Login successful.\n')
    child.exit(0)
    expect(last()).toEqual({ state: 'done' })
  })

  it('fails with what claude said, or the exit code', async () => {
    const one = setup()
    await one.login.start()
    one.child.stderr.write('Login failed: Request failed with status code 400\n')
    await Promise.resolve()
    one.child.exit(1)
    expect(one.last()).toEqual({ state: 'failed', message: 'Request failed with status code 400' })

    const two = setup()
    await two.login.start()
    two.child.exit(3)
    expect(two.last()).toEqual({ state: 'failed', message: 'claude stopped (exit 3)' })
  })

  it('sends a pasted code with a newline, and refuses anything that is not a code', async () => {
    const { login, child } = setup()
    await login.start()
    expect(login.sendCode('  abc-DEF_123#state.x~y  ')).toBe(true)
    expect(child.written).toEqual(['abc-DEF_123#state.x~y\n'])
    for (const bad of ['', 'two\nlines', 'a b', 'x'.repeat(513), '$(rm)']) expect(login.sendCode(bad), bad).toBe(false)
    expect(child.written).toHaveLength(1)
  })

  it('a code with no sign-in running goes nowhere', () => {
    const { login } = setup()
    expect(login.sendCode('abc')).toBe(false)
  })

  it('gives up after the time limit and stops claude', async () => {
    const { login, child, last, timeout } = setup()
    await login.start()
    timeout()
    expect(child.kill).toHaveBeenCalled()
    expect(last()).toEqual({ state: 'timeout' })
    child.exit(null)
    expect(last()).toEqual({ state: 'timeout' })
  })

  it('cancel stops claude and the exit after it changes nothing', async () => {
    const { login, child, last } = setup()
    await login.start()
    login.cancel()
    expect(child.kill).toHaveBeenCalled()
    child.exit(null)
    expect(last()).toEqual({ state: 'cancelled' })
  })

  it('starting again replaces a sign-in still waiting', async () => {
    const { login, child, spawn } = setup()
    await login.start()
    await login.start()
    expect(child.kill).toHaveBeenCalledTimes(1)
    expect(spawn).toHaveBeenCalledTimes(2)
  })

  it('a second start while doctor answers the first spawns once, and cancel then spawns nothing', async () => {
    let answer: (v: unknown) => void = () => {}
    const slow = () => new Promise((r) => (answer = r))
    const { login, spawn } = setup(DOCTOR, slow)
    const first = login.start()
    const firstAnswer = answer
    const second = login.start()
    firstAnswer(DOCTOR)
    answer(DOCTOR)
    await Promise.all([first, second])
    expect(spawn).toHaveBeenCalledTimes(1)

    const again = setup(DOCTOR, slow)
    const pending = again.login.start()
    again.login.cancel()
    answer(DOCTOR)
    await pending
    expect(again.spawn).not.toHaveBeenCalled()
    expect(again.last()).toEqual({ state: 'cancelled' })
  })

  it('a code written after claude has gone does not crash main', async () => {
    const { login, child } = setup()
    await login.start()
    expect(child.stdin.on).toHaveBeenCalledWith('error', expect.any(Function))
  })

  it('says so when claude is not installed', async () => {
    const { login, spawn, last } = setup({ checks: [{ name: 'claude CLI', status: 'missing' }] })
    await login.start()
    expect(spawn).not.toHaveBeenCalled()
    expect(last()).toEqual({ state: 'failed', message: 'The claude app is not installed.' })
  })

  it('a spawn error is a failure, not a crash', async () => {
    const { login, child, last } = setup()
    await login.start()
    child.emit('error', new Error('ENOENT'))
    expect(last()).toEqual({ state: 'failed', message: 'claude could not start: ENOENT' })
  })
})
