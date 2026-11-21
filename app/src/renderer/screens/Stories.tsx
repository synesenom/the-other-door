import { useEffect, useId, useState } from 'react'
import { ErrorBox, named } from './AppName'
import { call, errorText } from '../api'
import { Dialog } from './Dialog'
import { Spinner } from './Spinner'

interface Story {
  title: string
  context: string
  action: string
  result: string
  learning: string
}
interface Bank {
  exists: boolean
  stories: Story[]
}
interface Draft extends Story {
  missing?: string[]
  conflicts?: string[]
}
/** What a form holds: the title and the four CARL texts. */
export type Values = Record<(typeof TEXT)[number] | 'title', string>

const TEXT = ['context', 'action', 'result', 'learning'] as const
const LABEL: Record<string, string> = { title: 'Title', context: 'Context', action: 'Action', result: 'Result', learning: 'Learning' }

const toValues = (s: Story | Draft): Values => ({ title: s.title, context: s.context, action: s.action, result: s.result, learning: s.learning })
const complete = (v: Values) => [v.title, ...TEXT.map((k) => v[k])].every((x) => x.trim() !== '')
const missingOf = (v: Values) => ['title', ...TEXT].filter((k) => !(v as Record<string, string>)[k]!.trim())

/** The title and four texts, in place. */
export function Fields({ values, onChange }: { values: Values; onChange: (v: Values) => void }) {
  const id = useId()
  const set = (k: keyof Values, v: string) => onChange({ ...values, [k]: v })
  return (
    <div className="stories-fields">
      <div className="field onb-field">
        <label htmlFor={`${id}-title`} className="field-label">
          {LABEL.title}
        </label>
        <input id={`${id}-title`} className="onb-input" value={values.title} onChange={(e) => set('title', e.target.value)} />
      </div>
      {TEXT.map((k) => (
        <div className="field onb-field" key={k}>
          <label htmlFor={`${id}-${k}`} className="field-label">
            {LABEL[k]}
          </label>
          {/* two lines, fixed: a part of a story is a sentence or two, all of it in view */}
          <textarea id={`${id}-${k}`} className="onb-input" rows={2} value={values[k]} onChange={(e) => set(k, e.target.value)} />
        </div>
      ))}
    </div>
  )
}

const saveArgs = (v: Values, extra: Record<string, unknown> = {}) => ({ title: v.title.trim(), context: v.context, action: v.action, result: v.result, learning: v.learning, ...extra })

type View =
  | { kind: 'list' }
  | { kind: 'form'; old: string; values: Values }
  | { kind: 'text'; text: string; drafting: boolean }
  // the story a text was drafted into, in the same dialog
  | { kind: 'draft'; values: Values; conflicts: string[] }

/**
 * Profile's Stories: the story bank the tailor draws on (profile/story_bank.md). See, edit, and write a story: the
 * text is drafted into the one story it tells, shown in its four parts in the same dialog to check and save. Every rule
 * (what a story needs) is the server's; this only asks and shows.
 */
export function Stories() {
  const [bank, setBank] = useState<Bank | null>(null)
  const [view, setView] = useState<View>({ kind: 'list' })
  const [error, setError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [removing, setRemoving] = useState<Story | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let live = true
    call<Bank>('list_stories').then(
      (r) => live && setBank(r),
      // only a first read that failed is said: a re-read after a change keeps the bank shown
      (e) => live && setLoadError(errorText(e)),
    )
    return () => {
      live = false
    }
  }, [tick])

  const reload = () => setTick((t) => t + 1)
  const back = () => {
    setView({ kind: 'list' })
    setError(null)
  }

  /** Save an edited story in place of the one titled `old`. */
  const saveOne = async (old: string, v: Values) => {
    setBusy(true)
    setError(null)
    try {
      await call('save_story', saveArgs(v, { replace: old }))
      setNote(`Saved ${v.title.trim()}.`)
      back()
      reload()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (s: Story) => {
    setRemoving(null)
    setError(null)
    // the story leaving the list says it; an earlier note ("Added …") would be stale
    setNote(null)
    try {
      await call('remove_story', { title: s.title })
      reload()
    } catch (e) {
      setError(errorText(e))
    }
  }

  const draft = async (text: string) => {
    setView({ kind: 'text', text, drafting: true })
    setError(null)
    setNote(null)
    try {
      const r = await call<{ outcome: string; stories: Draft[] }>('draft_stories', { text })
      const story = r.stories?.[0]
      if (!story) {
        setNote(r.outcome === 'nothing_new' ? 'Nothing new to propose.' : 'No story could be drafted.')
        setView({ kind: 'list' })
        return
      }
      setView({ kind: 'draft', values: toValues(story), conflicts: story.conflicts ?? [] })
    } catch (e) {
      setError(errorText(e))
      setView({ kind: 'text', text, drafting: false })
    }
  }

  const saveDraft = async (values: Values) => {
    setBusy(true)
    setError(null)
    try {
      await call('save_story', saveArgs(values))
      setNote(`Added ${values.title.trim()}.`)
      back()
      reload()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  // the bank is all this part shows: one that could not be read says so (docs/design/README.md, principle 9)
  if (loadError && !bank)
    return (
      <ErrorBox text={loadError} />
    )
  if (!bank) return <Spinner message="Reading your story bank…" />

  // a draft, a save or a removal that failed: the error box, not a field's line; the user can try again
  const errorLine = error && (
    <ErrorBox text={error} />
  )

  // edited in a dialog over the list, the story it came from still in view behind it
  const form = view.kind === 'form' && (
    <Dialog title="Edit story" onClose={back}>
      <Fields values={view.values} onChange={(v) => setView({ ...view, values: v })} />
      {errorLine}
      <div className="actions">
        <button type="button" className="quiet" onClick={back}>
          Cancel
        </button>
        <button type="button" className="primary" disabled={busy || !complete(view.values)} onClick={() => void saveOne(view.old, view.values)}>
          Save
        </button>
      </div>
    </Dialog>
  )

  // one text box and "Draft it": a dialog over the list, where the draft is then checked and saved
  const writing = view.kind === 'text' && (
    <Dialog title="Write a story" onClose={back} initialFocus="textarea">
      {view.drafting ? (
        <Spinner message="Drafting your story (a minute or two)…" />
      ) : (
        <>
          <div className="field onb-field">
            <label htmlFor="stories-text" className="field-label">
              What did you do?
            </label>
            <textarea id="stories-text" className="onb-input" rows={6} value={view.text} onChange={(e) => setView({ kind: 'text', text: e.target.value, drafting: false })} />
          </div>
          {errorLine}
          <div className="actions">
            <button type="button" className="quiet" onClick={back}>
              Cancel
            </button>
            <button type="button" className="primary" disabled={!view.text.trim()} onClick={() => void draft(view.text)}>
              Draft it
            </button>
          </div>
        </>
      )}
    </Dialog>
  )

  // the drafted story in its four parts, in the same dialog: only what the text says, to fill in and correct
  const missing = view.kind === 'draft' ? missingOf(view.values) : []
  const drafted = view.kind === 'draft' && (
    <Dialog title="Your story" onClose={back}>
      <p className="small muted">Only what your text says. Fill in what is empty and change what is off.</p>
      {view.conflicts.map((c) => <p key={c} className="small field-error">{`Differs from your CV: ${c}`}</p>)}
      {missing.length > 0 && <p className="small field-error">{`Still to fill in: ${missing.join(', ')}`}</p>}
      <Fields values={view.values} onChange={(values) => setView({ ...view, values })} />
      {errorLine}
      <div className="actions">
        <button type="button" className="quiet" onClick={back}>
          Cancel
        </button>
        <button type="button" className="primary" disabled={busy || !complete(view.values)} onClick={() => void saveDraft(view.values)}>
          Save
        </button>
      </div>
    </Dialog>
  )

  return (
    <div className="stories">
      <p className="small muted">The stories the tailor draws on for your applications: the context, what you did, what came of it and what you learned.</p>
      {/* one way in: writing a story. Not drafted from the CV: a story adds what the CV does not say */}
      <div className="actions stories-add">
        <button type="button" className="primary" onClick={() => { setNote(null); setError(null); setView({ kind: 'text', text: '', drafting: false }) }}>
          Write a story
        </button>
      </div>
      {note && <p className="small">{named(note)}</p>}
      {!form && !writing && !drafted && errorLine}
      {bank.stories.length === 0 ? (
        <p className="small muted">No stories yet. Write one about something your CV only lists: what was going on, what you did, what came of it.</p>
      ) : (
        <ul className="story-list" aria-label="Your stories">
          {bank.stories.map((s) => (
            <li key={s.title} className="story" aria-label={s.title}>
              {/* all of it in view: the title, then the four parts, each label beside its text */}
              <span className="body story-title">{s.title}</span>
              <dl className="story-text">
                {TEXT.map((k) => (
                  <div key={k}>
                    <dt className="small muted">{LABEL[k]}</dt>
                    <dd className="small">{s[k]}</dd>
                  </div>
                ))}
              </dl>
              <div className="actions">
                <button type="button" className="secondary go" onClick={() => setView({ kind: 'form', old: s.title, values: toValues(s) })}>
                  Edit
                </button>
                <button type="button" className="secondary" onClick={() => setRemoving(s)}>
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {removing && (
        <Dialog title={`Remove ${removing.title}?`} onClose={() => setRemoving(null)}>
          <p className="body">The story leaves your story bank. Applications already prepared keep what they used.</p>
          <div className="actions">
            <button type="button" className="quiet" onClick={() => setRemoving(null)}>
              Cancel
            </button>
            <button type="button" className="primary" onClick={() => void remove(removing)}>
              Remove
            </button>
          </div>
        </Dialog>
      )}
      {form}
      {writing}
      {drafted}
    </div>
  )
}
