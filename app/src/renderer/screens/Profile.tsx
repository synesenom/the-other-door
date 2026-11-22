import { useEffect, useState, type ReactNode } from 'react'
import { ErrorBox, ErrorList } from './AppName'
import { call, errorText } from '../api'
import { photoPolicy, type ShowProfile } from './onboarding/reducer'
import { FormSections, formSections } from './profile-form/FormSections'
import { changedKeys, fieldErrors, formValues, toInitArgs, type FieldSpec, type FormValues } from './profile-form/form'
import { CvEditor } from './CvEditor'
import { CvStyle, type CvStyles } from './CvStyle'
import { PhotoField, photoHelp } from './PhotoField'
import { Spinner } from './Spinner'
import { Stories } from './Stories'
import { PageSections } from './PageSections'

type Profile = ShowProfile & { options: ShowProfile['options'] & { fields?: FieldSpec[]; cv_styles?: CvStyles }; config: Record<string, unknown> | null }

/**
 * Profile: one page. Every key of profile/config.json in sections (the tuning keys left to config.json), then the CV
 * and the Stories. One Save writes what changed: the details through init_profile (which checks it all; an error is
 * said under its field), then the CV through the editor. The CV's file and pages, the photo and the stories are
 * each saved the moment they change, by their own controls.
 */
/** Where Profile opens: a section scrolled into view, `cv` and `stories` among them. */
export type ProfileStart = { section: string }

export function Profile({ onSaved, onDraft, start }: { onSaved: () => void; onDraft: () => void; start?: ProfileStart }) {
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
  // The CV photo is saved the moment it is chosen or removed (its own tools), not with Save: why one was refused, and a counter that renews the preview.
  const [photoBusy, setPhotoBusy] = useState(false)
  const [photoError, setPhotoError] = useState<string | null>(null)
  const [photoVersion, setPhotoVersion] = useState(0)
  // Counts the saves of the CV text, for the CV style's sample
  const [cvSaves, setCvSaves] = useState(0)

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
  const startSection = start?.section ?? null
  // the section asked for, brought into view once it is on the page
  useEffect(() => {
    if (!profile || !startSection) return
    const show = () => {
      const target = document.getElementById(`profile-${startSection}`)
      target?.scrollIntoView?.({ block: 'start' })
      return Boolean(target)
    }
    if (show()) return
    const watch = new MutationObserver(() => show() && watch.disconnect())
    watch.observe(document.body, { childList: true, subtree: true })
    return () => watch.disconnect()
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
      try {
        await call('init_profile', toInitArgs(saved, values, specs))
      } catch (e) {
        setErrors(fieldErrors(errorText(e), specs))
        return
      }
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
    } finally {
      setSaving(false)
    }
  }

  const choosePhoto = async () => {
    setPhotoError(null)
    setPhotoBusy(true)
    try {
      const picked = await window.door.invoke('pick-photo')
      if ('error' in picked) setPhotoError(picked.error)
      else if ('token' in picked) {
        try {
          await call('save_photo', {}, { tokens: [picked.token] })
          setPhotoVersion((v) => v + 1)
          await load(true)
        } catch (e) {
          setPhotoError(errorText(e))
        }
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

  const shown = formSections(specs)
  const photoField = (p: Profile): ReactNode => {
    // Where the country's CVs carry no photo it is not asked about, unless there is one to change or remove.
    const policy = photoPolicy(p.options, String(values['location'] ?? ''))
    const kept = p.photo?.exists === true
    if (policy === 'no' && !kept) return null
    return (
      <PhotoField
        src={kept ? `door-file://profile/photo.jpg?v=${photoVersion}` : null}
        help={photoHelp(policy)}
        error={photoError}
        busy={photoBusy}
        onChoose={() => void choosePhoto()}
        onRemove={() => void removePhoto()}
      />
    )
  }
  const aside = (
    <PageSections
      sections={[
        ...(profile?.config ? shown.map((x) => ({ id: `profile-${x.section.id}`, label: x.section.label })) : []),
        { id: 'profile-cv', label: 'Master CV' },
        ...(profile?.config && profile.options.cv_styles ? [{ id: 'profile-cv-style', label: 'CV style' }] : []),
        { id: 'profile-stories', label: 'Stories' },
      ]}
    />
  )

  // the details: read, or why they could not be (only this part: the CV and the Stories read their own)
  const details = loadError ? (
    <ErrorBox text={loadError} />
  ) : !profile ? (
    <Spinner message="Reading your profile…" />
  ) : profile.config === null ? (
    <div role="alert" className="error">
      <p>profile/config.json could not be read:</p>
      <ul>
        {profile.errors.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
    </div>
  ) : (
    <div className="profile-details">
      <FormSections
        specs={specs}
        options={profile.options}
        values={values}
        set={set}
        errors={errors.byKey}
        idPrefix="profile"
        undone={undone}
        photo={photoField(profile)}
      />
      {/* the details' bar: with the details only, and only while they have unsaved changes (the CV, the photo and the stories save themselves) */}
      {(changes.length > 0 || saving || done) && (
        <div className="profile-save">
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
          ) : (
            <p className="small">Saved.</p>
          )}
        </div>
      )}
    </div>
  )

  return (
    <Wrap aside={aside}>
      {errors.general.length > 0 && <ErrorList messages={errors.general} />}
      {details}
      <CvEditor onDraft={onDraft} onSaved={onSaved} onCvSaved={() => setCvSaves((n) => n + 1)} />
      {profile?.config && profile.options.cv_styles && <CvStyle specs={specs} config={profile.config} styles={profile.options.cv_styles} cvSaves={cvSaves} />}
      <section className="part" aria-labelledby="profile-stories">
        <h2 className="display-s" id="profile-stories">
          Stories
        </h2>
        <Stories />
      </section>
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
