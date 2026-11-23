import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ErrorBox, ErrorList } from './AppName'
import { call, errorText } from '../api'
import { photoPolicy, type ShowProfile } from './onboarding/reducer'
import { FormSections, formSections } from './profile-form/FormSections'
import { changedKeys, fieldErrors, formValues, toInitArgs, type FieldSpec, type FormValues } from './profile-form/form'
import { CvEditor, SAVE_AFTER_MS } from './CvEditor'
import { CvStyle, type CvStyles } from './CvStyle'
import { PhotoField, photoHelp } from './PhotoField'
import { Spinner } from './Spinner'
import { Stories } from './Stories'
import { PageSections } from './PageSections'

type Profile = ShowProfile & { options: ShowProfile['options'] & { fields?: FieldSpec[]; cv_styles?: CvStyles }; config: Record<string, unknown> | null }

/**
 * Profile: one page. Every key of profile/config.json in sections (the tuning keys left to config.json), then the CV
 * and the Stories. Nothing is saved with a button: each detail goes to init_profile (alone, which checks it; an error is
 * said under its field) a second after typing stops, on leaving the field, at once for a choice, and when Profile is
 * left or the window closes. The CV text, the CV file and pages, the photo and the stories save themselves too.
 * On leaving, `onLeave(termsChanged, wrote)` tells the app whether the role targets or ad languages changed and whether anything was written, so it can
 * propose the search terms again (Profile is gone by then: the app runs it).
 */
/** Where Profile opens: a section scrolled into view, `cv` and `stories` among them. */
export type ProfileStart = { section: string }

/** Typed, so saved after a pause; every other field is a choice, saved at once. */
const TYPED = new Set(['string', 'path', 'integer', 'number'])
const termsOf = (v: FormValues) => JSON.stringify([v['role_targets'], v['languages']])

export function Profile({ onSaved, onDraft, onLeave, start }: { onSaved: () => void; onDraft: () => void; onLeave?: (termsChanged: boolean, wrote: boolean) => void; start?: ProfileStart }) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [values, setValues] = useState<FormValues>({})
  const [errors, setErrors] = useState<{ byKey: Record<string, string[]>; general: string[] }>({ byKey: {}, general: [] })
  // What is on disk and what is shown, read by the writes (which run later than the render that asked for them)
  const savedRef = useRef<FormValues>({})
  const valuesRef = useRef<FormValues>({})
  const specsRef = useRef<FieldSpec[]>([])
  // the value of a key that init_profile refused, not sent again until it changes
  const refused = useRef<Record<string, string>>({})
  const queue = useRef<Promise<void>>(Promise.resolve())
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const wrote = useRef(false)
  const termsAtStart = useRef<string | null>(null)
  // The CV photo is saved the moment it is chosen or removed (its own tools): why one was refused, and a counter that renews the preview.
  const [photoBusy, setPhotoBusy] = useState(false)
  const [photoError, setPhotoError] = useState<string | null>(null)
  const [photoVersion, setPhotoVersion] = useState(0)
  // Counts the saves of the CV text, for the CV style's sample
  const [cvSaves, setCvSaves] = useState(0)

  const specs = profile?.options.fields ?? []
  specsRef.current = specs
  /** Read the profile; `keepEdits` (a change made elsewhere, e.g. titles added from the CV's market report) keeps what is typed and unsaved. */
  const load = async (keepEdits = false) => {
    try {
      const p = await call<Profile>('show_profile')
      setProfile(p)
      const v = formValues(p.config, p.options.fields ?? [])
      const typed = valuesRef.current
      const kept = keepEdits ? { ...v, ...Object.fromEntries(changedKeys(savedRef.current, typed).map((k) => [k, typed[k]!])) } : v
      savedRef.current = v
      valuesRef.current = kept
      if (termsAtStart.current === null) termsAtStart.current = termsOf(v)
      setValues(kept)
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

  /** Write what differs from the disk (only `key`, or every key that does), each key alone so one refusal holds back no other; one write at a time. */
  const flush = (key?: string): Promise<void> => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    const run = queue.current.then(async () => {
      const keys = key ? [key] : changedKeys(savedRef.current, valuesRef.current)
      for (const k of keys) {
        const sent = valuesRef.current[k]
        if (sent === undefined || JSON.stringify(sent) === JSON.stringify(savedRef.current[k])) continue
        if (refused.current[k] === JSON.stringify(sent)) continue
        const args = toInitArgs({ [k]: savedRef.current[k]! }, { [k]: sent }, specsRef.current)
        try {
          if (Object.keys(args).length) await call('init_profile', args)
          savedRef.current = { ...savedRef.current, [k]: sent }
          delete refused.current[k]
          wrote.current = true
          setErrors((e) => ({ byKey: { ...e.byKey, [k]: [] }, general: [] }))
        } catch (e) {
          refused.current[k] = JSON.stringify(sent)
          const found = fieldErrors(errorText(e), specsRef.current)
          setErrors((prev) => ({ byKey: { ...prev.byKey, [k]: [], ...found.byKey }, general: found.general }))
        }
      }
    })
    queue.current = run
    return run
  }
  const flushRef = useRef(flush)
  flushRef.current = flush
  const onLeaveRef = useRef(onLeave)
  onLeaveRef.current = onLeave
  // what is still waiting is written when Profile is left, or when the window closes (the app waits for it)
  useEffect(() => {
    const unregister = window.door.onBeforeClose(() => flushRef.current())
    return () => {
      unregister()
      void flushRef.current().then(() => {
        onLeaveRef.current?.(termsAtStart.current !== null && termsOf(savedRef.current) !== termsAtStart.current, wrote.current)
      })
    }
  }, [])

  const set = (key: string, value: FormValues[string]) => {
    valuesRef.current = { ...valuesRef.current, [key]: value }
    setValues(valuesRef.current)
    if (TYPED.has(specs.find((s) => s.key === key)?.type ?? '')) {
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => void flush(), SAVE_AFTER_MS)
    } else void flush(key)
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
        onBlur={() => void flush()}
        photo={photoField(profile)}
      />
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
