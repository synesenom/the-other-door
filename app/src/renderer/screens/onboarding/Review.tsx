import { useEffect, useId, useRef, useState } from 'react'
import type { Dispatch, ReactNode } from 'react'
import { AppName, ErrorBox, ErrorList, named } from '../AppName'
import { call, errorText, styleUrl } from '../../api'
import { DocDialog, LEGAL_DISCLAIMER } from '../Documentation'
import { Markdown } from '../Markdown'
import { todoOffsets } from '../todos'
import { Spinner } from '../Spinner'
import { ChipInput, CityField, FieldLabel, Frame, TextField } from './parts'
import { saveProfile } from './save'
import { discoveryFor, hasOwnCv, ownTitles, photoPolicy, reviewProblem, stillUnfound, styleSource, todoCount } from './reducer'
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
  return messages?.length ? <ErrorList messages={messages} /> : null
}

function Part({ id, title, lead, messages, children }: { id: string; title: string; lead?: ReactNode; messages?: string[]; children: ReactNode }) {
  return (
    <section className="part" aria-label={title}>
      <div className="part-head">
        <h2 className="display-s" id={id}>{title}</h2>
        {lead && <p className="small muted">{lead}</p>}
      </div>
      <Errors messages={messages} />
      {children}
    </section>
  )
}

function Folded({ id, title, summary, open, messages, children }: { id: string; title: string; summary: string; open: boolean; messages?: string[]; children: ReactNode }) {
  return (
    <details className="part" open={open || undefined}>
      <summary id={id}>
        <span className="display-s">{title}</span> <span className="small muted">{summary}</span>
      </summary>
      <Errors messages={messages} />
      {children}
    </details>
  )
}

type Look = { cv: string[]; version: string }

/** The review's two looks side by side, one chosen: the drafted CV in The other door's style, and the uploaded CV as
 * it is, whose look a build copies after Save. The pictures come once, when the part opens; without them the choice
 * stays, with names only (principle 9: nothing the user can fix). */
function StyleChoice({ token, cvText, like, onChange }: { token: string; cvText: string; like: boolean; onChange: (like: boolean) => void }) {
  const [looks, setLooks] = useState<{ draft?: Look; original?: Look } | null>(null)
  const name = useId()
  useEffect(() => {
    let live = true
    void window.door.previewStyles(token, cvText).then(
      (r) => {
        const styles = (r.ok ? (r.data as { styles?: { default?: Look; original?: Look } }).styles : undefined) ?? {}
        if (live) setLooks({ draft: styles.default, original: styles.original })
      },
      () => live && setLooks({}),
    )
    return () => {
      live = false
    }
    // once, when the review opens: the draft's look does not change with an edit of its words
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])
  const card = (which: 'draft' | 'original', label: ReactNode, text: string, on: boolean) => {
    const look = looks?.[which]
    return (
      <label className={on ? 'style-card style-current style-pick' : 'style-card style-pick'}>
        <input type="radio" className="visually-hidden" name={name} checked={on} onChange={() => onChange(which === 'original')} aria-label={text} />
        <span className="style-thumb">
          {look?.cv[0] ? <img className="paper" src={styleUrl(which, look.cv[0], look.version)} alt={`${text}, first page`} /> : <span className="style-sheet" />}
        </span>
        <span className="small style-caption">{label}</span>
      </label>
    )
  }
  return (
    <>
      <div className="style-cards" role="radiogroup" aria-label="Your CV's style">
        {card('draft', <AppName />, 'The other door', !like)}
        {card('original', 'Your CV', 'Your CV', like)}
      </div>
      {looks === null && <Spinner message="Preparing the previews…" />}
      <p className="small muted">
        {like ? 'Copying your CV’s look takes 2–5 minutes in the background after Save.' : named('Left: your CV in The other door’s style. Right: your CV as you uploaded it.')}
      </p>
    </>
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

/** The review's parts, in order, for the list beside it: the ones always there, then those this answer has. */
export function reviewSections(state: WizardState): { id: string; label: string }[] {
  return [
    { id: 'review-you', label: 'You' },
    { id: 'review-titles', label: 'Titles' },
    { id: 'review-preferences', label: 'What matters to you' },
    { id: 'review-search', label: 'Search' },
    { id: 'review-cv', label: 'CV' },
    ...(styleSource(state) ? [{ id: 'review-style', label: "Your CV's style" }] : []),
    ...(state.story ? [{ id: 'review-story', label: 'Your story bank' }] : []),
    ...(discoveryFor(state).length > 0 ? [{ id: 'review-employers', label: 'Where to find employers' }] : []),
  ]
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
      <Part id="review-you" title="You" messages={errors('you')}>
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

      <Part id="review-titles" title="Titles" lead="The job titles to look for" messages={errors('titles')}>
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

      <Part id="review-preferences" title="What matters to you" lead="Optional: in your own words, the kind of employer and job you want, and anything you rule out. E.g. medical or green energy, maybe robotics; a smaller company, little travel; not banking or gambling." messages={errors('preferences')}>
        <textarea className="onb-input onb-field" aria-label="What matters to you" rows={3} value={state.preferences} onChange={(e) => dispatch({ type: 'set', field: 'preferences', value: e.target.value })} />
      </Part>

      <Folded
        id="review-search"
        title="Search"
        summary={proposing ? 'Choosing them…' : state.keywords.length > 0 ? `${state.keywords.length} search terms, ${state.topicTerms.length} title terms` : 'Your titles, as they are'}
        open={Boolean(errors('terms') || warnings.terms)}
        messages={errors('terms')}
      >
        <Warning text={warnings.terms && `Claude could not propose search terms, so your titles are searched as they are: ${warnings.terms}`} />
        <ChipInput label="Search terms" placeholder="Add a term and press Enter" values={state.keywords} onAdd={(v) => dispatch({ type: 'add', list: 'keywords', value: v })} onDrop={(v) => dispatch({ type: 'drop', list: 'keywords', value: v })} hint="What the job boards are searched for." />
        <ChipInput label="Title terms" placeholder="Add a word and press Enter" values={state.topicTerms} onAdd={(v) => dispatch({ type: 'add', list: 'topicTerms', value: v })} onDrop={(v) => dispatch({ type: 'drop', list: 'topicTerms', value: v })} hint="Words that make a job title on topic, in every ad language." />
      </Folded>

      <Folded id="review-cv" title="CV" summary={cvOverview(state, profile)} open={cvOpen || Boolean(errors('cv'))} messages={errors('cv')}>
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

      {styleSource(state) && (
        <Part id="review-style" title="Your CV's style" lead="How your tailored CVs will look. You can change it later in Profile.">
          <StyleChoice token={styleSource(state)!} cvText={state.cvText ?? ''} like={state.style} onChange={(on) => dispatch({ type: 'style', on })} />
        </Part>
      )}

      {state.story && (
        <Part
          id="review-story"
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
          id="review-employers"
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
        <ErrorBox text={saveError} />
      )}
    </Frame>
  )
}
