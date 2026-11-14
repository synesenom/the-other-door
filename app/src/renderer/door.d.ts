import type { Envelope } from '../main/ipc'
import type { PickResult } from '../main/cv-sources'
import type { LoginState } from '../main/claude-login'
import type { NoticeTarget } from '../main/notices'
import type { UpdateResult } from '../main/updates'
import type { RunBoard } from '../main/run-board'

declare global {
  interface Window {
    door: {
      call(tool: string, args?: Record<string, unknown>, callId?: string): Promise<Envelope>
      onProgress(callId: string, cb: (p: { progress: number; total?: number; message: string }) => void): () => void
      openExternal(url: string): Promise<{ ok: boolean; error?: string }>
      /** `sent`: the copy kept when the application was sent. */
      /** Save CV / Save letter: a save dialog on the desktop (`path` where it went), the browser's download on the phone. */
      saveMaterial(jobId: string, which: 'cv' | 'cover_letter', sent: boolean, name: string): Promise<{ ok: boolean; path?: string; canceled?: true; error?: string }>
      /** Opens the file dialog (in the main process); the files come back as tokens, never paths. */
      pickCvFiles(): Promise<PickResult>
      dropCvFiles(files: File[]): Promise<PickResult>
      /** Drafts a CV from picked files (by token) and web pages. */
      draftCv(payload: { files: string[]; urls: string[] }): Promise<Envelope>
      /** Forgets the picked files (the wizard closed). */
      clearCvSources(): Promise<void>
      /** The CV photo: a picture chosen in an open dialog (a token and its name, or why not), then saved by its token (save_photo's answer). */
      pickPhoto(): Promise<{ token: string; name: string } | { canceled: true } | { error: string }>
      savePhoto(token: string): Promise<Envelope>
      /** Signing in to Claude: the main process runs `claude auth login` and pushes its state. */
      claudeLogin: {
        start(email?: string): Promise<{ ok: boolean; error?: string }>
        /** The code the sign-in page showed, when the browser could not hand it back. */
        sendCode(code: string): Promise<{ ok: boolean; error?: string }>
        /** The page claude printed, again. */
        openPage(): Promise<{ ok: boolean; error?: string }>
        cancel(): Promise<{ ok: boolean }>
        state(): Promise<LoginState>
        onState(cb: (state: LoginState) => void): () => void
      }
      /** Where the app runs; `home` is the data folder, shown and never sent back. */
      info(): Promise<{ demo: boolean; sandbox?: 'onboard'; home?: string; remote?: boolean }>
      /** The phone app's address of a prepared page image (issue 303); the desktop app uses door-file://. */
      pageUrl?(jobId: string, pngPath: string, v: number, sent?: boolean): string
      /** Writes an export where the user says in a save dialog (export_data's answer, or canceled). */
      exportData(): Promise<Envelope | { ok: false; canceled: true }>
      /** Picks an archive to import in an open dialog: a token and the file's name. */
      pickArchive(): Promise<{ token: string; name: string } | { canceled: true } | { error: string }>
      /** Imports the picked archive (import_data's answer). */
      importData(token: string): Promise<Envelope>
      /** Writes a problem report where the user says in a save dialog (report_problem's answer, or canceled). */
      reportProblem(): Promise<Envelope | { ok: false; canceled: true }>
      /** Shows the data folder in the file manager. */
      showHome(): Promise<{ ok: boolean }>
      /** Is a newer version out: what the app's own checks found, at start and once a day (updates.ts). */
      checkUpdate(): Promise<UpdateResult | { enabled: false }>
      /** Restart now to install a downloaded update; `{ ok: false }` when none is downloaded. */
      installUpdate(): Promise<{ ok: boolean }>
      /** The update's state as it changes, e.g. a download finishing; returns the way to stop. */
      onUpdateState(cb: (state: UpdateResult | { enabled: false }) => void): () => void
      stopRun(): Promise<{ ok: boolean; error?: string }>
      showRun(startedAt: string): Promise<{ ok: boolean; error?: string }>
      runBoard(): Promise<RunBoard>
      onRunBoard(cb: (board: RunBoard) => void): () => void
      /** A notification was clicked: where to go. Anything else the page gets is checked by the page. */
      onOpen(cb: (target: NoticeTarget) => void): () => void
    }
  }
}

export {}
