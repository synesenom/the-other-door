// The developer demo (`npm run dev:demo`): the app runs on made-up data in app/.demo/ —
// the example profile (Jane Doe) and jobs in every state — so exploring it never changes
// your real profile/, jobs/ or Drive archive. Pure file work, no processes.
import { appendFileSync, cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join, relative, resolve, sep } from 'node:path'
import { JOBS_DATA_VERSION, PROFILE_DATA_VERSION } from './data-versions'

export type DemoMode = 'keep' | 'fresh'

/** electron-vite's `--mode`: `demo` keeps the demo folder, `demo-fresh` builds it again; anything else is no demo. */
export function demoMode(mode: string | undefined): DemoMode | null {
  if (mode === 'demo') return 'keep'
  if (mode === 'demo-fresh') return 'fresh'
  return null
}

/** The demo folder: `DOOR_DEMO_DIR` when set (tests use a temp folder), else `app/.demo` of the checkout. */
export function demoDir(env: Record<string, string | undefined>, repoRoot: string): string {
  const override = env['DOOR_DEMO_DIR']
  return override ? override : join(repoRoot, 'app', '.demo')
}

/** The demo mode of this start: the build mode's, else `keep` when `DOOR_DEMO_DIR` is set and the app is not packaged. */
export function demoModeFor(mode: string | undefined, env: Record<string, string | undefined>, packaged: boolean): DemoMode | null {
  return demoMode(mode) ?? (!packaged && env['DOOR_DEMO_DIR'] ? 'keep' : null)
}

/** `DOOR_DEMO_RUN_MS`: how long the simulated run takes (a test makes it short); read in the demo only. */
export function demoRunMs(env: Record<string, string | undefined>): number | undefined {
  const n = Number(env['DOOR_DEMO_RUN_MS'])
  return Number.isFinite(n) && n > 0 ? n : undefined
}

/**
 * The server's environment in the demo: the data folder is the demo's, and the config
 * folders The other door keeps its Drive connection in (drive.json) point inside it too, so the
 * sync sees no connection and never pulls or pushes. HOME and PATH stay yours, so claude
 * is still signed in: Prepare and Revise run for real, on your plan, on the made-up data.
 */
export function demoEnv(base: Record<string, string | undefined>, demo: string): Record<string, string | undefined> {
  return { ...base, DOOR_HOME: demo, XDG_CONFIG_HOME: join(demo, '.config'), APPDATA: join(demo, 'appdata') }
}

interface DemoJob {
  id: string
  title: string
  title_en?: string
  company: string
  location: string
  score: number
  score_reason: string
  matching_skills: string[]
  missing_skills: string[]
  language: string
  language_requirement: string
  /** Days before now it was first seen; 0 = today, after the last review (so it is new). */
  seen_days_ago: number
  description: string
  /** Its ledger entry, oldest event first; none = a match not acted on. */
  history?: { status: string; days_ago: number; notes?: string }[]
}

/** A full-length ad's sections, so the posting has to scroll: some of the made-up ads are long, some short. */
const LONG_AD = (role: string, team: string) =>
  `\n\nAbout the role\n\n` +
  `As our ${role} you join a finance team of twelve and report to the CFO. You take over a close that runs in eight ` +
  `working days today, and we would like it to run in five by the end of next year. You will be the person the ` +
  `business partners, the auditors and the management team come to with questions about the numbers, and you will ` +
  `have the room to change how we work where it makes sense.\n\n` +
  `Your responsibilities\n\n` +
  `- Own the monthly, quarterly and year-end close, including the group consolidation and the eliminations\n` +
  `- Prepare the management reporting pack and present it to the management team every month\n` +
  `- Lead the budget and forecast cycle together with the business partners, three times a year\n` +
  `- Keep our accounting policies in line with IFRS and document the judgements behind them\n` +
  `- Be the main contact for the external auditors and drive the year-end audit\n` +
  `- Develop the internal controls, and make sure they are followed in every entity\n` +
  `- Coach two accountants and take part in hiring as the team grows\n\n` +
  `What you bring\n\n` +
  `- A master's degree in finance, accounting or economics, or a state-authorised auditor's background\n` +
  `- Five or more years in controlling or audit, some of it in an international group\n` +
  `- A solid grip of IFRS and consolidation; experience with an ERP such as SAP or Dynamics\n` +
  `- Strong Excel, and the curiosity to automate what you do more than twice\n` +
  `- Clear written and spoken English; Danish is an advantage but not a requirement\n\n` +
  `What we offer\n\n` +
  `${team} offers a permanent full-time position with a hybrid setup (two days a week from home), a pension scheme ` +
  `from day one, health insurance, a lunch scheme and a yearly budget for courses and certifications. We have a flat ` +
  `organisation where you will see the effect of your work quickly, and colleagues who help each other.\n\n` +
  `How to apply\n\n` +
  `Send your CV and a short letter through the link below. We interview on a running basis and close the position ` +
  `when we have found the right person, so do not wait for the deadline. Questions about the role can go to our ` +
  `Head of Finance; we are happy to have a call before you apply.`

const ad = (role: string, team: string, extra: string, long = false) =>
  `${team} is looking for a ${role} to own the monthly close, reporting and the budget cycle.\n\n` +
  `You will work closely with the business on forecasts and investment cases, keep the numbers ` +
  `in line with IFRS and our group policies, and improve how we report. ${extra}\n\n` +
  `We offer a hybrid workplace, a pension scheme and a team that likes clean numbers.` +
  (long ? LONG_AD(role, team) : '')

/** The made-up jobs: matches at several scores (some new), one in Danish, and one in each state. */
// `tracker._SENT_STATUSES` (plus every interview round): the application went out.
const SENT = new Set(['applied', 'rejected', 'ghosted', 'offer'])

export const DEMO_JOBS: DemoJob[] = [
  {
    id: 'jobindex.demo-1', title: 'Senior Financial Controller', company: 'Oceanic Shipping', location: 'København',
    score: 0.88, score_reason: 'Senior controller role with IFRS consolidation and month-end close, both central in the CV.',
    matching_skills: ['IFRS', 'consolidation', 'month-end close', 'group reporting', 'budgeting', 'forecasting', 'internal controls', 'team leadership'], missing_skills: ['SAP S/4HANA', 'transfer pricing', 'Power BI'],
    language: 'en', language_requirement: 'none', seen_days_ago: 0,
    description: ad('Senior Financial Controller', 'Our group finance team in Copenhagen', 'Experience with SAP S/4HANA is a plus.', true),
  },
  {
    id: 'thehub.demo-2', title: 'Økonomichef', title_en: 'Head of Finance', company: 'Acme Foods', location: 'Aarhus',
    score: 0.82, score_reason: 'Head of Finance for a mid-sized food producer; leadership and budgeting match, Danish is required.',
    matching_skills: ['budgeting', 'team leadership', 'cash flow management', 'month-end close', 'forecasting', 'board reporting'], missing_skills: ['Danish (business level)', 'e-conomic', 'startup fundraising'],
    language: 'da', language_requirement: 'required', seen_days_ago: 0,
    description: 'Acme Foods søger en økonomichef, der vil stå for regnskab, budget og rapportering.\n\nDu leder et team på fem og arbejder tæt sammen med direktionen.',
  },
  {
    id: 'greenhouse.demo-3', title: 'Group Controller', company: 'Globex Energy', location: 'Esbjerg',
    score: 0.76, score_reason: 'Group reporting across subsidiaries matches the consolidation work in the CV.',
    matching_skills: ['group reporting', 'consolidation', 'IFRS', 'month-end close', 'internal controls', 'audit', 'budgeting'], missing_skills: ['energy sector', 'hedge accounting', 'SAP S/4HANA'],
    language: 'en', language_requirement: 'none', seen_days_ago: 3,
    description: ad('Group Controller', 'Globex Energy', 'You report to the CFO and travel to our sites a few times a year.', true),
  },
  {
    id: 'teamtailor.demo-4', title: 'Finance Business Partner', company: 'Hooli Software', location: 'København (hybrid)',
    score: 0.71, score_reason: 'Business partnering with product teams; forecasting fits, SaaS metrics are new.',
    matching_skills: ['forecasting', 'stakeholder management', 'budgeting', 'Excel modelling', 'business cases', 'KPI reporting'], missing_skills: ['SaaS metrics', 'Looker', 'revenue recognition (ASC 606)'],
    language: 'en', language_requirement: 'none', seen_days_ago: 4,
    description: ad('Finance Business Partner', 'Hooli Software', 'You will be the finance partner for two product lines.', true),
  },
  {
    id: 'jobindex.demo-5', title: 'Business Controller', company: 'Contoso Retail', location: 'Odense',
    score: 0.67, score_reason: 'Store-level controlling; close to the threshold because retail is new.',
    matching_skills: ['controlling', 'Excel modelling', 'budgeting', 'forecasting', 'variance analysis', 'KPI reporting', 'stakeholder management'], missing_skills: ['retail', 'Power BI', 'category management'],
    language: 'en', language_requirement: 'none', seen_days_ago: 6,
    description: ad('Business Controller', 'Contoso Retail', 'You follow 40 stores and their monthly results.'),
  },
  {
    id: 'successfactors.demo-6', title: 'Finance Manager', company: 'Initech Pharma', location: 'Hillerød',
    score: 0.84, score_reason: 'Finance manager for a pharma site; close, budgeting and audit all match.',
    matching_skills: ['audit', 'budgeting', 'month-end close', 'IFRS', 'internal controls', 'forecasting', 'team leadership', 'stakeholder management'], missing_skills: ['GxP', 'SAP S/4HANA', 'pharma regulatory reporting'],
    language: 'en', language_requirement: 'none', seen_days_ago: 5,
    description: ad('Finance Manager', 'Initech Pharma', 'You own the relationship with our external auditors.', true),
    history: [{ status: 'prepared', days_ago: 1 }],
  },
  {
    id: 'jobindex.demo-7', title: 'Accounting Manager', company: 'Vandelay Logistics', location: 'Køge',
    score: 0.74, score_reason: 'Accounting team lead; the close and team leadership match.',
    matching_skills: ['team leadership', 'month-end close', 'IFRS', 'accounts payable', 'accounts receivable', 'internal controls', 'budgeting'], missing_skills: ['Navision', 'logistics'],
    language: 'en', language_requirement: 'none', seen_days_ago: 9,
    description: ad('Accounting Manager', 'Vandelay Logistics', 'You lead a team of four accountants.'),
    history: [{ status: 'applied', days_ago: 7 }],
  },
  {
    id: 'greenhouse.demo-8', title: 'Head of Finance', company: 'Example Bank', location: 'København',
    score: 0.9, score_reason: 'Head of Finance in financial services; the strongest match of the week.',
    matching_skills: ['IFRS', 'team leadership', 'regulatory reporting', 'consolidation', 'budgeting', 'forecasting', 'board reporting', 'audit'], missing_skills: ['Basel III', 'treasury', 'ALM'],
    language: 'en', language_requirement: 'none', seen_days_ago: 10,
    description: ad('Head of Finance', 'Example Bank', 'You sit on the management team.', true),
    history: [
      { status: 'applied', days_ago: 8 },
      { status: 'interview:screening', days_ago: 2, notes: 'Recruiter call went well; salary range fits.' },
    ],
  },
  {
    id: 'teamtailor.demo-9', title: 'Controller', company: 'Initrode Media', location: 'Aalborg',
    score: 0.69, score_reason: 'Controller role; a fit on paper but far from Copenhagen.',
    matching_skills: ['controlling', 'budgeting', 'month-end close', 'forecasting', 'Excel modelling', 'KPI reporting'], missing_skills: ['media', 'advertising revenue', 'Aalborg'],
    language: 'en', language_requirement: 'none', seen_days_ago: 8,
    description: ad('Controller', 'Initrode Media', 'The role is on site in Aalborg four days a week.'),
    history: [{ status: 'discarded', days_ago: 3, notes: 'Too far from Copenhagen.' }],
  },
]

function within(dir: string, other: string): boolean {
  const r = relative(dir, other)
  return r === '' || (!r.startsWith('..') && !r.startsWith(sep) && !/^[A-Za-z]:/.test(r))
}

/** Throws unless `dir` is a folder that may be deleted: not the checkout, not inside it, not its jobs/ or profile/. */
function refuseRealData(dir: string, repoRoot: string, what: string): string {
  const to = resolve(dir)
  const repo = resolve(repoRoot)
  if (within(to, repo) || within(join(repo, 'jobs'), to) || within(join(repo, 'profile'), to)) {
    throw new Error(`refusing ${what} folder at ${to}: it is, or holds, the checkout's real data`)
  }
  return to
}

/** electron-vite's `--mode onboard` (`npm run dev:onboard`): the app on an empty data folder, to try the first launch. */
export function onboardMode(mode: string | undefined): 'onboard' | null {
  return mode === 'onboard' ? 'onboard' : null
}

/** The onboarding sandbox: `DOOR_ONBOARD_DIR` when set (tests use a temp folder), else `app/.onboard` of the checkout. */
export function onboardDir(env: Record<string, string | undefined>, repoRoot: string): string {
  const override = env['DOOR_ONBOARD_DIR']
  return override ? override : join(repoRoot, 'app', '.onboard')
}

/** The onboarding mode of this start: the build mode's, else on when `DOOR_ONBOARD_DIR` is set and the app is not packaged. */
export function onboardModeFor(mode: string | undefined, env: Record<string, string | undefined>, packaged: boolean): 'onboard' | null {
  return onboardMode(mode) ?? (!packaged && env['DOOR_ONBOARD_DIR'] ? 'onboard' : null)
}

/** Leaves `dir` an empty folder (whatever it held is deleted). Refuses, before deleting anything, a folder that is or holds the checkout's real data. */
export function resetOnboard(dir: string, repoRoot: string): void {
  const to = refuseRealData(dir, repoRoot, 'an onboarding')
  rmSync(to, { recursive: true, force: true })
  mkdirSync(to, { recursive: true })
}

/**
 * The server's environment in the onboarding sandbox: the demo's (data and Drive state inside the
 * folder, HOME and PATH yours so the claude CLI is real), plus, with DOOR_ONBOARD_SIGNED_OUT=1, a
 * Claude config folder of its own, so the sandbox starts signed out and your own login is untouched.
 */
export function onboardEnv(base: Record<string, string | undefined>, dir: string): Record<string, string | undefined> {
  const env = demoEnv(base, dir)
  if (base['DOOR_ONBOARD_SIGNED_OUT'] === '1') env['CLAUDE_CONFIG_DIR'] = join(dir, '.claude')
  return env
}

/** Build the demo folder unless it is there (`fresh` builds it again). Refuses, before deleting anything, a folder that is or holds the checkout's data. */
/** The discovery sources a profile can turn on, each off in a demo seeded with `discoveryOff`. */
const DISCOVERY_KEYS = ['linkedin_discovery', 'profession_discovery', 'hellowork_discovery', 'jobbsafari_discovery']

/** `DOOR_DEMO_DISCOVERY=off`: a demo whose profile has every discovery source off (the README's app.gif). */
export function demoDiscoveryOff(env: Record<string, string | undefined>): boolean {
  return env['DOOR_DEMO_DISCOVERY'] === 'off'
}

export function seedDemo(demo: string, repoRoot: string, mode: DemoMode, now: Date = new Date(), options: { discoveryOff?: boolean } = {}): { created: boolean } {
  const to = refuseRealData(demo, repoRoot, 'a demo')
  const repo = resolve(repoRoot)
  if (mode === 'fresh') rmSync(to, { recursive: true, force: true })
  if (existsSync(join(to, 'profile')) || existsSync(join(to, 'jobs'))) return { created: false }

  cpSync(join(repo, 'profile.example'), join(to, 'profile'), { recursive: true })
  if (options.discoveryOff) {
    const configPath = join(to, 'profile', 'config.json')
    const config = JSON.parse(readFileSync(configPath, 'utf8')) as Record<string, unknown>
    for (const key of DISCOVERY_KEYS) config[key] = false
    writeFileSync(configPath, JSON.stringify(config, null, 2))
  }
  // Prepare runs for real here, and the example CV itself is refused: the demo's is a changed copy.
  appendFileSync(join(to, 'profile', 'cv.md'), '\n<!-- the demo\'s copy -->\n')
  // The story bank is the demo's own too: a user's bank is never the example one, so the demo's is not either.
  appendFileSync(
    join(to, 'profile', 'story_bank.md'),
    '\n## Moved the sales forecast into one shared model at Acme Foods\n\n' +
      '**Context**: Sales, operations and finance each kept their own forecast, and the three never agreed; management needed one forecast they could all work from before the next budget round.\n' +
      '**Action**: Built one model on the ledger and the order book, agreed the definitions with each team and reviewed the gaps every Monday.\n' +
      '**Result**: One forecast used in the budget round; the gap between sales and finance fell from 12% to 3%.\n' +
      '**Learning**: Agreeing the definitions took longer than building the model, and mattered more.\n',
  )
  // A folder this build sets up carries its data version, or the first start would run the upgrade on it.
  writeFileSync(join(to, 'profile', '.data_version'), `${PROFILE_DATA_VERSION}\n`)
  const jobs = join(to, 'jobs')
  mkdirSync(jobs, { recursive: true })
  writeFileSync(join(jobs, '.data_version'), `${JOBS_DATA_VERSION}\n`)
  const at = (days: number, hours = 0) => new Date(now.getTime() - days * 86_400_000 - hours * 3_600_000).toISOString()
  const ledger: Record<string, unknown> = {}
  for (const job of DEMO_JOBS) {
    const seen = at(job.seen_days_ago, 2)
    const site = job.id.split('.')[0]
    const { history, seen_days_ago, ...fields } = job
    void seen_days_ago
    const posting = { ...fields, url: `https://example.com/jobs/${job.id}`, posted_at: at(job.seen_days_ago + 1), scraped_at: seen, source: site }
    const dir = join(jobs, 'postings', seen.slice(0, 10), site)
    mkdirSync(dir, { recursive: true })
    writeFileSync(join(dir, `${job.id}.json`), JSON.stringify(posting, null, 2))
    if (history?.length) {
      const events = history.map((h) => ({ status: h.status, at: at(h.days_ago), ...(h.notes ? { notes: h.notes } : {}) }))
      const last = events[events.length - 1]
      ledger[job.id] = { status: last.status, updated_at: last.at, ...(last.notes ? { notes: last.notes } : {}), history: events }
      // Prepared: its files. Sent (applied or later): also the copy `jobs status` keeps in `sent/` when it goes out.
      const sent = events.some((e) => SENT.has(e.status) || e.status.startsWith('interview:'))
      if (last.status === 'prepared' || sent) {
        const out = join(jobs, 'output', job.id)
        const pages = join(repo, 'app', 'test', 'fixtures', 'prepared')
        for (const dir of sent ? [out, join(out, 'sent')] : [out]) {
          mkdirSync(dir, { recursive: true })
          for (const name of readdirSync(pages)) cpSync(join(pages, name), join(dir, name))
          writeFileSync(join(dir, 'posting.json'), JSON.stringify(posting, null, 2))
        }
      }
    }
  }
  writeFileSync(join(jobs, 'applications.json'), JSON.stringify(ledger, null, 2))
  // Reviewed yesterday: today's jobs are new, the older ones are not.
  writeFileSync(join(jobs, 'last_review.json'), JSON.stringify({ reviewed_at: at(1) }))
  return { created: true }
}
