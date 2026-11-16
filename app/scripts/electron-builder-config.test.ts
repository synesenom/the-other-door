import { createRequire } from 'node:module'
import { afterEach, describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const PATH = require.resolve('../electron-builder.config.cjs')

function load(env: Record<string, string | undefined>) {
  const saved = process.env.DOOR_DMG_ONLY
  if (env.DOOR_DMG_ONLY === undefined) delete process.env.DOOR_DMG_ONLY
  else process.env.DOOR_DMG_ONLY = env.DOOR_DMG_ONLY
  delete require.cache[PATH]
  try {
    return require(PATH)
  } finally {
    if (saved === undefined) delete process.env.DOOR_DMG_ONLY
    else process.env.DOOR_DMG_ONLY = saved
    delete require.cache[PATH]
  }
}

afterEach(() => delete require.cache[PATH])

describe('electron-builder mac targets', () => {
  it('build the .dmg and the updater .zip by default (the release)', () => {
    expect(load({}).mac.target).toEqual(['dmg', 'zip'])
  })

  it('build the .dmg only when DOOR_DMG_ONLY=1 (pull-request package checks)', () => {
    expect(load({ DOOR_DMG_ONLY: '1' }).mac.target).toEqual(['dmg'])
  })
})
