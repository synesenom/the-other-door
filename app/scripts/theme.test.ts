import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'
import { generateTheme } from './theme'

const APP = join(__dirname, '..')
const tokens = JSON.parse(readFileSync(join(APP, '..', 'docs', 'design', 'tokens.json'), 'utf8'))
const css = generateTheme(tokens)

/** The declarations inside the first block that opens with `selector {`. */
function block(text: string, selector: string): Record<string, string> {
  const start = text.indexOf(`${selector} {`)
  expect(start, `no block for ${selector}`).toBeGreaterThanOrEqual(0)
  const body = text.slice(start + selector.length + 2, text.indexOf('}', start))
  return Object.fromEntries(
    body
      .split(';')
      .map((d) => d.trim())
      .filter(Boolean)
      .map((d) => {
        const i = d.indexOf(':')
        return [d.slice(0, i).trim(), d.slice(i + 1).trim()]
      }),
  )
}

describe('generateTheme', () => {
  const root = block(css, ':root')

  it('puts every light colour on :root', () => {
    for (const [name, { value }] of Object.entries<{ value: string }>(tokens.color.light)) {
      expect(root[`--color-${name}`]).toBe(value)
    }
  })

  it('overrides only the dark colours, under the media query and [data-theme="dark"]', () => {
    const dark = Object.keys(tokens.color.dark)
    expect(dark.sort()).toEqual(['accent', 'accent-tint', 'border', 'danger', 'ink', 'ink-muted', 'page', 'scrim', 'success', 'surface', 'ground', 'warning'].sort())
    const media = css.slice(css.indexOf('@media (prefers-color-scheme: dark)'))
    const inMedia = block(media, ':root:not([data-theme="light"])')
    const forced = block(css, '[data-theme="dark"]')
    for (const name of dark) {
      expect(inMedia[`--color-${name}`]).toBe(tokens.color.dark[name].value)
      expect(forced[`--color-${name}`]).toBe(tokens.color.dark[name].value)
    }
    expect(Object.keys(forced).sort()).toEqual(dark.map((n) => `--color-${n}`).sort())
  })

  it('has a dark page and a scrim in both schemes', () => {
    expect(tokens.color.dark.page.value).toBe('#36302A')
    expect(tokens.color.light.scrim.value).toBe('rgba(30,26,22,0.4)')
    expect(tokens.color.dark.scrim.value).toBe('rgba(0,0,0,0.55)')
    expect(root['--color-scrim']).toBe('rgba(30,26,22,0.4)')
  })

  it('declares the sidebar breakpoint', () => {
    expect(tokens.size['sidebar-breakpoint']).toBe(900)
    expect(root['--size-sidebar-breakpoint']).toBe('900px')
  })

  it('emits the phone sizes as --phone-* variables', () => {
    const p = tokens.phone
    expect(root['--phone-text-display-l-size']).toBe(`${p['type-scale']['display-l']}px`)
    expect(root['--phone-text-display-s-size']).toBe('19px')
    expect(root['--phone-text-score-l-size']).toBe('48px')
    expect(root['--phone-tab-bar-icon']).toBe('22px')
    expect(root['--phone-tab-bar-label']).toBe('11px')
    expect(root['--phone-tab-bar-dash-width']).toBe('16px')
    expect(root['--phone-tab-bar-dash-height']).toBe('3px')
    expect(root['--phone-tab-bar-bottom-inset']).toBe('22px')
    expect(root['--phone-action-bar-button-height']).toBe('48px')
    expect(root['--phone-action-bar-bottom-inset']).toBe('30px')
    expect(root['--phone-row-min-height']).toBe('72px')
    expect(root['--phone-gutter']).toBe('20px')
  })

  it('declares the fonts with fallbacks: Young Serif for display, Figtree for text', () => {
    expect(root['--font-display']).toBe('"Young Serif", Georgia, serif')
    expect(root['--font-text']).toBe('"Figtree", system-ui, sans-serif')
  })

  it('declares sizes, spacing, radii and the type scale', () => {
    expect(root['--size-control-height']).toBe('44px')
    expect(root['--size-sidebar-width']).toBe('220px')
    expect(root['--size-content-max-width']).toBe('760px')
    expect(root['--space-1']).toBe('4px')
    expect(root['--space-10']).toBe('64px')
    expect(root['--radius-m']).toBe('8px')
    expect(root['--radius-pill']).toBe('999px')
    expect(root['--text-score-s-size']).toBe('20px')
    expect(root['--text-display-l-line']).toBe('1.1')
    expect(root['--text-display-l-font']).toBe('var(--font-display)')
    expect(root['--shadow-page']).toBe(tokens.shadow.page)
  })
})

describe('the committed theme', () => {
  it('is what the generator writes', () => {
    expect(readFileSync(join(APP, 'src', 'renderer', 'theme.css'), 'utf8')).toBe(css)
  })

  it('uses no color-mix in the stylesheet (the scrim is a token)', () => {
    expect(readFileSync(join(APP, 'src', 'renderer', 'styles.css'), 'utf8')).not.toContain('color-mix')
  })

  it('is the only renderer file with a hex colour', () => {
    const hex = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/
    const offenders: string[] = []
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const p = join(dir, name)
        if (statSync(p).isDirectory()) walk(p)
        else if (/\.(tsx?|css|html|svg)$/.test(name) && name !== 'theme.css' && hex.test(readFileSync(p, 'utf8')))
          offenders.push(relative(APP, p))
      }
    }
    walk(join(APP, 'src', 'renderer'))
    expect(offenders).toEqual([])
  })
})
