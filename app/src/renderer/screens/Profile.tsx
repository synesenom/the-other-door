import { Fragment, useEffect, useId, useState, type CSSProperties, type ReactNode } from 'react'
import { named } from './AppName'
import { call, errorText } from '../api'
import { ChipInput, CityField, TextField } from './onboarding/parts'
import { photoPolicy, type ShowProfile } from './onboarding/reducer'
import layout from './profile-form/fields.json'
import { changedKeys, fieldErrors, formValues, toInitArgs, type Exclude, type FieldSpec, type FormValues } from './profile-form/form'
import { CvEditor } from './CvEditor'
import { Hint } from './Hint'
import { PhotoField, photoHelp } from './PhotoField'
import { Spinner } from './Spinner'
import { Stories } from './Stories'
import { PageSections } from './PageSections'

export interface Layout {
  /** `screen: "settings"`: a section of Settings (how the app works), not of Profile (who you are, what you want) */
  sections: { id: string; label: string; screen?: string }[]
  /** `group`: neighbouring fields shown together under that name (two checkboxes) */
  fields: { key: string; section: string; label: string; help?: string; group?: string }[]
}
export const LAYOUT = layout as Layout
/** The keys left to profile/config.json: tuning and file paths, not shown (fields.json's "config" section). */
const CONFIG_ONLY = 'config'

const REMOTE: Record<string, string> = { hybrid: 'Hybrid', yes: 'Remote only', no: 'On site' }
/** The minimum score as three words; a value set by hand in config.json shows as a fourth choice. */
const MATCH: [number, string][] = [[0.5, 'Broad'], [0.65, 'Balanced'], [0.75, 'Strong']]

type Profile = ShowProfile & { options: ShowProfile['options'] & { fields?: FieldSpec[] }; config: Record<string, unknown> | null }

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

/**
 * Profile: every key of profile/config.json in sections, the tuning keys left to config.json. Save sends
 * only what changed, through init_profile (which checks it all); an error is said under its field.
 */
/** Where Profile opens: the CV or the Stories, or a section of the details scrolled into view. */
export type ProfileStart = { view: 'cv' | 'stories' } | { section: string }

export function Profile({ onSaved, onDraft, start }: { onSaved: () => void; onDraft: () => void; start?: ProfileStart }) {
  // Details (config.json), the CV (cv.md) or the Stories (story_bank.md); the details' unsaved changes stay while the CV is shown.
  const [view, setView] = useState<'details' | 'cv' | 'stories'>(start && 'view' in start ? start.view : 'details')
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saved, setSaved] = useState<FormValues>({})
  const [values, setValues] = useState<FormValues>({})
  const [errors, setErrors] = useState<{ byKey: Record<string, string[]>; general: string[] }>({ byKey: {}, general: [] })
  const [saving, setSaving] = useState(false)
  // after a save that changed the role targets or languages: Claude proposing the search terms again
  const [refreshing, setRefreshing] = useState(false)
  const [done, setDone] = useState(false)
  // Counts Undo: the city field holds whether "Other…" is chosen, so Undo starts it afresh.
  const [undone, setUndone] = useState(0)
  // The CV's unsaved text, kept like the details' while the other part is shown.
  const [cvUnsaved, setCvUnsaved] = useState<string | null>(null)
  // The CV photo is saved the moment it is chosen or removed (its own tools), not with Save: why one was refused, and a counter that renews the preview.
  const [photoBusy, setPhotoBusy] = useState(false)
  const [photoError, setPhotoError] = useState<string | null>(null)
  const [photoVersion, setPhotoVersion] = useState(0)

  const specs = profile?.options.fields ?? []
  /** Read the profile; `keepEdits` (a change made elsewhere, e.g. titles added from the CV's market report) keeps what is typed and unsaved. */
  const load = async (keepEdits = false) => {
    try {
      const p = await call<Profile>('show_profile')
      setProfile(p)
      const v = formValues(p.config, p.options.fields ?? [])
      setSaved(v)
      setValues((typed) => (keepEdits ? { ...v, ...Object.fromEntries(changedKeys(saved, typed).map((k) => [k, typed[k]!])) } : v))
    } catch (e) {
      setLoadError(errorText(e))
    }
  }
  useEffect(() => {
    void load()
  }, [])
  const startSection = start && 'section' in start ? start.section : null
  useEffect(() => {
    if (profile && startSection) document.getElementById(`profile-${startSection}`)?.scrollIntoView({ block: 'start' })
  }, [profile, startSection])

  const set = (key: string, value: FormValues[string]) => {
    setDone(false)
    setValues((v) => ({ ...v, [key]: value }))
  }
  const changes = changedKeys(saved, values)
  const save = async () => {
    setSaving(true)
    setErrors({ byKey: {}, general: [] })
    // the search terms follow the role targets and the ad languages: Claude proposes them again, and they are saved
    const refresh = changes.includes('role_targets') || changes.includes('languages')
    try {
      await call('init_profile', toInitArgs(saved, values, specs))
      if (refresh) {
        setRefreshing(true)
        try {
          await call('keywords', { role_targets: values['role_targets'], languages: values['languages'], save: true })
        } catch {
          // the terms saved before stay; the next change of role targets asks again
        } finally {
          setRefreshing(false)
        }
      }
      await load()
      setDone(true)
      onSaved()
    } catch (e) {
      setErrors(fieldErrors(errorText(e), specs))
    } finally {
      setSaving(false)
    }
  }

  const choosePhoto = async () => {
    setPhotoError(null)
    setPhotoBusy(true)
    try {
      const picked = await window.door.pickPhoto()
      if ('error' in picked) setPhotoError(picked.error)
      else if ('token' in picked) {
        const saved = await window.door.savePhoto(picked.token)
        if (saved.ok) {
          setPhotoVersion((v) => v + 1)
          await load(true)
        } else setPhotoError(saved.error)
      }
    } finally {
      setPhotoBusy(false)
    }
  }
  const removePhoto = async () => {
    setPhotoError(null)
    setPhotoBusy(true)
    try {
      await call('remove_photo')
      setPhotoVersion((v) => v + 1)
      await load(true)
    } catch (e) {
      setPhotoError(errorText(e))
    } finally {
      setPhotoBusy(false)
    }
  }

  const fieldsOf = (id: string) => LAYOUT.fields.filter((f) => f.section === id && specs.some((x) => x.key === f.key))
  const shown = LAYOUT.sections.filter((s) => s.id !== CONFIG_ONLY && s.screen !== 'settings' && fieldsOf(s.id).length > 0)
  // the section list beside every part: Details' sections, then the CV and the Stories; from another part a
  // section opens Details and scrolls to it
  const [jump, setJump] = useState<string | null>(null)
  useEffect(() => {
    if (view === 'details' && jump && profile) {
      document.getElementById(jump)?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
      setJump(null)
    }
  }, [view, jump, profile])
  const openPart = (v: 'cv' | 'stories') => {
    setView(v)
    document.querySelector('.main')?.scrollTo?.({ top: 0 })
  }
  const aside = (
    <PageSections
      sections={profile?.config ? shown.map((x) => ({ id: `profile-${x.id}`, label: x.label })) : []}
      parts={[
        { label: 'CV', current: view === 'cv', onOpen: () => openPart('cv') },
        { label: 'Stories', current: view === 'stories', onOpen: () => openPart('stories') },
      ]}
      elsewhere={view === 'details' ? undefined : (id) => {
        setView('details')
        setJump(id)
      }}
    />
  )
  const switcher = (
    <div className="doc-switch" role="group" aria-label="Part of the profile">
      <button type="button" className="pill" aria-pressed={view === 'details'} onClick={() => setView('details')}>
        Details
      </button>
      <button type="button" className="pill" aria-pressed={view === 'cv'} onClick={() => setView('cv')}>
        CV
      </button>
      <button type="button" className="pill" aria-pressed={view === 'stories'} onClick={() => setView('stories')}>
        Stories
      </button>
    </div>
  )
  if (view === 'stories') {
    return (
      <Wrap aside={aside}>
        {switcher}
        <Stories />
      </Wrap>
    )
  }
  if (view === 'cv') {
    return (
      <Wrap aside={aside}>
        {switcher}
        <CvEditor onDraft={onDraft} onSaved={onSaved} onSearchChanged={() => void load(true)} unsaved={cvUnsaved} onUnsaved={setCvUnsaved} />
      </Wrap>
    )
  }
  if (loadError) {
    return (
      <Wrap aside={aside}>
        {switcher}
        <p role="alert" className="error">{named(loadError)}</p>
      </Wrap>
    )
  }
  if (!profile) return <Wrap aside={aside}><Spinner message="Reading your profile…" /></Wrap>
  if (profile.config === null) {
    return (
      <Wrap aside={aside}>
        {switcher}
        <div role="alert" className="error">
          <p>profile/config.json could not be read:</p>
          <ul>
            {profile.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      </Wrap>
    )
  }

  const control = (f: Layout['fields'][number]): ReactNode => {
    const spec = specs.find((s) => s.key === f.key)
    if (!spec) return null
    const err = errors.byKey[f.key]
    const value = values[f.key]
    if (f.key === 'location') return <CityField key={`${f.key}-${undone}`} label={f.label} help={f.help} errors={err} location={String(value)} options={profile.options} onChange={(v) => set(f.key, v)} />
    if (f.key === 'languages') {
      const chosen = value as string[]
      const offered = [...profile.options.languages, ...chosen.filter((l) => !profile.options.languages.some((o) => o.toLowerCase() === l.toLowerCase()))]
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
      const own = MATCH.some(([n]) => n === now) ? [] : [[now, `Your own (${String(value)})`] as [number, string]]
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
              <input type="radio" name={f.key} checked={now === n} onChange={() => set(f.key, String(n))} />
              <span>{label}</span>
            </label>
          ))}
          {err?.map((e) => <p key={e} className="field-error">{named(e)}</p>)}
        </fieldset>
      )
    }
    if (f.key === 'photo') {
      // Where the country's CVs carry no photo it is not asked about, unless there is one to change or remove.
      const policy = photoPolicy(profile.options, String(values['location'] ?? ''))
      const kept = profile.photo?.exists === true
      if (policy === 'no' && !kept) return null
      return (
        <PhotoField
          key={f.key}
          src={kept ? `door-file://profile/photo.jpg?v=${photoVersion}` : null}
          help={photoHelp(policy)}
          error={photoError}
          busy={photoBusy}
          onChoose={() => void choosePhoto()}
          onRemove={() => void removePhoto()}
        />
      )
    }
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
                <input type="radio" name={f.key} checked={value === c} onChange={() => set(f.key, c)} />
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
        return <TextField key={f.key} label={f.label} help={f.help} errors={err} value={String(value)} numeric={spec.type === 'integer' || spec.type === 'number'} onChange={(v) => set(f.key, v)} />
    }
  }

  /** The fields in order, each alone, but neighbours of one `group` together. */
  const runs = (fields: Layout['fields']) =>
    fields.reduce<Layout['fields'][]>((all, f) => {
      const last = all[all.length - 1]
      if (last && f.group && last[0]!.group === f.group) last.push(f)
      else all.push([f])
      return all
    }, [])
  const section = (s: Layout['sections'][number]) => {
    const fields = fieldsOf(s.id)
    return (
      <section key={s.id} className="part" aria-labelledby={`profile-${s.id}`}>
        <h2 className="display-s" id={`profile-${s.id}`}>
          {s.label}
        </h2>
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
    )
  }

  return (
    <Wrap aside={aside}>
      {switcher}
      {errors.general.length > 0 && (
        <ul role="alert" className="error onb-errors">
          {errors.general.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {shown.map(section)}
      <div className="profile-save">
        {/* always there, so Save does not move when the first change makes Undo possible */}
        <button type="button" className="quiet" disabled={changes.length === 0 || saving} onClick={() => {
            setValues(saved)
            setUndone((n) => n + 1)
          }}>
          Undo changes
        </button>
        <button type="button" className="primary" disabled={changes.length === 0 || saving} onClick={() => void save()}>
          Save
        </button>
        {saving ? (
          <Spinner message={refreshing ? 'Updating what we search for (up to two minutes)…' : 'Saving…'} />
        ) : changes.length > 0 ? (
          <p className="small muted">{changes.length === 1 ? '1 unsaved change' : `${changes.length} unsaved changes`}</p>
        ) : done ? (
          <p className="small">Saved.</p>
        ) : null}
      </div>
    </Wrap>
  )
}

function Wrap({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="page-with-aside">
      <div className="settings profile">
        <h1 className="display-l">Profile</h1>
        {children}
      </div>
      {aside}
    </div>
  )
}
