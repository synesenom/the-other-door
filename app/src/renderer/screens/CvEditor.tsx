import { Fragment, useEffect, useId, useRef, useState } from 'react'
import { named } from './AppName'
import { call, errorText } from '../api'
import { Dialog } from './Dialog'
import { Market } from './Market'
import { Markdown } from './Markdown'
import { MarkdownLink } from './MarkdownHelp'
import { ChipInput } from './onboarding/parts'
import type { ShowProfile } from './onboarding/reducer'
import { Spinner } from './Spinner'
import { Switch } from './Switch'
import { todoOffsets } from './todos'

type Profile = ShowProfile & { config: (ShowProfile['config'] & { role_targets?: string[] }) | null }

interface Proposal {
  n: number
  section: string
  text: string
  source: string
}
type Enriched = { outcome: 'proposed' | 'nothing_new'; proposals: Proposal[]; unreachable: string[] }

const basename = (p: string) => p.split(/[\\/]/).pop() ?? p

/**
 * The proposals of one read, ticked by default, grouped by the CV section each would go into. Plain blocks with
 * fixed gaps, not fieldsets: a fieldset's legend is laid out by the browser's own rules, and its spacing moved.
 */
function Proposals({ proposals, dropped, showSource, onToggle }: { proposals: Proposal[]; dropped: Set<number>; showSource: boolean; onToggle: (n: number) => void }) {
  const id = useId()
  const sections = [...new Set(proposals.map((p) => p.section))]
  return (
    <div className="cv-proposals">
      {sections.map((section, i) => (
        <div key={section} role="group" aria-labelledby={`${id}-${i}`} className="cv-proposal-group">
          <p id={`${id}-${i}`} className="field-label">
            {section}
          </p>
          {proposals
            .filter((p) => p.section === section)
            .map((p) => (
              <label key={p.n} className="choice cv-proposal">
                <input type="checkbox" checked={!dropped.has(p.n)} onChange={() => onToggle(p.n)} />
                <span>
                  {p.text}
                  {showSource && <span className="small muted">{` · from ${p.source}`}</span>}
                </span>
              </label>
            ))}
        </div>
      ))}
    </div>
  )
}

/** A page as typed, with https:// in front when it has no scheme ("github.com/you"): enrich reads web addresses only. */
const webAddress = (typed: string) => (/^[a-z][a-z0-9+.-]*:\/\//i.test(typed) ? typed : `https://${typed}`)

type Step = { kind: 'ask'; url: string; refused?: string } | { kind: 'reading' } | { kind: 'read'; result: Enriched; dropped: Set<number> } | { kind: 'adding' }

/**
 * "Add a page" (`again` false), in a dialog so the CV under it stays put: one page asked for, read (`enrich` proposes what it shows and the CV lacks),
 * the ticked proposals added; a page read is remembered (profile/config.json's enrich_sources). "Check again"
 * (`again`): the remembered pages read again, for what is new on them since.
 */
function Expand({ again, pages, blocked, onRead, onClose, onAdded }: { again: boolean; pages: string[]; blocked: boolean; onRead: (url: string) => void; onClose: () => void; onAdded: (texts: string[]) => void }) {
  const [step, setStep] = useState<Step>(again ? { kind: 'reading' } : { kind: 'ask', url: '' })
  const [error, setError] = useState<string | null>(null)
  const read = async (urls: string[]) => {
    setStep({ kind: 'reading' })
    setError(null)
    try {
      const r = await call<Enriched>('enrich', { urls })
      const result = { ...r, proposals: r.proposals ?? [], unreachable: r.unreachable ?? [] }
      // a page that could be read is remembered; one that could not is asked for again
      if (!again && result.unreachable.length > 0) return setStep({ kind: 'ask', url: urls[0]!, refused: urls[0] })
      if (!again) onRead(urls[0]!)
      setStep({ kind: 'read', result, dropped: new Set() })
    } catch (e) {
      setError(errorText(e))
      setStep(again ? { kind: 'read', result: { outcome: 'nothing_new', proposals: [], unreachable: [] }, dropped: new Set() } : { kind: 'ask', url: urls[0] ?? '' })
    }
  }
  useEffect(() => {
    if (again) void read(pages)
    // once, on opening
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const add = async (chosen: number[], proposals: Proposal[]) => {
    setStep({ kind: 'adding' })
    setError(null)
    try {
      const r = await call<{ added?: Proposal[] }>('enrich', { apply: chosen })
      onAdded((r.added ?? proposals.filter((p) => chosen.includes(p.n))).map((p) => p.text))
    } catch (e) {
      setError(errorText(e))
      setStep({ kind: 'ask', url: '' })
    }
  }
  const errorLine = error && (
    <p role="alert" className="field-error">
      {named(error)}
    </p>
  )
  const label = again ? 'Check your pages again' : 'Add a page'

  if (step.kind === 'reading') return <Dialog title={label} onClose={onClose}><Spinner message={again ? 'Reading your pages again (a few minutes)…' : 'Reading the page (a few minutes)…'} /></Dialog>
  if (step.kind === 'adding') return <Dialog title={label} onClose={() => {} /* the CV is being written: it ends by itself */}><Spinner message="Adding to your CV…" /></Dialog>
  if (step.kind === 'ask') {
    const url = step.url.trim()
    return (
      <Dialog title={label} onClose={onClose}>
        <div className="field onb-field">
          <label htmlFor="cv-page" className="field-label">
            Which page?
          </label>
          <input
            id="cv-page"
            className="onb-input"
            type="url"
            placeholder="github.com/you, your portfolio, a publication list"
            value={step.url}
            onChange={(e) => setStep({ kind: 'ask', url: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && url) void read([webAddress(url)])
            }}
          />
          {step.refused && <p className="field-error">{`Could not read ${step.refused}.`}</p>}
        </div>
        {errorLine}
        <div className="actions">
          <button type="button" className="quiet" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!url} onClick={() => void read([webAddress(url)])}>
            Read it
          </button>
        </div>
      </Dialog>
    )
  }
  const { result, dropped } = step
  const chosen = result.proposals.map((p) => p.n).filter((n) => !dropped.has(n))
  return (
    <Dialog title={label} onClose={onClose}>
      {result.unreachable.length > 0 && <p className="small muted">{`Could not read: ${result.unreachable.join(', ')}`}</p>}
      {errorLine}
      {result.proposals.length === 0 ? (
        <>
          {!error && <p className="body">{again ? 'Nothing new on your pages.' : 'Nothing on that page is missing from your CV.'}</p>}
          <div className="actions">
            <button type="button" className="secondary" onClick={onClose}>
              Close
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="small muted">What your CV does not have yet. Untick what should not go in.</p>
          <Proposals
            proposals={result.proposals}
            dropped={dropped}
            showSource={again && pages.length > 1}
            onToggle={(n) => {
              const next = new Set(dropped)
              if (next.has(n)) next.delete(n)
              else next.add(n)
              setStep({ ...step, dropped: next })
            }}
          />
          <div className="actions">
            <button type="button" className="quiet" onClick={onClose}>
              Cancel
            </button>
            <button type="button" className="primary" disabled={chosen.length === 0 || blocked} onClick={() => void add(chosen, result.proposals)}>
              {`Add ${chosen.length} to my CV`}
            </button>
          </div>
        </>
      )}
    </Dialog>
  )
}

/** "What should I learn?": `skill_gaps` compares the CV with roles (and the best matches) and writes a plan. */
function Gaps({ roles }: { roles: string[] }) {
  const [targets, setTargets] = useState(roles)
  const [withMatches, setWithMatches] = useState(false)
  const [state, setState] = useState<{ kind: 'idle' } | { kind: 'working' } | { kind: 'done'; report: string; path: string } | { kind: 'error'; message: string }>({ kind: 'idle' })
  const id = useId()
  const run = async () => {
    setState({ kind: 'working' })
    try {
      const r = await call<{ report?: string; report_path: string }>('skill_gaps', { targets, ...(withMatches ? { top: 3 } : {}) })
      setState({ kind: 'done', report: r.report ?? '', path: r.report_path })
    } catch (e) {
      setState({ kind: 'error', message: errorText(e) })
    }
  }
  return (
    <section className="cv-panel" aria-labelledby="cv-gaps">
      <h2 className="label" id="cv-gaps">
        What should I learn?
      </h2>
      {state.kind === 'working' ? (
        <Spinner message="Comparing your CV with the roles and looking for courses (several minutes)…" />
      ) : state.kind === 'done' ? (
        <>
          <Markdown text={state.report} className="cv-report" />
          <p className="small muted">{`Saved as ${basename(state.path)} in upskill/.`}</p>
          <div className="actions">
            <button type="button" className="quiet" onClick={() => setState({ kind: 'idle' })}>
              Make another plan
            </button>
          </div>
        </>
      ) : (
        <>
          <ChipInput label="Roles or skills" placeholder="Add one and press Enter" values={targets} hint="What you want to be ready for." onAdd={(v) => !targets.includes(v.trim()) && setTargets([...targets, v.trim()])} onDrop={(v) => setTargets(targets.filter((t) => t !== v))} />
          <label className="choice" htmlFor={id}>
            <input id={id} type="checkbox" checked={withMatches} onChange={(e) => setWithMatches(e.target.checked)} />
            <span>Also my three best matches</span>
          </label>
          <div className="actions">
            <button type="button" className="secondary" disabled={targets.length === 0 && !withMatches} onClick={() => void run()}>
              Make my plan
            </button>
            <p className="small muted">One Claude call on your plan, with web search for courses.</p>
          </div>
          {state.kind === 'error' && (
            <p role="alert" className="field-error">
              {named(state.message)}
            </p>
          )}
        </>
      )}
    </section>
  )
}

/**
 * Your CV (profile/cv.md): edited as Markdown, with a preview. Save goes through save_cv, which keeps the
 * previous version as cv.md.bak. "Add a page" is /expand as a button; drafting from a CV file is
 * the first launch's CV step (`onDraft`). `extras`: "What should I learn?" (/upskill) and the market report,
 * off for now (issue 480: they crowd the page; features to turn on later).
 */
export function CvEditor({
  onDraft,
  onSaved,
  onSearchChanged,
  unsaved = null,
  onUnsaved,
  extras = false,
}: {
  onDraft: () => void
  /** cv.md was written: what reads the profile (the sidebar's "no CV yet") reads it again. */
  onSaved?: () => void
  onSearchChanged?: () => void
  /** Text typed and not saved when the editor was last shown (Profile keeps it while Details is shown). */
  unsaved?: string | null
  onUnsaved?: (text: string | null) => void
  extras?: boolean
}) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saved, setSaved] = useState('')
  const [text, setText] = useState('')
  const [view, setView] = useState<'edit' | 'preview'>('edit')
  const [panel, setPanel] = useState<null | 'page' | 'again' | 'gaps'>(null)
  // The pages read before (enrich_sources): remembered when one is read, forgotten by its ×, each saved at once.
  const [pages, setPages] = useState<string[] | null>(null)
  const [pagesError, setPagesError] = useState<string | null>(null)
  // What "What should I learn?" starts from: the role targets, or the skills the market report found missing.
  const [planFor, setPlanFor] = useState<{ n: number; skills: string[] } | null>(null)
  // What the last "Add … to my CV" put in: tinted in the preview until the next edit or save.
  const [added, setAdded] = useState<string[] | null>(null)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const editorId = useId()
  // A preview marker opens the editor with its gap selected, so typing replaces it (as the onboarding review does).
  const box = useRef<HTMLTextAreaElement>(null)
  // the tinted copy behind the editor (what was just added), kept at the editor's scroll
  const backdrop = useRef<HTMLDivElement>(null)
  const gapToSelect = useRef<number | null>(null)
  const goToGap = (n: number) => {
    gapToSelect.current = n
    setView('edit')
  }
  useEffect(() => {
    const el = box.current
    const at = gapToSelect.current === null ? undefined : todoOffsets(el?.value ?? '')[gapToSelect.current]
    gapToSelect.current = null
    if (!el || at === undefined) return
    el.setSelectionRange(at, at + 'TODO'.length)
    el.focus()
    el.scrollTop = (el.scrollHeight * at) / el.value.length - el.clientHeight / 2
  }, [view])

  // While lines are marked as added: bring the first into view, once the new CV is read and again whenever the
  // view switches between the editor and the preview.
  useEffect(() => {
    if (!added?.length) return
    const line = `- ${added[0]!.trim()}`
    if (!text.includes(line)) return
    const el = box.current
    if (el) {
      // the editor may scroll inside (a long CV) and the page around it: first the editor, then the page
      el.scrollTop = (el.scrollHeight * text.indexOf(line)) / el.value.length - el.clientHeight / 3
      if (backdrop.current) backdrop.current.scrollTop = el.scrollTop
      const mark = backdrop.current?.querySelector('.md-added')
      const page = document.querySelector('.main')
      if (mark && page) page.scrollBy?.({ top: mark.getBoundingClientRect().top - page.clientHeight / 2 })
    } else document.querySelector('.cv-preview .md-added')?.scrollIntoView?.({ block: 'center' })
  }, [added, view, text.includes(`- ${added?.[0]?.trim()}`)])

  const load = async (first = false) => {
    try {
      const p = await call<Profile>('show_profile')
      setProfile(p)
      setPages((had) => had ?? (p as Profile).config?.enrich_sources ?? p.enrich_sources ?? [])
      setSaved(p.cv.text ?? '')
      setText(first && unsaved !== null ? unsaved : (p.cv.text ?? ''))
    } catch (e) {
      setLoadError(errorText(e))
    }
  }
  useEffect(() => {
    void load(true)
  }, [])

  const dirty = text !== saved
  useEffect(() => {
    if (profile) onUnsaved?.(dirty ? text : null)
  }, [profile, text, saved])
  const save = async () => {
    setSaving(true)
    setError(null)
    setMessage(null)
    setAdded(null)
    try {
      const r = await call<{ backup?: string | null }>('save_cv', { markdown: text })
      await load()
      setMessage(r.backup ? 'Saved. The previous version is kept as cv.md.bak.' : 'Saved.')
      onSaved?.()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setSaving(false)
    }
  }

  if (loadError) return <p role="alert" className="error">{named(loadError)}</p>
  if (!profile) return <Spinner message="Reading your CV…" />
  const keepPages = async (next: string[]) => {
    setPages(next)
    setPagesError(null)
    try {
      await call('init_profile', { other: { enrich_sources: next } })
    } catch (e) {
      setPagesError(errorText(e))
    }
  }
  const remembered = pages ?? []
  return (
    <div className="cv-editor">
      {/* the wizard may end with no CV; the example CV is never copied in, so only a developer's hand-made profile has it */}
      {!profile.cv.exists && (
        <div role="note" className="cv-example small">
          <span>You have no CV yet. Write it here, or </span>
          <button type="button" className="link-inline" onClick={onDraft}>
            Draft it from your CV file or pages
          </button>
        </div>
      )}
      {profile.cv.exists && profile.cv.text === null && (
        <p role="note" className="cv-example small">
          profile/cv.md could not be read as text (it may be in another encoding, or not text at all). What you save here replaces it; the file as it is now is kept as cv.md.bak.
        </p>
      )}
      {/* the pages the CV is read from, above it: each can be forgotten; a page added, or all read again, by the buttons under them */}
      {remembered.length > 0 && (
        <div className="cv-pages">
          <span className="field-label cv-pages-label">Pages</span>
          <ul className="cv-pages-list" aria-label="Pages your CV is read from">
            {remembered.map((u) => (
              <li key={u} className="chip small">
                <span className="chip-text" title={u}>
                  {u.replace(/^https?:\/\//, '')}
                </span>
                <button type="button" className="chip-x" aria-label={`Forget ${u}`} onClick={() => void keepPages(remembered.filter((x) => x !== u))}>
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="actions">
        <button type="button" className="secondary" disabled={dirty} onClick={() => { setMessage(null); setPanel('page') }}>
          Add a page
        </button>
        {remembered.length > 0 && (
          <button type="button" className="secondary" disabled={dirty} onClick={() => { setMessage(null); setPanel('again') }}>
            Check again
          </button>
        )}
      </div>
      {dirty && <p className="small muted">Save or undo your changes before adding from a page.</p>}
      {pagesError && (
        <p role="alert" className="field-error">
          {named(pagesError)}
        </p>
      )}
      {(panel === 'page' || panel === 'again') && (
        <Expand
          key={panel}
          again={panel === 'again'}
          pages={remembered}
          blocked={dirty}
          onRead={(url) => !remembered.includes(url) && void keepPages([...remembered, url])}
          onClose={() => setPanel(null)}
          onAdded={(texts) => {
            setPanel(null)
            void load()
            setAdded(texts)
          }}
        />
      )}
      {/* the CV: its name, with the Preview switch on the right, then the text or how it reads */}
      <div className="cv-head">
        <div className="field-name">
          <label htmlFor={editorId} className="field-label">
            Your CV
          </label>
          {/* a link like the pages' ones: small, not the label's weight */}
          <span className="small muted">
            (<MarkdownLink />)
          </span>
        </div>
        <Switch label="Preview" checked={view === 'preview'} onChange={(on) => setView(on ? 'preview' : 'edit')} />
      </div>
      {view === 'edit' ? (
        // an added line is a bullet, "- text", under its section: the copy behind the editor tints those lines
        <div className="cv-text-wrap">
          {added && added.length > 0 && (
            <div ref={backdrop} className="cv-text cv-backdrop" aria-hidden="true">
              {text.split('\n').map((line, i) => (
                <Fragment key={i}>
                  {added.some((a) => line.trim() === `- ${a.trim()}`) ? <mark className="md-added">{line}</mark> : line}
                  {'\n'}
                </Fragment>
              ))}
            </div>
          )}
          <textarea ref={box} id={editorId} aria-label="Your CV (Markdown)" className="cv-text" spellCheck value={text}
            onScroll={(e) => backdrop.current && (backdrop.current.scrollTop = e.currentTarget.scrollTop)}
            onChange={(e) => {
              setMessage(null)
              setAdded(null)
              setText(e.target.value)
            }} />
        </div>
      ) : (
        <Markdown text={text} className="cv-preview" onGap={goToGap} marked={added ?? undefined} />
      )}
      <div className="profile-save">
        {/* always there, so Save does not move when the first change makes Undo possible */}
        <button type="button" className="quiet" disabled={!dirty || saving} onClick={() => setText(saved)}>
          Undo changes
        </button>
        <button type="button" className="primary" disabled={!dirty || saving || text.trim() === ''} onClick={() => void save()}>
          Save
        </button>
        {saving ? <Spinner message="Saving…" /> : message ? <p className="small">{message}</p> : dirty ? <p className="small muted">Unsaved changes</p> : null}
        {error && (
          <p role="alert" className="field-error">
            {named(error)}
          </p>
        )}
      </div>
      {extras && (
        <div className="actions cv-tools">
          <button type="button" className="secondary" aria-expanded={panel === 'gaps'} onClick={() => {
              setPlanFor(null) // from here it starts from your role targets
              setPanel(panel === 'gaps' ? null : 'gaps')
            }}>
            What should I learn?
          </button>
        </div>
      )}
      {panel === 'gaps' && <Gaps key={planFor?.n ?? -1} roles={planFor ? planFor.skills : (profile.config?.role_targets ?? [])} />}
      {extras && (
        <Market
          onSearchChanged={onSearchChanged}
          onPlan={(skills) => {
            setPlanFor((p) => ({ n: (p?.n ?? 0) + 1, skills }))
            setPanel('gaps')
          }}
        />
      )}
    </div>
  )
}
