import { useState } from 'react'
import type { Dispatch, DragEvent } from 'react'
import { named } from '../AppName'
import { Hint } from '../Hint'
import { FromDrive } from './FromDrive'
import { Frame } from './parts'
import { isLinkedIn } from './reducer'
import type { Action, WizardState } from './reducer'

const LINKEDIN_HINT = "LinkedIn pages can't be read; save your profile as a PDF (More → Save to PDF) and add that file."

/** Why a typed address cannot be read, or null. */
function urlProblem(value: string): string | null {
  let u: URL
  try {
    u = new URL(value)
  } catch {
    return 'That is not a web page address (it starts with http:// or https://).'
  }
  if (u.protocol !== 'https:' && u.protocol !== 'http:') return 'That is not a web page address (it starts with http:// or https://).'
  return isLinkedIn(value) ? LINKEDIN_HINT : null
}

interface Props {
  state: WizardState
  dispatch: Dispatch<Action>
  onNext: () => void
  onBack?: () => void
  /** Only on a first set-up that may reach Google Drive: the profile was brought from there, so the wizard is over. */
  onPulled?: () => void
}

/** The one input step: the CV file, the LinkedIn PDF, any public page. Reading them is the next screen. */
export function Sources({ state, dispatch, onNext, onBack, onPulled }: Props) {
  const [refused, setRefused] = useState<{ name: string; reason: string }[]>([])
  const [urlText, setUrlText] = useState('')
  const [urlError, setUrlError] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  const redo = state.mode === 'redo'
  const chosen = [
    ...state.files.map((f) => ({ key: f.token, name: f.name, remove: () => dispatch({ type: 'dropFile', token: f.token }) })),
    ...state.urls.map((u) => ({ key: u, name: u, remove: () => dispatch({ type: 'dropUrl', url: u }) })),
  ]
  // An address typed and not yet entered counts when it can be read: Continue takes it, so the click is never lost.
  const typed = urlText.trim() !== '' && urlProblem(urlText.trim()) === null
  const nothingToRead = state.files.length === 0 && state.urls.length === 0 && !typed

  const add = (picked: Awaited<ReturnType<typeof window.door.pickCvFiles>>) => {
    setRefused(picked.refused)
    dispatch({ type: 'addFiles', files: picked.files })
  }
  /** Adds the typed address; false when it cannot be read (the box says why). */
  const addUrl = (): boolean => {
    const value = urlText.trim()
    if (!value) return true
    const problem = urlProblem(value)
    setUrlError(problem)
    if (problem) return false
    dispatch({ type: 'addUrl', url: value })
    setUrlText('')
    return true
  }
  const drop = async (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    add(await window.door.dropCvFiles(Array.from(e.dataTransfer.files)))
  }

  return (
    <Frame
      title="Tell me about yourself"
      lead={redo ? 'Your answers stay.' : undefined}
      onBack={onBack}
      onNext={() => {
        if (addUrl()) onNext()
      }}
      nextLabel="Continue"
      nextDisabled={nothingToRead}
    >
      {onPulled && !redo && <FromDrive onPulled={onPulled} />}
      <div
        className="onb-drop-area"
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => void drop(e)}
      >
        <button type="button" className={over ? 'onb-drop onb-drop-over' : 'onb-drop'} onClick={async () => add(await window.door.pickCvFiles())}>
          Drop relevant documents here (CV or LinkedIn PDF)
        </button>
        <Hint label="About the documents">PDF, DOCX, Markdown or text, up to 25 MB each. On LinkedIn: More → Save to PDF.</Hint>
      </div>
      {refused.map((r) => (
        <p key={r.name} role="alert" className="error small">{named(`${r.name}: ${r.reason}`)}</p>
      ))}
      <div className="field onb-field">
        <div className="onb-url">
          <input
            type="text"
            className="onb-input"
            aria-label="Any relevant URL"
            placeholder="Any relevant URL, then press Enter"
            value={urlText}
            onBlur={(e) => {
              // Leaving the box for Continue (or Back): the button takes it. Adding it here would put the chips
              // above the buttons between the press and the release, and the click would land on nothing.
              if (!(e.relatedTarget instanceof Element && e.relatedTarget.closest('.onb-actions'))) addUrl()
            }}
            onChange={(e) => {
              setUrlText(e.target.value)
              setUrlError(null)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                addUrl()
              }
            }}
          />
          <Hint label="About the URL">A personal site, GitHub, a publication list: anything public.</Hint>
        </div>
        {urlError && (
          <p role="alert" className="error small">
            {named(urlError)}
          </p>
        )}
      </div>
      {chosen.length > 0 && (
        <ul className="chips onb-chips" aria-label="Sources, chosen">
          {chosen.map((s) => (
            <li key={s.key} className="chip small">
              <span className="chip-text" title={s.name}>
                {s.name}
              </span>
              <button type="button" className="chip-x" aria-label={`Remove ${s.name}`} onClick={s.remove}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </Frame>
  )
}
