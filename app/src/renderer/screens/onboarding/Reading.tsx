import { named } from '../AppName'
import { CheckMark } from '../CheckMark'
import { useEffect, useRef, useState } from 'react'
import type { Dispatch } from 'react'
import { call, draftCv, errorText } from '../../api'
import { Frame } from './parts'
import type { Action, Basics, StoryValues, TitleSuggestion, WizardState } from './reducer'

type Phase = 'draft' | 'basics' | 'titles' | 'terms' | 'story' | 'done'
const PHASES: { id: Phase; word: string }[] = [
  { id: 'draft', word: 'Drafting your CV' },
  { id: 'basics', word: 'Reading your details' },
  { id: 'titles', word: 'Finding titles that fit' },
  { id: 'terms', word: 'Choosing search terms' },
  // a first set-up from sources only: one story from the CV, to show what the story bank is
  { id: 'story', word: 'Writing an example story' },
]

interface Proposal {
  keywords: string[]
  topic_terms: string[]
}

/** The running step's clock, to the second so it visibly moves: "45 s", "1 min 20 s". */
function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`
}

interface Props {
  state: WizardState
  dispatch: Dispatch<Action>
  onDone: () => void
  onBack: () => void
}

/**
 * Reads the sources: the draft, the basics, the titles, the search terms, one tool each, nothing written but
 * the scratch draft; on a first set-up, one story from the draft beside them (`draft_stories`), the example of
 * what the story bank holds: one that fails or finds none is simply not shown. What could not be found stays empty for the review to ask; a failed call does the same,
 * and leaves why in `warnings` for the review to say. Left with Back, it stops: an answer still on its way
 * lands nowhere and asks nothing more.
 */
export function Reading({ state, dispatch, onDone, onBack }: Props) {
  // the story bank is shown on a first set-up that has a CV to draft from
  const withStory = state.mode === 'fresh' && state.files.length + state.urls.length > 0
  const [phase, setPhase] = useState<Phase>('draft')
  const [draftError, setDraftError] = useState<string | null>(null)
  const started = useRef(false)
  const left = useRef(false)
  const [startedAt, setStartedAt] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())

  const terms = async (targets: string[], languages: string[]) => {
    setPhase('terms')
    let answer: Action
    try {
      const r = await call<Proposal>('keywords', { role_targets: targets, languages })
      answer = { type: 'keywords', keywords: r.keywords ?? [], topicTerms: r.topic_terms ?? [] }
    } catch (e) {
      // The titles themselves are searched; the review says so.
      answer = { type: 'skipKeywords', warning: errorText(e) }
    }
    if (left.current) return
    dispatch(answer)
  }

  const understand = async (markdown: string | null) => {
    setPhase('basics')
    let languages = state.languages
    let basics: Basics
    try {
      basics = await call<Basics>('infer_basics', markdown ? { markdown } : {})
      if (state.mode === 'fresh') languages = basics.languages
    } catch (e) {
      basics = { name: null, email: null, location: null, languages, remote: state.remote, missing: [], warning: errorText(e) }
    }
    if (left.current) return
    dispatch({ type: 'basics', basics })
    setPhase('titles')
    let titles: TitleSuggestion[] = []
    let warning: string | undefined
    try {
      const r = await call<{ titles?: TitleSuggestion[]; warning?: string }>('suggest_titles', { titles: state.roleTargets, languages })
      titles = r.titles ?? []
      warning = r.warning
    } catch (e) {
      // no suggestions: the review asks for titles, and says why
      warning = errorText(e)
    }
    if (left.current) return
    dispatch({ type: 'titles', titles, warning })
    const targets = [...state.roleTargets, ...titles.filter((t) => t.recommended && !state.roleTargets.includes(t.title)).map((t) => t.title)]
    // With no title there is nothing to choose terms for: the review proposes them once the user names one.
    if (targets.length > 0) await terms(targets, languages)
  }

  /** The example story, drafted from the CV draft just written; nothing on a failure (principle 9). */
  const exampleStory = async () => {
    try {
      const r = await call<{ stories?: StoryValues[] }>('draft_stories', { from_cv: true })
      const s = r.stories?.[0]
      if (s && !left.current) dispatch({ type: 'storyDrafted', story: { title: s.title, context: s.context, action: s.action, result: s.result, learning: s.learning } })
    } catch {
      // the review goes without it
    }
  }

  const finish = () => {
    if (!left.current) setPhase('done')
  }

  const read = async () => {
    setDraftError(null)
    setPhase('draft')
    if (state.files.length + state.urls.length === 0) {
      await understand(null)
      return finish()
    }
    try {
      const r = await draftCv({ files: state.files.map((f) => f.token), urls: state.urls })
      if (left.current) return
      dispatch({ type: 'draftDone', markdown: r.markdown, sources: r.sources ?? [], urls: state.urls })
      const story = withStory ? exampleStory() : Promise.resolve()
      await understand(r.markdown)
      if (withStory && !left.current) setPhase('story')
      await story
      finish()
    } catch (e) {
      if (!left.current) setDraftError(errorText(e))
    }
  }

  useEffect(() => {
    if (started.current) return
    started.current = true
    void read()
    // once, on opening: the answers land in the state
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  // Back unmounts it; a mount (again, as the dev build's StrictMode does) means it is still here.
  useEffect(() => {
    left.current = false
    return () => {
      left.current = true
    }
  }, [])

  useEffect(() => {
    if (phase === 'done') onDone()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase])

  // The ring and the clock run only while Claude is at work: not on a failed draft.
  const working = phase !== 'done' && !draftError
  useEffect(() => {
    if (!working) return undefined
    const start = Date.now()
    setStartedAt(start)
    setNow(start)
    const tick = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(tick)
  }, [working, phase])

  const phases = PHASES.filter((p) => p.id !== 'story' || withStory)
  const at = phases.findIndex((p) => p.id === phase)
  const empty = (state.cvDraft?.sources ?? []).filter((s) => s.chars === 0)
  return (
    <Frame title="Reading your CV…" lead="It should take a few minutes." onBack={onBack}>
      <ol className="steps" aria-label="Reading">
        {phases.map((p, i) => {
          const done = phase === 'done' || i < at
          return (
            <li key={p.id} className={`step ${done ? 'step-done' : i === at ? `step-running${working ? ' step-working' : ''}` : 'step-waiting'}`} aria-current={i === at ? 'step' : undefined}>
              <span className="step-mark" aria-hidden="true">
                {done ? <CheckMark /> : i + 1}
              </span>
              <div className="step-body">
                <h2 className="display-s step-name">{p.word}</h2>
              </div>
              <span className="step-time small muted">{i === at && working ? clock(now - startedAt) : ''}</span>
            </li>
          )
        })}
      </ol>
      {draftError && (
        <div role="alert">
          <p className="error">{named(`Your sources could not be read: ${draftError}`)}</p>
          <div className="actions">
            <button type="button" className="secondary" onClick={() => void read()}>
              Try again
            </button>
            <button
              type="button"
              className="quiet"
              onClick={() => {
                setDraftError(null)
                void understand(null).then(finish)
              }}
            >
              Go on without a draft
            </button>
          </div>
        </div>
      )}
      {empty.map((s) => (
        <p key={s.source} className="small muted">{`${s.source}: no text found in this file (a scanned PDF?)`}</p>
      ))}
    </Frame>
  )
}
