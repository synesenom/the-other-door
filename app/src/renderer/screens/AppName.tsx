import { Fragment } from 'react'
import type { ReactNode } from 'react'

const NAME = 'The other door'

/** The app's name in a sentence: in the display face, so it reads as a name and not as a phrase. */
export function AppName() {
  return <span className="app-name">{NAME}</span>
}

/** The name in a message, unless it is a folder of a path (`…/The other door/profile`, `…\\The other door\\logs`). */
const IN_TEXT = /(?<![/\\])The other door(?![/\\])/g

/** A message that may name the app, its own words or the server's, with the name set as `AppName`; inside a path it
 * stays plain, as the path's own letters. Anything else stays as it is. */
export function named(message: ReactNode): ReactNode {
  if (typeof message !== 'string' || message.search(IN_TEXT) < 0) return message   // search, not test: a /g regex's test keeps its lastIndex
  return message.split(IN_TEXT).map((part, i) => (
    <Fragment key={i}>
      {i > 0 && <AppName />}
      {part}
    </Fragment>
  ))
}
