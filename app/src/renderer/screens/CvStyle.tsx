import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { call, errorText } from '../api'
import { named } from './AppName'
import { toInitArgs, type FieldSpec } from './profile-form/form'
import swatches from './profile-form/cv-style.json'
import { Spinner } from './Spinner'

/** The accent colours by their config name (`Profile.cv_accent`): the label and the swatch (cv-style.json: the CV's own colours, not the app's; the table is `core/templates.ACCENTS`). */
const COLOURS = swatches.colours as unknown as Record<string, [string, string]>
/** The font pairs by their config name (`Profile.cv_fonts`): the label, the heading font and weight, the text font. */
const FONTS: Record<string, [string, string, number, string]> = {
  door: ['The other door', "'Young Serif', Georgia, serif", 400, "'Figtree', sans-serif"],
  editorial: ['Editorial', "'Playfair Display', Georgia, serif", 700, "'Lato', sans-serif"],
  friendly: ['Friendly', "'Montserrat', sans-serif", 700, "'Merriweather', Georgia, serif"],
  plain: ['Plain', "'Figtree', sans-serif", 600, "'Figtree', sans-serif"],
}

interface Props {
  /** `show_profile`'s `options.fields`: where the names of both choices come from */
  specs: FieldSpec[]
  /** profile/config.json as read (a key it does not set is its default) */
  config: Record<string, unknown>
}

/**
 * Profile -> CV style: the look of the tailored CVs and letters. Left a sample of the CV's first page in the chosen
 * style (`cv_style_sample`), right the two pickers. A pick is saved at once with `init_profile` and applies from the
 * next CV that is prepared; an answer for a pick that a newer one replaced is ignored.
 */
export function CvStyle({ specs, config }: Props) {
  const choices = (key: string) => specs.find((s) => s.key === key)?.choices ?? []
  const first = (key: string, fallback: string) => String(specs.find((s) => s.key === key)?.default ?? fallback)
  const [chosen, setChosen] = useState<Record<string, string>>({
    cv_accent: String(config['cv_accent'] ?? first('cv_accent', 'none')),
    cv_fonts: String(config['cv_fonts'] ?? first('cv_fonts', 'door')),
  })
  const [png, setPng] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)
  const [problem, setProblem] = useState<string | null>(null)
  const latest = useRef(0)

  const sample = async (now: Record<string, string>) => {
    const mine = ++latest.current
    setBusy(true)
    try {
      const r = await call<{ png_base64: string }>('cv_style_sample', now)
      if (mine !== latest.current) return
      setPng(r.png_base64)
      setProblem(null)
    } catch (e) {
      if (mine === latest.current) setProblem(errorText(e))
    } finally {
      if (mine === latest.current) setBusy(false)
    }
  }
  useEffect(() => {
    void sample(chosen)
  }, [])

  const pick = async (key: string, value: string) => {
    if (chosen[key] === value) return
    const before = chosen
    const now = { ...chosen, [key]: value }
    setChosen(now)
    try {
      await call('init_profile', toInitArgs({ [key]: before[key]! }, { [key]: value }, specs))
    } catch (e) {
      setChosen(before)
      setProblem(errorText(e))
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
        <p className="small muted">How your tailored CVs and cover letters look. A choice is saved at once; your CVs are printed with it from the next one you prepare.</p>
      </div>
      <div className="style-part">
        <div className="style-sample" aria-busy={busy}>
          {png ? <img src={`data:image/png;base64,${png}`} alt="A sample of your CV in this style" /> : busy ? <Spinner message="Printing a sample…" /> : null}
          {png && busy && <Spinner message="Printing a sample…" />}
          {problem && (
            <p role="alert" className="field-error">
              {named(problem)}
            </p>
          )}
        </div>
        <div className="style-pickers">
          <fieldset className="style-group">
            <legend className="field-label">Colour</legend>
            <div className="style-grid style-colours">
              {choices('cv_accent').map((c) => {
                const [label, hex] = COLOURS[c] ?? [c, 'currentColor']
                return (
                  <label key={c} className="style-pick" title={label}>
                    <input type="radio" name="cv_accent" aria-label={label} checked={chosen['cv_accent'] === c} onChange={() => void pick('cv_accent', c)} />
                    <span className={`style-tile${c === 'none' ? ' none' : ''}`} style={{ '--c': hex } as CSSProperties} />
                  </label>
                )
              })}
            </div>
          </fieldset>
          <fieldset className="style-group">
            <legend className="field-label">Fonts</legend>
            <div className="style-grid style-fonts">
              {choices('cv_fonts').map((f) => {
                const [label, heading, weight, text] = FONTS[f] ?? [f, 'serif', 400, 'sans-serif']
                return (
                  <label key={f} className="style-pick" title={label}>
                    <input type="radio" name="cv_fonts" aria-label={label} checked={chosen['cv_fonts'] === f} onChange={() => void pick('cv_fonts', f)} />
                    <span className="style-font" style={{ '--h': heading, '--hw': weight, '--t': text } as CSSProperties}>
                      <span>
                        <span className="h">A</span>
                        <span className="t">a</span>
                      </span>
                    </span>
                    <span className="style-name">{label}</span>
                  </label>
                )
              })}
            </div>
          </fieldset>
        </div>
      </div>
    </section>
  )
}
