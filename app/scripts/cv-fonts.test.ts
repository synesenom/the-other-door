import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { inflateSync } from 'node:zlib'
import { describe, expect, it } from 'vitest'

// The CV's default look is the app's own (docs/design/README.md, CV style): the TrueType files the CV prints with
// (profile.example/fonts/) must be the same cut of each family as the app's @fontsource files, or the CV's headings
// come out narrower or wider than the app's.

const APP = join(__dirname, '..')
const REPO = join(APP, '..')

/** The tables of a TrueType (.ttf) or WOFF 1 (.woff) file, by tag. */
function tables(bytes: Buffer): Map<string, Buffer> {
  const out = new Map<string, Buffer>()
  if (bytes.toString('latin1', 0, 4) === 'wOFF') {
    const n = bytes.readUInt16BE(12)
    for (let i = 0; i < n; i++) {
      const at = 44 + i * 20
      const tag = bytes.toString('latin1', at, at + 4)
      const offset = bytes.readUInt32BE(at + 4), comp = bytes.readUInt32BE(at + 8), orig = bytes.readUInt32BE(at + 12)
      const raw = bytes.subarray(offset, offset + comp)
      out.set(tag, comp < orig ? inflateSync(raw) : raw)
    }
  } else {
    const n = bytes.readUInt16BE(4)
    for (let i = 0; i < n; i++) {
      const at = 12 + i * 16
      out.set(bytes.toString('latin1', at, at + 4), bytes.subarray(bytes.readUInt32BE(at + 8), bytes.readUInt32BE(at + 8) + bytes.readUInt32BE(at + 12)))
    }
  }
  return out
}

/** The font's proportions, per 1000 units of its em: average letter width, capital height and x-height. */
function shape(file: string): { width: number; cap: number; x: number } {
  const t = tables(readFileSync(file))
  const em = t.get('head')!.readUInt16BE(18), os2 = t.get('OS/2')!
  const per = (v: number) => (v * 1000) / em
  return { width: per(os2.readInt16BE(2)), cap: per(os2.readInt16BE(88)), x: per(os2.readInt16BE(86)) }
}

describe('the CV prints with the app’s fonts', () => {
  const pairs: [string, string][] = [
    ['YoungSerif-Regular.ttf', '@fontsource/young-serif/files/young-serif-latin-400-normal.woff'],
    ['Figtree-Regular.ttf', '@fontsource/figtree/files/figtree-latin-400-normal.woff'],
  ]
  for (const [ttf, woff] of pairs) {
    it(`${ttf} has the app's proportions`, () => {
      const cv = shape(join(REPO, 'profile.example', 'fonts', ttf)), app = shape(join(APP, 'node_modules', woff))
      expect(cv.cap, 'capital height').toBe(app.cap)
      expect(cv.x, 'x-height').toBe(app.x)
      // a later release of the same cut may move a letter by a unit or two (Figtree 2.001 and 2.002), never 2% on average
      expect(Math.abs(cv.width - app.width) / app.width, 'average letter width').toBeLessThan(0.02)
    })
  }
})
