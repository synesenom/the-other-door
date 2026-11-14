# The other door desktop app (developer preview)

An Electron shell over *The other door*'s MCP server, run from the checkout. Its five destinations are
**Matches** (the ranked list; a posting opened full width with
"← Matches" and the previous and next match, "Prepare application", "Open in browser", "Status",
"Not for me", "Add a job"; opening a match makes it seen), **Applications** (the board of jobs in play), **Profile** (the settings and
the CV: the pages read for it, then the editor), **Settings** (connections, appearance, data moves, checks) and **Analytics** (Applications first: the funnel from scraped to offer, each bar a share of the step before, with a pass rate from applying on; then what Claude's work cost at API prices, per activity; not on the phone); **Finding jobs** ("Find new
jobs": the five steps live, Stop, a summary card) takes the place of the page during a run, and a
prepared job opens "Ready to send" (the pages, Revise and Undo). What each does is in
[`../docs/manual-app.md`](../docs/manual-app.md). Below 900 px the sidebar becomes a tab bar, which steps aside while a posting is open. The visual design is in [`../docs/design/`](../docs/design/).

## Run it

Needs Node 22 (`.nvmrc`) and the Python environment of the repo (`poetry install`, so
`../.venv` exists). Electron is pinned to the 43.x line: Electron 44 and later need
macOS 13.

```bash
cd app
npm ci
npm run dev        # opens the window; starts ../.venv/bin/python -m door.mcp_server
```

`DOOR_PYTHON` names another interpreter; `DOOR_HOME` points the server at another
data folder (the default is the checkout's `profile/` and `jobs/`).

## Work on one screen (`npm run dev:preview`)

`npm run dev:preview` serves the real screens in a browser tab at <http://localhost:5199/>, on made-up data: no Electron,
Python or claude, and nothing is saved. The first page lists the scenes (`src/preview/scenes.ts`); each has its own address,
which comes back after a reload:

```
?scene=onboarding-review            a screen; a new one is a line in SCENES
?scene=matches&state=empty          state: ok, empty, loading, error, long, plan-low
?scene=applications&theme=dark      theme: light or dark, for this tab only
```

Edits hot reload and keep the screen's state. After changing `docs/design/tokens.json`, run `npm run gen-theme`.
The answers are `src/preview/fixtures.json` (the real server's answers on the demo data, with a closed application added) and
`src/preview/mock-door.ts`; `src/preview/preview.test.tsx` renders every scene in every state, so a fixture a screen can no longer
read fails the tests. Only this dev server loads `src/preview/`: no build includes it. For dialogs, Drive, or anything in the main
process, use `npm run dev:demo`.

## The bundle a packaged app carries (#223)

A packaged app does not use the checkout's `.venv`: it carries its own Python and Tectonic. Build them for
this computer (macOS, or x64 Linux; Windows has `bundle-python.ps1`, #355) and check them:

```sh
scripts/bundle-python.sh   # → app/resources/{python,door,bin}, about 310 MB; downloads cached in app/.bundle-cache/
scripts/check-bundle.sh    # imports, the MCP handshake, doctor, a Tectonic page, nothing written inside (--offline: no page)
```

- `python/` is [python-build-standalone](https://github.com/astral-sh/python-build-standalone) 3.12 with *The other door*'s
  `poetry.lock` main group installed into it, every package by hash and from a wheel only
  (`scripts/lock_requirements.py` writes the requirements; a package with no wheel for the system fails the build).
- `door/` is `src/`, `.claude/agents/{tailor,matcher}.md` and `profile.example/`, laid out as in a checkout.
- `bin/` is Tectonic (the static musl build on Linux).
- Versions and sha256s are pinned in `scripts/bundle.lock.json` (from each release's metadata); a download
  that does not match is refused.
- No cross-building: each system builds its own. The app starts it through `resolvePackagedSpawn`
  (`src/main/door-server.ts`), with the data in the user's data folder and nothing written inside.

## Packaging (#223)

After the bundle (above), on the system you are packaging for:

```sh
npm run package:dir     # an unpacked app in dist/ (dist/mac/The other door.app, dist/linux-unpacked, dist/win-unpacked)
npm run test:package    # its smoke test: the bundled server serves Matches, doctor finds the bundled Tectonic,
                        # nothing is written inside the app (DOOR_PACKAGED_APP=<executable> for an installed one)
npm run package         # the installer: dist/the-other-door-<version>-mac-<arch>.dmg/.zip, The-other-door-<version>-Windows.exe, The-other-door-<version>-Linux.AppImage, the-other-door-<version>-linux-<arch>.deb
```

`electron-builder.config.cjs` is the one config (appId `dev.door.app`, productName `The other door`, the bundle as
`extraResources` outside the asar). macOS builds are signed ad hoc by `scripts/after-pack.cjs` (Apple silicon
refuses unsigned binaries); a Developer ID signature and notarization are #224's. A packaged app
keeps its data in the user's data folder (`docs/manual-app.md`, "Installing the app"); `DOOR_HOME` still
overrides it, which is how the smoke test runs it on a temp folder with the stand-in `claude`.

## The install test (#639)

`test:package` checks an unpacked app; the install test takes the file a user downloads. CI runs it on every
installer (#18): the package workflows on each build (macOS arm64 and x64, Windows x64, Linux AppImage and
`.deb`, and the Windows installer on `windows-11-arm`, emulated), and `release.yml` on what a tag ships. Locally:

```sh
npm run package         # or DOOR_INSTALLER=<file> for an installer from a draft release
npm run test:install    # about two minutes, plus the first LaTeX download
```

`e2e-install/setup.ts` installs it the user's way into a throwaway folder (macOS: the `.dmg` mounted and the app
copied out; Windows: the NSIS installer with `/S /D=`; Linux: the AppImage made executable, or with
`DOOR_INSTALLER_KIND=deb` the `.deb` through `sudo apt-get`, into `/opt`), prints its signature (`codesign`/`spctl`,
`Get-AuthenticodeSignature`; reported, not judged, while the builds are unsigned) and `teardown.ts` uninstalls it
(`DOOR_INSTALL_KEEP=1` keeps it). `install.e2e.ts` then launches the installed app with a throwaway `DOOR_HOME`,
HOME and Chromium folder and the journeys' test world (`test/world/`): a CV in, the review saved, the first run to
its summary, the best match prepared with the **bundled** Tectonic (a real LaTeX download), quit, reopened. It
checks the server is the bundled Python on the bundled door with the bundled `bin/` first on PATH, doctor finds
that Tectonic, the data folder is where `docs/manual-app.md` says, no ERROR line in `logs/door.log`, and nothing
written inside the app. The plan per system is `e2e-install/installer.ts` (unit-tested in `npm test`).

The one seam is on the test's side (`e2e-install/redirect.ts`): an installed app starts its server before
Playwright can reach it and reads no `-r` or `NODE_OPTIONS`, so right after launch the test patches its main
process's `spawn` to run `test/world/boot.py` instead of `-m door.mcp_server` (same bundled Python, cwd and
environment) and stops the server already running; the app starts it again through the patch. A journey that
starts from an empty world can run this way too with `DOOR_INSTALLED_APP=<executable>` (`journeys/fixtures.ts`).

Where to run it: macOS on Apple silicon natively (a clean VM, e.g. Tart, is optional); Windows x64 and Windows on
ARM (the x64 build, emulated) in a Windows 11 VM; Linux x64 on an x64 machine or VM (an AppImage needs `libfuse2`).
Each machine needs a checkout and `npm ci` in `app/`; nothing of the checkout's Python is used. Not covered: the
real Claude sign-in and real scoring (a plan login), and live job boards (`scripts/country_smoke.py`).

## Releasing (#224)

One version for *The other door* and the app: `python3 scripts/set_version.py 0.2.0` (from the repo root) sets it in
`pyproject.toml`, `src/door/version.py` and `app/package.json`; commit, then push the tag `v0.2.0`.
`.github/workflows/release.yml` builds macOS (Apple silicon and Intel), Windows and Linux, runs the unit tests
and the packaged smoke test on each, and uploads the installers to a **draft** release of this repo (the
workflow's own token writes it); publish it only after the checklist in [docs/releasing.md](../docs/releasing.md)
passed: a clean-machine install on each system, the release notes, the download link. Installed apps update from the published release (#17, `src/main/updates.ts`): a signed macOS build (the packed `package.json`'s `doorSigned`, set by `electron-builder.config.cjs` when the certificate and notarization are there), the Windows installer and the AppImage download the next version in the background through `electron-updater` (`latest*.yml`, the mac `.zip`, blockmaps; the release workflow uploads them, `scripts/merge-mac-manifest.ts` merges the two mac manifests) and install it on restart; an unsigned macOS build and the `.deb` read GitHub's `releases/latest` and link to its page; a checkout and the demo do nothing. `DOOR_UPDATES=off` keeps a packaged app from checking; `test:package` and `test:install` set it, nothing else should.

For signed builds add
`MAC_CERTIFICATE`/`MAC_CERTIFICATE_PASSWORD` (Developer ID Application, `.p12` in base64), `APPLE_ID`,
`APPLE_APP_SPECIFIC_PASSWORD` and `APPLE_TEAM_ID` (notarization), and `WINDOWS_CERTIFICATE`/
`WINDOWS_CERTIFICATE_PASSWORD` (Authenticode). Without them the builds are unsigned: macOS asks once
before opening it, Windows SmartScreen warns once.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` / `npm run build` | run / build with electron-vite (`predev`, `prebuild` regenerate the theme) |
| `npm run dev:demo` / `npm run dev:demo:fresh` | run on made-up data instead of yours: the example profile (Jane Doe) and nine finance jobs in every state (new matches, one in Danish, prepared with pages, applied, in a screening interview, discarded), built once in `app/.demo/` (gitignored; `:fresh` builds it again). The server's `DOOR_HOME` and the config folders that hold the Drive connection point inside it, so nothing reaches your `profile/`, `jobs/` or Drive archive (Settings shows Drive as not available, and the main process refuses the Drive tools on made-up data); `HOME` stays yours, so Prepare and Revise still call your signed-in `claude` (your plan). The sidebar and the window title say Demo. "Find new jobs" there plays a simulated run (about 20 s, `src/main/demo-run.ts`: no network, no claude) that adds two new matches. `DOOR_DEMO_DIR` names another demo folder (an unpackaged app only; `seedDemo` still refuses the checkout's real data) and `DOOR_DEMO_RUN_MS` the run's length: the e2e test uses both. |
| `npm run dev:onboard` | try the first launch: the app on an empty folder, `app/.onboard/` (gitignored), made again on every start, so the wizard always starts from nothing. Like the demo, the server's `DOOR_HOME` and the Drive config folders point inside it (`demoEnv`; `resetOnboard` refuses the checkout's real data) and `HOME` stays yours, so the reading step calls your signed-in `claude`. "Find new jobs" is the simulated run of the demo (no network, no claude). The sidebar and the window title say Onboarding sandbox. `DOOR_ONBOARD_DIR` names another folder (an unpackaged app only; the e2e test uses it), `DOOR_ONBOARD_SIGNED_OUT=1` gives it a Claude config folder of its own (`CLAUDE_CONFIG_DIR=<folder>/.claude`), so it starts signed out without touching your login and "Sign in with Claude" can be tried for real (that folder keeps its login across restarts; `CLAUDE_CONFIG_DIR=app/.onboard/.claude claude auth logout` signs it out). |
| `npm run build:web` / `npm run test:web` | the phone app (issue 303): the same renderer behind `src/web/` (`bridge.ts` is `window.door` over `door serve`'s `/mcp`, `Pair.tsx` trades a pairing code for the device token kept in IndexedDB, `Web.tsx` shows the pair screen or the desktop `App`; `remote.ts` tells the screens they run on a phone), built by `vite.web.config.mts` into `out/web`, which `./door serve` serves. `test:web` runs `e2e-web/` against a real `door serve` on the demo's made-up data in a phone-sized Electron window (`browser.cjs`, its own storage) at several narrow, tall sizes; `serve-fixture.ts` is the one file under `app/` the guard lets start *The other door*. |
| `npm run record:phone-gif` | re-record `docs/demo/phone.gif`: `demo-record/phone.record.ts` drives the phone app against a real `door serve` on the demo's made-up data (360 wide, its own storage), through the demo shim (fake boards, canned scores and CV), so Find new jobs and Prepare play out without the network or Claude; its frames are Chromium's screencast (a frame per repaint), which `app_gif.py --width 360` makes into the GIF and `scripts/demo/video_from_frames.py` into an .mp4 (needs an ffmpeg: `imageio-ffmpeg`'s or one on PATH). |
| `npm run record:gif` | re-record the README's `docs/demo/app.gif`: the built app on the demo's made-up data in a temp folder (never `app/.demo`), driven by `demo-record/app.record.ts` (Playwright; the stand-in claude, light theme by emulation, a drawn cursor), its screencast frames turned into the GIF by `scripts/demo/app_gif.py` (Pillow, from Poetry). Not a test; CI never runs it. |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | vitest unit tests: no Python, no network (what CI runs) |
| `npm run test:integration` | the real Python server on a generated `DOOR_HOME` (`test/home-fixture.ts`; `buildHome({ prepared: 'jobindex.123' })` adds a finished prepare from `test/fixtures/prepared/`: a 2-page CV, a 1-page letter, their page images and `.tex`) with isolated `HOME` and a stand-in `claude` first on `PATH` (it fails and leaves `claude-was-called` in the scratch folder, so a test never reaches your real one); skips with a message when there is no `.venv` or `DOOR_PYTHON` |
| `npm run test:e2e` | builds, then Playwright tests drive the built app against the real server on a temp `DOOR_HOME` (Python as above; skips with a message without it). CI runs it under `xvfb-run` |
| `npm run test:install` | install this system's installer from `dist/` (or `DOOR_INSTALLER`) the user's way, then set-up, the first run and Prepare in the installed app, then uninstall; CI runs it on every installer ("The install test" above) |
| `npm run gen-tools` | rewrite `src/generated/tools.json` from the running server |
| `npm run gen-theme` | rewrite `src/renderer/theme.css` from `../docs/design/tokens.json` |

Run `gen-tools` and commit the file whenever a tool or a tool parameter in
`src/door/mcp_server.py` changes: `tests/commands/test_mcp_server.py` fails until you do.
`theme.css` is checked against the generator by a test.

## How it is built

```
renderer (React) -- window.door.call / onProgress --> main (ipc.ts) -- door-server.ts --> python -m door.mcp_server
```

- `src/main/door-server.ts` is the typed client and the only module that spawns a process.
  A result is *The other door*'s JSON in one text block; `{"error": ..., "candidates"?}` and
  `isError` become a `DoorError`. When the child dies, a call in flight is rejected
  ("*The other door*'s server stopped; try again") and the next call starts a new child. It never
  retries by itself: retrying could apply a write such as `set_status` twice.
- Progress: `call(tool, args, { onProgress })` in `src/renderer/api.ts` gives the call an id;
  the main process forwards the server's progress notifications on `door:progress` under
  that id (id and message length validated) and the preload's `onProgress(callId, cb)`
  hands the page only the payload and an unsubscribe. Matches shows a spinner with the
  message of `status_summary.in_progress` while a run is on.
- The run: `find_jobs` writes the folded state of its five steps into `jobs/.progress.json`
  (`steps`). `src/main/run-board.ts` watches that file and `jobs/.lock.json` (a file watch and a
  1 s poll; a lock whose process is gone is no run) and pushes the board on `door:run-board`
  whoever started the run; the renderer keeps it in `App`. A run of the app's own is a
  `find_jobs` call with a 15 minute idle limit (progress restarts it) and progress coalesced to
  one message per 200 ms. **Stop** is `door:stop-run`: it kills the Python child
  (`DoorServer.stop()`), the call rejects as stopped and the next call starts a new child; a
  run started elsewhere cannot be stopped from here. "Show run record" is `door:show-run` (the
  run's `started_at`, mapped to `jobs/runs/<name>.json` like `find.py` does).
- Fonts: Young Serif and Figtree come from `@fontsource` packages (pinned,
  bundled by Vite, no request at run time); a build copies their SIL OFL licences to
  `out/renderer/licenses/`.
- Security: context isolation, sandbox, no Node in the renderer, a Content-Security-Policy
  (header and meta), navigation and new windows denied, `openExternal` for http(s) only,
  and the IPC accepts only tools listed in `tools.json`.
- Nothing under `app/` runs the `./door` command line or a model; `src/main/guard.test.ts`
  fails if it does.
- Prepared files: a page image is shown through the `door-file://output/<job id>/<page>.png`
  scheme (`src/main/protocol.ts`, registered in `index.ts` as secure, not standard, and
  listed in `img-src` only). It serves `HOME/jobs/output/<job id>/(cv|cover_letter)_page_<n>.png`
  and nothing else (names checked, symlinks resolved, `Cache-Control: no-store`; the page adds `?v=`
  after a revision). `HOME` follows `workspace.py` (`src/main/files.ts`; an integration test
  compares it with the server's `output_dir`). **Save CV** / **Save letter** is the IPC
  channel `door:save-material` (job id, `cv` or `cover_letter`, sent or not, the name `show`'s
  `file_names` offers): the main process runs the save dialog in Downloads and copies the PDF
  where the user chose; the renderer never names a path (on the phone, the browser downloads
  the same file from `/files`). `prepare` waits up to 180 s between progress
  reports, `revise` 420 s in all (`TOOL_TIMEOUTS` in `ipc.ts`).
- CV draft (#221, #495): the wizard's reading step drafts a CV from files and pages. The renderer never
  passes a path. `door:pick-cv-files` runs the open dialog in the main process
  (`src/main/cv-sources.ts`: pdf, docx, md, markdown, txt, up to 25 MB, checked again when used)
  and answers `{files: [{token, name, size}], refused}`; the paths stay in a registry in main
  under random tokens, with no way to read it. `door:draft-cv` takes `{files: tokens, urls}`,
  resolves the tokens, refuses a non-http address and a linkedin.com one, and calls `draft_cv`
  (960 s). `door:drop-cv-files` does the same for a drop: the preload turns each dropped `File` into its path with `webUtils.getPathForFile`, out of the page's reach, and the same checks and tokens apply. `door:cv-sources-clear` empties the registry when the wizard closes. `door:call`
  refuses every argument that names a local file (`PATH_ARGS` in `ipc.ts`: `draft_cv` `sources`
  other than http(s) addresses, `import_posting` `path`, `export_data` `path`, `import_data`
  `archive`); a test fails when a tool gains a parameter that could name a file and is in neither
  that table nor its short allow-list.
- Notifications (#350): `src/main/notices.ts` (pure) says what a settled `find_jobs`, `prepare`,
  `revise` or `import_posting` call, or the end of a run started elsewhere (`foreign-run.ts`,
  from the run board), deserves in words; `ipc.ts` and `index.ts` feed it, and `notifier.ts`
  shows it as an Electron `Notification` only while no window is focused (identical notices
  within 5 s are dropped). A click focuses the window and pushes the target on `door:open`
  (the preload's `onOpen`); `App.tsx` routes it. No off switch until Settings (#222).
- Colours, type, spacing and sizes come from the generated theme variables only (a test
  rejects a hex colour in the renderer).

## Known gaps

- The tools have no output schema, so the result types in `src/renderer/api.ts`
  (`StatusSummary`, `MatchesResult`, `Posting`, ...) are written by hand from
  `src/door/commands/matches.py` and `status.py`. A renamed field is not caught by
  `tools.json`.
- Matches and Applications are live, with Prepare, Ready to send, Revise and Undo. A real
  Prepare and a real Revise need the `claude` command line and a LaTeX compiler, so no test runs
  them (vitest covers their states with a mocked bridge); try them by hand. A real `find_jobs` run is never started by a test (it reads
  the network and calls `claude`); the demo's simulated run and the run board are what the tests cover.
