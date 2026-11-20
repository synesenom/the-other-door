import type { ActionArgs, ActionName, ActionResult, Envelope, Events } from '../main/ipc'
import type { PickResult } from '../main/cv-sources'

declare global {
  interface Window {
    door: {
      call(tool: string, args?: Record<string, unknown>, callId?: string, tokens?: string[]): Promise<Envelope>
      onProgress(callId: string, cb: (p: { progress: number; total?: number; message: string }) => void): () => void
      /** Every other capability of the main process: one entry of the action table in src/main/ipc.ts (its handler and its types). A misspelled action fails the typecheck. */
      invoke<A extends ActionName>(action: A, ...args: ActionArgs<A>): Promise<ActionResult<A>>
      /** What the main process pushes (run board, update state, sign-in state, a clicked notification); returns the way to stop. */
      on<E extends keyof Events>(event: E, cb: (payload: Events[E]) => void): () => void
      onBeforeClose(cb: () => Promise<void>): () => void
      /** A drop: only the preload can turn a dropped File into a path; the files come back as tokens. */
      dropCvFiles(files: File[]): Promise<PickResult>
      /** The phone app's address of a prepared page image (issue 303); the desktop app uses door-file://. */
      pageUrl?(jobId: string, pngPath: string, v: number, sent?: boolean): string
    }
  }
}

export {}
