// The release's one latest-mac.yml (#17): the arm64 and the x64 runner each build their own, and a file named
// latest-mac.yml on the release is the only one the updater reads, so the two `files` lists are merged here.
// Only the .zip entries are kept (the .dmg files are renamed on the release); the top-level path/sha512 are the
// arm64 zip's (electron-updater picks by "arm64" in a file's name).
// CLI: tsx scripts/merge-mac-manifest.ts <arm64.yml> <x64.yml> <out.yml>
import { readFileSync, writeFileSync } from 'node:fs'
import { dump, load } from 'js-yaml'

interface Manifest {
  version?: string
  files?: { url: string }[]
  [key: string]: unknown
}

function parse(text: string, name: string): Manifest & { version: string; files: { url: string }[] } {
  const m = load(text) as Manifest | null
  if (!m || typeof m.version !== 'string') throw new Error(`${name}: no version`)
  if (!Array.isArray(m.files) || m.files.length === 0) throw new Error(`${name}: no files`)
  return m as Manifest & { version: string; files: { url: string }[] }
}

export function mergeMacManifests(armYml: string, x64Yml: string): string {
  const arm = parse(armYml, 'arm64 manifest')
  const x64 = parse(x64Yml, 'x64 manifest')
  if (arm.version !== x64.version) throw new Error(`version mismatch: ${arm.version} and ${x64.version}`)
  const seen = new Set<string>()
  // only the zips: the release renames the .dmg files, and the mac updater installs from the zip
  const files = [...arm.files, ...x64.files].filter((f) => /\.zip$/.test(f.url) && !seen.has(f.url) && Boolean(seen.add(f.url)))
  const armZip = arm.files.find((f) => /\.zip$/.test(f.url)) as { url: string; sha512?: string } | undefined
  if (!armZip) throw new Error('arm64 manifest: no zip')
  if (!x64.files.some((f) => /\.zip$/.test(f.url))) throw new Error('x64 manifest: no zip')
  return dump({ ...arm, files, path: armZip.url, sha512: armZip.sha512 }, { lineWidth: -1 })
}

if (process.argv[1] && /merge-mac-manifest\.ts$/.test(process.argv[1])) {
  const [armPath, x64Path, outPath] = process.argv.slice(2)
  if (!armPath || !x64Path || !outPath) throw new Error('usage: merge-mac-manifest.ts <arm64.yml> <x64.yml> <out.yml>')
  writeFileSync(outPath, mergeMacManifests(readFileSync(armPath, 'utf8'), readFileSync(x64Path, 'utf8')))
}
