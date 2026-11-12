// The window's own background before the page paints: the ground colour (docs/design/tokens.json) of the
// system's theme, so the first frame is parchment (or the dark ground), never white.
const GROUND = { light: '#F1E6CF', dark: '#1E1A16' }

export function windowBackground(dark: boolean): string {
  return dark ? GROUND.dark : GROUND.light
}
