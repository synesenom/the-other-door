// The one place that starts The other door's MCP server: a typed client over stdio.
// Every result is The other door's own JSON in a single text block; expected failures
// are {"error": ..., "candidates"?: ...} and become a DoorError.
import { posix, win32 } from 'node:path'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js'
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js'

export interface Candidate {
  job_id: string
  title: string
  company: string
  status: string
}

export class DoorError extends Error {
  candidates?: Candidate[]
  /** Set when the app ended the call on purpose (`stop()`), as opposed to a failure. */
  stopped?: true
  /** Set when a call gave up waiting (its idle limit ran out). */
  timedOut?: true
  /** Set when Drive and this computer both changed (sync_data): the caller picks which to keep. */
  conflict?: true
  constructor(message: string, candidates?: Candidate[]) {
    super(message)
    this.name = 'DoorError'
    if (candidates) this.candidates = candidates
  }
}

export interface SpawnSpec {
  command: string
  args: string[]
  cwd?: string
  env?: Record<string, string>
}

export interface ToolInfo {
  name: string
  description: string
  inputSchema: unknown
}

export interface CallOptions {
  /** Milliseconds before the call is given up on (default 60 s). */
  timeout?: number
  /** Called for each progress notification the tool sends; also lifts the timeout while they keep coming. */
  onProgress?: (p: { progress: number; total?: number; message: string }) => void
}

export interface ServerOptions {
  /** Milliseconds to wait for the child to answer the handshake (default 30 s). */
  startupTimeoutMs?: number
  /** The version the server must report in `initialize` (a packaged app's own, #224); none: any. */
  expectedVersion?: string
  /**
   * Told what went wrong that the server cannot log itself (#593): it would not start, it stopped in a
   * call (with the end of its stderr), a call timed out. Its `{"error"}` answers it logs on its own; a stop
   * the app asked for is no problem.
   */
  onProblem?: (where: string, message: string) => void
}

type Env = Record<string, string | undefined>

/** How to start the server from a checkout: its venv's Python, `-m door.mcp_server`. */
export function resolveSpawn(repoRoot: string, env: Env, platform: string = process.platform): SpawnSpec {
  const path = platform === 'win32' ? win32 : posix
  const python =
    env.DOOR_PYTHON ||
    (platform === 'win32'
      ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
      : path.join(repoRoot, '.venv', 'bin', 'python'))
  // The SDK merges only a short safe list from the parent; everything else is named here.
  // DOOR_PATHS_FROM_DIALOGS: every local path this app hands the server comes from a dialog the main
  // process ran (ipc.ts PATH_ARGS), so the server's data-folder check (path_scope.py) is not needed.
  const child: Record<string, string> = { PYTHONPATH: path.join(repoRoot, 'src'), DOOR_PATHS_FROM_DIALOGS: '1' }
  // CLAUDE_CONFIG_DIR picks which plan claude is signed in to (an isolated one in the onboarding sandbox).
  // PATH too when given, so a test can put a stand-in claude first (the SDK would pass the parent's).
  for (const key of ['DOOR_HOME', 'HOME', 'XDG_CONFIG_HOME', 'APPDATA', 'PATH', 'CLAUDE_CONFIG_DIR'] as const) {
    const value = env[key]
    if (value) child[key] = value
  }
  return { command: python, args: ['-m', 'door.mcp_server'], cwd: repoRoot, env: child }
}

/** The app's one id: the macOS bundle id, the Windows AppUserModelID, electron-builder's appId. */
export const APP_ID = 'dev.door.app'

/**
 * How a packaged app starts the server: the bundled Python (python-build-standalone, its packages
 * installed into it) on the bundled `src/`, from `<resources>/door` (where `.claude/agents` and
 * `profile.example` sit beside `src`, as in a checkout). Nothing is written inside the app: the data
 * is `home` (the user's data folder, or DOOR_HOME), Python writes no bytecode and reads no user
 * site-packages. PATH starts with the bundled Tectonic, then where claude's own installer puts it.
 */
export function resolvePackagedSpawn(opts: { resourcesPath: string; home: string; platform: string; env: Env }): SpawnSpec {
  const { resourcesPath, home, platform, env } = opts
  const path = platform === 'win32' ? win32 : posix
  const inside = path.resolve(resourcesPath)
  const rel = path.relative(inside, path.resolve(home))
  if (rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel))) throw new Error(`the data folder ${home} is inside the app`)
  const python = platform === 'win32' ? path.join(resourcesPath, 'python', 'python.exe') : path.join(resourcesPath, 'python', 'bin', 'python3')
  const bin = path.join(resourcesPath, 'bin')
  const userHome = (platform === 'win32' ? env.USERPROFILE : env.HOME) ?? ''
  const pathSep = platform === 'win32' ? ';' : ':'
  const child: Record<string, string> = {
    PYTHONPATH: path.join(resourcesPath, 'door', 'src'),
    DOOR_HOME: home,
    DOOR_BIN: bin,
    // the phone app's build (issue 444), which `door serve` serves when the phone is set up
    DOOR_WEB_DIR: path.join(resourcesPath, 'web'),
    PYTHONNOUSERSITE: '1',
    PYTHONDONTWRITEBYTECODE: '1',
    DOOR_PATHS_FROM_DIALOGS: '1',  // the paths it is handed come from the main process's dialogs
    PATH: [bin, ...(userHome ? [path.join(userHome, '.local', 'bin')] : []), ...(env.PATH ? [env.PATH] : [])].join(pathSep),
  }
  for (const key of ['HOME', 'USERPROFILE', 'XDG_CONFIG_HOME', 'APPDATA', 'LOCALAPPDATA', 'CLAUDE_CONFIG_DIR'] as const) {
    const value = env[key]
    if (value) child[key] = value
  }
  // What Windows needs to run a program the server starts, an npm-installed claude.cmd above all (#18): the
  // command interpreter, the extensions a bare name may have, the system folder and a temp folder. Windows
  // names are any case, so each is kept under the name it has.
  if (platform === 'win32') {
    const wanted = new Set(['COMSPEC', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'])
    for (const [key, value] of Object.entries(env)) if (value && wanted.has(key.toUpperCase())) child[key] = value
  }
  return { command: python, args: ['-s', '-m', 'door.mcp_server'], cwd: path.join(resourcesPath, 'door'), env: child }
}

const STDERR_KEEP = 8192

interface Connection {
  client: Client
  transport: StdioClientTransport
}

export class DoorServer {
  private conn: Connection | null = null
  private connecting: Promise<Connection> | null = null
  private stderr = ''
  private readonly stoppedConns = new WeakSet<Connection>()

  constructor(
    private readonly spec: SpawnSpec,
    private readonly options: ServerOptions = {},
  ) {}

  /** The child's process id while it is running. */
  get pid(): number | null {
    return this.conn?.transport.pid ?? null
  }

  /** The last of the child's stderr, for a message when it will not start. */
  stderrTail(): string {
    return this.stderr
  }

  async call<T = unknown>(tool: string, args: Record<string, unknown> = {}, options: CallOptions = {}): Promise<T> {
    const conn = await this.connection()
    let result
    try {
      const onProgress = options.onProgress
      result = await conn.client.callTool({ name: tool, arguments: args }, undefined, {
        timeout: options.timeout ?? 60_000,
        ...(onProgress
          ? {
              onprogress: (p: { progress: number; total?: number; message?: string }) =>
                onProgress({
                  progress: p.progress,
                  ...(p.total !== undefined ? { total: p.total } : {}),
                  message: p.message ?? '',
                }),
              resetTimeoutOnProgress: true,
            }
          : {}),
      })
    } catch (e) {
      throw this.translate(e, conn, tool, options.timeout ?? 60_000)
    }
    const block = Array.isArray(result.content) ? result.content[0] : undefined
    const text = block && block.type === 'text' ? String(block.text) : ''
    if (result.isError) throw new DoorError(text || `${tool} failed`)
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      throw new DoorError(`${tool} returned something that is not JSON`)
    }
    if (parsed && typeof parsed === 'object' && typeof (parsed as { error?: unknown }).error === 'string') {
      const { error, candidates, conflict } = parsed as { error: string; candidates?: Candidate[]; conflict?: unknown }
      const e = new DoorError(error, candidates)
      if (conflict === true) e.conflict = true
      throw e
    }
    return parsed as T
  }

  async listTools(): Promise<ToolInfo[]> {
    const conn = await this.connection()
    try {
      const { tools } = await conn.client.listTools()
      return tools.map((t) => ({ name: t.name, description: t.description ?? '', inputSchema: t.inputSchema }))
    } catch (e) {
      throw this.translate(e, conn)
    }
  }

  async close(): Promise<void> {
    const conn = this.conn
    this.conn = null
    if (conn) await conn.client.close().catch(() => undefined)
  }

  /**
   * Ends the child now (a run the user stopped): the calls in flight reject with a DoorError
   * whose `stopped` is true, and the next call starts a new child.
   */
  async stop(): Promise<void> {
    const conn = this.conn
    if (conn) this.stoppedConns.add(conn)
    await this.close()
  }

  /** The end of the child's stderr, its lines joined, for one line of the problem log. */
  private stderrLines(n: number): string {
    return this.stderr.trim().split('\n').slice(-n).join(' | ')
  }

  private problem(where: string, message: string): void {
    try {
      this.options.onProblem?.(where, message)
    } catch {
      // the log is a courtesy: never the reason a call fails
    }
  }

  private translate(e: unknown, conn: Connection, tool?: string, timeout?: number): DoorError {
    if (e instanceof DoorError) return e
    if (this.stoppedConns.has(conn)) {
      const stopped = new DoorError('stopped')
      stopped.stopped = true
      return stopped
    }
    if (e instanceof McpError && e.code === ErrorCode.ConnectionClosed) {
      this.drop(conn)
      this.problem('server stopped', this.stderrLines(20) || 'no output')
      return new DoorError("The other door's server stopped; try again")
    }
    if (e instanceof McpError && e.code === ErrorCode.RequestTimeout) {
      if (tool) this.problem(`${tool} timed out`, `no answer in ${(timeout ?? 0) / 1000} s`)
      const slow = new DoorError('The other door took too long to answer')
      slow.timedOut = true
      return slow
    }
    return new DoorError(e instanceof Error ? e.message : String(e))
  }

  private drop(conn: Connection) {
    if (this.conn === conn) this.conn = null
  }

  private connection(): Promise<Connection> {
    if (this.conn) return Promise.resolve(this.conn)
    if (!this.connecting) {
      this.connecting = this.connect().finally(() => {
        this.connecting = null
      })
    }
    return this.connecting
  }

  private async connect(): Promise<Connection> {
    const transport = new StdioClientTransport({
      command: this.spec.command,
      args: this.spec.args,
      cwd: this.spec.cwd,
      env: this.spec.env,
      stderr: 'pipe',
    })
    const client = new Client({ name: 'door-app', version: '0.0.0' })
    const conn = { client, transport }
    this.stderr = ''
    transport.stderr?.on('data', (chunk: Buffer) => {
      this.stderr = (this.stderr + chunk.toString()).slice(-STDERR_KEEP)
    })
    client.onclose = () => this.drop(conn)
    client.onerror = () => undefined
    try {
      await client.connect(transport, { timeout: this.options.startupTimeoutMs ?? 30_000 })
    } catch (e) {
      await client.close().catch(() => undefined)
      const detail = this.stderr.trim().split('\n').slice(-3).join(' ')
      const why = e instanceof Error ? e.message : String(e)
      this.problem('server would not start', `${why}${this.stderr.trim() ? ` | ${this.stderrLines(20)}` : ''}`)
      throw new DoorError(`could not start the door server: ${why}${detail ? ` (${detail})` : ''}`)
    }
    const theirs = client.getServerVersion()?.version
    if (this.options.expectedVersion && theirs !== this.options.expectedVersion) {
      await client.close().catch(() => undefined)
      throw new DoorError(`This app is version ${this.options.expectedVersion}, but the door inside it is ${theirs ?? 'unknown'}. Install the app again.`)
    }
    this.conn = conn
    return conn
  }
}
