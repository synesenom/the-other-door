// The onboarding wizard's brain: a pure reducer that holds every answer until the review's Save
// (nothing is written before it), the three screens, the arguments of `init_profile` and the
// routing of its errors back to the review section that owns the field. No React, no calls.

import { todoOffsets } from '../todos'

export type StepId = 'sources' | 'reading' | 'review'
/** The parts of the review; a failed Save puts each error line under the part that owns its field. */
export type ReviewSection = 'you' | 'photo' | 'titles' | 'sectors' | 'terms' | 'cv' | 'story' | 'employers' | 'review'
/** A story of the story bank: a title and the four CARL parts. */
export interface StoryValues {
  title: string
  context: string
  action: string
  result: string
  learning: string
}
export const STORY_PARTS = ['context', 'action', 'result', 'learning'] as const
const STORY_WORDS: Record<keyof StoryValues, string> = { title: 'Title', context: 'Context', action: 'Action', result: 'Result', learning: 'Learning' }

/** The parts of a story still empty, in words ("Learning"). */
export function storyGaps(v: StoryValues): string[] {
  return (['title', ...STORY_PARTS] as (keyof StoryValues)[]).filter((k) => !v[k].trim()).map((k) => STORY_WORDS[k])
}

/** What the reading step could not infer, asked one card at a time. */
export type MissingKey = 'name' | 'email' | 'location' | 'titles'
export type Remote = 'yes' | 'no' | 'hybrid'

/** A discovery source onboarding asks about: its config key and its name in words, with the terms verdict and the
 * disclaimer the server writes for it (`door.core.disclaimer`): shown as it is, whenever the source is on or offered. */
export interface DiscoveryChoice {
  key: string
  label: string
  verdict?: string
  terms_url?: string
  terms_summary?: string
  disclaimer?: string
}
/** How a CV is written in a country (its `[cv]` block); `photo` says whether the review asks for one. */
export interface CvConventions {
  photo: 'no' | 'optional' | 'expected'
  date_of_birth: boolean
  max_pages: number
  date_format: string
}
export interface CityOption {
  name: string
  country: string
  boards: string[]
  /** The CV conventions of the city's country. */
  cv?: CvConventions
  /** The discovery sources serving the city's country. */
  discovery?: DiscoveryChoice[]
}
export interface ProfileOptions {
  cities: CityOption[]
  languages: string[]
  worldwide_boards: string[]
  /** The discovery sources asked about for a city in no known country. */
  worldwide_discovery?: DiscoveryChoice[]
  /** Each board in words ("The Hub"); a missing name falls back to the board's id. */
  board_names?: Record<string, string>
}
export interface CvState {
  path: string
  exists: boolean
  is_example: boolean
  text: string | null
  headline: string | null
  sections: unknown[]
}
/** The parts of `show_profile` the wizard reads. */
export interface ShowProfile {
  path: string
  config: {
    name?: string
    email?: string
    location?: string
    languages?: string[]
    role_targets?: string[]
    search_keywords?: string[]
    topic_terms?: string[]
    sectors?: string
    remote?: Remote
    min_score?: number
    exclude?: { companies?: string[]; keywords?: string[] }
    enrich_sources?: string[]
    linkedin_discovery?: boolean
    profession_discovery?: boolean
    jobbsafari_discovery?: boolean
    hellowork_discovery?: boolean
  } | null
  errors: string[]
  cv: CvState
  options: ProfileOptions
  enrich_sources: string[]
  /** The discovery sources serving the profile's city that were never chosen, so do not run. */
  discovery_unchosen?: DiscoveryChoice[]
  /** The CV photo kept (profile/photo.jpg), if any. */
  photo?: { exists: boolean; path?: string }
}
export interface DoctorCheck {
  name: string
  status: string
  required: boolean
  detail: string
  fix?: string | null
  details?: Record<string, unknown>
}
export interface DoctorReport {
  ok: boolean
  checks: DoctorCheck[]
  /** Set by the app when doctor itself could not answer: why (its checks are then empty). */
  error?: string
}

export interface CvDraftInfo {
  sources: { source: string; kind: 'file' | 'url'; chars?: number }[]
}

/** A title `suggest_titles` proposes, or one the user named. */
export interface TitleSuggestion {
  title: string
  reason: string
  recommended: boolean
}

/** What `infer_basics` answers. */
export interface Basics {
  name: string | null
  email: string | null
  location: string | null
  languages: string[]
  remote: Remote
  missing: string[]
  unsupported_location?: string
  warning?: string
}

/** A file picked or dropped: its token stands for a path only the main process knows. */
export interface PickedFile {
  token: string
  name: string
  size: number
}

/** How many gaps the CV still has (the draft marks what it could not find). */
export function todoCount(text: string): number {
  return todoOffsets(text).length
}

/** A LinkedIn page, which cannot be read: its host, a trailing dot or not ("linkedin.com." is linkedin.com). */
export function isLinkedIn(url: string): boolean {
  let host: string
  try {
    host = new URL(url).hostname.toLowerCase().replace(/\.+$/, '')
  } catch {
    return false
  }
  return host === 'linkedin.com' || host.endsWith('.linkedin.com')
}

/** The reading steps that ask Claude and go on without an answer: the review says why each came back empty. */
export type ReadingWarning = 'basics' | 'titles' | 'terms'

export type ListField = 'languages' | 'keywords' | 'topicTerms'
export type ScalarField = 'name' | 'email' | 'location' | 'remote' | 'cvText' | 'sectors'

/** What the review does with the CV photo on Save: keep what there is, save a picked picture (by its token), or remove the one kept. */
export type PhotoChoice = { kind: 'keep' } | { kind: 'new'; token: string; name: string } | { kind: 'none' }

export interface WizardState {
  mode: 'fresh' | 'redo'
  step: StepId
  /** The one input step's answers: files by token, public pages by address. */
  files: PickedFile[]
  urls: string[]
  name: string
  email: string
  location: string
  languages: string[]
  /** The titles offered in the review, with their reasons. */
  titles: TitleSuggestion[]
  /** The titles picked, saved as `role_targets`. */
  roleTargets: string[]
  remote: Remote
  /** The sectors wanted and to avoid, in the user's own words (optional; `sectors` in the config). */
  sectors: string
  /** What is left to ask; only the reading step adds to it. */
  missing: MissingKey[]
  /** A place the CV names outside the covered countries, shown when asking for the city. */
  unsupportedLocation: string | null
  /** The answer for each discovery source (`linkedin_discovery`, ...): the user's call, their terms forbid automated access. */
  discovery: Record<string, boolean>
  /** Which discovery sources a city is asked about (from `show_profile`'s options), by lower-case city name. */
  discoveryChoices: { byCity: Record<string, DiscoveryChoice[]>; worldwide: DiscoveryChoice[] }
  keywords: string[]
  topicTerms: string[]
  /** Where the keywords came from: proposed by Claude, skipped (the titles stand in), or already in the config. */
  keywordsState: 'none' | 'proposed' | 'skipped' | 'config'
  /** The CV photo, held until Save (`save_photo` is its own tool, called after the profile is written). */
  photo: PhotoChoice
  /** The CV text to save, or null to leave profile/cv.md as it is. */
  cvText: string | null
  enrichSources: string[]
  /** What a CV draft learned (`draft_cv`): where each part came from, what is left to fill in, what was read. */
  cvDraft: CvDraftInfo | null
  /** The public pages the draft was made from and added to `enrichSources`, to take them out again. */
  cvUrls: string[]
  /** Messages from a failed Save, by the review section that owns the field. */
  errors: Partial<Record<ReviewSection, string[]>>
  /** Why a reading step came back empty (Claude failed): the review shows each where it belongs. */
  warnings: Partial<Record<ReadingWarning, string>>
  /** One story drafted from the CV, to show what the story bank is: saved with Save while kept. */
  story: { values: StoryValues; keep: boolean } | null
}

export function initialState(profile: ShowProfile): WizardState {
  const c = profile.config
  return {
    mode: c !== null ? 'redo' : 'fresh',
    step: 'sources',
    files: [],
    urls: [],
    name: c?.name ?? '',
    email: c?.email ?? '',
    location: c?.location ?? '',
    languages: c?.languages?.length ? [...c.languages] : ['English'],
    titles: (c?.role_targets ?? []).map((title) => ({ title, reason: 'In your profile', recommended: true })),
    roleTargets: [...(c?.role_targets ?? [])],
    remote: c?.remote ?? 'hybrid',
    sectors: c?.sectors ?? '',
    missing: [],
    unsupportedLocation: null,
    discovery: Object.fromEntries(
      Object.entries(c ?? {}).filter(([k, v]) => k.endsWith('_discovery') && typeof v === 'boolean'),
    ) as Record<string, boolean>,
    discoveryChoices: {
      byCity: Object.fromEntries(profile.options.cities.map((city) => [city.name.toLowerCase(), city.discovery ?? []])),
      worldwide: profile.options.worldwide_discovery ?? [],
    },
    keywords: [...(c?.search_keywords ?? [])],
    topicTerms: [...(c?.topic_terms ?? [])],
    keywordsState: c?.search_keywords?.length ? 'config' : 'none',
    photo: { kind: 'keep' },
    cvText: null,
    enrichSources: [...(c?.enrich_sources ?? profile.enrich_sources ?? [])],
    cvDraft: null,
    cvUrls: [],
    errors: {},
    warnings: {},
    story: null,
  }
}

export const STEPS: StepId[] = ['sources', 'reading', 'review']

export const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** A CV of the user's: written here, or on disk and not the example `init_profile` copies. */
export function hasOwnCv(state: WizardState, profile: ShowProfile): boolean {
  return Boolean(state.cvText?.trim()) || (profile.cv.exists && !profile.cv.is_example)
}

/** Why the review cannot be saved yet, in a sentence, or null. It needs a CV of the user's: nothing is scored without one. */
const UNFOUND_WORDS: Record<MissingKey, string> = { name: 'your name', email: 'your email', location: 'your city', titles: 'job titles' }

/** What reading could not find and the review still needs, in words: gone as each is filled in. */
export function stillUnfound(state: WizardState): string[] {
  const filled: Record<MissingKey, boolean> = {
    name: state.name.trim() !== '',
    email: EMAIL.test(state.email.trim()),
    location: state.location.trim() !== '',
    titles: state.roleTargets.length > 0,
  }
  return state.missing.filter((key) => !filled[key]).map((key) => UNFOUND_WORDS[key])
}

export function reviewProblem(state: WizardState, profile: ShowProfile): string | null {
  if (state.name.trim() === '') return 'Your name is needed.'
  if (!EMAIL.test(state.email.trim())) return 'A valid email is needed.'
  if (state.location.trim() === '') return 'A city is needed.'
  if (state.languages.length === 0) return 'Choose at least one language.'
  if (state.roleTargets.length === 0) return 'Choose at least one title.'
  if (!hasOwnCv(state, profile)) return 'Your CV is needed: paste it above.'
  const gaps = state.story?.keep ? storyGaps(state.story.values) : []
  if (gaps.length > 0) return `Fill in the ${gaps.join(', ')} of your story, or untick it.`
  return null
}

/** Which review section asks for which answer. */
const OWNER: Record<ListField | ScalarField, ReviewSection> = {
  name: 'you', email: 'you', location: 'you', languages: 'you', remote: 'you',
  keywords: 'terms', topicTerms: 'terms', cvText: 'cv', sectors: 'sectors',
}

const CONFIG_OWNER: Record<string, ReviewSection> = {
  name: 'you', email: 'you', location: 'you', languages: 'you', remote: 'you',
  role_targets: 'titles', search_keywords: 'terms', topic_terms: 'terms', sectors: 'sectors',
  linkedin_discovery: 'employers', profession_discovery: 'employers',
  jobbsafari_discovery: 'employers', hellowork_discovery: 'employers',
}

/** `init_profile`'s `{error}` text, one `profile/config.json: <field> — <message>` per line, by the review section that owns each field. */
export function routeErrors(text: string): Partial<Record<ReviewSection, string[]>> {
  const out: Partial<Record<ReviewSection, string[]>> = {}
  const put = (section: ReviewSection, message: string) => {
    ;(out[section] ??= []).push(message)
  }
  for (const line of text.split('\n').map((l) => l.trim()).filter(Boolean)) {
    const m = /config\.json: ([A-Za-z0-9_.]+) — (.*)$/.exec(line)
    if (!m) {
      put('review', line)
      continue
    }
    const owner = CONFIG_OWNER[m[1].split('.')[0]]
    if (owner) put(owner, m[2])
    else put('review', `${m[1]}: ${m[2]}`)
  }
  return out
}

export type Action =
  | { type: 'next' }
  | { type: 'back' }
  | { type: 'goto'; step: StepId }
  | { type: 'addFiles'; files: PickedFile[] }
  | { type: 'dropFile'; token: string }
  | { type: 'addUrl'; url: string }
  | { type: 'dropUrl'; url: string }
  | { type: 'set'; field: ScalarField; value: string | null }
  | { type: 'discovery'; key: string; value: boolean }
  | { type: 'add'; list: ListField; value: string }
  | { type: 'drop'; list: ListField; value: string }
  | { type: 'basics'; basics: Basics }
  | { type: 'titles'; titles: TitleSuggestion[]; warning?: string }
  | { type: 'toggleTitle'; title: string }
  | { type: 'addTitle'; title: string }
  | { type: 'dropTitle'; title: string }
  | { type: 'keywords'; keywords: string[]; topicTerms: string[] }
  | { type: 'skipKeywords'; warning?: string }
  | ({ type: 'draftDone'; markdown: string; urls: string[] } & CvDraftInfo)
  | { type: 'saveFailed'; error: string }
  | { type: 'photo'; choice: PhotoChoice }
  | { type: 'photoFailed'; error: string }
  | { type: 'storyDrafted'; story: StoryValues }
  | { type: 'story'; values: StoryValues }
  | { type: 'keepStory'; keep: boolean }
  | { type: 'storyFailed'; error: string }

function withoutErrors(state: WizardState, section: ReviewSection): WizardState {
  if (!state.errors[section]) return state
  const { [section]: _gone, ...rest } = state.errors
  return { ...state, errors: rest }
}

const without = (missing: MissingKey[], key: MissingKey) => missing.filter((m) => m !== key)

/** `warnings` with the step's warning, or without one when the step answered. */
function warned(state: WizardState, step: ReadingWarning, warning: string | undefined): WizardState['warnings'] {
  const { [step]: _gone, ...rest } = state.warnings
  return warning ? { ...rest, [step]: warning } : rest
}

const sameTitle = (a: string, b: string) => a.toLowerCase() === b.toLowerCase()

/** A title typed in is picked: as the suggestion it names, if it names one, so the suggestion's own box is ticked. */
function pickTitle(state: WizardState, title: string): WizardState {
  const name = state.titles.find((t) => sameTitle(t.title, title))?.title ?? title
  return { ...state, roleTargets: state.roleTargets.some((t) => sameTitle(t, name)) ? state.roleTargets : [...state.roleTargets, name] }
}

/** The picked titles that are no suggestion: the user's own, which can be removed. */
export function ownTitles(state: WizardState): string[] {
  return state.roleTargets.filter((r) => !state.titles.some((t) => sameTitle(t.title, r)))
}

export function wizardReducer(state: WizardState, action: Action): WizardState {
  switch (action.type) {
    case 'next': {
      const at = STEPS.indexOf(state.step)
      return at < STEPS.length - 1 ? { ...state, step: STEPS[at + 1] } : state
    }
    case 'back':
      // Reading runs by itself, so Back from the review goes past it, to the sources.
      return state.step === 'sources' ? state : { ...state, step: 'sources' }
    case 'goto':
      return { ...state, step: action.step }
    case 'addFiles':
      return { ...state, files: [...state.files, ...action.files.filter((f) => !state.files.some((c) => c.name === f.name && c.size === f.size))] }
    case 'dropFile':
      return { ...state, files: state.files.filter((f) => f.token !== action.token) }
    case 'addUrl':
      return state.urls.includes(action.url) ? state : { ...state, urls: [...state.urls, action.url] }
    case 'dropUrl':
      return { ...state, urls: state.urls.filter((u) => u !== action.url) }
    case 'set':
      return withoutErrors({ ...state, [action.field]: action.value }, OWNER[action.field])
    case 'discovery':
      return withoutErrors({ ...state, discovery: { ...state.discovery, [action.key]: action.value } }, 'employers')
    case 'add': {
      const value = action.value.trim()
      const list = state[action.list]
      if (!value || list.some((v) => v.toLowerCase() === value.toLowerCase())) return state
      return withoutErrors({ ...state, [action.list]: [...list, value] }, OWNER[action.list])
    }
    case 'drop':
      return withoutErrors({ ...state, [action.list]: state[action.list].filter((v) => v !== action.value) }, OWNER[action.list])
    case 'basics': {
      // A value already there (a redo, an edit) stands: what was read only fills the gaps.
      const { basics } = action
      const fresh = state.mode === 'fresh'
      const next = {
        ...state,
        name: state.name || (basics.name ?? ''),
        email: state.email || (basics.email ?? ''),
        location: state.location || (basics.location ?? ''),
        languages: fresh ? basics.languages : state.languages,
        remote: fresh ? basics.remote : state.remote,
        unsupportedLocation: basics.unsupported_location ?? null,
        warnings: warned(state, 'basics', basics.warning),
      }
      const missing: MissingKey[] = []
      if (!next.name) missing.push('name')
      if (!next.email) missing.push('email')
      if (!next.location) missing.push('location')
      return { ...next, missing: [...missing, ...state.missing.filter((m) => m === 'titles')] }
    }
    case 'titles': {
      const picked = new Set(state.roleTargets.map((t) => t.toLowerCase()))
      const recommended = action.titles.filter((t) => t.recommended).map((t) => t.title)
      const roleTargets = [...state.roleTargets, ...recommended.filter((t) => !picked.has(t.toLowerCase()))]
      const missing = roleTargets.length === 0 ? [...without(state.missing, 'titles'), 'titles' as const] : without(state.missing, 'titles')
      return { ...state, titles: action.titles, roleTargets, missing, warnings: warned(state, 'titles', action.warning) }
    }
    case 'toggleTitle': {
      const on = state.roleTargets.includes(action.title)
      return withoutErrors({ ...state, roleTargets: on ? state.roleTargets.filter((t) => t !== action.title) : [...state.roleTargets, action.title] }, 'titles')
    }
    case 'addTitle': {
      const title = action.title.trim()
      return title ? withoutErrors(pickTitle(state, title), 'titles') : state
    }
    case 'dropTitle':
      return { ...state, roleTargets: state.roleTargets.filter((t) => t !== action.title) }
    case 'keywords':
      return withoutErrors({ ...state, keywords: action.keywords, topicTerms: action.topicTerms, keywordsState: 'proposed', warnings: warned(state, 'terms', undefined) }, 'terms')
    case 'skipKeywords':
      return { ...state, keywords: [], topicTerms: [], keywordsState: 'skipped', warnings: warned(state, 'terms', action.warning) }
    case 'draftDone': {
      const kept = state.enrichSources.filter((u) => !state.cvUrls.includes(u))
      const added: string[] = []
      for (const url of action.urls) if (!isLinkedIn(url) && ![...kept, ...added].includes(url)) added.push(url)
      return withoutErrors(
        { ...state, cvText: action.markdown, cvDraft: { sources: action.sources }, cvUrls: added, enrichSources: [...kept, ...added] },
        'cv',
      )
    }
    case 'saveFailed':
      return { ...state, errors: routeErrors(action.error), step: 'review' }
    case 'photo':
      return withoutErrors({ ...state, photo: action.choice }, 'photo')
    case 'photoFailed':
      return { ...state, errors: { ...state.errors, photo: [action.error] }, step: 'review' }
    case 'storyDrafted':
      return { ...state, story: { values: action.story, keep: true } }
    case 'story':
      return state.story ? withoutErrors({ ...state, story: { ...state.story, values: action.values } }, 'story') : state
    case 'keepStory':
      return state.story ? withoutErrors({ ...state, story: { ...state.story, keep: action.keep } }, 'story') : state
    case 'storyFailed':
      return { ...state, errors: { ...state.errors, story: [action.error] }, step: 'review' }
  }
}

/** The arguments of `init_profile`: EVERY answer, so nothing of the example config survives a fresh home; a redo leaves what the wizard does not ask alone. */
export function toInitArgs(state: WizardState): Record<string, unknown> {
  const args: Record<string, unknown> = {
    name: state.name.trim(),
    email: state.email.trim(),
    location: state.location.trim(),
    languages: state.languages,
    role_targets: state.roleTargets,
    search_keywords: state.keywords.length > 0 ? state.keywords : state.roleTargets,
    topic_terms: state.topicTerms,
    remote: state.remote,
  }
  if (state.mode === 'fresh') {
    args['exclude_companies'] = []
    args['exclude_keywords'] = []
  }
  const other: Record<string, unknown> = Object.fromEntries(discoveryFor(state).map((d) => [d.key, d.on]))
  if (state.enrichSources.length > 0) other['enrich_sources'] = state.enrichSources
  // a redo sends it even empty, so clearing the text clears the key; a first set-up has none to clear
  if (state.sectors.trim() || state.mode === 'redo') other['sectors'] = state.sectors.trim()
  args['other'] = other
  return args
}

/** What the city's country does with a CV photo: `no` for a city the options do not know. */
export function photoPolicy(options: ProfileOptions, location: string): CvConventions['photo'] {
  const city = options.cities.find((c) => c.name.toLowerCase() === location.trim().toLowerCase())
  return city?.cv?.photo ?? 'no'
}

/** The discovery sources serving *location*'s city (`show_profile`'s options), the worldwide ones for any other place. */
export function sourcesForCity(options: ProfileOptions, location: string): DiscoveryChoice[] {
  const city = options.cities.find((c) => c.name.toLowerCase() === location.trim().toLowerCase())
  return city ? city.discovery ?? [] : options.worldwide_discovery ?? []
}

/** The discovery sources serving the profile's city when every one of them is off (turned off or never
 * chosen): what a first run with few matches reminds about. None without a config, or once one is on. */
export function discoveryOff(profile: ShowProfile): DiscoveryChoice[] {
  const config = profile.config as Record<string, unknown> | null
  if (!config) return []
  const sources = sourcesForCity(profile.options, String(config.location ?? ''))
  return sources.some((d) => config[d.key] === true) ? [] : sources
}

/** Every discovery source's config key the options know of, served anywhere. */
export function discoveryKeys(options: ProfileOptions): Set<string> {
  return new Set([...options.cities.flatMap((c) => c.discovery ?? []), ...(options.worldwide_discovery ?? [])].map((d) => d.key))
}

/** The discovery sources asked about for the city in *state*, each with its answer: off until the user ticks it. */
export function discoveryFor(state: WizardState): (DiscoveryChoice & { on: boolean })[] {
  const choices = state.discoveryChoices.byCity[state.location.trim().toLowerCase()] ?? state.discoveryChoices.worldwide
  return choices.map((d) => ({ ...d, on: state.discovery[d.key] ?? false }))
}

export interface ClaudeLogin {
  connected: boolean
  email?: string
  plan?: string
}

/** What doctor's `claude login` check says: signed in to a plan, and as whom. */
export function claudeLogin(doctor: DoctorReport | null): ClaudeLogin {
  const check = doctor?.checks.find((c) => c.name === 'claude login')
  if (!check || check.status !== 'ok' || check.details?.['loggedIn'] === false) return { connected: false }
  const email = check.details?.['email']
  const plan = check.details?.['subscriptionType']
  return { connected: true, ...(typeof email === 'string' ? { email } : {}), ...(typeof plan === 'string' ? { plan } : {}) }
}

/** The `claude` command line is missing: nothing can be read until it is installed. */
export function claudeMissing(doctor: DoctorReport | null): boolean {
  return doctor?.checks.some((c) => c.name === 'claude CLI' && c.status !== 'ok') ?? false
}

/** Whether the steps that read with Claude can run: it is installed and signed in. */
export function claudeReady(doctor: DoctorReport): boolean {
  return !claudeMissing(doctor) && claudeLogin(doctor).connected
}

/**
 * Whether the first run can start after the Save. `profile` is `show_profile` after it (`init_profile`
 * copies the example CV, so it only counts once it is the user's); in the sandbox the run is
 * simulated, so Claude does not matter there. When it cannot, the sidebar's lines say what is missing.
 */
export function canRunFirst(state: WizardState, profile: ShowProfile, doctor: DoctorReport | null, sandbox = false): boolean {
  return hasOwnCv(state, profile) && (sandbox || claudeLogin(doctor).connected)
}
