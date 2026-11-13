// The test world of the journeys (app/journeys/): a temp door home made from a persona and the
// ad corpus, and the world.json the server's edges answer from (boot.py, claude.py, tectonic.py).
// Nothing here starts a process except the one-off compile of prepared applications; the caller
// hands `env` to Electron, which starts the real server through the DOOR_PYTHON wrapper.
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { appendFileSync, chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { ADS, type Ad } from './data/ads'
import { PERSONAS, type Persona } from './data/personas'
import { coverLetterTex, cvTex } from './tailor'

export const repoRoot = resolve(__dirname, '..', '..', '..')
const HERE = __dirname

/** The world's "now": the server's clock starts here (boot.py) and the window's too (fixtures.ts). */
export const NOW = '2026-10-26T09:00:00.000Z'
const NOW_MS = Date.parse(NOW)
const DAY = 86_400_000
const iso = (ms: number) => new Date(ms).toISOString()

export type Status =
  | 'prepared'
  | 'applied'
  | 'interview:screening'
  | 'interview:technical'
  | 'offer'
  | 'rejected'
  | 'ghosted'
  | 'discarded'

/** One job's place in the application ledger: its status, how it was sent, and the path it took there. */
export interface LedgerEntry {
  status: Status
  /** Earlier statuses, oldest first, each `days` before now; the last status is `status` itself. */
  history?: { status: string; daysAgo: number; notes?: string }[]
  notes?: string
  /** Prepared materials on disk (a prepared or sent job). */
  materials?: boolean
}

export interface WorldOptions {
  persona?: string
  /** A first launch: no profile/, no jobs/. */
  empty?: boolean
  /** Whether the stand-in claude is signed in (default true). */
  signedIn?: boolean
  /** Extra keys for profile/config.json. */
  config?: Record<string, unknown>
  /** Google Drive: configured in this build (default true), and connected as the persona's account. */
  drive?: { configured?: boolean; connected?: boolean }
  /** Leave profile/cv.md out. */
  noCv?: boolean
  /** No `claude` on the server's PATH (or in ~/.local/bin): doctor says it is missing. `world.installClaude()` puts it there. */
  noClaude?: boolean
  /** The Python that runs the world's scripts: a path (default: the checkout's, or DOOR_PYTHON), or `bundled`,
   * the installed app's own, found from the DOOR_BIN its server is given (the install test, e2e-install/). */
  python?: string
  /** The stand-in `tectonic` on PATH (default true). The install test leaves it out: the app's own compiles. */
  tectonic?: boolean
}

/** The ledger most journeys start from: a job in every column of the Applications board. */
export const FULL_LEDGER: Record<string, LedgerEntry> = {
  'kronvej-ml-engineer-mlops': { status: 'prepared', materials: true },
  'sundline-network-optimisation': {
    status: 'applied',
    materials: true,
    history: [{ status: 'prepared', daysAgo: 4 }],
  },
  'pakkepost-causal-experimentation': {
    status: 'interview:technical',
    history: [
      { status: 'applied', daysAgo: 16 },
      { status: 'interview:screening', daysAgo: 9, notes: 'Thirty minutes with the recruiter; went well.' },
    ],
  },
  'torvehal-demand-forecasting': {
    status: 'offer',
    history: [
      { status: 'applied', daysAgo: 28 },
      { status: 'interview:screening', daysAgo: 21 },
      { status: 'interview:technical', daysAgo: 12, notes: 'Case on promotion forecasting.' },
    ],
  },
  'lindegaard-bio-clinical-analytics': {
    status: 'rejected',
    notes: 'They went with someone with clinical-trial experience.',
    history: [
      { status: 'applied', daysAgo: 20 },
      { status: 'interview:screening', daysAgo: 13 },
    ],
  },
  'engvang-supply-chain-ds': { status: 'ghosted', history: [{ status: 'applied', daysAgo: 35 }] },
  'kystbanken-quant-analyst': { status: 'discarded', notes: 'Market risk is too far from forecasting.' },
}

const SENT = new Set(['applied', 'interview:screening', 'interview:technical', 'offer', 'rejected', 'ghosted'])

export interface Call {
  kind: 'tool' | 'claude' | 'http'
  tool?: string
  call?: string
  args?: Record<string, unknown>
  url?: string
  at: number
}

export interface World {
  scratch: string
  home: string
  dir: string
  env: Record<string, string>
  python: string
  hasPython: boolean
  persona: Persona
  /** The ads of this persona, by key. */
  ads: Record<string, Ad>
  /** An ad's job id (`<site>.<platform_id>`). */
  jobId(key: string): string
  /** Make the next calls fail or wait: tools by name (`{"error": ...}`, `delay_s`, `crash`, `once`), claude calls by kind, drive steps. */
  faults(f: Faults): void
  clearFaults(): void
  calls(): Call[]
  toolCalls(tool: string): Call[]
  claudeCalls(kind: string): Call[]
  readJson<T = any>(relative: string): T
  exists(relative: string): boolean
  /** Puts the stand-in `claude` on the PATH of a `noClaude` world, as installing it by hand would. */
  installClaude(): void
}

export interface Faults {
  tools?: Record<string, { error?: string; delay_s?: number; crash?: boolean; once?: boolean }>
  claude?: Record<string, { fail?: string; delay_s?: number; answer?: unknown; cv?: string; cover_letter?: string; stay_signed_out?: boolean }>
  drive?: { upload?: string }
  phone?: { start?: unknown }
}

const platformId = (ad: Ad) => ad.key
export const jobIdOf = (ad: Ad) => `${ad.site}.${platformId(ad)}`

function postingJson(ad: Ad, persona: Persona) {
  const posted = NOW_MS - ad.postedDaysAgo * DAY - 3 * 3_600_000
  return {
    id: jobIdOf(ad),
    title: ad.title,
    company: ad.company,
    location: ad.location,
    url: `https://${ad.site === 'manual' ? 'jobs' : ad.site}.example/${ad.key}`,
    description: ad.description,
    source: ad.site,
    platform_id: platformId(ad),
    posted_at: iso(posted),
    scraped_at: iso(posted + 2 * 3_600_000),
    apply_type: 'external',
    ...(ad.applyUrl ? { apply_url: ad.applyUrl } : {}),
    ...(ad.titleEn ? { title_en: ad.titleEn } : {}),
    language: ad.language,
    ...(ad.score === null
      ? {}
      : {
          score: ad.score,
          score_reason: ad.reason,
          matching_skills: ad.matching,
          missing_skills: ad.missing,
          scored_by: 'claude-haiku-4-5',
          scored_at: iso(posted + 2.5 * 3_600_000),
          language_requirement: ad.language === 'da' && !persona.languages.includes('Danish') ? 'required' : 'none',
        }),
  }
}

function python(): string {
  return process.env.DOOR_PYTHON || join(repoRoot, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
}

function script(path: string, lines: string[]): void {
  writeFileSync(path, lines.join('\n') + '\n')
  chmodSync(path, 0o755)
}

/** A program in the world's bin/ that runs one world script with `py`: a shell script; on Windows a `<name>.exe` launcher (a `.cmd` without arguments, or without a C# compiler). */
/** A program's own command line, passed on untouched to `<exe> "<file>" "<world>"` (a Windows launcher's C#). */
function launcherSource(exe: string, file: string, worldDir: string): string {
  const lit = (v: string) => JSON.stringify(v)   // a JSON string is a valid C# string literal for these paths
  return `using System; using System.Diagnostics;
class Launcher {
  static int Main() {
    try { return Run(); } catch (Exception e) { Console.Error.WriteLine("launcher: " + e.Message); return 1; }
  }
  static int Run() {
    string raw = Environment.CommandLine;
    int at = raw.StartsWith("\\"") ? raw.IndexOf('"', 1) + 1 : raw.IndexOf(' ');
    string rest = at < 0 || at >= raw.Length ? "" : raw.Substring(at);
    string prefix = "\\"" + ${lit(file)} + "\\" \\"" + ${lit(worldDir)} + "\\"";
    var info = new ProcessStartInfo(Environment.ExpandEnvironmentVariables(${lit(exe)}), prefix + rest) { UseShellExecute = false };
    var child = Process.Start(info);
    child.WaitForExit();
    return child.ExitCode;
  }
}
`
}

/** Windows' own C# compiler (.NET Framework, on every Windows 10 and 11), or null. */
function csc(): string | null {
  const path = join(process.env.SystemRoot ?? 'C:\\Windows', 'Microsoft.NET', 'Framework64', 'v4.0.30319', 'csc.exe')
  return existsSync(path) ? path : null
}

function wrapper(bin: string, name: string, py: string, file: string, worldDir: string, passArgs: boolean): string {
  if (process.platform === 'win32') {
    const exe = py === BUNDLED ? '%DOOR_BIN%\\..\\python\\python.exe' : py
    // A program that takes arguments is a real .exe, as the real claude and tectonic are: a .cmd's arguments go
    // through cmd.exe, which mangles quotes (a --json-schema), so the stand-in would not see what door sent.
    const compiler = passArgs ? csc() : null
    if (compiler) {
      const source = join(bin, `${name}.cs`)
      const path = join(bin, `${name}.exe`)
      writeFileSync(source, launcherSource(exe, file, worldDir))
      execFileSync(compiler, ['/nologo', `/out:${path}`, source], { stdio: 'pipe' })
      return path
    }
    const path = join(bin, `${name}.cmd`)
    writeFileSync(path, `@"${exe}" "${file}" "${worldDir}"${passArgs ? ' %*' : ''}\r\n`)
    return path
  }
  const path = join(bin, name)
  const exe = py === BUNDLED ? '$DOOR_BIN/../python/bin/python3' : py
  script(path, ['#!/bin/sh', `exec "${exe}" "${file}" "${worldDir}"${passArgs ? ' "$@"' : ''}`])
  return path
}

/** `python: 'bundled'`: the world's scripts run on the installed app's own Python. */
export const BUNDLED = 'bundled'

/** The PATH of the world: its own bin/ first, then only the system's own folders (no Python, Node or TeX of the machine's). */
export function worldPath(bin: string, platform: string = process.platform, systemRoot = process.env.SystemRoot ?? 'C:\\Windows'): string {
  return platform === 'win32' ? [bin, `${systemRoot}\\System32`, systemRoot].join(';') : [bin, '/usr/bin', '/bin'].join(':')
}

/** A job board's or feed's posting as boot.py hands it to door (no score: the run scores it). */
function freshPosting(ad: Ad) {
  const { score, score_reason, matching_skills, missing_skills, scored_by, scored_at, language_requirement, scraped_at, posted_at, ...rest } =
    postingJson(ad, PERSONAS[ad.persona]) as Record<string, unknown>
  return { ...rest, posted_at: iso(NOW_MS - 3 * 3_600_000) }
}

function companiesJson(ads: Ad[]) {
  const followed = new Map<string, Ad>()
  for (const ad of ads) if ((ad.site === 'greenhouse' || ad.site === 'lever') && !followed.has(ad.company)) followed.set(ad.company, ad)
  return {
    version: 1,
    companies: [...followed.values()].map((ad) => ({
      name: ad.company,
      feed: { platform: ad.site, id: slug(ad.company) },
      aliases: [],
      status: 'followed',
      reason: null,
      found_via: 'linkedin',
      evidence: `${ad.site} board ${slug(ad.company)} lists open jobs`,
      first_seen: iso(NOW_MS - 40 * DAY),
      last_checked: iso(NOW_MS - DAY),
      last_relevant: iso(NOW_MS - 2 * DAY),
    })),
  }
}

const slug = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')

function worldJson(persona: Persona, ads: Ad[], options: WorldOptions) {
  const scores: Record<string, unknown> = {}
  const titlesEn: Record<string, string> = {}
  for (const ad of ADS) {
    if (ad.score !== null) {
      scores[`${ad.title}|${ad.company}`] = {
        score: ad.score,
        score_reason: ad.reason,
        matching_skills: ad.matching,
        missing_skills: ad.missing,
        language_requirement: 'none',
      }
    }
    if (ad.titleEn) titlesEn[ad.title] = ad.titleEn
  }
  const fresh = ads.filter((a) => a.fresh)
  const boards: Record<string, { postings: unknown[] }> = {}
  const feeds: Record<string, { platform: string; entry: string; postings: unknown[] }> = {}
  for (const ad of ads.filter((a) => a.site === 'greenhouse' || a.site === 'lever')) {
    feeds[ad.company] ??= { platform: ad.site, entry: slug(ad.company), postings: [] }
  }
  for (const ad of fresh) {
    if (ad.site === 'greenhouse' || ad.site === 'lever') feeds[ad.company].postings.push(freshPosting(ad))
    else if (ad.site !== 'manual') (boards[ad.site] ??= { postings: [] }).postings.push(freshPosting(ad))
  }
  for (const site of new Set(ads.filter((a) => !['greenhouse', 'lever', 'manual'].includes(a.site)).map((a) => a.site))) boards[site] ??= { postings: [] }
  // Pages the user can paste a link to ("Add a job"): each manual ad on its employer's site.
  const internet: Record<string, unknown> = {}
  const readAds: unknown[] = []
  for (const ad of ads.filter((a) => a.site === 'manual')) {
    internet[`https://careers.${slug(ad.company)}.example/jobs/${ad.key}`] = {
      body: `<html><head><title>${ad.title} – ${ad.company}</title></head><body><h1>${ad.title}</h1><p>${ad.company} · ${ad.location}</p>${ad.description
        .split('\n\n')
        .map((p) => `<p>${p}</p>`)
        .join('')}</body></html>`,
    }
    readAds.push({ title: ad.title, company: ad.company, location: ad.location })
  }
  return {
    now: NOW,
    persona: { key: persona.key, name: persona.name, email: persona.email },
    boards,
    feeds,
    internet,
    read_ads: readAds,
    scores,
    titles_en: titlesEn,
    tailor: { cv: cvTex(persona), cover_letter: coverLetterTex(persona) },
    answers: answersFor(persona),
    drive: { configured: options.drive?.configured ?? true, account: persona.email },
  }
}

/** What the stand-in claude says to the onboarding and CV calls, from the persona. */
export function answersFor(persona: Persona) {
  return {
    draft: {
      cv_markdown: persona.cv,
      provenance: [{ source: 'the CV you added', contributed: 'work history, education and skills' }],
      todos: [...persona.cv.matchAll(/TODO[^\n]*/g)].map((m) => m[0]),
    },
    basics: {
      name: persona.name,
      email: persona.email,
      city: /\*\*Location:\*\*/.test(persona.cv) ? persona.city : null,
      languages: persona.languages.map((language, i) => ({ language, level: i === 0 ? 'native' : 'fluent' })),
    },
    titles: {
      titles: [
        ...persona.roleTargets.map((title, i) => ({ title, reason: i === 0 ? 'your latest title' : 'close to your experience', recommended: i < 2 })),
      ],
    },
    keywords: { keywords: persona.searchKeywords, topic_terms: persona.topicTerms },
    // onboarding's example story, complete so a review saves as it is (a journey leaves a part empty with a fault)
    stories: {
      stories: [
        {
          title: `Built the forecasting models at ${persona.name.split(' ')[0]}'s last team`,
          context: 'The team planned with spreadsheets and missed the peaks.',
          action: 'Built and ran the forecasting models in Python.',
          result: 'The planners used them every week.',
          learning: 'Planners trust a forecast they can check against last week.',
          missing: [],
          conflicts: [],
        },
      ],
    },
    enrich: {
      proposals: [
        { section: 'Skills', text: 'Bayesian hierarchical models (PyMC)', source: 'https://github.example/mkl' },
        { section: 'Work Experience', text: 'Gave a talk on probabilistic load forecasting at PyData Copenhagen 2024.', source: 'https://mkl.example/talks' },
      ],
      unreachable: [],
    },
    gaps:
      '# Skill-gap report\n\n## Where you stand\n\nYour forecasting and causal-inference work covers most of what these roles ask for.\n\n## Gaps\n\n1. **Kubernetes** — asked for by three of the five ads.\n2. **dbt** — the analytics-engineering roles expect it.\n\n## Plan\n\n- Week 1–2: the official Kubernetes basics course, then deploy one of your models.\n- Week 3: build a small dbt project on a public dataset.\n',
    ask: { answer: 'Three of your matches are with energy companies, and the strongest is the forecasting role.', sources: [] },
  }
}

const dirsOf = (scratch: string) => ({ home: join(scratch, 'home'), world: join(scratch, 'world'), bin: join(scratch, 'bin'), userHome: join(scratch, 'userhome') })

/** Builds a world in a fresh temp folder. */
export function buildWorld(options: WorldOptions = {}): World {
  const persona = PERSONAS[options.persona ?? 'mette']
  if (!persona) throw new Error(`no persona ${options.persona}`)
  const ads = ADS.filter((a) => a.persona === persona.key)
  const scratch = mkdtempSync(join(tmpdir(), 'door-world-'))
  const { home, world: worldDir, bin, userHome } = dirsOf(scratch)
  // a user folder as Windows lays it out: its known folders (Downloads, AppData) resolve only when they exist
  const roaming = join(userHome, 'AppData', 'Roaming')
  const local = join(userHome, 'AppData', 'Local')
  for (const d of [home, worldDir, bin, userHome, roaming, local, join(userHome, 'Downloads')]) mkdirSync(d, { recursive: true })
  const py = options.python ?? python()
  if (py === BUNDLED && !options.empty) throw new Error('a world on the bundled Python starts empty: its materials are compiled with the checkout\'s')

  writeFileSync(join(worldDir, 'world.json'), JSON.stringify(worldJson(persona, ads, options), null, 2))
  writeFileSync(join(worldDir, 'faults.json'), '{}')
  writeFileSync(join(worldDir, 'calls.jsonl'), '')
  if (options.signedIn ?? true) writeFileSync(join(worldDir, 'claude-signed-in'), '')

  // The server and its two outside programs, each a wrapper around a world script.
  const doorPython = wrapper(bin, 'door-python', py, join(HERE, 'boot.py'), worldDir, false)
  const installClaude = () => void wrapper(bin, 'claude', py, join(HERE, 'claude.py'), worldDir, true)
  if (!options.noClaude) installClaude()
  if (options.tectonic ?? true) wrapper(bin, 'tectonic', py, join(HERE, 'tectonic.py'), worldDir, true)

  const env: Record<string, string> = {
    DOOR_PYTHON: doorPython,
    DOOR_HOME: home,
    HOME: userHome,
    USERPROFILE: userHome,
    XDG_CONFIG_HOME: join(userHome, '.config'),
    APPDATA: roaming,
    LOCALAPPDATA: local,
    PATH: worldPath(bin),
    LANG: 'en_US.UTF-8',
    TZ: 'Europe/Copenhagen',
  }

  if (!options.empty) writeHome(home, persona, ads, options)
  if (!options.empty && options.drive?.connected) connectDrive(worldDir, persona)
  if (!options.empty) prepareMaterials({ home, py, env, ads, persona, ledger: persona.key === 'mette' ? FULL_LEDGER : {} })

  const read = <T>(rel: string): T => JSON.parse(readFileSync(join(home, rel), 'utf8'))
  const calls = (): Call[] =>
    readFileSync(join(worldDir, 'calls.jsonl'), 'utf8')
      .split('\n')
      .filter(Boolean)
      .map((l) => JSON.parse(l))
  const byKey = Object.fromEntries(ads.map((a) => [a.key, a]))
  return {
    scratch,
    home,
    dir: worldDir,
    env,
    python: py,
    hasPython: py === BUNDLED || existsSync(py),
    persona,
    ads: byKey,
    jobId: (key) => {
      const ad = byKey[key]
      if (!ad) throw new Error(`no ad ${key} for ${persona.key}`)
      return jobIdOf(ad)
    },
    faults: (f) => writeFileSync(join(worldDir, 'faults.json'), JSON.stringify(f)),
    clearFaults: () => writeFileSync(join(worldDir, 'faults.json'), '{}'),
    calls,
    toolCalls: (tool) => calls().filter((c) => c.kind === 'tool' && c.tool === tool),
    claudeCalls: (kind) => calls().filter((c) => c.kind === 'claude' && c.call === kind),
    readJson: read,
    exists: (rel) => existsSync(join(home, rel)),
    installClaude,
  }
}

function writeHome(home: string, persona: Persona, ads: Ad[], options: WorldOptions) {
  const profile = join(home, 'profile')
  mkdirSync(profile, { recursive: true })
  for (const f of ['cv.template.tex', 'cover-letter.template.tex']) copyFileSync(join(repoRoot, 'profile.example', f), join(profile, f))
  writeFileSync(
    join(profile, 'config.json'),
    JSON.stringify(
      {
        name: persona.name,
        email: persona.email,
        location: persona.city,
        cv_template: 'profile/cv.template.tex',
        cv_content: 'profile/cv.md',
        cover_letter_template: 'profile/cover-letter.template.tex',
        role_targets: persona.roleTargets,
        search_keywords: persona.searchKeywords,
        topic_terms: persona.topicTerms,
        remote: 'hybrid',
        exclude: { companies: [], keywords: ['internship', 'unpaid'] },
        min_score: 0.65,
        max_age_days: null,
        languages: persona.languages,
        enrich_sources: [],
        linkedin_discovery: false,
        ...options.config,
      },
      null,
      2,
    ),
  )
  if (!options.noCv) writeFileSync(join(profile, 'cv.md'), persona.cv)
  writeFileSync(join(profile, 'story_bank.md'), persona.storyBank)
  writeFileSync(join(profile, 'companies.json'), JSON.stringify(companiesJson(ads), null, 2))

  const jobs = join(home, 'jobs')
  mkdirSync(jobs, { recursive: true })
  for (const ad of ads.filter((a) => !a.fresh && a.site !== 'manual')) {
    const p = postingJson(ad, persona)
    const dir = join(jobs, 'postings', p.scraped_at.slice(0, 10), ad.site)
    mkdirSync(dir, { recursive: true })
    writeFileSync(join(dir, `${p.id}.json`), JSON.stringify(p, null, 2))
  }
  // Reviewed four and a half days ago: the two ads scraped since are new.
  writeFileSync(join(jobs, 'last_review.json'), JSON.stringify({ reviewed_at: iso(NOW_MS - 4.5 * DAY), seen: [] }))
  writePastRun(jobs)
}

function writePastRun(jobs: string) {
  const runs = join(jobs, 'runs')
  mkdirSync(runs, { recursive: true })
  const started = NOW_MS - 20 * 3_600_000
  const stamp = iso(started).replace(/[:.]/g, '-')
  const record = {
    started_at: iso(started),
    finished_at: iso(started + 41 * 60_000),
    elapsed_s: 41 * 60,
    steps: ['search', 'follow', 'collect', 'match'],
    skipped: { discover: 'linkedin_discovery not chosen' },
    search: { sites: [{ site: 'jobindex', outcome: 'ok', count: 14 }], summary: 'search: 14 new postings' },
    discover: null,
    follow: { summary: 'follow: nothing new to follow' },
    collect: { sites: [{ site: 'greenhouse', outcome: 'ok', count: 3 }], summary: 'collect: 3 new postings' },
    match: { failed: [], summary: 'match: scored 17' },
    new_above_threshold: [],
    top: [],
    failures: [],
  }
  writeFileSync(join(runs, `${stamp}.json`), JSON.stringify(record, null, 2))
  appendFileSync(join(runs, 'latest.log'), `${record.finished_at} search 14, collect 3, scored 17\n`)
}

function connectDrive(worldDir: string, persona: Persona) {
  const config = join(worldDir, 'config')
  mkdirSync(config, { recursive: true })
  writeFileSync(join(config, 'drive.json'), JSON.stringify({ refresh_token: 'world', access_token: 'world', expires_at: NOW_MS / 1000 + 3600, account: persona.email }))
}

/** The ledger, and the output folder of every job in it with materials: tailored .tex compiled by door's own compile. */
function prepareMaterials(opts: { home: string; py: string; env: Record<string, string>; ads: Ad[]; persona: Persona; ledger: Record<string, LedgerEntry> }) {
  const { home, py, env, ads, persona, ledger } = opts
  const entries = Object.entries(ledger)
  if (entries.length === 0) return
  const jobs = join(home, 'jobs')
  const book: Record<string, unknown> = {}
  for (const [key, e] of entries) {
    const ad = ads.find((a) => a.key === key)
    if (!ad) throw new Error(`ledger names ${key}, not an ad of ${persona.key}`)
    const id = jobIdOf(ad)
    const steps = [...(e.history ?? []), { status: e.status, daysAgo: e.history?.length ? 0.5 : 1, notes: e.notes }]
    const history = steps.map((s) => ({ status: s.status, at: iso(NOW_MS - s.daysAgo * DAY), ...(s.notes ? { notes: s.notes } : {}) }))
    book[id] = {
      status: e.status,
      updated_at: history[history.length - 1].at,
      ...(e.notes ? { notes: e.notes } : {}),
      history,
    }
    if (e.materials) {
      const out = join(jobs, 'output', id)
      mkdirSync(out, { recursive: true })
      writeFileSync(join(out, 'posting.json'), JSON.stringify(postingJson(ad, persona), null, 2))
      writeFileSync(join(out, 'cv.tex'), cvTex(persona))
      writeFileSync(join(out, 'cover_letter.tex'), coverLetterTex(persona))
      execFileSync(py, ['-c', 'import sys; from door.commands import compile as c; c._compile_core(sys.argv[1], render=True)', id], {
        env: { ...env, PYTHONPATH: join(repoRoot, 'src') },
        stdio: 'pipe',
      })
      if (SENT.has(e.status)) {
        // What set_status does on the first sent status: a copy in sent/ and the hash of each file.
        const sent = join(out, 'sent')
        mkdirSync(sent, { recursive: true })
        const hashes: Record<string, string> = {}
        for (const name of readdirSync(out).filter((n) => n !== 'sent')) {
          copyFileSync(join(out, name), join(sent, name))
          if (['posting.json', 'cv.tex', 'cover_letter.tex', 'cv.pdf', 'cover_letter.pdf'].includes(name))
            hashes[name] = createHash('sha256').update(readFileSync(join(out, name))).digest('hex')
        }
        ;(book[id] as Record<string, unknown>).materials = hashes
      }
    }
  }
  writeFileSync(join(jobs, 'applications.json'), JSON.stringify(book, null, 2))
}
