// A throwaway door home for the tests that run the real Python server: two
// scored postings (one of them optionally already prepared) under jobs/postings/<today>/jobindex/, and an isolated user
// home so nothing outside the temp folder is read or written. No process is
// started here; the caller hands `env` to the server or to Electron.
import { appendFileSync, chmodSync, cpSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { delimiter, join, resolve } from 'node:path'

export const repoRoot = resolve(__dirname, '..', '..')

export interface Home {
  scratch: string
  home: string
  env: Record<string, string>
  python: string
  hasPython: boolean
}

function posting(id: string, extra: Record<string, unknown>) {
  const now = new Date().toISOString()
  return {
    id,
    title: 'Data Analyst',
    company: 'Acme',
    location: 'Copenhagen',
    url: `https://example.com/${id}`,
    description: 'Analyse things.',
    posted_at: now,
    scraped_at: now,
    source: 'jobindex',
    ...extra,
  }
}

const PREPARED = join(__dirname, 'fixtures', 'prepared')

/** A finished prepare for `jobId`: the output folder (2-page CV, 1-page letter, their page images and .tex) and a `prepared` ledger entry. */
function preparePrepared(home: string, jobId: string, row: unknown): void {
  const out = join(home, 'jobs', 'output', jobId)
  mkdirSync(out, { recursive: true })
  for (const name of readdirSync(PREPARED)) copyFileSync(join(PREPARED, name), join(out, name))
  writeFileSync(join(out, 'posting.json'), JSON.stringify(row))
  const at = new Date().toISOString()
  writeFileSync(
    join(home, 'jobs', 'applications.json'),
    JSON.stringify({ [jobId]: { status: 'prepared', updated_at: at, history: [{ status: 'prepared', at }] } }),
  )
}

/** Words of each onboarding call's system prompt, and the file its answer is in. */
const ANSWERED = [
  ["You draft a job seeker's CV", 'draft.json'],
  ["You read a job seeker's CV", 'basics.json'],
  ['You suggest the job titles', 'titles.json'],
  ['You propose search terms', 'keywords.json'],
]

/** Scripts the stand-in claude's onboarding answers: `draft` is the CV it writes, and `city` what it reads there. */
export function answerOnboarding(scratch: string, draft: string, city: string | null): void {
  const dir = join(scratch, 'claude-answers')
  mkdirSync(dir, { recursive: true })
  const envelope = (answer: unknown) => JSON.stringify({ result: JSON.stringify(answer) })
  writeFileSync(join(dir, 'draft.json'), envelope({ cv_markdown: draft, provenance: [{ source: 'https://ada.dev', contributed: 'two projects' }], todos: ['phone number'] }))
  writeFileSync(join(dir, 'basics.json'), envelope({ name: null, email: null, city, languages: [{ language: 'English', level: 'native' }, { language: 'Danish', level: 'fluent' }] }))
  writeFileSync(join(dir, 'titles.json'), envelope({ titles: [{ title: 'Data Scientist', reason: 'your latest title', recommended: true }, { title: 'Quant', reason: 'your maths', recommended: false }] }))
  writeFileSync(join(dir, 'keywords.json'), envelope({ keywords: ['data scientist', 'ml engineer'], topic_terms: ['data'] }))
}

/**
 * A `claude` that only leaves a mark and fails, first on the server's PATH: a test that
 * reaches the tailor or a revise meets it, never the developer's real (signed-in) claude.
 * Signing in is scripted, as claude 2.1.310 printed it over pipes (thoughts/plan/221-pr3.md):
 * `auth login` prints its page and the paste prompt, and the code `stand-in-code#ok` signs in
 * (`claude-signed-in`, read by `auth status`; its arguments go to `claude-login-args`). Neither
 * is a model call, so neither leaves the mark. No browser, no network.
 * With a `claude-answers/` folder (`answerOnboarding`), each onboarding model call is answered from its file, by
 * the words its system prompt starts with; without it, every model call fails.
 */
function standInClaude(scratch: string): string {
  const bin = join(scratch, 'bin')
  mkdirSync(bin, { recursive: true })
  const mark = join(scratch, 'claude-was-called')
  const signedIn = join(scratch, 'claude-signed-in')
  const loginArgs = join(scratch, 'claude-login-args')
  const sh = [
    '#!/bin/sh',
    'if [ "$1" = auth ] && [ "$2" = status ]; then',
    `  if [ -f '${signedIn}' ]; then echo '{"loggedIn": true, "authMethod": "claude.ai", "email": "ada@example.com", "subscriptionType": "max"}'; exit 0; fi`,
    `  echo '{"loggedIn": false, "authMethod": "none"}'; exit 1`,
    'fi',
    'if [ "$1" = auth ] && [ "$2" = login ]; then',
    `  echo "$*" > '${loginArgs}'`,
    "  echo 'Opening browser to sign in…'",
    `  echo "If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true&state=stand-in"`,
    "  printf 'Paste code here if prompted > '",
    '  read code',
    `  if [ "$code" = 'stand-in-code#ok' ]; then touch '${signedIn}'; echo 'Login successful.'; exit 0; fi`,
    "  echo 'Login failed: Request failed with status code 400' >&2; exit 1",
    'fi',
    `if [ -d '${scratch}/claude-answers' ]; then`,
    '  case "$*" in',
    ...ANSWERED.map(([words, file]) => `    *"${words}"*) cat '${scratch}/claude-answers/${file}'; exit 0;;`),
    '  esac',
    'fi',
    `touch '${mark}'`,
    "echo 'tests never call the real claude' >&2",
    'exit 97',
    '',
  ].join('\n')
  writeFileSync(join(bin, 'claude'), sh)
  chmodSync(join(bin, 'claude'), 0o755)
  writeFileSync(join(bin, 'claude.cmd'), `@echo off\r\ntype nul > "${mark}"\r\necho tests never call the real claude 1>&2\r\nexit /b 97\r\n`)
  return bin
}

/** The scratch folder, an isolated user home, the stand-in claude and the environment that points the server at them. */
function scaffold(home: (scratch: string) => string): Home {
  const python =
    process.env.DOOR_PYTHON || join(repoRoot, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
  const scratch = mkdtempSync(join(tmpdir(), 'door-app-'))
  const homeDir = home(scratch)
  mkdirSync(homeDir, { recursive: true })
  const userHome = join(scratch, 'userhome')
  mkdirSync(userHome, { recursive: true })
  const bin = standInClaude(scratch)
  return {
    scratch,
    home: homeDir,
    python,
    hasPython: existsSync(python),
    env: {
      DOOR_PYTHON: python,
      DOOR_HOME: homeDir,
      HOME: userHome,
      XDG_CONFIG_HOME: join(userHome, '.config'),
      APPDATA: join(userHome, 'appdata'),
      PATH: [bin, process.env.PATH ?? ''].join(delimiter),
    },
  }
}

/** A home with nothing in it, as on a first launch: no profile/, no jobs/. */
export function buildEmptyHome(): Home {
  return scaffold((scratch) => join(scratch, 'home'))
}

export function buildHome(options: { prepared?: string } = {}): Home {
  const built = scaffold((scratch) => join(scratch, 'home'))
  const { home } = built
  // A profile that is the user's own, so the app opens on Matches and not on the first-launch wizard.
  cpSync(join(repoRoot, 'profile.example'), join(home, 'profile'), { recursive: true })
  appendFileSync(join(home, 'profile', 'cv.md'), '\nTest candidate.\n')
  const today = new Date().toISOString().slice(0, 10)
  const dir = join(home, 'jobs', 'postings', today, 'jobindex')
  mkdirSync(dir, { recursive: true })
  const rows = [
    posting('jobindex.123', { title: 'Dataanalytiker', title_en: 'Data Analyst', score: 0.91, score_reason: 'Strong match on SQL.' }),
    posting('jobindex.456', { title: 'BI Developer', company: 'Globex', score: 0.74 }),
  ]
  for (const r of rows) writeFileSync(join(dir, `${r.id}.json`), JSON.stringify(r))
  if (options.prepared) preparePrepared(home, options.prepared, rows.find((r) => r.id === options.prepared) ?? rows[0])
  return built
}
