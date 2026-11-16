// electron-builder's afterPack (#223): on macOS, an unsigned build is signed ad hoc, every binary in it included
// (the bundled Python's .so files, and the Chromium headless shell with its dylibs under bin/chromium, #165): Apple
// silicon refuses to run an unsigned or partly signed binary ("damaged"). `codesign --deep` signs only nested code in
// the bundle's standard places, not under Contents/Resources, so each Mach-O there is signed first, the deepest first
// (#176: an Intel build's Chromium shell was "not signed at all"). A release build with a Developer ID certificate
// (CSC_LINK, #224) is signed by electron-builder.
const { execFileSync } = require('node:child_process')
const { closeSync, openSync, readSync, readdirSync } = require('node:fs')
const { join, sep } = require('node:path')

// the first four bytes of a Mach-O file, thin (32 and 64 bit, either byte order) or universal
const MAGICS = new Set(['feedface', 'feedfacf', 'cefaedfe', 'cffaedfe', 'cafebabe', 'bebafeca'])

function isMachO(path) {
  const fd = openSync(path, 'r')
  try {
    const head = Buffer.alloc(4)
    return readSync(fd, head, 0, 4, 0) === 4 && MAGICS.has(head.toString('hex'))
  } finally {
    closeSync(fd)
  }
}

/** Every Mach-O file under `dir`, the deepest first, so a library is signed before what loads it. */
function machOFiles(dir) {
  const found = []
  for (const entry of readdirSync(dir, { withFileTypes: true, recursive: true })) {
    const path = join(entry.parentPath ?? entry.path, entry.name)
    if (entry.isFile() && isMachO(path)) found.push(path)
  }
  return found.sort((a, b) => b.split(sep).length - a.split(sep).length || a.localeCompare(b))
}

exports.machOFiles = machOFiles

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin' || process.env.CSC_LINK) return
  const app = join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`)
  for (const file of machOFiles(join(app, 'Contents', 'Resources'))) {
    execFileSync('codesign', ['--force', '--sign', '-', file], { stdio: 'inherit' })
  }
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', app], { stdio: 'inherit' })
}
