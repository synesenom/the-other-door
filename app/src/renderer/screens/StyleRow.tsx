import { useEffect, useRef, useState } from 'react'
import { named } from './AppName'
import { call, errorText, styleUrl } from '../api'
import { Dialog } from './Dialog'
import { PageStack } from './PageStack'
import { Spinner } from './Spinner'

type Which = 'default' | 'like'
interface StyleSet {
  cv: string[]
  letter: string[]
  version: string
  two_column: boolean
}
interface Shown {
  styles: Partial<Record<Which, StyleSet>>
  in_use: Which
  candidate: boolean
}
type Doc = 'cv' | 'letter'
/** After a switch: the prepared CVs the new style could be printed on, asked about, being printed, or done. */
type Rerender = { kind: 'offer'; prepared: number; style: Which } | { kind: 'busy' } | { kind: 'done'; printed: number; failed: number }

const NAMES: Record<Which, string> = { like: 'Like your CV', default: "The other door's" }
const pages = (n: number) => `${n} ${n === 1 ? 'page' : 'pages'}`
const noun = (n: number) => `${n} prepared ${n === 1 ? 'CV' : 'CVs'}`

/** The full pages of one style in a dialog: a document to read and close. */
function Pages({ which, set, onClose }: { which: Which; set: StyleSet; onClose: () => void }) {
  const [doc, setDoc] = useState<Doc>('cv')
  const files = set[doc]
  return (
    <Dialog title={NAMES[which]} onClose={onClose} wide>
      <div className="doc-switch" role="group" aria-label="Document">
        {(['cv', 'letter'] as const).map((d) => (
          <button key={d} type="button" className="pill" aria-pressed={doc === d} onClick={() => setDoc(d)}>
            {`${d === 'cv' ? 'CV' : 'Cover letter'} · ${pages(set[d].length)}`}
          </button>
        ))}
      </div>
      <PageStack urls={files.map((f) => styleUrl(which, f, set.version))} label={`${NAMES[which]}, ${doc === 'cv' ? 'CV' : 'cover letter'}`} />
      <div className="actions">
        <button type="button" className="secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  )
}

/**
 * Profile → CV's Style: The other door's style and, once one is built from a CV of the user's, theirs, side by side to
 * compare and choose. `state` is the build's, from the sidebar's summary (the app polls it while a build runs);
 * `onChanged` tells the app a build started or a style was chosen, so the summary is read again; `reload` counts what
 * makes the previews stale (a saved CV). Nothing is said when the previews cannot be made or a build fails (the
 * doctor and the sidebar say what the user can act on), but a file with no style to copy is named.
 */
export function StyleRow({ state, canBuild, onChanged, reload }: { state: 'none' | 'building' | 'ready' | 'failed' | null; canBuild: boolean; onChanged: () => void; reload: number }) {
  // null: the first read is still going. A later read keeps what is shown until it answers.
  const [shown, setShown] = useState<Shown | null>(null)
  const [open, setOpen] = useState<Which | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rerender, setRerender] = useState<Rerender | null>(null)
  const latest = useRef(0)

  const read = async () => {
    const n = ++latest.current
    let answer: Shown
    try {
      answer = await call<Shown>('show_style')
    } catch {
      answer = { styles: {}, in_use: 'default', candidate: false }
    }
    if (n === latest.current) setShown(answer)
  }
  useEffect(() => {
    void read()
  }, [reload, state])
  useEffect(
    () => () => {
      latest.current++
    },
    [],
  )

  const choose = async () => {
    setError(null)
    setBusy(true)
    try {
      const r = (await window.door.chooseStyleFile()) as { ok: boolean; error?: string; data?: { canceled?: true } }
      if (!r.ok) setError(r.error ?? 'That file could not be used.')
      else if (!r.data?.canceled) {
        setRerender(null)
        onChanged()
      }
    } finally {
      setBusy(false)
    }
  }
  const use = async (style: Which | 'current') => {
    setError(null)
    setBusy(true)
    try {
      const r = await call<{ in_use: Which; prepared: number }>('use_style', { style })
      setRerender(style !== 'current' && r.prepared > 0 ? { kind: 'offer', prepared: r.prepared, style: r.in_use } : null)
      onChanged()
      await read()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const printAgain = async (style: Which) => {
    setRerender({ kind: 'busy' })
    try {
      const r = await call<{ rerendered?: string[]; failed?: string[] }>('use_style', { style, rerender: true })
      setRerender({ kind: 'done', printed: r.rerendered?.length ?? 0, failed: r.failed?.length ?? 0 })
    } catch (e) {
      setRerender(null)
      setError(errorText(e))
    }
  }

  const building = state === 'building'
  const sets = shown?.styles ?? {}
  const hasLike = Boolean(sets.like)
  const candidate = Boolean(shown?.candidate)
  const inUse = shown?.in_use ?? 'default'
  const earlier = candidate && inUse === 'like'
  const marked = (which: Which) => (which === 'default' ? inUse === 'default' : inUse === 'like' && !candidate)
  const twoColumn = sets.like?.two_column === true

  const card = (which: Which) => {
    const set = sets[which]
    if (!set) return null
    const action =
      which === 'like'
        ? candidate
          ? (
            <>
              <button type="button" className="primary" disabled={busy} onClick={() => void use('like')}>
                Use this style
              </button>
              {earlier && (
                <button type="button" className="secondary" disabled={busy} onClick={() => void use('current')}>
                  Keep my current style
                </button>
              )}
            </>
          )
          : inUse !== 'like' && (
            <button type="button" className="secondary" disabled={busy} onClick={() => void use('like')}>
              Use my CV's style
            </button>
          )
        : (inUse !== 'default' || candidate) && (
          <button type="button" className="secondary" disabled={busy} onClick={() => void use('default')}>
            {inUse === 'default' ? "Keep The other door's" : "Use The other door's"}
          </button>
        )
    return (
      <div key={which} className="style-card" role="group" aria-label={NAMES[which]}>
        <button type="button" className="style-thumb" aria-label={`Show ${NAMES[which]} in full`} onClick={() => setOpen(which)}>
          <img className="paper" src={styleUrl(which, set.cv[0]!, set.version)} alt={`${NAMES[which]}, first page`} />
        </button>
        <p className="small style-caption">
          <span>{NAMES[which]}</span>
          {marked(which) && <span className="style-mark">In use</span>}
        </p>
        {action}
      </div>
    )
  }

  return (
    <div className="style-row">
      <span className="field-label">Style</span>
      {shown === null ? (
        <div className="style-cards">
          <div className="style-card">
            <div className="style-sheet" aria-hidden="true" />
          </div>
          <Spinner message="Preparing the previews…" />
        </div>
      ) : (
        <>
          {(hasLike || sets.default) && (
            <div className="style-cards">
              {card('like')}
              {card('default')}
            </div>
          )}
          {earlier && <p className="small muted">You use your earlier style now.</p>}
          {twoColumn && <p className="small muted">Some application systems read two-column CVs less well.</p>}
          {!hasLike && !building && canBuild && <p className="small muted">Make your tailored CVs look like a CV of yours. Takes 5–10 minutes in the background.</p>}
          {building ? (
            <Spinner message="Building your style…" />
          ) : (
            canBuild &&
            !candidate && (
              <div className="actions">
                <button type="button" className="secondary" disabled={busy} onClick={() => void choose()}>
                  {hasLike ? 'Use the style of another CV…' : 'Use the style of my CV…'}
                </button>
              </div>
            )
          )}
          {rerender?.kind === 'offer' && (
            <div className="style-rerender">
              <button type="button" className="secondary" onClick={() => void printAgain(rerender.style)}>
                {`Re-render ${noun(rerender.prepared)} in the new style`}
              </button>
            </div>
          )}
          {rerender?.kind === 'busy' && <Spinner message="Re-rendering…" />}
          {rerender?.kind === 'done' && (
            <p role="status" className="small">
              {`${rerender.printed} re-rendered.${rerender.failed > 0 ? ` ${rerender.failed} could not be printed.` : ''}`}
            </p>
          )}
          {error && (
            <p role="alert" className="field-error">
              {named(error)}
            </p>
          )}
        </>
      )}
      {open && sets[open] && <Pages which={open} set={sets[open]!} onClose={() => setOpen(null)} />}
    </div>
  )
}
