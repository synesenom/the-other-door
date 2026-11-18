// electron-vite sets the build's mode (`--mode sandbox`) on import.meta.env in the main process too.
interface ImportMetaEnv {
  readonly MODE: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
