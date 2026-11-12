import { placeLine, scoreText, statusWord } from '../api'
import type { Match } from '../api'

interface Props {
  match: Match
  /** The posting last opened from the list: its row stays marked on the way back. */
  selected: boolean
  onSelect: () => void
  /** Below the bar: shown only until a first posting reaches it. */
  weak?: boolean
}

/** One posting in a list: title, company and place, status word, score. */
export function MatchRow({ match: m, selected, onSelect, weak = false }: Props) {
  const word = statusWord(m.status)
  return (
    <li>
      <button type="button" className="row" aria-current={selected} onClick={onSelect}>
        <span className="row-main">
          <span className="row-title">
            {m.is_new && <span className="new-dot" role="img" aria-label="New since your last review" />}
            <span className="title">{m.title}</span>
          </span>
          {m.title_en && m.title_en !== m.title && <span className="small muted">{m.title_en}</span>}
          <span className="small muted">{placeLine(m.company, m.location)}</span>
          {word && <span className="small muted">{word}</span>}
          {weak && <span className="small muted">Weak match</span>}
        </span>
        <span className="score-s">{scoreText(m.score)}</span>
      </button>
    </li>
  )
}
