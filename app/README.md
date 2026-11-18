# The other door desktop app (developer preview)

An Electron shell over *The other door*'s MCP server, run from the checkout. Its five destinations are
**Matches** (the ranked list; a posting opened full width with
"← Matches" and the previous and next match, "Prepare application", "Open in browser", "Status",
"Not for me", "Add a job"; opening a match makes it seen), **Applications** (the board of jobs in play), **Profile** (the settings and
the CV: the pages read for it, then the editor), **Settings** (connections, appearance, data moves, checks) and **Analytics** (Applications first: the interview rate of the applications with an outcome, and under it that rate for the better-scored and the near-minimum half of them; then what Claude's work cost at API prices, per activity; then Market, the skills the ads ask for most; not on the phone); **Finding jobs** ("Find new
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

## Environments

The app runs in one of three environments, and only these three (`src/main/environments.ts`). A fourth is not
added: a new need is a start of one of them (like the sandbox's `:empty`), not a new mode.

| Environment | Start it with | Data | What is real |
|---|---|---|---|
| **Production** | the installed app, or `npm run dev` | yours: the data folder (`DOOR_HOME`, else the checkout's `profile/` and `jobs/`) and your Google Drive archive | everything |
| **Staging** | `npm run dev:staging`, `:fresh` empties it first | a throwaway folder, `app/.staging/`, kept between starts | everything but Google Drive: real runs, the wizard, the CV style build, Prepare, on your Claude plan |
| **Sandbox** | `npm run dev:sandbox` (made-up data, kept), `:fresh` (made again), `:empty` (empty: the wizard opens) | `app/.sandbox/`: the example profile (Jane Doe) and nine finance jobs in every state (`src/main/sandbox.ts`), or nothing | everything but Google Drive and "Find new jobs", which plays a simulated run of about 20 s (`src/main/demo-run.ts`: no network, no claude) adding two made-up matches; the wizard installs nothing |

Use staging to try a feature for real from a fresh start; use the sandbox to look at every screen in every state, or to
try the first launch, without waiting on job boards. In both, the server's `DOOR_HOME` and the config folders that hold
the Drive connection point inside the folder, the main process refuses the Drive tools (Settings says Drive is not
available, the wizard does not offer it), and the sidebar and the window title say Staging or Sandbox. `HOME` stays
yours, so `claude` is signed in and runs on your plan. Both refuse a folder that is or holds the checkout's real data.
Delete the folder when you are done. A packaged app is always production.

For tests (an unpackaged built app): `DOOR_SANDBOX_DIR` starts the sandbox in that folder, `DOOR_SANDBOX_EMPTY=1`
starts it empty, `DOOR_SANDBOX_RUN_MS` sets the simulated run's length, `DOOR_SANDBOX_DISCOVERY=off` seeds a profile
with every discovery source off (the README's GIF), and `DOOR_SANDBOX_SIGNED_OUT=1` gives the sandbox a Claude config
folder of its own (`<folder>/.claude`), so it starts signed out and "Sign in with Claude" can be tried without touching
your login (`CLAUDE_CONFIG_DIR=app/.sandbox/.claude claude auth logout` signs it out again).

`npm run dev:preview` (below) and the journeys' test world (`app/test/world/`) are test tools, not environments: the
first draws screens from saved answers, the second is a fake world the automated tests drive.

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
The answers are `src/preview/fixtures.json` (the real server's answers on the sandbox's made-up data, with a closed application added) and
`src/preview/mock-door.ts`; `src/preview/preview.test.tsx` renders every scene in every state, so a fixture a screen can no longer
read fails the tests. Only this dev server loads `src/preview/`: no build includes it. For dialogs, Drive, or anything in the main
process, use the sandbox (`npm run dev:sandbox`).

## The bundle a packaged app carries (#223)

A packaged app does not use the checkout's `.venv`: it carries its own Python and Chromium. Build them for
this computer (Apple silicon macOS, or x64 Linux; Windows has `bundle-python.ps1`, #355) and check them:

```sh
scripts/bundle-python.sh   # → app/resources/{python,door,bin}, about 310 MB before Chromium, which adds an estimated 200 MB unpacked; downloads cached in app/.bundle-cache/
scripts/check-bundle.sh    # imports, the MCP handshake, doctor (with its Chromium test print), nothing written inside
```

- `python/` is [python-build-standalone](https://github.com/astral-sh/python-build-standalone) 3.12 with *The other door*'s
  `poetry.lock` main group installed into it, every package by hash and from a wheel only
  (`scripts/lock_requirements.py` writes the requirements; a package with no wheel for the system fails the build).
- `door/` is `src/`, `.claude/agents/{tailor,matcher}.md` and `profile.example/`, laid out as in a checkout.
- `bin/` is `chromium/`, the Chrome for Testing headless shell that
  prints CVs (#165), pinned in `src/door/core/downloads/chromium_pin.json` (the one pin, also what `doctor --fix` installs;
  not in `bundle.lock.json`): an estimated 105-128 MB more per installer zipped and about 200 MB unpacked. On Windows on ARM the
  win64 shell runs under emulation.
- Versions and sha256s are pinned in `scripts/bundle.lock.json` (from each release's metadata); a download
  that does not match is refused.
- No cross-building: each system builds its own. The app starts it through `resolvePackagedSpawn`
  (`src/main/door-server.ts`), with the data in the user's data folder and nothing written inside.

## Packaging (#223)

After the bundle (above), on the system you are packaging for:

```sh
npm run package:dir     # an unpacked app in dist/ (dist/mac/The other door.app, dist/linux-unpacked, dist/win-unpacked)
npm run test:package    # its smoke test: the bundled server serves Matches, doctor finds the bundled Chromium and prints a page with it,
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
installer (#18): the package workflows on each build (macOS arm64, Windows x64, Linux AppImage and
`.deb`, and the Windows installer on `windows-11-arm`, emulated), and `release.yml` on what a tag ships. Locally:

```sh
npm run package         # or DOOR_INSTALLER=<file> for an installer from a draft release
npm run test:install    # about two minutes
```

`e2e-install/setup.ts` installs it the user's way into a throwaway folder (macOS: the `.dmg` mounted and the app
copied out; Windows: the NSIS installer with `/S /D=`, except in CI's x64 job, which runs it on its own default per-user install through `DOOR_INSTALLED_APP` (#168); Linux: the AppImage made executable, or with
`DOOR_INSTALLER_KIND=deb` the `.deb` through `sudo apt-get`, into `/opt`), prints its signature (`codesign`/`spctl`,
`Get-AuthenticodeSignature`; reported, not judged, while the builds are unsigned; on macOS the Mach-O signatures of the bundled Chromium are judged here) and `teardown.ts` uninstalls it
(`DOOR_INSTALL_KEEP=1` keeps it; a failed uninstall command, an install folder the NSIS uninstaller left behind on
Windows, or after the `.deb`'s `apt-get remove` its `/opt` folder, `/usr/bin` link or launcher left behind, fails the run). `install.e2e.ts` then launches the installed app with a throwaway `DOOR_HOME`,
HOME and Chromium folder and the journeys' test world (`test/world/`): a CV in, the review saved, the first run to
its summary, the best match prepared (its CV printed by the **bundled** Chromium), quit, reopened. It
checks the server is the bundled Python on the bundled door with `DOOR_BIN` the bundled `bin/`, doctor finds
the bundled Chromium, a page printed with the installed interpreter (`python -m door.render.html_pdf`), the data folder is where `docs/manual-app.md` says, no ERROR line in `logs/door.log`, and nothing
written inside the app. The plan per system is `e2e-install/installer.ts` (unit-tested in `npm test`).
A Prepare that logs an ERROR line fails the test at once. A failed run leaves in
`install-report/` (uploaded by CI) the data folder's `logs/` (`door.log`: when the server stopped, its exit code or
signal and the end of its stderr) and in `world/` the server's stacks, the stand-in claude's starts, the spawn and,
on Windows, the processes still running.

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
`.github/workflows/release.yml` builds macOS (Apple silicon), Windows and Linux, runs the unit tests
(off Linux, where `app.yml` runs them) and the packaged smoke test on each, and uploads the installers to a **draft** release of this repo (the
workflow's own token writes it; run by hand, Actions → Release → Run workflow, it is a dry run that uploads to no release, the installers kept as run artifacts: do it before tagging); publish it only after the checklist in [docs/releasing.md](../docs/releasing.md)
passed: a clean-machine install on each system, the release notes, the download link. Installed apps update from the published release (#17, `src/main/updates.ts`): a signed macOS build (the packed `package.json`'s `doorSigned`, set by `electron-builder.config.cjs` when the certificate and notarization are there), the Windows installer and the AppImage download the next version in the background through `electron-updater` (`latest*.yml`, the mac `.zip`, blockmaps; the release workflow uploads them) and install it on restart (the phone server and a running CV style build are stopped first, `src/main/phone-update.ts`, #77, #215; a Tailscale phone server starts again with the new version, a style build has to be started again); an unsigned macOS build and the `.deb` read GitHub's `releases/latest` and link to its page; a checkout, staging and the sandbox do nothing. `DOOR_UPDATES=off` keeps a packaged app from checking; `test:package` and `test:install` set it, nothing else should.

For signed builds add
`MAC_CERTIFICATE`/`MAC_CERTIFICATE_PASSWORD` (Developer ID Application, `.p12` in base64), `APPLE_ID`,
`APPLE_APP_SPECIFIC_PASSWORD` and `APPLE_TEAM_ID` (notarization), and `WINDOWS_CERTIFICATE`/
`WINDOWS_CERTIFICATE_PASSWORD` (Authenticode). Without them the builds are unsigned: macOS asks once
before opening it, Windows SmartScreen warns once.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` / `npm run build` | run / build with electron-vite (`predev`, `prebuild` regenerate the theme) |
| `npm run dev:staging` / `:fresh` | staging: the real app on a throwaway folder (see Environments) |
| `npm run dev:sandbox` / `:fresh` / `:empty` | the sandbox: made-up data or an empty folder, a simulated run (see Environments) |
| `npm run build:web` / `npm run test:web` | the phone app (issue 303): the same renderer behind `src/web/` (`bridge.ts` is `window.door` over `door serve`'s `/mcp`, `Pair.tsx` trades a pairing code for the device token kept in IndexedDB, `Web.tsx` shows the pair screen or the desktop `App`; `remote.ts` tells the screens they run on a phone), built by `vite.web.config.mts` into `out/web`, which `./door serve` serves. `test:web` runs `e2e-web/` against a real `door serve` on the sandbox's made-up data in a phone-sized Electron window (`browser.cjs`, its own storage) at several narrow, tall sizes; `serve-fixture.ts` is the one file under `app/` the guard lets start *The other door*. |
| `npm run record:phone-gif` | re-record `docs/demo/phone.gif`: `demo-record/phone.record.ts` drives the phone app against a real `door serve` on the sandbox's made-up data (360 wide, its own storage), through the demo shim (fake boards, canned scores and CV), so Find new jobs and Prepare play out without the network or Claude; its frames are Chromium's screencast (a frame per repaint), which `app_gif.py --width 360` makes into the GIF and `scripts/demo/video_from_frames.py` into an .mp4 (needs an ffmpeg: `imageio-ffmpeg`'s or one on PATH). |
| `npm run record:gif` | re-record the README's `docs/demo/app.gif`: the built app on the sandbox's made-up data in a temp folder (never `app/.sandbox`), driven by `demo-record/app.record.ts` (Playwright; the stand-in claude, light theme by emulation, a drawn cursor), its screencast frames turned into the GIF by `scripts/demo/app_gif.py` (Pillow, from Poetry). Not a test; CI never runs it. |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | vitest unit tests: no Python, no network (what CI runs) |
| `npm run test:integration` | the real Python server on a generated `DOOR_HOME` (`test/home-fixture.ts`; `buildHome({ prepared: 'jobindex.123' })` adds a finished prepare from `test/fixtures/prepared/`: a 2-page CV, a 1-page letter, their page images and `.html` bodies) with isolated `HOME` and a stand-in `claude` first on `PATH` (it fails and leaves `claude-was-called` in the scratch folder, so a test never reaches your real one); skips with a message when there is no `.venv` or `DOOR_PYTHON` |
| `npm run test:e2e` | builds, then the Playwright smoke tests (`e2e/`) drive the built app in the sandbox, which the journeys never start (its simulated run, and the first launch on an empty sandbox), against the real server on a temp `DOOR_HOME` (Python as above; skips with a message without it). CI runs it under `xvfb-run` |
| `npm run test:journeys` | builds, then every journey (`journeys/`): each user action in the built app against the real server in a test world (`test/world/`), the screen and the data checked after each (`journeys/README.md`). CI runs all of them on each PR and on main, split over four runners and retried once: a journey that passes only on its retry is reported flaky, not failed (#121) |
| `npm run test:journeys:core` | builds, then only the journeys tagged `@core` (the main paths): the quick local check before a push |
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
  under random tokens, with no way to read it. `door:call` takes `tokens` as its fourth argument for the tools whose `PATH_ARGS` rule is `picked`
  (`draft_cv`, `enrich`, `build_style`): it resolves them into the paths of that argument, and for
  `draft_cv` (`sources` are its pages) refuses a non-http address and a linkedin.com one and calls it
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
  Prepare and a real Revise need the `claude` command line and Chromium, so no test runs
  them (vitest covers their states with a mocked bridge); try them by hand. A real `find_jobs` run is never started by a test (it reads
  the network and calls `claude`); the sandbox's simulated run and the run board are what the tests cover.
