// Test helpers for the wizard's steps: a stateful host around the real reducer, and sample data.
import { useReducer, type Dispatch, type ReactNode } from 'react'
import { initialState, wizardReducer, type Action, type DoctorReport, type ShowProfile, type WizardState } from './reducer'

const LINKEDIN = { key: 'linkedin_discovery', label: 'LinkedIn', verdict: 'unsure', terms_url: 'https://example.com/li', terms_summary: 'its terms ask for no scrapers', disclaimer: 'LinkedIn disclaimer text: its terms ask for no scrapers.' }
const HELLOWORK = { key: 'hellowork_discovery', label: 'HelloWork', verdict: 'unsure', terms_url: 'https://example.com/hw', terms_summary: 'its terms ask for no bots', disclaimer: 'HelloWork disclaimer text: its terms ask for no bots.' }
const CV = { photo: 'optional' as const, date_of_birth: false, max_pages: 2, date_format: 'DD.MM.YYYY' }

export const options = {
  cities: [
    { name: 'Copenhagen', country: 'Denmark', boards: ['jobindex', 'thehub', 'workable'], discovery: [LINKEDIN, HELLOWORK], cv: CV },
    { name: 'Aarhus', country: 'Denmark', boards: ['jobindex', 'thehub', 'workable'], discovery: [LINKEDIN, HELLOWORK], cv: CV },
  ],
  languages: ['English', 'Danish'],
  worldwide_boards: ['workable'],
  worldwide_discovery: [LINKEDIN],
  board_names: { jobindex: 'Jobindex', thehub: 'The Hub', workable: 'Workable' },
}

export const cvState = (over: Record<string, unknown> = {}) => ({ path: '/p/cv.md', exists: false, is_example: false, text: null, headline: null, sections: [], ...over })

/** `show_profile` on an empty home. */
export const freshProfile: ShowProfile = { path: '/p', config: null, errors: ['config.json not found'], cv: cvState(), options, enrich_sources: [] }

export const savedConfig = {
  name: 'Ada Lovelace',
  email: 'ada@example.com',
  location: 'Aarhus',
  languages: ['English'],
  role_targets: ['Data Scientist'],
  search_keywords: ['data scientist'],
  remote: 'hybrid' as const,
  min_score: 0.65,
  exclude: { companies: [], keywords: [] },
}

/** `show_profile` for a profile that exists, with the user's own CV. */
export const existingProfile: ShowProfile = { ...freshProfile, config: savedConfig, errors: [], cv: cvState({ exists: true, text: '# Ada\n' }) }

export const doctorReport = (login: 'ok' | 'out' = 'ok', latex = true): DoctorReport => ({
  ok: login === 'ok' && latex,
  checks: [
    { name: 'python', status: 'ok', required: true, detail: 'Python 3.12.1' },
    { name: 'latex', status: latex ? 'ok' : 'missing', required: true, detail: latex ? 'tectonic: /bin/tectonic' : 'no tectonic or xelatex found', fix: latex ? null : 'install it' },
    { name: 'claude CLI', status: 'ok', required: true, detail: 'claude: /bin/claude', details: { path: '/bin/claude' } },
    login === 'ok'
      ? { name: 'claude login', status: 'ok', required: true, detail: 'logged in', details: { loggedIn: true, email: 'ada@example.com', subscriptionType: 'max' } }
      : { name: 'claude login', status: 'missing', required: true, detail: 'not logged in', fix: 'claude auth login', details: { loggedIn: false } },
  ],
})

/** Renders `children` with a real reducer state, starting from `state` (or a fresh wizard on `profile`). */
export function Host({ profile = freshProfile, start, children }: { profile?: ShowProfile; start?: Partial<WizardState>; children: (state: WizardState, dispatch: Dispatch<Action>) => ReactNode }) {
  const [state, dispatch] = useReducer(wizardReducer, undefined, () => ({ ...initialState(profile), ...start }))
  return <>{children(state, dispatch)}</>
}
