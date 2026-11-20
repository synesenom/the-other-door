import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { call, errorText } from '../api'
import { named } from './AppName'
import { toInitArgs, type FieldSpec } from './profile-form/form'

/** What each choice is called (the names are the server's, `core/templates`; what each looks like comes from `show_profile`). */
const LABELS: Record<string, string> = {
  none: 'No colour', navy: 'Navy', blue: 'Blue', teal: 'Teal', forest: 'Forest', burgundy: 'Burgundy', plum: 'Plum', slate: 'Slate', rust: 'Rust',
  door: 'The other door', editorial: 'Editorial', friendly: 'Friendly', plain: 'Plain',
}

/** `show_profile`'s `options.cv_styles`: the swatch of each colour, the fonts and weight of each pair. */
export interface CvStyles {
  accents: Record<string, string>
  fonts: Record<string, { heading: string; text: string; weight: number }>
}

interface Props {
  /** `show_profile`'s `options.fields`: where the names of both choices come from */
  specs: FieldSpec[]
  /** profile/config.json as read (a key it does not set is its default) */
  config: Record<string, unknown>
  /** What each choice looks like */
  styles: CvStyles
  /** Counts the saves of the CV text: the sample is printed again from the new text */
  cvSaves?: number
}

/**
 * Profile -> CV style: the look of the tailored CVs and letters. Left a sample of the CV's first page in the chosen
 * style (`cv_style_sample`), right the two pickers. A pick is saved at once with `init_profile` and applies from the
 * next CV that is prepared; an answer for a pick that a newer one replaced is ignored.
 */
export function CvStyle({ specs, config, styles, cvSaves = 0 }: Props) {
  const choices = (key: string) => specs.find((s) => s.key === key)?.choices ?? []
  const first = (key: string, fallback: string) => String(specs.find((s) => s.key === key)?.default ?? fallback)
  const [chosen, setChosen] = useState<Record<string, string>>({
    cv_accent: String(config['cv_accent'] ?? first('cv_accent', 'blue')),
    cv_fonts: String(config['cv_fonts'] ?? first('cv_fonts', 'door')),
  })
  const [png, setPng] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)
  // Only what the user can act on is said: a CV that could not be read (under the sample), a pick that was not saved (under its row)
  const [unreadable, setUnreadable] = useState(false)
  const [saveError, setSaveError] = useState<{ key: string; text: string } | null>(null)
  const latest = useRef(0)

  const sample = async (now: Record<string, string>) => {
    const mine = ++latest.current
    setBusy(true)
    try {
      const r = await call<{ png_base64: string }>('cv_style_sample', now)
      if (mine !== latest.current) return
      setPng(r.png_base64)
      setUnreadable(false)
    } catch (e) {
      // any other failure of the print is nothing to act on: the last picture (or the placeholder) stays
      if (mine === latest.current) setUnreadable(errorText(e) === 'cv_unreadable')
    } finally {
      if (mine === latest.current) setBusy(false)
    }
  }
  useEffect(() => {
    void sample(chosen)
  }, [])
  // The CV was saved while this part is open (a pause in typing): its sample is printed again once the saves stop
  const chosenNow = useRef(chosen)
  chosenNow.current = chosen
  useEffect(() => {
    if (cvSaves === 0) return
    const timer = setTimeout(() => void sample(chosenNow.current), 2000)
    return () => clearTimeout(timer)
  }, [cvSaves])

  const pick = async (key: string, value: string) => {
    if (chosen[key] === value) return
    const before = chosen
    const now = { ...chosen, [key]: value }
    setChosen(now)
    setSaveError(null)
    try {
      await call('init_profile', toInitArgs({ [key]: before[key]! }, { [key]: value }, specs))
    } catch (e) {
      setChosen(before)
      setSaveError({ key, text: errorText(e) })
      return
    }
    await sample(now)
  }

  return (
    <section className="part style-container" aria-labelledby="profile-cv-style">
      <div className="part-head">
        <h2 className="display-s" id="profile-cv-style">
          CV style
        </h2>
        <p className="small muted">How your tailored CVs and cover letters look. A choice is saved at once; they are printed with it from the next one you prepare or revise.</p>
      </div>
      <div className="style-part">
        <div className="style-sample-column">
        <div className="style-sample" aria-busy={busy}>
          {png ? <img src={`data:image/png;base64,${png}`} alt="A sample of your CV in this style" /> : <div className="style-sample-wait">{busy && <span className="small">Printing a sample…</span>}</div>}
        </div>
        {unreadable && (
          <p role="alert" className="field-error style-sample-error">
            Your CV could not be read, so there is no sample. Check your Master CV above and try again.
          </p>
        )}
        </div>
        <div className="style-pickers">
          <fieldset className="style-group">
            <legend className="field-label">Colour</legend>
            <div className="style-grid style-colours">
              {choices('cv_accent').map((c) => {
                const label = LABELS[c] ?? c
                const hex = styles.accents[c] ?? 'currentColor'
                return (
                  <label key={c} className="style-pick" title={label}>
                    <input type="radio" name="cv_accent" aria-label={label} checked={chosen['cv_accent'] === c} onChange={() => void pick('cv_accent', c)} />
                    <span className={`style-tile${c === 'none' ? ' none' : ''}`} style={{ '--c': hex } as CSSProperties} />
                  </label>
                )
              })}
            </div>
            <PickError of="cv_accent" error={saveError} />
          </fieldset>
          <fieldset className="style-group">
            <legend className="field-label">Fonts</legend>
            <div className="style-grid style-fonts">
              {choices('cv_fonts').map((f) => {
                const label = LABELS[f] ?? f
                const { heading, weight, text } = styles.fonts[f] ?? { heading: 'serif', weight: 400, text: 'sans-serif' }
                return (
                  <label key={f} className="style-pick" title={label}>
                    <input type="radio" name="cv_fonts" aria-label={label} checked={chosen['cv_fonts'] === f} onChange={() => void pick('cv_fonts', f)} />
                    <span className="style-font" style={{ '--h': heading, '--hw': weight, '--t': text } as CSSProperties}>
                      <span>
                        <span className="h">A</span>
                        <span className="t">a</span>
                      </span>
                    </span>
                    <span className="style-name">{named(label)}</span>
                  </label>
                )
              })}
            </div>
            <PickError of="cv_fonts" error={saveError} />
          </fieldset>
        </div>
      </div>
    </section>
  )
}

/** Why a pick was not saved, under the row it belongs to. */
function PickError({ of, error }: { of: string; error: { key: string; text: string } | null }) {
  if (error?.key !== of) return null
  return (
    <p role="alert" className="field-error">
      {named(error.text)}
    </p>
  )
}
