// Pieces every step shares: the frame (title, errors, one primary button,
// quiet Back and Skip), the chip input and the city picker.
import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import { named } from '../AppName'
import { Hint } from '../Hint'
import type { ProfileOptions } from './reducer'

interface FrameProps {
  title: string
  lead?: ReactNode
  /** What a failed Save says about this step's answers. */
  errors?: string[]
  children?: ReactNode
  onBack?: () => void
  onNext?: () => void
  nextLabel?: string
  nextDisabled?: boolean
  /** Shown beside a disabled primary button: why it waits. */
  reason?: string
  busy?: boolean
}

export function Frame({ title, lead, errors, children, onBack, onNext, nextLabel = 'Next', nextDisabled, reason, busy }: FrameProps) {
  return (
    <section className="onb-step" aria-label={title}>
      <h1 className="display-l">{title}</h1>
      {lead && <p className="subtitle">{lead}</p>}
      {errors && errors.length > 0 && (
        <ul role="alert" className="error onb-errors">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {children}
      <div className="actions onb-actions">
        {onBack && (
          <button type="button" className="quiet" disabled={busy} onClick={onBack}>
            Back
          </button>
        )}
        {onNext && (
          <button type="button" className="primary" disabled={nextDisabled || busy} onClick={onNext}>
            {nextLabel}
          </button>
        )}
        {reason && nextDisabled && <p className="small muted onb-reason">{reason}</p>}
      </div>
    </section>
  )
}

/** A field's name, and what it means behind an icon beside it: nothing under the box but its errors. */
export function FieldLabel({ htmlFor, label, help, after }: { htmlFor: string; label: string; help?: ReactNode; after?: ReactNode }) {
  return (
    <div className="field-name">
      <label htmlFor={htmlFor} className="field-label">
        {label}
      </label>
      {after}
      {help && <Hint label={`About ${label}`}>{typeof help === 'string' ? named(help) : help}</Hint>}
    </div>
  )
}

/** A list of chips with an input: Enter adds what is typed, and the box says so; the x drops a chip. */
export function ChipInput({ label, hideLabel, values, onAdd, onDrop, hint, placeholder = 'Type, then press Enter' }: { hideLabel?: boolean; placeholder?: string;  label: string; values: string[]; onAdd: (v: string) => void; onDrop: (v: string) => void; hint?: string }) {
  const [text, setText] = useState('')
  const id = useId()
  return (
    <div className="field onb-field">
      {!hideLabel && <FieldLabel htmlFor={id} label={label} help={hint} />}
      <input
        id={id}
        type="text"
        className="onb-input"
        value={text}
        placeholder={placeholder}
        aria-label={hideLabel ? label : undefined}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            if (text.trim()) onAdd(text)
            setText('')
          }
        }}
      />
      {values.length > 0 && (
        <ul className="chips onb-chips" aria-label={`${label}, chosen`}>
          {values.map((v) => (
            <li key={v} className="chip small">
              <span className="chip-text" title={v}>
                {v}
              </span>
              <button type="button" className="chip-x" aria-label={`Remove ${v}`} onClick={() => onDrop(v)}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** A field: its name with its help behind an icon, its control, and its errors under it. */
function Field({ id, label, help, errors, children }: { id: string; label: string; help?: string; errors?: string[]; children: ReactNode }) {
  return (
    <div className="field onb-field">
      <FieldLabel htmlFor={id} label={label} help={help} />
      {children}
      {errors?.map((e) => (
        <p key={e} className="field-error">
          {named(e)}
        </p>
      ))}
    </div>
  )
}

/** A text field with its label. */
export function TextField({ label, help, errors, value, onChange, type = 'text', autoComplete, numeric }: { label: string; help?: string; errors?: string[]; value: string; onChange: (v: string) => void; type?: string; autoComplete?: string; numeric?: boolean }) {
  const id = useId()
  return (
    <Field id={id} label={label} help={help} errors={errors}>
      <input id={id} type={type} inputMode={numeric ? 'decimal' : undefined} className="onb-input" value={value} autoComplete={autoComplete} onChange={(e) => onChange(e.target.value)} />
    </Field>
  )
}

const OTHER = 'Other…'

/** The city: a known one from the list, or any other typed in, which only the worldwide boards serve. */
export function CityField({ label = 'City', help, errors, location, onChange, options }: { label?: string; help?: string; errors?: string[]; location: string; onChange: (v: string) => void; options: ProfileOptions }) {
  const known = options.cities.find((c) => c.name.toLowerCase() === location.trim().toLowerCase())
  const [other, setOther] = useState(location !== '' && !known)
  const id = useId()
  return (
    <>
      <Field id={id} label={label} help={help} errors={errors}>
        <select
          id={id}
          className="onb-input"
          value={other ? OTHER : (known?.name ?? '')}
          onChange={(e) => {
            const isOther = e.target.value === OTHER
            setOther(isOther)
            onChange(isOther ? '' : e.target.value)
          }}
        >
          <option value="">Choose a city</option>
          {options.cities.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
          <option value={OTHER}>{OTHER}</option>
        </select>
      </Field>
      {other && (
        <>
          <TextField label="Your city" value={location} onChange={onChange} />
          {location.trim() !== '' && !known && (
            <p className="notice small">{named(`${location.trim()} isn't in a supported country yet, so only the worldwide job boards are searched. Adding a country and its job sites is described in docs/adding-a-site.md.`)}</p>
          )}
        </>
      )}
    </>
  )
}
