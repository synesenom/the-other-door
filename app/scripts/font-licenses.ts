// The bundled font packages and where their licences go in a build
// (out/renderer/licenses/<family>-OFL.txt, see electron.vite.config.ts).
export const FONT_PACKAGES = [
  { package: '@fontsource/figtree', family: 'figtree' },
  { package: '@fontsource/young-serif', family: 'young-serif' },
] as const
