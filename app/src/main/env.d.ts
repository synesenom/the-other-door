// electron-vite sets the build's mode (`--mode demo`) on import.meta.env in the main process too.
interface ImportMetaEnv {
  readonly MODE: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
// Set by electron-vite's `define` from DOOR_UPDATE_FEED at build time (electron.vite.config.ts).
declare const __UPDATE_FEED__: string
