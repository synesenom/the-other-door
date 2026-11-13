import { useEffect, useRef, useState } from 'react'
import type { Dispatch, ReactNode } from 'react'
import { AppName, named } from '../AppName'
import { call, errorText } from '../../api'
import { DocDialog, LEGAL_DISCLAIMER } from '../Documentation'
import { Markdown } from '../Markdown'
import { todoOffsets } from '../todos'
import { Spinner } from '../Spinner'
import { ChipInput, CityField, FieldLabel, Frame, TextField } from './parts'
import { saveProfile } from './save'
import { discoveryFor, hasOwnCv, ownTitles, photoPolicy, reviewProblem, stillUnfound, todoCount } from './reducer'
import type { Action, Remote, ReviewSection, ShowProfile, WizardState } from './reducer'
import { Switch } from '../Switch'
import { PhotoField, photoHelp } from '../PhotoField'
import { MarkdownLink } from '../MarkdownHelp'
import { Fields } from '../Stories'


const REMOTE: { value: Remote; word: string }[] = [
  { value: 'hybrid', word: 'Hybrid' },
  { value: 'yes', word: 'Remote only' },
  { value: 'no', word: 'On site' },
]

/** How long the title picks stay still before their search terms are proposed again. */
export const TERMS_DEBOUNCE_MS = 800

/** The last part of a path, whichever way it is written. A web address stays whole. */
export function basename(source: string): string {
  if (/^https?:\/\//i.test(source)) return source
  return source.split(/[\\/]/).filter(Boolean).pop() ?? source
}

/** "Ready", or how much is left to fill in, for the CV the user wrote; what happens to the CV otherwise. */
export function cvOverview(state: WizardState, profile: ShowProfile): string {
  if (state.cvText && state.cvText.trim() !== '') {
    const todos = todoCount(state.cvText)
    return todos === 0 ? 'Ready' : `${todos} ${todos === 1 ? 'thing' : 'things'} to fill in`
  }
  if (profile.cv.exists && !profile.cv.is_example) return 'Kept as it is'
  return profile.cv.exists ? 'Still the example CV' : 'No CV yet'
}

function Errors({ messages }: { messages?: string[] }) {
  if (!messages?.length) return null
  return (
    <ul role="alert" className="error onb-errors">
      {messages.map((e) => (
        <li key={e}>{e}</li>
      ))}
    </ul>
  )
}

function Part({ title, lead, messages, children }: { title: string; lead?: ReactNode; messages?: string[]; children: ReactNode }) {
  return (
    <section className="part" aria-label={title}>
      <div className="part-head">
        <h2 className="display-s">{title}</h2>
        {lead && <p className="small muted">{lead}</p>}
      </div>
      <Errors messages={messages} />
      {children}
    </section>
  )
}

function Folded({ title, summary, open, messages, children }: { title: string; summary: string; open: boolean; messages?: string[]; children: ReactNode }) {
  return (
    <details className="part" open={open || undefined}>
      <summary>
        <span className="display-s">{title}</span> <span className="small muted">{summary}</span>
      </summary>
      <Errors messages={messages} />
      {children}
    </details>
  )
}

/** The titles' search terms, proposed again a moment after the picks change. */
function useTermsFollowTitles(state: WizardState, dispatch: Dispatch<Action>) {
  const [proposing, setProposing] = useState(false)
  const proposedFor = useRef(state.roleTargets.join('\n'))
  const asking = useRef(0)
  useEffect(() => {
    const now = state.roleTargets.join('\n')
    // Back to the titles last proposed for, or no title at all: nothing to wait for, and a late answer is dropped.
    if (now === proposedFor.current || state.roleTargets.length === 0) {
      asking.current += 1
      setProposing(false)
      return
    }
    const mine = ++asking.current
    setProposing(true)
    const timer = setTimeout(() => {
      call<{ keywords?: string[]; topic_terms?: string[] }>('keywords', { role_targets: state.roleTargets, languages: state.languages }).then(
        (r) => {
          if (mine !== asking.current) return
          proposedFor.current = now
          dispatch({ type: 'keywords', keywords: r.keywords ?? [], topicTerms: r.topic_terms ?? [] })
          setProposing(false)
        },
        (e) => {
          if (mine !== asking.current) return
          proposedFor.current = now
          dispatch({ type: 'skipKeywords', warning: errorText(e) })
          setProposing(false)
        },
      )
    }, TERMS_DEBOUNCE_MS)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.roleTargets])
  return proposing
}

/** Why a reading step came back empty, in a line. */
function Warning({ text }: { text?: string }) {
  return text ? <p className="small muted">{named(text)}</p> : null
}

/** What the review says when Save did not get through, by the step that failed. */
const SAVE_FAILED: Record<'cv' | 'read', string> = {
  cv: 'Your answers are saved, but the CV was not: ',
  read: 'Your answers and CV are saved, but they could not be read back: ',
}

interface Props {
  state: WizardState
  profile: ShowProfile
  dispatch: Dispatch<Action>
  onSaved: (profile: ShowProfile) => void
  onBack?: () => void
}

/** One review with everything inferred, editable in place. Only Save writes. */
export function Review({ state, profile, dispatch, onSaved, onBack }: Props) {
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [legalOpen, setLegalOpen] = useState(false)
  // Why the file dialog's pick was refused (the type or size), under the photo like a refusal on Save.
  const [photoNote, setPhotoNote] = useState<string | null>(null)
  const proposing = useTermsFollowTitles(state, dispatch)
  const { warnings } = state
  // Open from the start when there is no CV, and left open while the user types one.
  const [cvOpen] = useState(() => !hasOwnCv(state, profile))
  // Formatted first, so a CV can be checked without knowing Markdown; with nothing to format, the box.
  const [cvRaw, setCvRaw] = useState(() => !state.cvText)
  const cvBox = useRef<HTMLTextAreaElement>(null)
  const gapToSelect = useRef<number | null>(null)
  const goToGap = (n: number) => {
    gapToSelect.current = n
    setCvRaw(true)
  }
  // A marker's gap selected in the box, so typing replaces it. A box this size scrolls: the gap is brought into view.
  useEffect(() => {
    const box = cvBox.current
    const at = gapToSelect.current === null ? undefined : todoOffsets(box?.value ?? '')[gapToSelect.current]
    gapToSelect.current = null
    if (!box || at === undefined) return
    box.setSelectionRange(at, at + 'TODO'.length)
    box.focus()
    box.scrollTop = (box.scrollHeight * at) / box.value.length - box.clientHeight / 2
  }, [cvRaw])
  const problem = proposing ? 'Choosing search terms for your titles…' : reviewProblem(state, profile)
  const sources = discoveryFor(state)
  const fresh = state.mode === 'fresh'
  const errors = (section: ReviewSection) => state.errors[section]
  const empty = (state.cvDraft?.sources ?? []).filter((s) => s.chars === 0)
  const unfound = stillUnfound(state)

  const save = async () => {
    setSaving(true)
    setSaveError(null)
    const result = await saveProfile(state)
    setSaving(false)
    if (result.ok) onSaved(result.profile)
    else if (result.kind === 'fields') dispatch({ type: 'saveFailed', error: result.error })
    else if (result.kind === 'photo') dispatch({ type: 'photoFailed', error: result.error })
    else if (result.kind === 'story') dispatch({ type: 'storyFailed', error: result.error })
    else setSaveError(SAVE_FAILED[result.kind] + result.error)
  }

  const policy = photoPolicy(profile.options, state.location)
  const kept = profile.photo?.exists === true
  // Asked only where the country's CVs may carry one, or when there is one to change or remove.
  const askPhoto = policy !== 'no' || kept || state.photo.kind === 'new'
  const choosePhoto = async () => {
    setPhotoNote(null)
    const picked = await window.door.pickPhoto()
    if ('token' in picked) dispatch({ type: 'photo', choice: { kind: 'new', token: picked.token, name: picked.name } })
    else if ('error' in picked) setPhotoNote(picked.error)
  }
  const photoErrors = [...(photoNote ? [photoNote] : []), ...(errors('photo') ?? [])]

  return (
    <Frame
      title="Check your answers"
      lead={fresh ? 'Nothing is saved yet. Save puts it in place and starts your first search.' : 'Nothing is saved yet. Save puts it in place.'}
      errors={errors('review')}
      onBack={onBack}
      onNext={() => void save()}
      nextLabel={fresh ? 'Save and start searching' : 'Save'}
      nextDisabled={problem !== null}
      reason={problem ?? undefined}
      busy={saving}
    >
      {legalOpen && <DocDialog doc={LEGAL_DISCLAIMER} onClose={() => setLegalOpen(false)} />}
      {unfound.length > 0 && <p className="notice body">{named(`These could not be found in your sources: ${unfound.join(', ')}. Fill them in below to finish.`)}</p>}
      <Part title="You" messages={errors('you')}>
        <Warning text={warnings.basics && `Claude could not read your details: ${warnings.basics}`} />
        <TextField label="Name" value={state.name} onChange={(v) => dispatch({ type: 'set', field: 'name', value: v })} autoComplete="name" />
        <TextField label="Email" value={state.email} onChange={(v) => dispatch({ type: 'set', field: 'email', value: v })} type="email" autoComplete="email" />
        <CityField location={state.location} onChange={(v) => dispatch({ type: 'set', field: 'location', value: v })} options={profile.options} />
        {state.unsupportedLocation && state.location.trim() === '' && (
          <p className="notice small">{named(`Your CV says ${state.unsupportedLocation}, which isn't covered yet. Choose a city, or keep yours under Other…: only the worldwide job boards are searched then.`)}</p>
        )}
        <fieldset className="choices onb-field">
          <legend className="field-label">Where you would work</legend>
          {REMOTE.map((r) => (
            <label key={r.value} className="choice">
              <input type="radio" name="remote" checked={state.remote === r.value} onChange={() => dispatch({ type: 'set', field: 'remote', value: r.value })} />
              <span>{r.word}</span>
            </label>
          ))}
        </fieldset>
        {askPhoto && (
          <PhotoField
            src={state.photo.kind === 'keep' && kept ? 'door-file://profile/photo.jpg' : null}
            pending={state.photo.kind === 'new' ? state.photo.name : null}
            help={photoHelp(policy)}
            error={photoErrors.join(' ') || null}
            onChoose={() => void choosePhoto()}
            onRemove={() => {
              setPhotoNote(null)
              dispatch({ type: 'photo', choice: state.photo.kind === 'keep' && kept ? { kind: 'none' } : { kind: 'keep' } })
            }}
          />
        )}
        <fieldset className="choices onb-field">
          <legend className="field-label">Languages of the job ads</legend>
          {profile.options.languages.map((l) => (
            <label key={l} className="choice">
              <input type="checkbox" checked={state.languages.includes(l)} onChange={(e) => dispatch({ type: e.target.checked ? 'add' : 'drop', list: 'languages', value: l })} />
              <span>{l}</span>
            </label>
          ))}
        </fieldset>
      </Part>

      <Part title="Titles" lead="The job titles to look for" messages={errors('titles')}>
        <Warning text={warnings.titles && `Claude could not suggest titles: ${warnings.titles}`} />
        {state.titles.length > 0 && (
          <fieldset className="choices onb-field" aria-label="The job titles to look for">
            {state.titles.map((t) => (
              <label key={t.title} className="choice">
                <input type="checkbox" checked={state.roleTargets.includes(t.title)} onChange={() => dispatch({ type: 'toggleTitle', title: t.title })} />
                <span>
                  {t.title} <span className="small muted">{t.reason}</span>
                </span>
              </label>
            ))}
          </fieldset>
        )}
        <ChipInput label="Add your own title" hideLabel placeholder="Add your own title and press Enter" values={ownTitles(state)} onAdd={(v) => dispatch({ type: 'addTitle', title: v })} onDrop={(v) => dispatch({ type: 'dropTitle', title: v })} />
      </Part>

      <Part title="Sectors" lead="Optional: the kinds of employer you want, and any to avoid, in your own words. E.g. medical and green energy; not banking or gambling." messages={errors('sectors')}>
        <textarea className="onb-input onb-field" aria-label="Sectors" rows={3} value={state.sectors} onChange={(e) => dispatch({ type: 'set', field: 'sectors', value: e.target.value })} />
      </Part>

      <Folded
        title="Search"
        summary={proposing ? 'Choosing them…' : state.keywords.length > 0 ? `${state.keywords.length} search terms, ${state.topicTerms.length} title terms` : 'Your titles, as they are'}
        open={Boolean(errors('terms') || warnings.terms)}
        messages={errors('terms')}
      >
        <Warning text={warnings.terms && `Claude could not propose search terms, so your titles are searched as they are: ${warnings.terms}`} />
        <ChipInput label="Search terms" placeholder="Add a term and press Enter" values={state.keywords} onAdd={(v) => dispatch({ type: 'add', list: 'keywords', value: v })} onDrop={(v) => dispatch({ type: 'drop', list: 'keywords', value: v })} hint="What the job boards are searched for." />
        <ChipInput label="Title terms" placeholder="Add a word and press Enter" values={state.topicTerms} onAdd={(v) => dispatch({ type: 'add', list: 'topicTerms', value: v })} onDrop={(v) => dispatch({ type: 'drop', list: 'topicTerms', value: v })} hint="Words that make a job title on topic, in every ad language." />
      </Folded>

      <Folded title="CV" summary={cvOverview(state, profile)} open={cvOpen || Boolean(errors('cv'))} messages={errors('cv')}>
        <Switch label="Preview" checked={!cvRaw} onChange={(on) => setCvRaw(!on)} />
        {cvRaw ? (
          <div className="field onb-field">
            <FieldLabel
              htmlFor="cv-text"
              label="Your CV"
              help={profile.cv.exists && !profile.cv.is_example ? (state.cvText ? 'The CV you have now is kept as cv.md.bak.' : 'Leave this empty to keep the CV you have.') : undefined}
              after={<span className="field-label">(<MarkdownLink />)</span>}
            />
            <textarea ref={cvBox} id="cv-text" className="cv-text" rows={16} value={state.cvText ?? ''} onChange={(e) => dispatch({ type: 'set', field: 'cvText', value: e.target.value === '' ? null : e.target.value })} />
          </div>
        ) : state.cvText ? (
          <Markdown text={state.cvText} className="cv-preview" onGap={goToGap} />
        ) : (
          <p className="small muted">Nothing here yet.</p>
        )}
        {empty.length > 0 && (
          <ul className="small" aria-label="Files without text">
            {empty.map((s, i) => (
              <li key={i}>{`${basename(s.source)}: no text found in this file (a scanned PDF?)`}</li>
            ))}
          </ul>
        )}
      </Folded>

      {state.story && (
        <Part
          title="Your story bank"
          messages={errors('story')}
          lead="Your CV lists what you did. A story tells what was behind it, and the tailor draws on it when it writes an application. Here is one from your CV: fill in what the CV could not say. Add more later in Profile → Stories."
        >
          <label className="choice">
            <input type="checkbox" checked={state.story.keep} onChange={(e) => dispatch({ type: 'keepStory', keep: e.target.checked })} />
            <span>Keep this story</span>
          </label>
          {state.story.keep && <Fields values={state.story.values} onChange={(values) => dispatch({ type: 'story', values })} />}
        </Part>
      )}

      {sources.length > 0 && (
        <Part
          title="Where to find employers"
          messages={errors('employers')}
          lead={
            <>
              <AppName /> can read these sites&apos; public job search, logged out and slowly, to find employers. Each stays off unless you tick it, and ticking one is your decision, at your own risk: read the{' '}
              <button type="button" className="link-inline" onClick={() => setLegalOpen(true)}>
                legal disclaimer
              </button>
              .
            </>
          }
        >
          <fieldset className="choices onb-field" aria-label="Find employers on">
            {sources.map((d) => (
              <div key={d.key}>
                <label className="choice">
                  <input
                    type="checkbox"
                    checked={d.on}
                    aria-describedby={d.disclaimer ? `disclaimer-${d.key}` : undefined}
                    onChange={(e) => dispatch({ type: 'discovery', key: d.key, value: e.target.checked })}
                  />
                  <span>{d.label}</span>
                </label>
                {d.disclaimer && (
                  <p id={`disclaimer-${d.key}`} className="small muted">
                    {d.disclaimer}
                  </p>
                )}
              </div>
            ))}
          </fieldset>
        </Part>
      )}

      {saving && <Spinner message="Saving…" />}
      {saveError && (
        <p role="alert" className="error">
          {named(saveError)}
        </p>
      )}
    </Frame>
  )
}
