// electron-builder's afterPack (#223): on macOS, an unsigned build is signed ad hoc, every binary in it included
// (the bundled Python's .so files and Tectonic): Apple silicon refuses to run an unsigned or partly signed binary
// ("damaged"). A release build with a Developer ID certificate (CSC_LINK, #224) is signed by electron-builder.
const { execFileSync } = require('node:child_process')
const { join } = require('node:path')

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin' || process.env.CSC_LINK) return
  const app = join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`)
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', app], { stdio: 'inherit' })
}
