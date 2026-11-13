# Releasing

A release is a tag `vX.Y.Z`. `.github/workflows/release.yml` builds the installers on every system, runs the
unit tests and the packaged smoke test on each, and uploads them to a **draft** release. A draft is published
only after a person has installed it on a clean machine of each system and gone through the checklist below
(#502). `/dev-release` in Claude Code walks through it (the maintainer only). How the build, the bundle and the signing work is in [app/README.md](../app/README.md#releasing-224).

## Before the tag

- `./scripts/run-test.sh --release` passes: the offline suite, the app's tests with every journey and the skill
  tests, which only run locally (the real model on your Claude plan runs `/onboard` against the app's test world).
- `main` is green (the Python suite and the app's unit tests, smoke test and core journeys).
- The repository variable `DOOR_UPDATE_FEED` names the public repo's `releases/latest`
  (`https://api.github.com/repos/<owner>/<repo>/releases/latest`). Empty, the build never checks for updates
  and Settings has no Version part.
- The signing secrets are set if this release is to be signed (`app/README.md`); without them macOS and
  Windows warn once, as `docs/manual-app.md` describes.

## 1. Version, tag, draft

```sh
python3 scripts/set_version.py X.Y.Z       # pyproject.toml, src/door/version.py, app/package.json and its lock
git commit -am "release: vX.Y.Z"
git tag vX.Y.Z && git push origin main vX.Y.Z
```

The workflow refuses a tag that is not the version. It takes about 20 minutes; the draft then holds
`the-other-door-X.Y.Z-mac-arm64.dmg`, `-mac-x64.dmg`, `-windows-x64.exe`, `-linux-x64.AppImage` and the `.deb`.

## 2. Install on a clean machine, each system

A clean machine (or VM) has no checkout, no Poetry, no Python of ours, no `claude` and no data folder of a
previous install (`docs/manual-app.md`, "Your data"). Go through every system the draft has an installer for:

| System | Installer | Machine |
|--------|-----------|---------|
| macOS, Apple silicon | `-mac-arm64.dmg` | macOS 13 or later |
| macOS, Intel | `-mac-x64.dmg` | macOS 13 or later |
| Windows | `-windows-x64.exe` | Windows 10 or 11, x64 (on an ARM machine it runs emulated: note it) |
| Linux | `-linux-x64.AppImage` and `.deb` | a recent Ubuntu, x64 |

Steps 1 and 3–6 below are also the install test, which `release.yml` runs on every installer of the draft
and on Windows on ARM (the x64 installer, emulated): a green release run means they passed on each system, on a
test world with a stand-in Claude ([app/README.md](../app/README.md#the-install-test-639)). Locally it is
`DOOR_INSTALLER=<the downloaded file> ./scripts/run-test.sh --release`. The first-open warnings of step 1, the
real sign-in, real scoring and the update stay by hand, on one machine.

On each, download the installer from the draft release and check, in order:

1. **Install.** It installs as `docs/manual-app.md` says, warnings included (macOS: Open Anyway once;
   Windows: SmartScreen's Run anyway once; Linux: the AppImage runs once made executable, the `.deb`
   installs with `apt`).
2. **First launch.** The app opens on the onboarding wizard. The Connect screen installs the `claude`
   command line and **Sign in with Claude** signs in to a plan; the wizard then goes on to the sources.
3. **Set-up.** A CV goes in (a file, or dropped), the reading finishes, the review saves.
4. **First run.** Finding jobs runs all five steps to the summary card, and Matches lists what it found.
5. **Prepare.** Prepare on one match makes both PDFs (the bundled Tectonic, which downloads its LaTeX
   packages the first time), and Open shows them.
6. **Reopen.** Quit and open the app again: the profile, the matches and the prepared materials are
   still there, and the data is in the user's data folder, not inside the app (Settings → Your data).
7. **Update** (from the second release on). Install the previous version, set it up, then install this one
   over it: the data stays, the app opens on Matches, and before that Settings → Version of the old one says
   this version is out.

Anything that fails is fixed on `main` and released as a new version (the next patch number); a draft is
never rebuilt under the same tag. Delete the failed draft and its tag.

Note the results in the release's pull request or issue, one line per system:

```text
vX.Y.Z  macOS 15 arm64: 1–7 ok · macOS 13 x64: 1–7 ok · Windows 11 x64: 1–6 ok, 7 n/a · Ubuntu 24.04: 1–7 ok (AppImage and .deb)
```

## 3. Release notes

Written for users, not developers: what they can now do, what works better, what was fixed. Start from the
pull requests merged since the last tag:

```sh
git log --merges --format='%s%n%b' vPREVIOUS..vX.Y.Z    # the merge titles and their PR bodies
```

Leave out tests, refactors, CI and developer tools. Put the notes on the draft (`gh release edit vX.Y.Z
--notes-file notes.md`, or the release page), with one line on installing: download the installer for your
system, and on macOS allow it once (link to `docs/manual-app.md#opening-it-on-macos-the-first-time`).

## 4. Download link

README's Desktop app section links to the installers on `releases/latest`. Check that the link points to the
public repo, the one `DOOR_UPDATE_FEED` names, and that it opens there once the release is published.

## 5. Publish

Publish the draft. Then open the README's link and an installed older app's Settings → Version once:
both should show the new version.
