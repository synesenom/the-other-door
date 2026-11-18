import { Fragment, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { ErrorBox } from './AppName'
import { call, draftCv, errorText } from '../api'
import { Dialog } from './Dialog'
import { Hint } from './Hint'
import { Markdown } from './Markdown'
import { MarkdownLink } from './MarkdownHelp'
import type { ShowProfile } from './onboarding/reducer'
import { Spinner } from './Spinner'
import { StyleRow } from './StyleRow'
import { todoOffsets } from './todos'

type Profile = ShowProfile & { config: (ShowProfile['config'] & { role_targets?: string[] }) | null }

interface Proposal {
  n: number
  section: string
  text: string
  source: string
}
type Enriched = { outcome: 'proposed' | 'nothing_new'; proposals: Proposal[]; unreachable: string[] }


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
    <ErrorBox text={error} />
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

/** A field's name with what it means in the info bubble beside it: a label of its control, or (`id`) of a group. */
function FieldName({ label, help, after, htmlFor, id }: { label: string; help: string; after?: ReactNode; htmlFor?: string; id?: string }) {
  return (
    <div className="field-name">
      {htmlFor ? (
        <label htmlFor={htmlFor} className="field-label">
          {label}
        </label>
      ) : (
        <span id={id} className="field-label">
          {label}
        </span>
      )}
      {after}
      <Hint label={`About ${label}`}>{help}</Hint>
    </div>
  )
}

/**
 * Profile's "Master CV" and "CV style". Master CV: the CV file a draft read, replaced by drafting from another, the pages
 * the CV is read from ("Add a page" is /expand as a button), then profile/cv.md as Markdown with a preview. The text
 * saves itself a second after typing stops, and when the editor is left: no Save. The first save of a visit keeps the
 * CV as it was as cv.md.bak; the later ones leave that backup alone (save_cv's `backup`).
 */
/** How long typing must stop before the text is written. */
export const SAVE_AFTER_MS = 1000

export function CvEditor({
  onDraft,
  onSaved,
  style,
}: {
  onDraft: () => void
  /** cv.md was written and the editor left (or the first CV written): what reads the profile (the sidebar's "no CV
   * yet") reads it again. */
  onSaved?: () => void
  /** The CV style: how its build stands (the sidebar's summary), whether one can be built here (not on made-up data),
   * and what to tell the app when a build starts or a style is chosen. */
  style?: { state: 'none' | 'building' | 'ready' | 'failed' | null; canBuild: boolean; onChanged: () => void }
}) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saved, setSaved] = useState('')
  const [text, setText] = useState('')
  // read: the CV as it reads, Edit opens the text; a CV that opens empty has nothing to read and is the text at once
  const [view, setView] = useState<'edit' | 'read'>('read')
  const [panel, setPanel] = useState<null | 'page' | 'again'>(null)
  // The pages read before (enrich_sources): remembered when one is read, forgotten by its ×, each saved at once.
  const [pages, setPages] = useState<string[] | null>(null)
  const [pagesError, setPagesError] = useState<string | null>(null)
  // What the last "Add … to my CV" put in: tinted in the preview until the next edit or save.
  const [added, setAdded] = useState<string[] | null>(null)
  // counts the saves: the style previews are made from the CV
  const [saves, setSaves] = useState(0)
  // what a draft from another CV file asks of the user
  const [message, setMessage] = useState<string | null>(null)
  // the CV file a draft read, by its name (the main process keeps its path); being drafted from; its error
  const [cvFile, setCvFile] = useState<string | null>(null)
  const [drafting, setDrafting] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)
  // counts the CV files drafted from here: the style of the user's own is built again from a new one
  const [replaced, setReplaced] = useState(0)
  // the live save: writing, or why the last write failed (tried again at the next pause)
  const [writing, setWriting] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  // the text to write, read by the timer and on leaving; whether this visit has kept its backup yet; a write running
  const latest = useRef('')
  const backedUp = useRef(false)
  const inFlight = useRef<Promise<void> | null>(null)
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

  const load = async () => {
    try {
      const p = await call<Profile>('show_profile')
      setProfile(p)
      setPages((had) => had ?? (p as Profile).config?.enrich_sources ?? p.enrich_sources ?? [])
      setSaved(p.cv.text ?? '')
      setText(p.cv.text ?? '')
      if (!p.cv.text?.trim()) setView('edit') // nothing to read: the text at once
      latest.current = p.cv.text ?? ''
    } catch (e) {
      setLoadError(errorText(e))
    }
  }
  useEffect(() => {
    void load()
    window.door.cvFile().then(setCvFile, () => undefined)
  }, [])

  /** Write the text as it is now, unless it is saved or empty; one write at a time. */
  const savedRef = useRef('')
  savedRef.current = saved
  const flush = async (): Promise<void> => {
    if (inFlight.current) await inFlight.current
    const markdown = latest.current
    if (markdown === savedRef.current || markdown.trim() === '') return
    const first = !backedUp.current
    const run = (async () => {
      setWriting(true)
      try {
        await call('save_cv', { markdown, backup: first })
        backedUp.current = true
        savedRef.current = markdown
        setSaved(markdown)
        setSaveError(null)
        // the first CV: the sidebar's "no CV yet" goes at once
        if (profile && !profile.cv.exists && first) onSaved?.()
      } catch (e) {
        setSaveError(errorText(e))
      } finally {
        setWriting(false)
      }
    })()
    inFlight.current = run
    await run
    inFlight.current = null
  }
  // a pause in typing writes it
  useEffect(() => {
    latest.current = text
    if (!profile || text === saved || text.trim() === '') return
    const t = setTimeout(() => void flush(), SAVE_AFTER_MS)
    return () => clearTimeout(t)
  }, [text, saved, profile])
  // leaving Profile with a pause not yet reached still writes it
  useEffect(() => () => void flush(), [])
  /** The editor left: written now, and the style previews (made from the CV) and the app read it again. */
  const leave = async () => {
    const before = savedRef.current
    await flush()
    if (savedRef.current !== before) {
      setSaves((n) => n + 1)
      onSaved?.()
    }
  }

  /** Another CV file: drafted into the editor, and saved like any change (the CV before it kept as cv.md.bak). */
  const replaceFile = async () => {
    setFileError(null)
    setMessage(null)
    const picked = await window.door.pickCvFiles()
    const refused = picked.refused[0]
    if (refused) return setFileError(`${refused.name}: ${refused.reason}`)
    const file = picked.files[0]
    if (!file) return
    setDrafting(true)
    try {
      const r = await draftCv({ files: [file.token], urls: [] })
      setAdded(null)
      setText(r.markdown)
      setView('read')
      setMessage(`Drafted from ${file.name}. Your CV before it is kept as cv.md.bak.`)
      setReplaced((n) => n + 1)
      window.door.cvFile().then(setCvFile, () => undefined)
    } catch (e) {
      setFileError(errorText(e))
    } finally {
      setDrafting(false)
    }
  }

  // a change not written yet: what reads or rewrites the CV on the server waits for it
  const dirty = text !== saved
  const editing = view === 'edit'
  const written = writing ? 'Saving…' : saveError ? null : dirty ? null : saves > 0 || backedUp.current ? 'Saved' : null

  // Profile's part "Master CV": the file and the pages it is read from, then the text; the style is a part of its own after it
  const part = (body: ReactNode) => (
    <section className="part" aria-labelledby="profile-cv">
      <h2 className="display-s" id="profile-cv">
        Master CV
      </h2>
      {body}
    </section>
  )
  if (loadError) return part(<ErrorBox text={loadError} />)
  if (!profile) return part(<Spinner message="Reading your CV…" />)
  const keepPages = async (next: string[]) => {
    const before = pages
    setPages(next)
    setPagesError(null)
    try {
      await call('init_profile', { other: { enrich_sources: next } })
    } catch (e) {
      setPages(before) // not saved: the list shown is the one saved
      setPagesError(errorText(e))
    }
  }
  const remembered = pages ?? []
  return (
    <>
      <section className="part cv-editor" aria-labelledby="profile-cv">
      <h2 className="display-s" id="profile-cv">
        Master CV
      </h2>
      <p className="small muted">Everything about your work, in one place. It is never sent as it is: each application gets a CV of its own, picked from this one and tailored to the ad, so put in more than one CV would hold.</p>
      {/* the wizard may end with no CV; the example CV is never copied in, so only a developer's hand-made profile has it */}
      {!profile.cv.exists && (
        <div role="note" className="cv-example small">
          <span>You have no CV yet. Choose your CV file, write it below, or </span>
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
        {/* three fields, as every form's (docs/design/README.md "Field name"): a name 4 px above its control, what
            belongs under it (the pages, a line, an error) under it, 28 px between fields */}
        <div className="field onb-field" role="group" aria-labelledby="cv-file-name">
          <FieldName id="cv-file-name" label="CV file" help="The file your CV was drafted from. Replacing it drafts your CV again from the new file, and builds your own style from it when you use one." />
          <div className="cv-file">
            {cvFile ? <span className="body">{cvFile}</span> : <span className="body muted">No CV file yet</span>}
            {drafting ? (
              <Spinner message="Reading your CV file (a minute or two)…" />
            ) : (
              <button type="button" className="secondary" onClick={() => void flush().then(replaceFile)}>
                {cvFile ? 'Replace…' : 'Choose a CV file…'}
              </button>
            )}
          </div>
          {message && <p className="small muted">{message}</p>}
          {fileError && <p className="field-error" role="alert">{fileError}</p>}
        </div>
        <div className="field onb-field" role="group" aria-labelledby="cv-pages-name">
          <FieldName id="cv-pages-name" label="Pages" help="Public pages about you: a portfolio, GitHub, a publication list. Add a page proposes what one shows and your CV does not; Check again reads them all for what is new." />
          <div className="actions">
            <button type="button" className="secondary" onClick={() => void flush().then(() => { setMessage(null); setPanel('page') })}>
              Add a page
            </button>
            {remembered.length > 0 && (
              <button type="button" className="secondary" onClick={() => void flush().then(() => { setMessage(null); setPanel('again') })}>
                Check again
              </button>
            )}
          </div>
          {/* under the control only its pills: each page, forgotten by its × */}
          {remembered.length > 0 && (
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
          )}
          {pagesError && <p className="field-error" role="alert">{pagesError}</p>}
        </div>
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
        {/* the CV as it reads, with Edit on the right; editing, the text with Saved and Done */}
        <div className="field onb-field">
        <div className="cv-head">
          {editing ? (
            <FieldName htmlFor={editorId} label="Text" after={<span className="small muted">(<MarkdownLink />)</span>} help="Everything about your work in Markdown, what every application's CV is picked from and tailored. It saves itself as you type." />
          ) : (
            <FieldName id="cv-text-name" label="Text" help="Everything about your work, what every application's CV is picked from and tailored. Edit to change it; it saves itself as you type." />
          )}
          {written && (
            <span className="small muted cv-written" role="status">
              {written}
            </span>
          )}
          {(!editing || text.trim() !== '') && (
            <button type="button" className="secondary" aria-label={editing ? 'Done editing' : 'Edit the Master CV'} onClick={() => setView(editing ? 'read' : 'edit')}>
              {editing ? 'Done' : 'Edit'}
            </button>
          )}
        </div>
        {editing ? (
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
              onBlur={() => void leave()}
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
        {/* the write failed: said under the text, tried again at the next pause */}
        {saveError && <p className="field-error" role="alert">{saveError}</p>}
        </div>
      </section>
      {style && <StyleRow state={style.state} canBuild={style.canBuild} onChanged={style.onChanged} reload={saves} replaced={replaced} />}
    </>
  )
}
