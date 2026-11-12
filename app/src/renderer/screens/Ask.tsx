import { useEffect, useId, useRef, useState } from 'react'
import { named } from './AppName'
import { call, errorText } from '../api'
import { Spinner } from './Spinner'

export interface AskGoTo {
  screen: 'matches' | 'posting' | 'applications' | 'employers' | 'cv'
  job_ids?: string[]
}
interface Answer {
  answer: string
  go_to: AskGoTo | null
  sources: string[]
}

const OPEN: Record<AskGoTo['screen'], string> = {
  matches: 'Open Matches',
  posting: 'Open the posting',
  applications: 'Open Applications',
  employers: 'Open your employers',
  cv: 'Open your CV',
}
const HISTORY = 5

/**
 * "Ask about your jobs": one question, answered from the read tools (`ask`), in the sidebar. The answer is a
 * sentence or two with, when a screen shows it, a button to go there. A question and an answer, not a
 * conversation: a second question waits until the first is answered.
 */
export function Ask({ onGo }: { onGo: (to: AskGoTo) => void }) {
  const [text, setText] = useState('')
  const [state, setState] = useState<{ kind: 'idle' } | { kind: 'asking'; since: number } | { kind: 'done'; a: Answer } | { kind: 'error'; message: string }>({ kind: 'idle' })
  const [, tick] = useState(0)
  const past = useRef<string[]>([])
  const back = useRef(-1)
  const id = useId()

  useEffect(() => {
    if (state.kind !== 'asking') return
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [state.kind])

  const send = async () => {
    const question = text.trim()
    if (!question || state.kind === 'asking') return
    past.current = [question, ...past.current.filter((q) => q !== question)].slice(0, HISTORY)
    back.current = -1
    setState({ kind: 'asking', since: Date.now() })
    try {
      setState({ kind: 'done', a: await call<Answer>('ask', { question }) })
    } catch (e) {
      setState({ kind: 'error', message: errorText(e) })
    }
  }

  const asking = state.kind === 'asking'
  return (
    <div className="ask">
      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault()
          void send()
        }}
      >
        <label htmlFor={id} className="visually-hidden">
          Ask about your jobs
        </label>
        <input
          id={id}
          className="onb-input ask-input"
          placeholder="Ask about your jobs…"
          value={text}
          disabled={asking}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowUp' && past.current.length) {
              e.preventDefault()
              back.current = Math.min(back.current + 1, past.current.length - 1)
              setText(past.current[back.current]!)
            } else if (e.key === 'ArrowDown' && back.current >= 0) {
              e.preventDefault()
              back.current -= 1
              setText(back.current >= 0 ? past.current[back.current]! : '')
            }
          }}
        />
        <button type="submit" className="primary ask-send" disabled={asking || !text.trim()}>
          Ask
        </button>
      </form>
      {asking && <Spinner message={`Looking… ${Math.round((Date.now() - state.since) / 1000)} s`} />}
      {state.kind === 'error' && (
        <p role="alert" className="field-error">
          {named(state.message)}
        </p>
      )}
      {state.kind === 'done' && (
        <div className="ask-answer">
          <span className="dash" aria-hidden="true" />
          <p className="body">{state.a.answer}</p>
          {state.a.go_to && (
            <button type="button" className="secondary" onClick={() => onGo(state.a.go_to!)}>
              {OPEN[state.a.go_to.screen]}
            </button>
          )}
          {state.a.sources.length > 0 && <p className="small muted">{`from: ${state.a.sources.join(', ')}`}</p>}
        </div>
      )}
    </div>
  )
}
