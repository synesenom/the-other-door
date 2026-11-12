import { useEffect, useState, type CSSProperties } from 'react'
import { named } from './AppName'
import { call, errorText } from '../api'
import { discoveryKeys, sourcesForCity, type ShowProfile } from './onboarding/reducer'
import { LAYOUT } from './Profile'
import { fieldErrors, formValues, toInitArgs, type FieldSpec, type FormValues } from './profile-form/form'

type Shown = ShowProfile & { options: ShowProfile['options'] & { fields?: FieldSpec[] }; config: Record<string, unknown> | null }

/**
 * The keys of profile/config.json that say how The other door works, not who you are (fields.json's sections
 * with `screen: "settings"`, today the risky sources): switches shown in Settings, each saved at once through
 * init_profile when ticked, like the theme. Only the sources serving the profile's city. Nothing shows until
 * the profile is read, or when it cannot be.
 */
export function SettingsFields({ section }: { section: string }) {
  const [shown, setShown] = useState<Shown | null>(null)
  const [saved, setSaved] = useState<FormValues>({})
  const [values, setValues] = useState<FormValues>({})
  const [errors, setErrors] = useState<Record<string, string[]>>({})

  const read = async () => {
    try {
      const p = await call<Shown>('show_profile')
      const v = formValues(p.config, p.options.fields ?? [])
      setShown(p)
      setSaved(v)
      setValues(v)
    } catch {
      setShown(null)
    }
  }
  useEffect(() => {
    void read()
  }, [])
  if (!shown || shown.config === null) return null

  const specs = shown.options.fields ?? []
  const choices = sourcesForCity(shown.options, String(saved['location'] ?? ''))
  const served = new Set(choices.map((d) => d.key))
  const notServed = new Set([...discoveryKeys(shown.options)].filter((k) => !served.has(k)))
  const fields = LAYOUT.fields.filter((f) => f.section === section && specs.some((s) => s.key === f.key) && !notServed.has(f.key))

  const save = async (key: string, value: FormValues[string]) => {
    const after = { ...saved, [key]: value }
    setValues((v) => ({ ...v, [key]: value }))
    setErrors({})
    try {
      await call('init_profile', toInitArgs(saved, after, specs))
      // only this key: another switch saved meanwhile keeps its own
      setSaved((s) => ({ ...s, [key]: value }))
    } catch (e) {
      const { byKey, general } = fieldErrors(errorText(e), specs)
      setErrors({ ...byKey, ...(general.length ? { [key]: [...(byKey[key] ?? []), ...general] } : {}) })
    }
  }

  // the switches' names in three columns, read down each
  const said = fields.flatMap((f) => errors[f.key] ?? [])
  return (
    <div className="field onb-field">
      <div className="choice-columns" style={{ '--rows': Math.ceil(fields.length / 3) } as CSSProperties}>
        {fields.map((f) => (
          <label key={f.key} className="choice">
            <input type="checkbox" checked={Boolean(values[f.key] ?? specs.find((s) => s.key === f.key)!.default)} onChange={(e) => void save(f.key, e.target.checked)} />
            <span>{f.label}</span>
          </label>
        ))}
      </div>
      {/* a source whose terms verdict is unsure: once on, its disclaimer (written by the server) */}
      {fields.map((f) => {
        const disclaimer = values[f.key] ? choices.find((d) => d.key === f.key)?.disclaimer : undefined
        return disclaimer && <p key={f.key} className="small muted">{disclaimer}</p>
      })}
      {said.map((e) => <p key={e} className="field-error">{named(e)}</p>)}
    </div>
  )
}
