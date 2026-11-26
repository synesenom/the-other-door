import type { AdIntegrity } from '../api'
import { WarningMark } from './CheckMark'

/** The posting's note on a suspicious ad: what was done, and (behind a disclosure) the text found, shown as text. */
export function AdFindings({ integrity }: { integrity?: AdIntegrity | null }) {
  if (integrity?.verdict !== 'suspicious' || !integrity.findings.length) return null
  const removed = integrity.findings.some((f) => f.kind !== 'link_mismatch')  // every other kind is text taken out
  const link = integrity.findings.some((f) => f.kind === 'link_mismatch')
  const lines = integrity.findings.map((f) => f.excerpt).filter((e): e is string => Boolean(e))
  return (
    <div className="ad-findings">
      {removed && <Line text="Part of this ad was hidden from readers or written for an AI. It was left out of the score." />}
      {link && <Line text="A link in this ad names one site and opens another." />}
      {lines.length > 0 && (
        <details className="small muted">
          <summary>See what was found</summary>
          <ul>
            {lines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function Line({ text }: { text: string }) {
  return (
    <p className="small marked">
      <span className="mark">
        <WarningMark />
      </span>
      <span>{text}</span>
    </p>
  )
}
