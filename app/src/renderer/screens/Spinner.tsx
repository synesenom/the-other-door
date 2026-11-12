import { named } from './AppName'
// A quiet "something is running" line: the message only, never ids or pids.
export function Spinner({ message }: { message: string }) {
  return (
    <p role="status" className="spinner-line small muted">
      <span className="spinner" aria-hidden="true" />
      {named(message)}
    </p>
  )
}
