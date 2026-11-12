import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'
import { FONT_PACKAGES } from './font-licenses'

const APP = join(__dirname, '..')
const read = (...p: string[]) => readFileSync(join(APP, ...p), 'utf8')

describe('bundled fonts', () => {
  const main = read('src', 'renderer', 'main.tsx')

  it('main.tsx imports latin and latin-ext for the weights the design uses', () => {
    const want: Record<string, number[]> = { figtree: [400, 500, 600], 'young-serif': [400] }
    for (const [family, weights] of Object.entries(want)) {
      for (const w of weights) {
        for (const subset of ['latin', 'latin-ext']) {
          expect(main, `${family} ${subset} ${w}`).toContain(`@fontsource/${family}/${subset}-${w}.css`)
        }
      }
    }
  })

  it('every imported stylesheet exists in node_modules', () => {
    for (const m of main.matchAll(/'(@fontsource\/[^']+\.css)'/g)) {
      expect(existsSync(join(APP, 'node_modules', m[1])), m[1]).toBe(true)
    }
  })

  it('the licence list covers the two packages and each LICENSE is the OFL', () => {
    expect(FONT_PACKAGES.map((f) => f.package).sort()).toEqual(['@fontsource/figtree', '@fontsource/young-serif'])
    for (const f of FONT_PACKAGES) {
      expect(readFileSync(join(APP, 'node_modules', f.package, 'LICENSE'), 'utf8')).toContain('SIL Open Font License')
    }
  })

  it('nothing fetches a font at run time', () => {
    const offenders: string[] = []
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const p = join(dir, name)
        if (statSync(p).isDirectory()) walk(p)
        else if (/(googleapis|gstatic)/.test(readFileSync(p, 'utf8'))) offenders.push(relative(APP, p))
      }
    }
    walk(join(APP, 'src'))
    expect(offenders.filter((o) => !o.endsWith('fonts.test.ts'))).toEqual([])
  })

  it('a build ships the licences (skipped without out/)', () => {
    const dir = join(APP, 'out', 'renderer', 'licenses')
    if (!existsSync(join(APP, 'out', 'renderer'))) return
    for (const f of FONT_PACKAGES) expect(existsSync(join(dir, `${f.family}-OFL.txt`)), f.family).toBe(true)
  })
})
