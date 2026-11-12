// Signing in to the user's Claude plan from the app (#221): the ordinary `claude auth login`, run over plain
// pipes (it needs no terminal: thoughts/plan/221-pr3.md). claude opens the browser itself and saves the login
// where it always does, so the terminal claude and door share it. The only other module that may start a
// process besides door-server.ts (guard.test.ts), and only this one command. doctor is the judge of
// the outcome: the window checks it again after `done`. Nothing here is logged, and a pasted code is never echoed.
import { spawn as nodeSpawn } from 'node:child_process'

export type LoginState =
  | { state: 'idle' }
  | { state: 'starting' }
  | { state: 'waiting'; canOpen: boolean }
  | { state: 'done' }
  | { state: 'failed'; message: string }
  | { state: 'timeout' }
  | { state: 'cancelled' }

type Env = Record<string, string | undefined>

interface Child {
  stdout: NodeJS.ReadableStream | null
  stderr: NodeJS.ReadableStream | null
  stdin: { write(s: string): unknown; end(): unknown; on(event: 'error', cb: (e: Error) => void): unknown } | null
  kill(): boolean
  on(event: 'exit', cb: (code: number | null) => void): unknown
  on(event: 'error', cb: (e: Error) => void): unknown
}

export interface LoginDeps {
  spawn?: (cmd: string, args: string[], opts: { env: Env; shell: false; windowsHide: true; stdio: 'pipe' }) => Child
  /** The environment The other door's server runs in. */
  env: Env
  /** The doctor tool's data, asked here (never taken from the window) for claude's path and folder. */
  doctor: () => Promise<unknown>
  openExternal: (url: string) => Promise<unknown>
  onState: (state: LoginState) => void
  timeoutMs?: number
  setTimer?: (cb: () => void, ms: number) => unknown
  clearTimer?: (handle: unknown) => void
}

/** How long the browser has to come back: the issue's five minutes. */
export const LOGIN_TIMEOUT_MS = 5 * 60_000

// eslint-disable-next-line no-control-regex
const ANSI = /\u001b\[[0-9;?]*[A-Za-z]/g
const SIGN_IN_HOST = /^([a-z0-9-]+\.)*claude\.(ai|com)$/

function signInPage(text: string): string | null {
  for (const match of text.matchAll(/https:\/\/\S+/g)) {
    try {
      const url = new URL(match[0])
      if (url.protocol === 'https:' && SIGN_IN_HOST.test(url.hostname)) return url.toString()
    } catch {
      // not a URL
    }
  }
  return null
}

/** What claude has printed so far: the sign-in page, the success line, a failure. */
export function readLogin(text: string): { url: string | null; done: boolean; failure: string | null } {
  const plain = text.replace(ANSI, '')
  const failure = /Login failed:\s*(.+)/.exec(plain)
  return { url: signInPage(plain), done: /Login successful/.test(plain), failure: failure ? failure[1]!.trim() : null }
}

const EMAIL = /^[^\s@-][^\s@]*@[^\s@]+\.[^\s@]+$/

/** claude's arguments: the plan login, the email pre-filled on the page when it is a plain address. */
export function loginArgs(email?: string): string[] {
  const args = ['auth', 'login', '--claudeai']
  return email && email.length <= 254 && EMAIL.test(email) ? [...args, '--email', email] : args
}

/**
 * The sign-in's environment: the server's, without a parent Claude Code session's variables (as
 * claude_cli.env() does), signed in to the folder The other door's claude calls use, or claude's default.
 */
export function loginEnv(base: Env, configDir: string | undefined): Env {
  const env: Env = {}
  for (const [k, v] of Object.entries(base)) {
    if (k.startsWith('CLAUDE_CODE_') || k === 'CLAUDECODE' || k === 'CLAUDE_CONFIG_DIR') continue
    env[k] = v
  }
  if (configDir) env['CLAUDE_CONFIG_DIR'] = configDir
  return env
}

function fromDoctor(data: unknown): { path: string | null; configDir: string | undefined } {
  const checks = (data as { checks?: { name?: string; details?: Record<string, unknown> }[] } | null)?.checks ?? []
  const details = (name: string) => checks.find((c) => c.name === name)?.details ?? {}
  const path = details('claude CLI')['path']
  const dir = details('claude login')['doorConfigDir']
  return { path: typeof path === 'string' && path ? path : null, configDir: typeof dir === 'string' && dir ? dir : undefined }
}

const CODE = /^[A-Za-z0-9#_.~+/=-]{1,512}$/

export function createClaudeLogin(deps: LoginDeps) {
  const spawn = deps.spawn ?? (nodeSpawn as unknown as NonNullable<LoginDeps['spawn']>)
  const setTimer = deps.setTimer ?? ((cb, ms) => setTimeout(cb, ms))
  const clearTimer = deps.clearTimer ?? ((h) => clearTimeout(h as NodeJS.Timeout))
  let current: { child: Child; url: string | null; timer: unknown; over: boolean } | null = null
  // Each start and cancel draws a new number: a start whose doctor answer comes after another start or
  // a cancel spawns nothing.
  let generation = 0
  let state: LoginState = { state: 'idle' }
  const set = (s: LoginState) => {
    state = s
    deps.onState(s)
  }

  function end(run: NonNullable<typeof current>, s: LoginState, kill = false) {
    if (run.over) return
    run.over = true
    clearTimer(run.timer)
    if (kill) run.child.kill()
    if (current === run) current = null
    set(s)
  }

  return {
    state: () => state,

    async start(email?: string): Promise<void> {
      const mine = ++generation
      if (current) end(current, { state: 'cancelled' }, true)
      set({ state: 'starting' })
      let found: ReturnType<typeof fromDoctor>
      try {
        found = fromDoctor(await deps.doctor())
      } catch (e) {
        if (mine !== generation) return
        set({ state: 'failed', message: `The other door could not check claude: ${e instanceof Error ? e.message : String(e)}` })
        return
      }
      if (mine !== generation) return
      if (!found.path) {
        set({ state: 'failed', message: 'The claude app is not installed.' })
        return
      }
      const child = spawn(found.path, loginArgs(email), { env: loginEnv(deps.env, found.configDir), shell: false, windowsHide: true, stdio: 'pipe' })
      const run = { child, url: null as string | null, timer: null as unknown, over: false }
      current = run
      // A code written just as claude exits must not become an uncaught EPIPE in main.
      child.stdin?.on('error', () => undefined)
      let out = ''
      let err = ''
      child.stdout?.on('data', (chunk: Buffer | string) => {
        out += chunk.toString()
        const seen = readLogin(out)
        if (seen.url && !run.url && !run.over) {
          run.url = seen.url
          set({ state: 'waiting', canOpen: true })
        }
      })
      child.stderr?.on('data', (chunk: Buffer | string) => {
        err += chunk.toString()
      })
      child.on('exit', (code) => {
        if (code === 0) return end(run, { state: 'done' })
        const failure = readLogin(err).failure ?? readLogin(out).failure
        end(run, { state: 'failed', message: failure ?? `claude stopped (exit ${code})` })
      })
      child.on('error', (e) => end(run, { state: 'failed', message: `claude could not start: ${e.message}` }))
      run.timer = setTimer(() => end(run, { state: 'timeout' }, true), deps.timeoutMs ?? LOGIN_TIMEOUT_MS)
      set({ state: 'waiting', canOpen: false })
    },

    /** The code the sign-in page shows when the browser could not hand it back to claude. */
    sendCode(code: string): boolean {
      const clean = code.trim()
      if (!current || !CODE.test(clean) || !current.child.stdin) return false
      current.child.stdin.write(clean + '\n')
      return true
    },

    /** Opens the page claude printed, never one the window names. */
    async openPage(): Promise<boolean> {
      if (!current?.url) return false
      await deps.openExternal(current.url)
      return true
    },

    cancel(): void {
      const starting = state.state === 'starting'
      generation++
      if (current) end(current, { state: 'cancelled' }, true)
      else if (starting) set({ state: 'cancelled' })
    },
  }
}

export type ClaudeLogin = ReturnType<typeof createClaudeLogin>
