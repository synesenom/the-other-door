import { useEffect, useId, useRef, useState } from 'react'
import { ErrorBox, named } from './AppName'
import { call, errorText, styleUrl } from '../api'
import type { StyleStep } from '../api'
import { styleText } from './run-text'
import { Dialog } from './Dialog'
import { PageStack } from './PageStack'
import { Spinner } from './Spinner'
import { Switch } from './Switch'

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
  /** the CV could not be read for the previews: no sets, but `in_use` and `candidate` still tell the truth */
  warning?: string
}
type Doc = 'cv' | 'letter'
/** After a switch: the prepared CVs the new style could be printed on, asked about, being printed, or done. */
type Rerender = { kind: 'offer'; prepared: number; style: Which } | { kind: 'busy'; prepared: number; style: Which } | { kind: 'done'; printed: number; failed: number; again: string[]; style: Which }

const NAMES: Record<Which, string> = { like: 'Your CV', default: 'The other door' }
const pages = (n: number) => `${n} ${n === 1 ? 'page' : 'pages'}`
const noun = (n: number) => `${n} prepared ${n === 1 ? 'CV' : 'CVs'}`

/** The full pages of one style in a dialog: a document to read and close. */
function Pages({ which, set, onClose }: { which: Which; set: StyleSet; onClose: () => void }) {
  const [doc, setDoc] = useState<Doc>('cv')
  const files = set[doc]
  return (
    <Dialog title={named(NAMES[which])} onClose={onClose} wide>
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
 * Profile's CV style, a section of its own: its heading with the switch "Use my own style" at its right, then The
 * other door's style and, once one is built from the user's CV file (under Master CV), theirs, side by side to compare; the
 * one in use has the accent border. On with no style of theirs yet, the switch builds one from the CV file and
 * uses it once ready; off goes back to The other door. A new CV file (`replaced` counts them) builds the style
 * again from it. `state` is the build's, from the sidebar's summary (the app polls it while a build runs);
 * `onChanged` tells the app a build started or a style was chosen; `reload` counts what makes the previews stale (a
 * saved CV). Nothing is said when the previews cannot be made or a build fails later (the doctor and the sidebar say
 * what the user can act on), but a CV file that cannot be used is named.
 */
export function StyleRow({ state, step, canBuild, onChanged, reload, replaced = 0 }: { state: 'none' | 'building' | 'ready' | 'failed' | null; step?: StyleStep; canBuild: boolean; onChanged: () => void; reload: number; replaced?: number }) {
  // null: the first read is still going. A later read keeps what is shown until it answers.
  const [shown, setShown] = useState<Shown | null>(null)
  const [open, setOpen] = useState<Which | null>(null)
  const [busy, setBusy] = useState(false)
  const [reading, setReading] = useState(false) // the CV file's structure is being read, before the build starts
  // the switch was turned on with no style built: the one being built is used once it is ready
  const [wanted, setWanted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rerender, setRerender] = useState<Rerender | null>(null)
  const latest = useRef(0)
  const was = useRef(state)
  const firstReplaced = useRef(replaced)
  const ids = useId()

  const read = async () => {
    const n = ++latest.current
    let answer: Shown
    try {
      answer = await call<Shown>('show_style')
    } catch {
      answer = { styles: {}, in_use: 'default', candidate: false }
    }
    if (n === latest.current) setShown(answer)
    return answer
  }
  useEffect(
    () => () => {
      latest.current++
    },
    [],
  )

  const build = async () => {
    setError(null)
    setBusy(true)
    const stop = window.door.onStyleReading(() => setReading(true))
    try {
      const r = (await window.door.styleFromCvFile()) as { ok: boolean; error?: string }
      if (!r.ok) {
        setWanted(false)
        setError(r.error ?? 'Your CV file could not be used.')
      } else {
        setRerender(null)
        onChanged()
      }
    } finally {
      stop()
      setBusy(false)
      setReading(false)
    }
  }
  const use = async (style: Which) => {
    setError(null)
    setBusy(true)
    // shown at once: the answer can wait behind the app's other calls; a choice that fails is read back below
    setShown((s) => s && { ...s, in_use: style, candidate: style === 'like' ? false : s.candidate })
    try {
      const r = await call<{ in_use: Which; prepared: number }>('use_style', { style })
      setRerender(r.prepared > 0 ? { kind: 'offer', prepared: r.prepared, style: r.in_use } : null)
      onChanged()
      await read()
    } catch (e) {
      setError(errorText(e))
      void read() // back to what is in use
    } finally {
      setBusy(false)
    }
  }
  const printAgain = async (style: Which, prepared: number) => {
    setError(null)
    setRerender({ kind: 'busy', prepared, style })
    try {
      const r = await call<{ rerendered?: string[]; failed?: { job: string; title: string | null; company: string | null; reason: string; prepare_again: boolean }[] }>('use_style', { style, rerender: true })
      const failed = r.failed ?? []
      // `again`: prepared before sections had a kind, which a two-column style cannot place: printing again never helps
      setRerender({ kind: 'done', printed: r.rerendered?.length ?? 0, failed: failed.length, again: failed.filter((f) => f.prepare_again).map((f) => [f.title, f.company].filter(Boolean).join(' at ') || f.job), style })
    } catch (e) {
      setRerender({ kind: 'offer', prepared, style }) // the offer stays, to try again
      setError(errorText(e))
    }
  }

  // the previews are read on opening, after a save and when the build moves on; a build that ends while the user's
  // own style is wanted or in use is put in use (it was built from their CV file for that)
  useEffect(() => {
    const finished = was.current === 'building' && state === 'ready'
    was.current = state
    void read().then((answer) => {
      if (finished && answer.candidate && (wanted || answer.in_use === 'like')) {
        setWanted(false)
        void use('like')
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reload, state])

  // a new CV file: the style of the user's own is built again from it
  useEffect(() => {
    if (replaced === firstReplaced.current || !canBuild || !shown?.styles.like) return
    firstReplaced.current = replaced
    void build()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replaced])

  const building = state === 'building'
  const held = busy || building || reading
  const sets = shown?.styles ?? {}
  const hasLike = Boolean(sets.like)
  const candidate = Boolean(shown?.candidate)
  const inUse = shown?.in_use ?? 'default'
  const current = (which: Which) => (which === 'default' ? inUse === 'default' : inUse === 'like' && !candidate)
  const twoColumn = sets.like?.two_column === true

  const toggle = (on: boolean) => {
    if (held) return
    if (!on) {
      setWanted(false)
      void use('default')
    } else if (hasLike || inUse === 'like' || shown?.warning) void use('like') // never a build when a style may be kept
    else {
      setWanted(true)
      void build()
    }
  }

  // the sheet in use has the accent border (docs/design/README.md, Profile → CV style)
  const card = (which: Which) => {
    const set = sets[which]
    if (!set) return null
    const caption = `${ids}-${which}`
    return (
      <div key={which} className={current(which) ? 'style-card style-current' : 'style-card'} role="group" aria-labelledby={caption}>
        <button type="button" className="style-thumb" aria-label={`Show ${NAMES[which]} in full`} onClick={() => setOpen(which)}>
          <img className="paper" src={styleUrl(which, set.cv[0]!, set.version)} alt={`${NAMES[which]}, first page`} />
        </button>
        <p className="small style-caption">
          <span id={caption}>{named(NAMES[which])}</span>
          {current(which) && <span className="visually-hidden">, in use</span>}
        </p>
      </div>
    )
  }

  return (
    <section className="part" aria-labelledby="profile-style">
      <div className="part-head part-head-row">
        <h2 className="display-s" id="profile-style">
          CV style
        </h2>
        {shown !== null && (canBuild || hasLike) && (
          <div className={held ? 'style-switch style-switch-busy' : 'style-switch'}>
            <Switch label="Use my own style" checked={inUse === 'like' || wanted} onChange={toggle} />
          </div>
        )}
      </div>
      <div className="style-row">
        {shown === null ? (
          <>
            <div className="style-cards">
              <div className="style-card" aria-hidden="true">
                <div className="style-sheet" />
                <p className="small style-caption">
                  <span>&nbsp;</span>
                </p>
              </div>
            </div>
            <div className="style-below">
              <Spinner message="Preparing the previews…" />
            </div>
          </>
        ) : (
          <>
            {(hasLike || sets.default) && (
              <div className="style-cards">
                {card('default')}
                {card('like')}
              </div>
            )}
            <div className="style-below">
              {!hasLike && !building && !reading && canBuild && !shown?.warning && <p className="small muted">Your tailored CVs printed in the style of your CV file. Building it takes 2–5 minutes in the background.</p>}
              {twoColumn && <p className="small muted">Some application systems read two-column CVs less well.</p>}
              {(building || reading) && <Spinner message={building ? styleText(step) : "Reading your CV's look…"} />}
            </div>
            {rerender?.kind === 'offer' && (
              <div className="style-rerender">
                <button type="button" className="secondary" onClick={() => void printAgain(rerender.style, rerender.prepared)}>
                  {`Print ${noun(rerender.prepared)} again`}
                </button>
              </div>
            )}
            {rerender?.kind === 'busy' && <Spinner message="Printing again…" />}
            {rerender?.kind === 'done' && (
              <div className="style-rerender">
                <p role="status" className="small">
                  {`${rerender.printed} printed again.`}
                </p>
                {rerender.again.length > 0 && (
                  <p className="small muted">{`${rerender.again.length === 1 ? 'This CV' : 'These CVs'} could not be printed in this style: ${rerender.again.join(', ')}. Prepare ${rerender.again.length === 1 ? 'it' : 'them'} again or revise ${rerender.again.length === 1 ? 'it' : 'them'}.`}</p>
                )}
                {rerender.failed > rerender.again.length && (
                  <button type="button" className="secondary" onClick={() => void printAgain(rerender.style, rerender.printed + rerender.failed)}>
                    Try again
                  </button>
                )}
              </div>
            )}
            {error && <ErrorBox text={error} />}
          </>
        )}
        {open && sets[open] && <Pages which={open} set={sets[open]!} onClose={() => setOpen(null)} />}
      </div>
    </section>
  )
}
