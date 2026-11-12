import { named } from './AppName'

export type PhotoPolicy = 'no' | 'optional' | 'expected'

/** What the city's country does with a photo on a CV, in a line. */
export function photoHelp(policy: PhotoPolicy): string {
  if (policy === 'expected') return "CVs in your city's country usually carry a photo. It goes on the CVs for jobs there; the cover letter has none."
  if (policy === 'optional') return "A photo is optional on a CV in your city's country. If you add one, it goes on the CVs for jobs there; the cover letter has none."
  return 'CVs in your city\'s country do not carry a photo, so none is added.'
}

interface Props {
  /** The address of the photo kept, when there is one (the preview). */
  src?: string | null
  /** The name of a picture chosen but not saved yet (it has no preview). */
  pending?: string | null
  help?: string
  /** Why the last picture was refused. */
  error?: string | null
  busy?: boolean
  onChoose: () => void
  onRemove: () => void
}

/**
 * The CV photo: its preview, Choose or Change (a file dialog the main process runs), Remove, and the reason a
 * picture was refused under it. It saves nothing itself; the Profile screen and the wizard's review decide when.
 */
export function PhotoField({ src, pending, help, error, busy, onChoose, onRemove }: Props) {
  const has = Boolean(src || pending)
  return (
    <div className="field onb-field photo-field">
      <span className="field-label">Photo</span>
      {src && <img className="photo-preview" src={src} alt="Your photo" width={96} />}
      {pending && <p className="body">{pending}</p>}
      <div className="actions">
        <button type="button" className="secondary" disabled={busy} onClick={onChoose}>
          {has ? 'Change photo…' : 'Choose a photo…'}
        </button>
        {has && (
          <button type="button" className="quiet" disabled={busy} onClick={onRemove}>
            Remove
          </button>
        )}
      </div>
      {help && <p className="small muted">{help}</p>}
      {error && (
        <p role="alert" className="field-error">
          {named(error)}
        </p>
      )}
    </div>
  )
}
