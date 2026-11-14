// The packaged app (#223, #224): electron-builder, one config for every system. The bundle (python/, door/,
// bin/) is built first by scripts/bundle-python.sh (.ps1 on Windows) and lands outside the asar.
//
// Signing happens only when the release workflow has the certificates (CSC_LINK, and APPLE_TEAM_ID with the
// Apple ID for notarization): a Developer ID signature with the hardened runtime, then notarization, on macOS;
// Authenticode on Windows. Without them the build is unsigned and macOS is signed ad hoc (scripts/after-pack.cjs).
// The release workflow drafts the installers as a release of this repo. Installed apps update from it once it is
// published (#17, src/main/updates.ts): a signed macOS app, the Windows installer and the AppImage download the
// next version in the background (electron-updater reads latest*.yml and the .zip/.blockmap files); an unsigned
// macOS app and the .deb only link to the release page. `doorSigned` in the packed package.json tells which.
const signed = Boolean(process.env.CSC_LINK)
const notarized = signed && Boolean(process.env.APPLE_TEAM_ID)

module.exports = {
  // read by the app at run time: only a signed and notarized macOS build can install an update itself
  extraMetadata: { doorSigned: signed && notarized },
  appId: 'dev.door.app',
  productName: 'The other door',
  copyright: 'Copyright © 2026 Enys Mones',
  directories: { output: 'dist', buildResources: 'build' },
  files: ['out/**', 'package.json'],
  asar: true,
  extraResources: [
    { from: 'resources/python', to: 'python' },
    { from: 'resources/door', to: 'door' },
    { from: 'resources/bin', to: 'bin' },
    // the phone app (issue 444): the renderer's web build, served by `door serve`
    { from: 'out/web', to: 'web' },
  ],
  icon: '../docs/logo/door-512.png',
  afterPack: 'scripts/after-pack.cjs',
  // A tag build looks for this even with --publish never (without it electron-builder crashes, v0.1.0's first
  // run). The release workflow uploads the installers itself; nothing is published from here.
  publish: { provider: 'github', owner: 'synesenom', repo: 'the-other-door', releaseType: 'draft' },
  // The packed package.json says whether this build is signed: an unsigned macOS app cannot update itself.
  mac: {
    // the .dmg a person downloads, and the .zip (with its blockmap) that macOS's updater installs from
    target: ['dmg', 'zip'],
    category: 'public.app-category.productivity',
    artifactName: 'the-other-door-${version}-mac-${arch}.${ext}',
    ...(signed
      ? { hardenedRuntime: true, entitlements: 'build/entitlements.mac.plist', entitlementsInherit: 'build/entitlements.mac.plist', notarize: notarized }
      : { identity: null }),
  },
  win: { executableName: 'the-other-door', target: 'nsis' },
  // The names a person downloads are the files themselves: latest.yml / latest-linux.yml name these assets.
  nsis: { oneClick: true, perMachine: false, deleteAppDataOnUninstall: false, artifactName: 'The-other-door-${version}-Windows.${ext}' },
  appImage: { artifactName: 'The-other-door-${version}-Linux.${ext}' },
  linux: {
    executableName: 'the-other-door',
    target: ['AppImage', 'deb'],
    category: 'Office',
    maintainer: 'Enys Mones <enys.mones@gmail.com>',
    artifactName: 'the-other-door-${version}-linux-${arch}.${ext}',
  },
}
