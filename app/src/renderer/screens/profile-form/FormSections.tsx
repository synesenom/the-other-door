// The form of Profile's details, rendered from fields.json and `show_profile`'s field specs: one component for
// Profile and the onboarding review, each feeding it values and a `set`, so both show the same parts, names and
// controls in the same order. The review shows the keys it holds; the rest of the layout is left out, never changed.
import { Fragment, type CSSProperties, type ReactNode } from 'react'
import { named } from '../AppName'
import { Hint } from '../Hint'
import { MATCH, minScoreChoice } from '../minScore'
import { ChipInput, CityField, TextAreaField, TextField } from '../onboarding/parts'
import type { ProfileOptions } from '../onboarding/reducer'
import layout from './fields.json'
import type { Exclude, FieldSpec, FormValue, FormValues } from './form'

export interface Layout {
  /** `screen: "settings"`: a section of Settings (how the app works), not of Profile (who you are, what you want) */
  sections: { id: string; label: string; screen?: string }[]
  /** `group`: neighbouring fields shown together under that name (two checkboxes) */
  fields: { key: string; section: string; label: string; help?: string; group?: string; multiline?: boolean }[]
}
export const LAYOUT = layout as Layout
/** The keys left to profile/config.json: tuning and file paths, not shown (fields.json's "config" section). */
const CONFIG_ONLY = 'config'

const REMOTE: Record<string, string> = { hybrid: 'Hybrid', yes: 'Remote only', no: 'On site' }

type LayoutField = Layout['fields'][number]

/**
 * The sections of the form with something to show, in the layout's order: not Settings' (`screen`), not the
 * config-only keys, and only keys with a spec (and, when `keys` is given, among them).
 */
export function formSections(specs: FieldSpec[], keys?: ReadonlySet<string>): { section: Layout['sections'][number]; fields: LayoutField[] }[] {
  return LAYOUT.sections
    .filter((s) => s.id !== CONFIG_ONLY && s.screen !== 'settings')
    .map((section) => ({
      section,
      fields: LAYOUT.fields.filter((f) => f.section === section.id && specs.some((x) => x.key === f.key) && (!keys || keys.has(f.key))),
    }))
    .filter((s) => s.fields.length > 0)
}

function Chips({ label, help, errors, values, onChange }: { label: string; help?: string; errors?: string[]; values: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="profile-chips">
      <ChipInput
        label={label}
        values={values}
        hint={help}
        onAdd={(v) => !values.includes(v.trim()) && onChange([...values, v.trim()])}
        onDrop={(v) => onChange(values.filter((x) => x !== v))}
      />
      {errors?.map((e) => (
        <p key={e} className="field-error">
          {named(e)}
        </p>
      ))}
    </div>
  )
}

/** The fields in order, each alone, but neighbours of one `group` together. */
const runs = (fields: LayoutField[]) =>
  fields.reduce<LayoutField[][]>((all, f) => {
    const last = all[all.length - 1]
    if (last && f.group && last[0]!.group === f.group) last.push(f)
    else all.push([f])
    return all
  }, [])

interface Props {
  specs: FieldSpec[]
  options: ProfileOptions
  values: FormValues
  set: (key: string, value: FormValue) => void
  /** Each key's error lines, said under its field. */
  errors?: Record<string, string[]>
  /** The keys shown, when not all of them (the review holds fewer). */
  keys?: ReadonlySet<string>
  /** The sections' ids are `<idPrefix>-<section>`. */
  idPrefix: string
  /** The photo control, which each screen saves its own way; none, no photo field. */
  photo?: ReactNode
  /** What a section says under its name before its fields: a note or the errors of the part, by section id. */
  notes?: Record<string, ReactNode>
  /** A text field was left. */
  onBlur?: () => void
}

export function FormSections({ specs, options, values, set, errors = {}, keys, idPrefix, photo, notes = {}, onBlur }: Props) {
  const control = (f: LayoutField): ReactNode => {
    const spec = specs.find((s) => s.key === f.key)
    if (!spec) return null
    const err = errors[f.key]
    const value = values[f.key]
    if (f.key === 'location') return <CityField key={f.key} label={f.label} help={f.help} errors={err} location={String(value)} options={options} onChange={(v) => set(f.key, v)} onBlur={onBlur} />
    if (f.key === 'languages') {
      const chosen = value as string[]
      const offered = [...options.languages, ...chosen.filter((l) => !options.languages.some((o) => o.toLowerCase() === l.toLowerCase()))]
      return (
        <fieldset key={f.key} className="choices onb-field">
          <legend className="field-label">{f.label}</legend>
          <div className="choice-columns" style={{ '--rows': Math.ceil(offered.length / 3) } as CSSProperties}>
            {offered.map((l) => {
              const on = chosen.some((c) => c.toLowerCase() === l.toLowerCase())
              return (
                <label key={l} className="choice">
                  <input type="checkbox" checked={on} onChange={() => set(f.key, on ? chosen.filter((c) => c.toLowerCase() !== l.toLowerCase()) : [...chosen, l])} />
                  <span>{l}</span>
                </label>
              )
            })}
          </div>
          {f.help && <p className="small muted">{f.help}</p>}
          {err?.map((e) => <p key={e} className="field-error">{named(e)}</p>)}
        </fieldset>
      )
    }
    if (f.key === 'min_score') {
      const now = Number(value)
      const own = MATCH.some(([n]) => n === now) ? [] : [[now, minScoreChoice(now)] as [number, string]]
      return (
        <fieldset key={f.key} className="choices onb-field">
          <legend className="field-label">
            <span className="field-name">
              {f.label}
              {f.help && <Hint label={`About ${f.label}`}>{f.help}</Hint>}
            </span>
          </legend>
          {[...MATCH, ...own].map(([n, label]) => (
            <label key={label} className="choice">
              <input type="radio" name={`${idPrefix}-${f.key}`} checked={now === n} onChange={() => set(f.key, String(n))} />
              <span>{label}</span>
            </label>
          ))}
          {err?.map((e) => <p key={e} className="field-error">{named(e)}</p>)}
        </fieldset>
      )
    }
    if (f.key === 'photo') return photo ? <Fragment key={f.key}>{photo}</Fragment> : null
    switch (spec.type) {
      case 'path':
        return (
          <div key={f.key} className="field onb-field">
            <span className="field-label">{f.label}</span>
            <p className="body settings-path">{String(value) || 'Not set'}</p>
            <p className="small muted">Change it in profile/config.json.</p>
          </div>
        )
      case 'boolean': {
        const on = Boolean(value ?? spec.default)
        return (
          <div key={f.key} className="field onb-field">
            <label className="choice">
              <input type="checkbox" checked={on} onChange={(e) => set(f.key, e.target.checked)} />
              <span>{f.label}</span>
            </label>
            {f.help && <p className="small muted">{f.help}</p>}
            {err?.map((e) => <p key={e} className="field-error">{named(e)}</p>)}
          </div>
        )
      }
      case 'choice':
        return (
          <fieldset key={f.key} className="choices onb-field">
            <legend className="field-label">{f.label}</legend>
            {(spec.choices ?? []).map((c) => (
              <label key={c} className="choice">
                <input type="radio" name={`${idPrefix}-${f.key}`} checked={value === c} onChange={() => set(f.key, c)} />
                <span>{REMOTE[c] ?? c}</span>
              </label>
            ))}
            {err?.map((e) => <p key={e} className="field-error">{named(e)}</p>)}
          </fieldset>
        )
      case 'list':
        return (
          <div key={f.key}>
            <Chips label={f.label} help={f.help} errors={err} values={value as string[]} onChange={(v) => set(f.key, v)} />
          </div>
        )
      case 'exclude': {
        const ex = value as Exclude
        // two fields of the section, spaced as every other pair of fields is
        return (
          <Fragment key={f.key}>
            <Chips label="Companies to skip" values={ex.companies} onChange={(v) => set(f.key, { ...ex, companies: v })} />
            <Chips label="Words that rule an ad out" errors={err} values={ex.keywords} onChange={(v) => set(f.key, { ...ex, keywords: v })} />
          </Fragment>
        )
      }
      default:
        if (f.multiline) return <TextAreaField key={f.key} label={f.label} help={f.help} errors={err} value={String(value)} onChange={(v) => set(f.key, v)} onBlur={onBlur} />
        return <TextField key={f.key} label={f.label} help={f.help} errors={err} value={String(value)} numeric={spec.type === 'integer' || spec.type === 'number'} onChange={(v) => set(f.key, v)} onBlur={onBlur} />
    }
  }

  return (
    <>
      {formSections(specs, keys).map(({ section, fields }) => (
        <section key={section.id} className="part" aria-labelledby={`${idPrefix}-${section.id}`}>
          <h2 className="display-s" id={`${idPrefix}-${section.id}`}>
            {section.label}
          </h2>
          {notes[section.id]}
          {runs(fields).map((run) =>
            // a group's fields sit together under its name, as the choices of one field
            run[0]!.group ? (
              <fieldset key={run[0]!.key} className="choices onb-field checks">
                <legend className="field-label">{run[0]!.group}</legend>
                {run.map(control)}
              </fieldset>
            ) : (
              control(run[0]!)
            ),
          )}
        </section>
      ))}
    </>
  )
}
