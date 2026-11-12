# Settings: inventory of interactions and branches (desktop app, real Python server)

Sources I read in full: `app/src/renderer/screens/{Settings,Connections,SignIn,DataMoves,PhoneSetup,Documentation,Switch,Dialog,Spinner,AppName,PageSections}.tsx`, `connection-rows.ts`, `problems.ts`, `renderer/theme.ts`, `renderer/api.ts`, the Settings-related parts of `renderer/App.tsx`, `main/{claude-login,archive-files,ipc,index}.ts`, `preload/index.ts`, `main/door-server.ts` (env, error translation), plus the Python side: `commands/setup.py`, `core/doctor.py`, `commands/archive.py`, `core/drive.py` (connect/state/errors), `core/sync.py`, `core/phone.py`, `core/pairing.py` (in part), `core/scraper_fix.py` (refusals/outcomes), `core/installers.py` (`plan_install`, `find_claude`), and the tool wrappers in `mcp_server.py`. I also used the unit test names and the existing `e2e/settings.e2e.ts`, `e2e/data.e2e.ts` and `test/home-fixture.ts`.

## 0. Things that hold for the whole area

### How a tool error reaches the screen
- If a Python core raises an expected exception, `_tool_errors` turns it into `{"error": str(exc)}` (`mcp_server._EXPECTED_ERRORS` covers ValueError, LookupError, FileNotFoundError, FileExistsError, ConfigError, CompaniesError, DuplicateApplicationError, LockHeldError, DriveError, SyncConflict, ReviseError, ClaudeError). `SyncConflict` also adds `"conflict": true`. — unit: `app/src/renderer/screens/Connections.test.tsx`
- A core can also return `{"error": ...}` itself (`phone.start` and `phone.pair` do). Either way, `door-server.ts` throws `DoorError(error)` for any result with a string `error`, and the renderer's `call()` throws `ApiError`. **This means the `failure(r)` checks in `PhoneSetup` (`begin`, `showQr`) can never fire against the real server.** The same text arrives through the `catch` instead, and the screen looks the same. — unit: `app/src/renderer/screens/PhoneSetup.test.tsx` (the catch path; failure() unreachable)
- An unexpected exception (OSError, RuntimeError, requests.HTTPError…) becomes an MCP `isError` result. Its text is `Error executing tool <tool>: <exception text>` (FastMCP `tools/base.py:117`), and it reaches the screen as `DoorError(text)`. — not tested: no Settings action of the world raises an unexpected exception; the fault wrapper answers {error} only
- Main-side errors: — not tested: a note on the harness, not an action
  - The server child died: `The other door's server stopped; try again`. — not tested: a crashed server is the shell's own journey (crash fault), not a Settings one
  - The per-tool timeout ran out: `The other door took too long to answer`. The limits are `doctor` 600 s, `setup` 1800 s, `connect_drive` 330 s, `sync_data` 120 s, `phone_start` 300 s. Export and import use `MOVE_TIMEOUT` 180 s. The other tools use the SDK default. — not tested: the shortest of these timeouts is 120 s
  - `unknown tool` (not in `tools.json`). — not tested: unreachable: every tool is in tools.json
- `named(text)` puts every literal "The other door" inside a `<span class="app-name">`. The text content is unchanged, so `toContainText` and `getByText` on the parent `<p>` still match the whole string. — ✓ the row cannot read the sign-in and offers Check again, which recovers once doctor answers
- Every `role="alert"` error paragraph is `<p role="alert">`. Spinners are `<p role="status">` holding the message. — unit: `app/src/renderer/screens/Connections.test.tsx`; unit: `app/src/main/claude-login.test.ts`

### Child environment (what a test can and cannot inject)
- From a checkout, `resolveSpawn` passes the Python child only `PYTHONPATH`, `DOOR_PATHS_FROM_DIALOGS=1`, `DOOR_HOME`, `HOME`, `XDG_CONFIG_HOME`, `APPDATA`, `PATH`, `CLAUDE_CONFIG_DIR`, plus the MCP SDK's short default list (HOME, LOGNAME, PATH, SHELL, TERM, USER). — not tested: a note on the harness, not an action
- **`BROWSER`, `HTTPS_PROXY`, `DOOR_BIN`, `DOOR_WEB_DIR` etc. do NOT reach Python.** To set any other variable, or to monkeypatch Python, use `DOOR_PYTHON`: point it at a wrapper script that exports the variables (or puts a `sitecustomize.py` on the path) and then execs the real venv python. — not tested: a note on the harness, not an action
- `PATH` does reach Python, so stand-in executables work: `claude` (already in `home-fixture.ts`), `cloudflared`, `curl`, `xdg-open` on Linux. — not tested: a note on the harness, not an action (the world's bin/: claude, tectonic, and these journeys' stand-in curl)
- Drive state lives in `$XDG_CONFIG_HOME/door/drive.json` and phone instances in `$XDG_CONFIG_HOME/door/instances.json`. The fixture already isolates `XDG_CONFIG_HOME`. — not tested: a note on the harness, not an action (the world keeps drive.json in <world>/config, boot.py)

### Main-process stub seams (Playwright `app.evaluate`, as `data.e2e.ts` does)
- `dialog.showSaveDialog` and `dialog.showOpenDialog`: export target and import pick. `archive-files` is built with closures that call `dialog.*` at call time, so patching the property works. — not tested: a note on the harness, not an action (fixtures.ts os.nextSave/nextOpen)
- `shell.showItemInFolder`: the data folder's path in Your data. `shell.openExternal`: "Open the sign-in page again" (the only one). Both are called through closures at call time. — not tested: a note on the harness, not an action (fixtures.ts os.opened)
- Pushed IPC events can drive renderer-only states with `BrowserWindow.getAllWindows()[0].webContents.send(channel, payload)`: — not tested: a note on the harness, not an action
  - `door:claude-login` drives the sign-in states, e.g. `{state:'timeout'}`. — unit: `app/src/main/claude-login.test.ts`
- `ipcMain.removeHandler(ch)` followed by `ipcMain.handle(ch, …)` can replace any handler, e.g. `door:claude-login-code`, `door:export-data`. — not tested: a note on the harness, not an action

### What reaches the network, browser or OS (a test must stub it)
| Action | What it reaches | Seam |
|---|---|---|
| Drive **Connect** (`connect_drive`) | Python `webbrowser.open(Google auth URL)` (real default browser; on macOS via `osascript`), then a POST to `oauth2.googleapis.com` and a GET to `www.googleapis.com` | `DOOR_PYTHON` wrapper setting `BROWSER=<script>`. The script can GET `http://127.0.0.1:<port>/?state=<state>&error=access_denied` (both taken from the URL it is given) to make the denial branch reachable offline. The token exchange needs a code-level patch (sitecustomize) or an unreachable proxy via the wrapper's `HTTPS_PROXY`. | — ✓ Connect waits for the browser, then syncs at once: this computer’s data goes to an empty Drive (boot.py's fake Drive; no browser)
| Drive's own syncs (on connecting, on opening the app, before disconnecting), **Keep this computer**, **Keep Drive** (`sync_data`) | Google token refresh and Drive API | Same wrapper. Without it (no network): `Google Drive is unreachable (ConnectionError)`. | — ✓ opening the app syncs once: this computer’s data goes to an empty Drive, and the row says when; ✓ opening the app brings Drive’s data here, keeping this computer’s in backups/, and reads it again; ✓ opening the app replaces nothing: a line opens Settings, where the row asks which to keep; Not now puts it away; ✓ Keep this computer sends its data to Drive, replacing the copy there; ✓ Keep Drive brings Drive’s data here; this computer’s is kept in backups/ (the world's drive folder)
| Drive **Disconnect** (`disconnect_drive`) | Best-effort POST to Google's revoke URL (errors swallowed, 15 s timeout) | Harmless offline; can add up to 15 s when the network hangs. | — ✓ Disconnect asks first: Cancel keeps it; Disconnect sends the last changes, then forgets Drive and leaves the copy there
| **Sign in with Claude** | The main process spawns `claude auth login`; the real claude opens a browser | Stand-in `claude` on PATH (already in `home-fixture.ts`). | — ✓ Sign in with Claude waits for the browser, with the profile’s email on claude’s page (claude.py)
| **Open the sign-in page again** | `shell.openExternal(url)` | Patch `shell.openExternal`. | — ✓ Sign in with Claude waits for the browser, with the profile’s email on claude’s page
| **the data folder's path** (Your data) | `shell.showItemInFolder(home)` (Finder) | Patch `shell.showItemInFolder`. | — ✓ Your data says where the data folder is; its path shows it
| **Export…** and **Import…** | Native dialogs | Patch `dialog.*`. | — ✓ Export… writes an archive where the user says, and names it; ✓ Import replaces the data and keeps what was here in backups/
| Phone **Continue** (`phone_start{connection:'cloudflare'}`) | Spawns `python -m door serve start` (local), `caffeinate` on macOS, and `cloudflared tunnel` (internet). Downloads cloudflared from GitHub if none is found. | Stand-in `cloudflared` on PATH that prints `https://x.trycloudflare.com` and `Registered tunnel connection` to stdout (which is `logs/tunnel.log`) and stays alive. **These processes outlive the app: a test must call `phone_stop` (or kill them) in teardown.** | — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired (boot.py's pretend tunnel)

---

## 1. Settings page shell (`Settings.tsx`)

### Getting there
- Sidebar `nav "Main"` → `getByRole('button', {name:'Settings', exact:true})`. — ✓ Settings shows who is signed in and the plan, with Use another account
- Or a problem line at the sidebar foot: `getByRole('group', {name:'Needs you'})` → button `Claude is not signed in`, `Claude is not installed` or `Google Drive sync failed` (all target Settings). `You have no CV yet` targets Profile instead. — ✓ the sidebar line opens Settings, where the row says Claude is not signed in; ✓ the sidebar says Google Drive sync failed and opens Settings, where the row says why; unit: `app/src/renderer/screens/Connections.test.tsx`; You have no CV yet is the Profile area's

### On mount
- `onRecheck()` runs once, unless on the phone, and calls `doctor` with `{}`. While it is in flight the previous doctor answer stays on screen; the very first time it is `null`. — unit: `app/src/renderer/screens/Connections.test.tsx`
- If doctor fails, App replaces the answer with `{ok:false, checks:[]}`. The doctor error text is never shown. Claude's row then reads "unknown". — ✓ the row cannot read the sign-in and offers Check again, which recovers once doctor answers

### Structure (desktop, `remote=false`)
- `h1` "Settings". — ✓ Settings shows who is signed in and the plan, with Use another account
- `region "Connections"` (h2 `#settings-connections`) containing `list "Connections"`. — ✓ Settings shows who is signed in and the plan, with Use another account
- `region "Your data"` (h2 `#settings-data`, §5). — unit: `app/src/renderer/screens/Settings.test.tsx`
- `region "Appearance"` (h2): a `group` (fieldset) named by the heading and three radios named **"Same as the system"**, **"Light"**, **"Dark"** (`name="theme"`). — unit: `app/src/renderer/theme.test.ts`
- `region "Documentation"` (h2 `#settings-docs`). — unit: `app/src/renderer/screens/Documentation.test.tsx`
- `region "Report a problem"` (h2 `#settings-report`, §5b), last — ✓ Save logs… saves an archive with what went wrong, emails and the home folder masked, nothing of the profile
- A side nav `navigation "Sections"` with links **Connections**, **Your data**, **Appearance**, **Documentation**, **Report a problem**. — unit: `app/src/renderer/screens/Settings.test.tsx`
  - Clicking a link scrolls to that section and marks it `aria-current="location"`. — unit: `app/src/renderer/screens/Settings.test.tsx`
  - The current link also follows scrolling of `.main`. — not tested: scrolling by wheel is not driven; the click case is

### The data folder (Your data, `DataMoves.tsx`)
- One muted `.settings-path` paragraph: "Your profile and jobs are stored in <home>. Export saves them in one file, to move to another computer or keep a copy; Import replaces them with the ones in such a file." (the first sentence only when `info.home` is set). — ✓ Your data says where the data folder is; its path shows it
- `<home>` is a link-styled button (`.link-inline`, its name the path, title "Show in Finder" on macOS, "Show in folder" elsewhere) → `window.door.showHome()` → IPC `door:show-home` → `shell.showItemInFolder(home)`. The OS opens Finder; nothing shows in the window. Stub it. — ✓ Your data says where the data folder is; its path shows it

### Appearance (`theme.ts`)
- On load, `readTheme()` reads `localStorage['door.theme']`: `light` or `dark`, anything else is `system`. The radio matching it is checked. — unit: `app/src/renderer/theme.test.ts`; ✓ Dark turns the whole app dark and stays dark after a reload; Light turns it light
- Choosing a radio calls `saveTheme(v)`: — ✓ Dark turns the whole app dark and stays dark after a reload; Light turns it light
  - `system`: removes the key and the `data-theme` attribute from `<html>`. — ✓ Dark turns the whole app dark and stays dark after a reload; Light turns it light
  - `light` or `dark`: sets the key and `<html data-theme="light|dark">`. — ✓ Dark turns the whole app dark and stays dark after a reload; Light turns it light
- If storage throws, the change applies to this window only. — not tested: Electron's storage does not throw; nothing to break it with
- Assert on `page.locator('html')` with `toHaveAttribute('data-theme', 'dark')`, or check that the attribute is absent for system. — ✓ Dark turns the whole app dark and stays dark after a reload; Light turns it light
- The choice persists across a reload (localStorage) and is per window origin. Nothing goes to disk under `profile/`. — ✓ Dark turns the whole app dark and stays dark after a reload; Light turns it light
- Where `applyTheme` is called at startup is outside this area (`main.tsx`). It is worth an e2e check that a stored `dark` applies after a relaunch. — ✓ Dark turns the whole app dark and stays dark after a reload; Light turns it light (a reload keeps dark)

### Phone (`remote=true`, the web build only; never in Electron)
- No Connections, no Your data, no Report a problem, no Documentation, no side nav, and no doctor call. — not tested: the phone build is the web journeys' (npm run test:web), not Electron
- Shown: Appearance, plus a `region "This computer"` with: — not tested: phone build
  - "Your profile and jobs are on the computer running The other door, in" — not tested: phone build
  - `home` — not tested: phone build
  - "The phone finds, prepares and keeps your applications. Setting up, your profile, CV and employers, connections and moving your data are done on the computer where it is installed." — not tested: phone build

### Narrow window (< 900 px; Electron `minWidth` is 720, so 720–899 px is testable)
- `.page-aside` (the "Sections" nav) is `display:none`, so its links cannot be clicked. — ✓ Settings has no side nav and no sidebar lines; Matches says Claude is not signed in on top
- The sidebar becomes a bottom tab bar and its foot is hidden: no "Find new jobs" button and **no problem lines**. Problem lines only appear on top of **Matches** (`.narrow-top`), never on Settings. — ✓ Settings has no side nav and no sidebar lines; Matches says Claude is not signed in on top
- `h2.display-s` and `h1.display-l` use the phone font sizes. Nothing else in Settings changes; Settings has no pushed or back state. — ✓ Settings has no side nav and no sidebar lines; Matches says Claude is not signed in on top

---

## 2. Connections list (`Connections.tsx`, `connection-rows.ts`)

`list "Connections"` has three `listitem`s, each named by its h3 (`aria-labelledby`):
- **"Claude"** (Required) — ✓ Settings shows who is signed in and the plan, with Use another account
- **"Google Drive"** (Optional) — ✓ Connect waits for the browser, then syncs at once: this computer’s data goes to an empty Drive
- **"Your phone"** (Optional) — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`

Each row shows its "Required" or "Optional" tag. A green check mark (`connection-fine`, aria-hidden, so only the CSS class can be asserted) means the row is fine.

### 2a. Claude row (`claudeRow(doctor)`)
`claudeRow` decides in this order:
- doctor `null` → **checking**. — not tested: too quick to catch: doctor answers before Settings is reached
- `checks` is not an array → **unknown**. — not tested: doctor always answers a list; a failure gives []
- A `claude CLI` check exists with status ≠ ok → **not-installed**. — unit: `app/src/renderer/screens/Connections.test.tsx`
- No `claude login` check, or it has no `details` → **unknown**. — ✓ the row cannot read the sign-in and offers Check again, which recovers once doctor answers
- Login status `ok` → **signed-in** (email and plan from details; plan mapped `max→Max`, `pro→Pro`, `team→Team`, `enterprise→Enterprise`, anything else shown raw). — ✓ Settings shows who is signed in and the plan, with Use another account
- Otherwise, `details.loggedIn === true` and `authMethod` (lowercased) contains both "api" and "key" → **api-key**. — not tested: claude.py says signed in (claude.ai, max) or signed out only; no API-key or plan-less answer
- Otherwise → **signed-out**. — ✓ the sidebar line opens Settings, where the row says Claude is not signed in

| kind | What a real doctor returns to cause it | Visible |
|---|---|---|
| checking | doctor not answered yet | status "Checking Claude…" | — not tested: doctor answers before Settings opens
| not-installed | `claude CLI` status `missing` (no `claude` on PATH or in `~/.local/bin`). The `claude login` check is then absent. | "Not installed", button **"Install"** | — unit: `app/src/renderer/screens/Connections.test.tsx`
| unknown | doctor call failed (App sets `checks:[]`); or `claude auth status --json` printed non-JSON or JSON without `loggedIn` (login check `warn`, no details) | "The other door could not read the Claude sign-in." + button **"Check again"** | — ✓ the row cannot read the sign-in and offers Check again, which recovers once doctor answers; the unreadable-status variant: not tested (claude.py always prints JSON)
| signed-in | `auth status` says `loggedIn:true` with a non-API-key method | `Signed in as <email> (<Plan>)`. Variants: "Signed in as x" (no plan), "Signed in (Max)" (no email), "Signed in". Button **"Use another account"** (quiet); no Check again, since opening Settings reads doctor again. Fine mark. | — ✓ Settings shows who is signed in and the plan, with Use another account; the other variants (no plan, no email): not tested, claude.py has one answer
| api-key | `loggedIn:true`, `authMethod` like `api_key` or `apiKey` | "Signed in with an API key. The other door runs on a Pro or Max plan, never an API key." then the SignIn block (§3) | — not tested: claude.py has no API-key answer
| signed-out | `loggedIn:false` | "Not signed in. The other door needs your Claude plan to score jobs and write applications." then the SignIn block | — ✓ the sidebar line opens Settings, where the row says Claude is not signed in

To drive these, the stand-in `claude auth status` prints `{"loggedIn":true,"authMethod":"api_key"}`, non-JSON, `{"loggedIn":true,"authMethod":"claude.ai","subscriptionType":"pro"}` (no email), and so on. Not-installed means no `claude` on PATH and none in `$HOME/.local/bin`.

Actions:
- **Check again** (signed-in and unknown) → `onRecheck` → `doctor {}`. The row re-renders from the new report. — unit: `app/src/renderer/screens/Connections.test.tsx`; ✓ the row cannot read the sign-in and offers Check again, which recovers once doctor answers
- **Use another account** → that button disappears and the SignIn block (§3) appears under the row. There is no way to collapse it again short of leaving Settings. — ✓ (expected fail, BUG) Use another account opens the sign-in under the row, and a right code keeps it signed in
- **Install** opens `dialog "Install the Claude command line?"`: — unit: `app/src/renderer/screens/Connections.test.tsx`
  - Text: "It is installed for you only, without asking for a password." — unit: `app/src/renderer/screens/Connections.test.tsx`
  - Buttons **"Cancel"** (quiet; closes) and **"Install the Claude command line"** (primary). Escape also closes. — unit: `app/src/renderer/screens/Connections.test.tsx`
  - Install → `setup {install:['claude'], yes:true}`. While it runs the status reads "Installing the Claude command line…". — unit: `app/src/renderer/screens/Connections.test.tsx`; the spinner itself is not caught (the stand-in install is instant)
  - After it: if `outcome` is set and ≠ `ok`, an alert shows `todo.join(' ')` or **"The install did not finish."**. Then `onRecheck()` runs. — ✓ (expected fail, BUG) a working install says nothing failed and leads to Sign in with Claude; ✓ (expected fail, BUG) the installer failing says why (its own error), and the row stays Not installed
  - If the call throws, the alert shows the error text. — unit: `app/src/renderer/screens/Connections.test.tsx`
  - **Surprise:** `_setup_core`'s outcome is `incomplete` whenever any required check is still `missing` after the install, the profile excepted. The `claude login` check is required and `missing` while signed out. **So installing claude from a signed-out state always ends `incomplete`.** The alert then shows either `todo` (texts about the profile, CV or search keywords that have nothing to do with the install) or, with a complete profile like the fixture's, "The install did not finish.", even when the install worked. `results[].error` (the real failure, e.g. `` `sh -c …` exited 1: … ``) is never shown. — ✓ (expected fail, BUG) a working install says nothing failed and leads to Sign in with Claude; ✓ (expected fail, BUG) the installer failing says why (its own error), and the row stays Not installed
  - `ValueError` for an unknown tool cannot happen from the app. — not tested: unreachable from the app
- The error alert stays after a recheck. It clears only on the next install. — unit: `app/src/renderer/screens/Connections.test.tsx`

### 2b. Google Drive row (`driveRow(drive, where)`)
- `drive` comes from `status_summary.drive`. App keeps it only if `connected` is a boolean, otherwise `null`. — ✓ Connect waits for the browser, then syncs at once: this computer’s data goes to an empty Drive

| kind | Condition | Visible |
|---|---|---|
| unavailable | `where==='demo'` | "Not available in the demo" (no buttons) | — not tested: the demo window is not this world
| unavailable | `where==='sandbox'` (onboarding sandbox) | "Not available in the onboarding sandbox" | — not tested: the onboarding sandbox window is not this world
| checking | drive `null` (summary not answered or failed) | status "Checking Google Drive…" (**forever if `status_summary` fails**) | — not tested: status_summary answers before Settings opens; its failure is the shell's journey
| unavailable | `configured === false` | "Not available in this build". **Not reachable from this repo's build:** `CLIENT_ID` and `CLIENT_SECRET` are set in `drive.py`. Needs a Python patch. | — unit: `app/src/renderer/screens/Connections.test.tsx` (world option drive.configured=false)
| off | `!connected` | "Keeps this computer and another one in step." + **"Connect"** | — ✓ Connect waits for the browser, then syncs at once: this computer’s data goes to an empty Drive
| connected | `connected` | One muted line, `<account> · last synced <Mon D, HH:MM>` (locale `toLocaleString`, so the format depends on the locale; `<account> · not synced yet` when null or unparsable; "Connected" when there is no account), plus `The last sync failed: <last_error>` (class `error`, not an alert) when `last_error` is set. Button **"Disconnect"** (quiet), on the right; no Sync now. Fine mark only when there is no `last_error`. | — ✓ opening the app syncs once: this computer’s data goes to an empty Drive, and the row says when; ✓ the sidebar says Google Drive sync failed and opens Settings, where the row says why

To produce each state, seed `$XDG_CONFIG_HOME/door/drive.json`:
- `{"refresh_token":"x","account":"a@b.c","last_synced":"2026-10-29T09:00:00+00:00","last_error":"Google Drive is unreachable (ConnectionError)"}` — ✓ the sidebar says Google Drive sync failed and opens Settings, where the row says why
- Without `refresh_token`, the row reads not connected. — ✓ Disconnect asks first: Cancel keeps it; Disconnect sends the last changes, then forgets Drive and leaves the copy there

Sidebar lines (`problems.ts`, `attention`): when a sync found both sides changed (App's `driveConflict`), the sidebar shows **"Google Drive needs a choice"**; otherwise, when `connected && last_error`, **"Google Drive sync failed"**. Both open Settings. (`attention()` has its own "Drive sync failed" text, but `problems()` calls it with `drive=null`, so that string is never shown.) — ✓ the sidebar says Google Drive sync failed and opens Settings, where the row says why; unit: `app/src/renderer/screens/connection-rows.test.ts`

Actions (all go through `act`):
- `act` clears the message and error first. — unit: `app/src/renderer/screens/Connections.test.tsx`
- Its `finally` always calls `onDriveChanged()`, which bumps `refreshKey` and re-reads `status_summary`, success or failure. — ✓ Connect waits for the browser, then syncs at once: this computer’s data goes to an empty Drive; unit: `app/src/renderer/screens/connection-rows.test.ts`
- Success sets a plain `<p class="small">` message, not role=status. — ✓ opening the app syncs once: this computer’s data goes to an empty Drive, and the row says when
- Failure: if the error is an `ApiError` with `conflict`, the row shows the conflict box; otherwise an alert with the text. — ✓ opening the app replaces nothing: a line opens Settings, where the row asks which to keep; Not now puts it away; unit: `app/src/renderer/screens/Connections.test.tsx`

**Connect** → `connect_drive {}`:
- While waiting, the status reads "Waiting for you to allow access in the browser (up to five minutes), then syncing…". — ✓ Connect waits for the browser, then syncs at once: this computer’s data goes to an empty Drive
- Success: then `sync_data {}` at once, and its message (below); a conflict opens the choice. The re-read summary turns the row to connected. On disk: `drive.json` gains `refresh_token`, `access_token`, `expires_at`, `account`. — ✓ Connect waits for the browser, then syncs at once: this computer’s data goes to an empty Drive
- Errors, exact Python wording: — unit: `app/src/renderer/screens/Connections.test.tsx`

| Trigger | Error text |
|---|---|
| Not configured | "Google Drive sync is not configured in this build: the maintainer has not set the OAuth client (CLIENT_ID / CLIENT_SECRET in src/door/core/drive.py)." | — not tested: the row offers no Connect when not configured (covered by: the row says it is not available, with nothing to click)
| No redirect within 300 s | "Google Drive connect: no answer from the browser within 300 s. Open this address and allow access, then run `data connect` again: <url>". **The app's IPC timeout is 330 s, so the Python message arrives first.** | — not tested: five minutes; the fake Drive answers at once
| State mismatch | "Google Drive connect: the answer did not match this request (state); try again." | — not tested: the fake Drive has no OAuth redirect; any text is a drive.connect fault, as the denial test does
| Denied, or no code | "Google Drive connect was not allowed (access_denied)." / "(no code)." | — unit: `app/src/renderer/screens/Connections.test.tsx`
| Offline at token exchange | "Google Drive is unreachable (ConnectionError)" (or ProxyError, Timeout…) | — not tested: same path as the denial (a DriveError text); covered by Connect refused in the browser says so, and connecting again works
| HTTP ≥ 400 | "Google Drive sign-in failed (HTTP 400)" / "Google Drive account lookup failed (HTTP n)" | — not tested: same path as the denial; covered by Connect refused in the browser says so, and connecting again works
| No refresh token | "Google Drive connect: Google sent no refresh token; try again." | — not tested: same path as the denial; covered by Connect refused in the browser says so, and connecting again works
| Demo, guarded in main | "Google Drive is not available on made-up data." Unreachable from the UI: the row offers nothing in the demo or sandbox. | — not tested: unreachable from the UI, as this inventory says

No Sync now: `sync_data {}` runs by itself on connecting, once when the app opens (App, decided on the first `status_summary`, so a Drive connected later does not sync twice; not on the phone, the demo or the sandbox; a pull re-reads the profile, doctor and the summary; a conflict sets `driveConflict`), and before **Disconnect**. **Keep this computer** → `sync_data {keep_local:true}`; **Keep Drive** → `sync_data {keep_drive:true}`: — ✓ opening the app syncs once: this computer’s data goes to an empty Drive, and the row says when; ✓ Keep this computer sends its data to Drive, replacing the copy there; ✓ Keep Drive brings Drive’s data here; this computer’s is kept in backups/
- While running, the status reads "Syncing with Google Drive…". — not tested: the fake Drive is instant and a tool delay would hold the lock; the spinner is not caught
- Success message by `action`: — ✓ opening the app syncs once: this computer’s data goes to an empty Drive, and the row says when
  - `push`: "Sent this computer's data to Drive." — ✓ opening the app syncs once: this computer’s data goes to an empty Drive, and the row says when; ✓ Keep this computer sends its data to Drive, replacing the copy there
  - `pull`: "Brought Drive's data to this computer." Also calls `onDataChanged` (show_profile, doctor, summary refresh). — ✓ opening the app brings Drive’s data here, keeping this computer’s in backups/, and reads it again; ✓ Keep Drive brings Drive’s data here; this computer’s is kept in backups/
  - `nothing`: "Already in step." — ✓ opening the app syncs once: this computer’s data goes to an empty Drive, and the row says when
  - `skipped`: "Nothing to send yet." — not tested: skipped needs a home with no profile, which has no Settings
  - Anything else: "Synced." — not tested: unreachable: sync_core answers the four actions only
  - On disk: `drive.json` `last_synced`, `fingerprint`, `synced_version`; `last_error` cleared. A pull also replaces `profile/` and `jobs/` and makes a `backups/<ts>/`. — ✓ opening the app syncs once: this computer’s data goes to an empty Drive, and the row says when; ✓ opening the app brings Drive’s data here, keeping this computer’s in backups/, and reads it again
- **Conflict:** SyncConflict comes back with `conflict:true` (App's `driveConflict`, so a sync on opening asks here too) and Disconnect is replaced by: — ✓ opening the app replaces nothing: a line opens Settings, where the row asks which to keep; Not now puts it away
  - "This computer and Drive both changed since they last synced. Nothing was replaced." — ✓ opening the app replaces nothing: a line opens Settings, where the row asks which to keep; Not now puts it away
  - Bullets: "Keep this computer: its data replaces the copy on Drive." / "Keep Drive: Drive's data replaces this computer's, which is kept as a backup." — ✓ opening the app replaces nothing: a line opens Settings, where the row asks which to keep; Not now puts it away
  - Buttons **"Keep this computer"**, **"Keep Drive"**, **"Not now"**. Not now hides the box and the sidebar line. — ✓ opening the app replaces nothing: a line opens Settings, where the row asks which to keep; Not now puts it away; ✓ Keep this computer sends its data to Drive, replacing the copy there; ✓ Keep Drive brings Drive’s data here; this computer’s is kept in backups/
  - The Python conflict message itself is never shown. — ✓ opening the app replaces nothing: a line opens Settings, where the row asks which to keep; Not now puts it away
- Errors (alert): — unit: `app/src/renderer/screens/Connections.test.tsx`
  - "Google Drive is not connected; run `./door data connect`." (state has no `refresh_token`) — not tested: the app syncs only a connected Drive
  - "Google Drive is unreachable (<Exc>)" — unit: `app/src/renderer/screens/Connections.test.tsx` (a drive fault; same path)
  - "Drive disconnected (access was revoked or expired); run `./door data connect`." — unit: `app/src/renderer/screens/Connections.test.tsx` (same path)
  - "Google Drive <what> failed (HTTP n)" — unit: `app/src/renderer/screens/Connections.test.tsx`
  - "There is nothing on Google Drive to keep." (Keep Drive with no remote archive) — not tested: Keep Drive is offered only after a conflict, which needs a copy on Drive
  - "There is no archive of The other door on Google Drive." (pull) — not tested: a pull is decided only when Drive has an archive
  - "choose one of keep_local and keep_drive, not both" (unreachable) — not tested: unreachable
  - The `_locked("sync")` LockHeldError text when a run holds the lock: "a run is in progress (started HH:MM, pid N); try again when it has finished" or "another process of The other door is writing the ledgers (<purpose>) (...); try again in a moment". — not tested: the same failure path as any other; holding the lock from a test would race the app
  - Timeout (120 s): "The other door took too long to answer". — not tested: 120 s
- A failed `sync_data` writes `last_error` (`sync.sync_now`), so a sync on opening that fails shows as the sidebar's "Google Drive sync failed" and the row's red line. On Disconnect, a failed last sync (not a conflict) does not stop it: "Disconnected. The last changes did not reach Drive: <why>". — ✓ a sync on opening that fails: the sidebar says so, and the row says why; unit: `app/src/renderer/screens/Connections.test.tsx`
- Every outcome other than lock-held and "not connected" needs Google's API, so it is unreachable offline without the `DOOR_PYTHON` wrapper and sitecustomize seam. That includes conflict, push, pull, nothing and skipped. — not tested: a note on the harness, not an action (the world's fake Drive makes all of them reachable offline)

**Disconnect** opens `dialog "Disconnect Google Drive?"`: — ✓ Disconnect asks first: Cancel keeps it; Disconnect sends the last changes, then forgets Drive and leaves the copy there
- Text: "This computer stops syncing. The copy on Drive stays, and you can connect again later." — ✓ Disconnect asks first: Cancel keeps it; Disconnect sends the last changes, then forgets Drive and leaves the copy there
- Buttons **"Cancel"** and **"Disconnect"** (primary). — ✓ Disconnect asks first: Cancel keeps it; Disconnect sends the last changes, then forgets Drive and leaves the copy there
- Confirm → `disconnect_drive {}`. The status reads "Disconnecting…", then the message "Disconnected. The copy on Drive stays.". — ✓ Disconnect asks first: Cancel keeps it; Disconnect sends the last changes, then forgets Drive and leaves the copy there
- On disk: `drive.json` deleted, plus a best-effort revoke POST. — ✓ Disconnect asks first: Cancel keeps it; Disconnect sends the last changes, then forgets Drive and leaves the copy there
- **The result `{disconnected:false}` is ignored:** the same success text shows even if nothing was connected. — not tested: the row offers Disconnect only when connected
- No expected errors. — not tested: a note on the harness, not an action

### 2c. Your phone row (`PhoneConnection`)
- On mount, `phone_status` is called. This is the only Connections call that runs by itself. — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
- **No demo or sandbox guard:** in the demo, Continue really serves the made-up data. — not tested: the demo window is not this world

| Condition | Visible |
|---|---|
| `status===null` and no error | status "Checking your phone…" (no buttons) | — not tested: phone_status answers before the row is looked at
| `phone_status` threw | alert with the error text, no state line, **no buttons at all** (the button needs `status!==null`). Dead end until Settings remounts. | — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`; ✓ (expected fail, BUG) phone_status failing still leaves a way to try again in the row
| not running, `devices.length>0` | "Disconnected when this computer restarted. Set it up again and scan a new code." + **"Set up your phone"** | — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
| not running, no devices | no state line, only **"Set up your phone"** | — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
| running | One muted line, no address and no word of serving: "Connected" (lasting) or "Connected until this computer restarts" when a phone is paired, "Not paired yet." when none is. Buttons **"Disconnect"** (quiet), and **"Pair your phone"** when none is paired. No device names: the app pairs one phone, always as "My phone". Fine mark only when running and a phone is paired. | — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired; ✓ closed before the scan: Pair your phone brings the code back; Disconnect asks, then unpairs and stops; lasting (Tailscale): not tested, the app never asks for it

- "running" means `.serve/run.json` exists and the `serve_pid` (and `tunnel_pid` if set) are alive. A dead tunnel reads not running. — not tested: a note on the harness, not an action (the pretend tunnel keeps its state in the server)
- To seed: `<home>/.serve/devices.json` = `[{"device","paired_at","last_seen","token_hash"…}]`. Only `device`, `paired_at` and `last_seen` are read. A `run.json` with live pids gives running; a test can use pids of its own long-lived processes. — not tested: a note on the harness, not an action

Actions:
- **Set up your phone** → PhoneSetup dialog starting at step `how`. **Pair your phone** → starting at step `pair` (§7). — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`; ✓ closed before the scan: Pair your phone brings the code back; Disconnect asks, then unpairs and stops
- **Disconnect** → a dialog "Disconnect your phone?" (Cancel / Disconnect); Disconnect runs `unpair_phone {device}` for each paired device (one, or an older second), then `phone_stop {}`, then `phone_status`. A failed unpair stops there: its error shows and nothing is stopped. — ✓ closed before the scan: Pair your phone brings the code back; Disconnect asks, then unpairs and stops
  - Error: "no paired phone is called '<d>'" (alert; Python repr quotes). — ✓ closed before the scan: Pair your phone brings the code back; Disconnect asks, then unpairs and stops
  - Buttons are disabled while busy. — not tested: the pretend server answers at once
- `phone_stop {}` (the end of Disconnect) That kills the tunnel, caffeinate and serve, and deletes `run.json`. Returns `{stopped}`, which is ignored. — ✓ closed before the scan: Pair your phone brings the code back; Disconnect asks, then unpairs and stops; unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
- When the dialog closes, `phone_status` is read again. — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired

---

## 3. Sign-in block (`SignIn.tsx` + `main/claude-login.ts`)

It appears in the Claude row for signed-out and api-key, and under "Use another account". `email` is the profile's `config.email`.

On mount:
- Subscribes to `door:claude-login` and reads `door:claude-login-state`. — unit: `app/src/renderer/screens/SignIn.test.tsx`
- A carried state (`starting`, `waiting`, `done`) is adopted. An old `failed`, `timeout` or `cancelled` is not shown. — unit: `app/src/renderer/screens/SignIn.test.tsx`
- An adopted `done` sets `stale`. — unit: `app/src/renderer/screens/SignIn.test.tsx`
- Leaving Settings does not cancel a sign-in; coming back picks up `waiting`. — unit: `app/src/renderer/screens/SignIn.test.tsx`

Renders by state:
- **idle** (and `cancelled`, and an un-carried failure) → button **"Sign in with Claude"** (primary). — unit: `app/src/main/claude-login.test.ts`
- **starting** → status "Starting the sign-in…". — not tested: over in milliseconds; not caught
- **waiting** → — ✓ Sign in with Claude waits for the browser, with the profile’s email on claude’s page
  - Status "Finish signing in in your browser. The other door waits here." — ✓ Sign in with Claude waits for the browser, with the profile’s email on claude’s page
  - **"Open the sign-in page again"**: disabled while `canOpen:false`, which is true until claude prints a `https://*.claude.ai|claude.com` URL on stdout. — ✓ Sign in with Claude waits for the browser, with the profile’s email on claude’s page (enabled once claude prints its page; the disabled moment is not caught)
  - **"Cancel"**. — unit: `app/src/main/claude-login.test.ts`
  - Button **"The page showed a code?"**, which reveals a form with the label **"Sign-in code"** (`getByLabel('Sign-in code')`) and **"Send code"**. Send code is disabled while the box is blank (trimmed). It submits on Enter too. — unit: `app/src/main/claude-login.test.ts`
- **done** (just pushed, not stale) → status "Checking the sign-in…". `onDone` → doctor. — ✓ (expected fail, BUG) claude says the sign-in worked but doctor cannot see it: the block says so instead of checking forever
- **done & stale** (`done` was already the state when the block mounted) → alert "claude said the sign-in worked, but The other door still can't see the sign-in." + **"Try again"**. — unit: `app/src/renderer/screens/SignIn.test.tsx`
- **failed** → alert `The sign-in didn't go through: <message>` + **"Try again"**. — ✓ a wrong code fails the sign-in; Try again with the right one signs in and clears the sidebar line
- **timeout** → alert "The sign-in waited five minutes for the browser and stopped." + **"Try again"**. — unit: `app/src/main/claude-login.test.ts`

Clicks:
- **Sign in with Claude** or **Try again** → `door:claude-login-start(email)`. The main process: — ✓ Sign in with Claude waits for the browser, with the profile’s email on claude’s page; ✓ a wrong code fails the sign-in; Try again with the right one signs in and clears the sidebar line
  - Calls `doctor` (server) to find the claude path (`claude CLI` `details.path`) and `claude login.details.doorConfigDir`. — ✓ Sign in with Claude waits for the browser, with the profile’s email on claude’s page
  - Spawns `<path> auth login --claudeai [--email <email>]`. `--email` is added only when the email matches `^[^\s@-][^\s@]*@[^\s@]+\.[^\s@]+$` and is ≤ 254 characters. The env drops `CLAUDE_CODE_*`, `CLAUDECODE` and `CLAUDE_CONFIG_DIR`, then sets `CLAUDE_CONFIG_DIR` to `doorConfigDir`. — ✓ Sign in with Claude waits for the browser, with the profile’s email on claude’s page
  - Then `waiting{canOpen:false}`, then `waiting{canOpen:true}` once the URL is seen. — ✓ Sign in with Claude waits for the browser, with the profile’s email on claude’s page
- **Open the sign-in page again** → `door:claude-login-open` → `shell.openExternal(<url claude printed>)`. Its `{ok:false}` result is ignored. — ✓ Sign in with Claude waits for the browser, with the profile’s email on claude’s page
- **Cancel** → `door:claude-login-cancel` kills the child. State becomes `cancelled`, so the block shows "Sign in with Claude" again. — unit: `app/src/main/claude-login.test.ts`
- **Send code** → `door:claude-login-code(code)`. — unit: `app/src/main/claude-login.test.ts`; ✓ a wrong code fails the sign-in; Try again with the right one signs in and clears the sidebar line
  - Main refuses with `{ok:false, error:'That is not a sign-in code.'}` when the trimmed code fails `^[A-Za-z0-9#_.~+/=-]{1,512}$` (e.g. it contains a space or `!`) or no child is running. The alert under the box reads "That is not a sign-in code.". — unit: `app/src/main/claude-login.test.ts`
  - **The renderer's fallback "That code did not go through." is unreachable**: main always sends an `error`. — not tested: unreachable
  - An accepted code is written to claude's stdin. — ✓ a wrong code fails the sign-in; Try again with the right one signs in and clears the sidebar line

Outcome by what claude does:

| claude does | state → visible |
|---|---|
| exits 0 | `done` → "Checking the sign-in…" → doctor → row turns signed-in (e.g. "Signed in as ada@example.com (Max)") and the sidebar line disappears | — ✓ a wrong code fails the sign-in; Try again with the right one signs in and clears the sidebar line
| exits ≠ 0 with `Login failed: X` on stderr or stdout | failed: "The sign-in didn't go through: X". Stand-in with a wrong but syntactically valid code: "…: Request failed with status code 400" | — ✓ a wrong code fails the sign-in; Try again with the right one signs in and clears the sidebar line
| exits ≠ 0 without that line | "The sign-in didn't go through: claude stopped (exit N)" | — not tested: claude.py always says Login failed
| spawn error | "…: claude could not start: <msg>" | — not tested: the stand-in claude always starts
| doctor call threw at start | "…: The other door could not check claude: <msg>" | — not tested: a doctor fault would first turn the row to unknown, which offers no Sign in
| no claude path | "…: The claude app is not installed." (only if claude vanished after the row decided it was installed) | — not tested: only if claude vanishes between the row and the click
| no answer for 5 min | `timeout`. `LOGIN_TIMEOUT_MS` is fixed (no env override in the built app), so reach it in tests by pushing `{state:'timeout'}` on `door:claude-login` from main. | — unit: `app/src/main/claude-login.test.ts` (pushed from main)

- **Stuck-spinner edge:** after a real `done`, if doctor still says not signed in (claude saved the login somewhere doctor does not read), the block keeps "Checking the sign-in…" indefinitely. `stale` is only set at mount. Leaving and returning shows the stale message. — ✓ (expected fail, BUG) claude says the sign-in worked but doctor cannot see it: the block says so instead of checking forever; unit: `app/src/renderer/screens/SignIn.test.tsx`
- **Same edge under "Use another account":** the row stays signed-in, `again` stays true, and the block stays on "Checking the sign-in…" forever after a successful re-sign-in. — ✓ (expected fail, BUG) Use another account opens the sign-in under the row, and a right code keeps it signed in
- No sign-in from the phone. The `door:claude-login-start` handler without `claudeLogin` ("signing in is not available here") is unreachable in the real main. — not tested: unreachable

---

## 5. Your data (`DataMoves.tsx` + `archive-files.ts` + ipc), region "Your data"

- Buttons **"Export…"** and **"Import…"** (secondary), both disabled while busy (export or import running; not during the pick). — ✓ Export… writes an archive where the user says, and names it; unit: `app/src/renderer/screens/DataMoves.test.tsx`; disabled while busy: not caught
- Spinner: "Exporting…" / "Importing…". — not tested: both finish in under a second; not caught
- A message (plain `p`), `list "Worth checking"` (warnings), and an error (`p[role=alert].field-error`). — ✓ Export… writes an archive where the user says, and names it; ✓ Import replaces the data and keeps what was here in backups/

### Export…
- IPC `door:export-data`. Main runs `exportTarget()`, which shows a save dialog: title "Export your data", message "Choose a new name: an export never replaces a file.", default `door-export-<YYYY-MM-DD>.tar.gz`, filter "The other door export" (`tar.gz`, `tgz`). — ✓ Export… writes an archive where the user says, and names it
- A chosen path without `.tar.gz` or `.tgz` gets `.tar.gz` appended. — unit: `tests/commands/test_archive_cli.py`
- Branches: — unit: `app/src/renderer/screens/DataMoves.test.tsx`; unit: `tests/commands/test_archive_cli.py`; ✓ Export… writes an archive where the user says, and names it
  - **Cancelled** (`{canceled:true}` or an empty filePath) → `{ok:false, canceled:true}`. No message, no error; the spinner flashes. — unit: `app/src/renderer/screens/DataMoves.test.tsx`
  - **Exists** → error "<basename> is there already. An export never replaces a file, so nothing was written: choose another name." — unit: `tests/commands/test_archive_cli.py`
  - Otherwise `export_data {path}` (timeout 180 s). `path_scope` is skipped (`DOOR_PATHS_FROM_DIALOGS=1`). — ✓ Export… writes an archive where the user says, and names it
- Success: **`Exported <files> files (<size>) to <basename>.`**, where size is `x.y MB` at ≥ 1,000,000 bytes, else `<n> kB` (minimum 1; **lowercase kB**, unlike the CLI's KB). On disk: the archive (`manifest.json`, `profile/…`, `jobs/…` without the lock and progress files). The tmp file is removed on failure. — ✓ Export… writes an archive where the user says, and names it (MB: the world's home holds PDFs; kB not tested)
- Python errors (alert): — unit: `tests/commands/test_archive_cli.py`
  - "nothing to export: <home>/profile/config.json not found" — not tested: a home without a profile opens the wizard, not Settings
  - "write the export outside <profile_dir> and <jobs_dir>, not to <target>" (a target inside the data folders) — unit: `tests/commands/test_archive_cli.py`
  - "<target> already exists — pass another path" (race) — not tested: a race between the dialog and the export
  - Lock held: "a run is in progress (started HH:MM, pid N); try again when it has finished" / "another process of The other door is writing the ledgers (<purpose>) (…); try again in a moment" — not tested: same alert path as Export… into the data folder itself is refused by door, and nothing is written
  - Permission denied and similar OSErrors → `Error executing tool export_data: [Errno 13] Permission denied: '…'` — not tested: same alert path as Export… into the data folder itself is refused by door, and nothing is written
  - Timeout → "The other door took too long to answer" — not tested: 180 s
- Export runs no Drive hooks ("export" is in `_NO_SYNC_PURPOSES`). — not tested: not observable on screen; the push tests show the hooks' effect

### Import…
- IPC `door:pick-archive` shows an open dialog: title "Import data", openFile, same filter. — ✓ Import… asks first; Cancel imports nothing
- Branches: — unit: `app/src/renderer/screens/DataMoves.test.tsx`; unit: `app/src/main/archive-files.test.ts`; ✓ Import… asks first; Cancel imports nothing
  - **Cancelled** → `{canceled:true}`. Nothing is shown (message and error were already cleared). — unit: `app/src/renderer/screens/DataMoves.test.tsx`
  - Not a `.tar.gz` or `.tgz` by name, or by realpath (a symlink to another file) → error **"Choose an export, a .tar.gz file."** — unit: `app/src/main/archive-files.test.ts`; the symlink case: not tested
  - OK → `{token, name: basename}`. The token is single use; a new pick replaces the old one. — ✓ Import… asks first; Cancel imports nothing
- Then `dialog "Import <name>?"`: — ✓ Import… asks first; Cancel imports nothing
  - "This replaces your profile and jobs on this computer with the ones in <name>. What is here now is kept as a backup first, so nothing is lost." — ✓ Import… asks first; Cancel imports nothing
  - Muted: "If Google Drive is connected, the next sync sends the imported data to Drive, replacing the copy there; if Drive changed meanwhile, it asks which to keep first." — ✓ Import… asks first; Cancel imports nothing
  - Buttons **"Cancel"** (drops the token; nothing imported) and **"Import"** (primary). Escape also cancels. — ✓ Import… asks first; Cancel imports nothing
- **Import** → `door:import-data(token)`. Main runs `take(token)`; an unknown or used token gives **"Choose the archive again."** (renderer-unreachable normally). Then `import_data {archive: realpath}` (180 s). — ✓ Import replaces the data and keeps what was here in backups/; "Choose the archive again.": not tested (unreachable from the window)
- Success: — ✓ Import replaces the data and keeps what was here in backups/
  - **`Imported <files> files.`**, plus ` What was here is kept in <backup_dir>.` when `backup_dir` is set (an absolute path: `<home>/backups/<YYYYMMDD-HHMMSS>[-n]`). — ✓ Import replaces the data and keeps what was here in backups/
  - `warnings` → `list "Worth checking"`, one item per string, e.g. `cv_template points to /x/y, which doesn't exist on this computer; update profile/config.json`, or `<home>/profile/config.json is not valid JSON; run \`doctor\``. — not tested: the world's own export has no foreign paths to warn about
  - Then `onImported` → `onDataChanged`: show_profile, doctor, summary refresh, and remounted Matches. — ✓ Import replaces the data and keeps what was here in backups/
  - On disk: the old `profile/` and `jobs/*` (minus lock files) moved to `backups/<ts>/`, the new data swapped in. — ✓ Import replaces the data and keeps what was here in backups/
- Python errors (alert): — ✓ Import… of something that is not an export is refused; nothing changes
  - "<archive> not found" (deleted between pick and Import) — not tested: needs the file deleted between the pick and Import; same alert path as Import… of something that is not an export is refused; nothing changes
  - "<archive> is not an export from The other door (not a .tar.gz archive)" (corrupt or not gzip; a test can write junk bytes to `x.tar.gz`) — ✓ Import… of something that is not an export is refused; nothing changes
  - "<archive> is not an export from The other door (no readable manifest.json)" — not tested: same alert path as Import… of something that is not an export is refused; nothing changes
  - "<archive> is not an export from The other door (manifest.json has no format)" — not tested: same alert path as Import… of something that is not an export is refused; nothing changes
  - "<archive> was written by a newer version of The other door (format N); update it first" — not tested: same alert path as Import… of something that is not an export is refused; nothing changes
  - "<archive>: unexpected entry '<name>'; nothing was imported" (absolute path, `..`, a symlink or device, or a top-level entry other than profile/jobs) — not tested: same alert path as Import… of something that is not an export is refused; nothing changes
  - "<archive> has no profile/config.json; nothing was imported" — not tested: same alert path as Import… of something that is not an export is refused; nothing changes
  - Lock held (as above) — not tested: same alert path as Import… of something that is not an export is refused; nothing changes
  - Timeout — not tested: 180 s
  - All of these name the **absolute realpath** (on macOS `/private/var/...` for tmp). Assert with a regex. — ✓ Import… of something that is not an export is refused; nothing changes
- Import runs no Drive pull or push hooks ("import" is in `_NO_SYNC_PURPOSES`). The next ledger write elsewhere pushes it, or reports a conflict. — not tested: not observable on screen

## 5b. Report a problem (`ReportProblem.tsx` + `archive-files.ts` `reportTarget` + ipc `door:report-problem`), region "Report a problem"

- Intro (muted): "Saves one file to send when something does not work: what went wrong lately, the last runs and the checks of this computer. No CV, profile, job ads or applications; emails and folder names are hidden." — ✓ Save logs… saves an archive with what went wrong, emails and the home folder masked, nothing of the profile
- Button **"Save logs…"** (secondary), disabled while saving; spinner "Saving…". — unit: `app/src/renderer/screens/ReportProblem.test.tsx`; the spinner: not tested (under a second)
- IPC `door:report-problem`. Main runs `reportTarget()`: a save dialog titled "Report a problem", message "Choose a new name: a report never replaces a file.", default `door-report-<YYYY-MM-DD>.zip`, filter "Problem report" (`zip`); a name without `.zip` gets it. Then `report_problem {path}` (120 s). The window never names the file (`report_problem` is in `PATH_ARGS`). — ✓ Save logs… saves an archive with what went wrong, emails and the home folder masked, nothing of the profile; the added `.zip`: archive-files.test.ts
- Branches: — ✓ each below
  - **Cancelled** → nothing shown, nothing written, no tool call. — unit: `app/src/renderer/screens/ReportProblem.test.tsx`
  - **Exists** → alert "<basename> is there already. A report never replaces a file, so nothing was written: choose another name." — unit: `tests/commands/test_report_cli.py`
  - **door fails** (any `{"error"}`, e.g. a full disk) → that error as the alert; no file left. — unit: `app/src/renderer/screens/ReportProblem.test.tsx`
  - **Saved** → **"Saved as <basename>. Send it to enys.mones@gmail.com."** — ✓ Save logs… saves an archive with what went wrong, emails and the home folder masked, nothing of the profile
- The archive (`src/door/commands/report.py`): `README.txt`, `about.json` (version, OS, Python), `doctor.json` (each check's name, status, required, detail), `logs/door.log*`, `runs/<last 5>.json` (counts, outcomes, errors; no titles, companies or folders). Emails become `<email>`, the data folder `<data folder>`, the home folder `~`. Nothing from `profile/`, no postings, no ledger. — ✓ Save logs… saves an archive with what went wrong, emails and the home folder masked, nothing of the profile (a doctor fault naming the home and the email is in the log, masked; no cv.md, no persona name)
- The log has the app's own lines too (`app/src/main/problem-log.ts`): a server that died (with its stderr), a call that timed out, what the window was refused. — ✓ a server that died is in the report, from the app's side
- Opened from the sidebar's **"Something keeps going wrong. Send a report"** (jobs.md §0): Settings with this part scrolled into view. A saved report stamps `logs/reported_at` (`recurring.stamp_report`), the app reads `status_summary` again and the line goes. — ✓ a board that failed in each of the last three runs: the line opens Report a problem, and a saved report takes it away (report.journey.ts)
- Not on the phone (`reportProblem` is `machineOnly` in the web bridge; `report_problem` is not in `serve_policy.PHONE_TOOLS`). — not tested here: Settings.test.tsx checks the phone has no button

---

## 6. Documentation (`Documentation.tsx`)

- `region "Documentation"` with `list` → one button per doc. Only one exists: **"Legal disclaimer"** (link-inline). — unit: `app/src/renderer/screens/Documentation.test.tsx`
- Clicking it opens `dialog "Legal disclaimer"`: — unit: `app/src/renderer/screens/Documentation.test.tsx`
  - The body is `LEGAL_DISCLAIMER.md` with its first `# Legal disclaimer` heading stripped, rendered by `Markdown` (real elements). — unit: `app/src/renderer/screens/Documentation.test.tsx`
  - The h2 sections inside: "You decide what it reads, and you answer for it", "Your data", "What Claude writes for you", "No affiliation, no warranty, no legal advice", "For site owners". — unit: `app/src/renderer/screens/Documentation.test.tsx`
  - A **"Close"** button (secondary) closes it, as does Escape. — unit: `app/src/renderer/screens/Documentation.test.tsx`
  - The body's first line is "The other door is a personal job-search tool. …". — unit: `app/src/renderer/screens/Documentation.test.tsx`
- Not shown on the phone. — not tested: phone build

---

## 7. Phone setup dialog (`PhoneSetup.tsx`), `dialog "Set up your phone"`

Focus: the Dialog focuses its first control on open. After a step change, if focus fell to `body`, it moves to **Close** (step `pair`) so that Escape still works. Escape → `onClose` at any step (polling stops; `phone_status` reloads).

### Step `how` (from "Set up your phone")
- Text: "The other door on your phone is this app, served by this computer. There is nothing to install: scan a code and it works anywhere while this computer is on." — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
- Muted: "When this computer restarts, set this up again and scan a new code. What you see on your phone passes through Cloudflare, which could read it on the way." — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
- Buttons **"Continue"** (primary; disabled while busy) and **"Cancel"** (quiet). — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`; ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
- **Continue** → `phone_start {connection:'cloudflare'}` (timeout 300 s). While running, the status reads "Starting The other door for your phone…". — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired; the spinner: not caught
  - Success → step `pair`, showing that status. — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
  - It reuses a running cloudflare server. A stale `run.json` is stopped first. — not tested: the pretend tunnel has no stale run.json
- Errors (alert, stays on `how`): — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`

| Trigger | Error text |
|---|---|
| serve does not answer `/manifest.webmanifest` within 30 s | "The other door's server did not start; see <home>/logs/serve.log" | — unit: `app/src/renderer/screens/PhoneSetup.test.tsx` (one text for all: the same path)
| No `trycloudflare.com` URL in `tunnel.log` within 60 s | "the tunnel gave no address; see <home>/logs/tunnel.log" | — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
| No "Registered tunnel connection" within 60 s | "the tunnel could not connect to Cloudflare; see <log>" | — not tested: same path as a tunnel that does not start says why and stays on the first step; Continue again works
| cloudflared missing and the download fails | `Error executing tool phone_start: <HTTPError/ConnectionError…>` (requests errors are not "expected") | — not tested: same path as a tunnel that does not start says why and stays on the first step; Continue again works
| Digest mismatch | "the cloudflared download does not match its pinned checksum; nothing was installed (<url>)" | — not tested: same path as a tunnel that does not start says why and stays on the first step; Continue again works
| Unsupported arch | "no cloudflared for <key>; install it yourself (https://github.com/cloudflare/cloudflared)" | — not tested: same path as a tunnel that does not start says why and stays on the first step; Continue again works
| No free port | `Error executing tool phone_start: no free port for the phone server` | — not tested: same path as a tunnel that does not start says why and stays on the first step; Continue again works
| Timeout (300 s) | "The other door took too long to answer" | — not tested: 300 s

  - `{needs: …}` answers exist only for tailscale, which the app never asks for, so those are unreachable. — not tested: unreachable
  - With a stand-in `cloudflared` on PATH that prints both lines, the happy path is offline: on disk `<home>/.serve/run.json`, `<home>/logs/{serve,tunnel,awake}.log`, `$XDG_CONFIG_HOME/door/instances.json`, and real child processes (**clean them up**). — not tested: a note on the harness, not an action (boot.py's pretend tunnel instead: no processes)

### Step `pair` (directly from "Pair your phone", or after Continue)
- A muted line when `status.address` is set: — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
  - `Serving at <address>, an address that stays the same.` (lasting) — not tested: Tailscale; the app never asks for it
  - or `Serving at <address>. This address changes when this computer restarts.` — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
  - **Opened via "Pair your phone" the dialog has no `status`, so this line is absent**, and the "already paired" baseline for polling is empty (see below). — ✓ closed before the scan: Pair your phone brings the code back; Disconnect asks, then unpairs and stops
- On entering the step the code is made at once (`pair_phone {device: "My phone"}`, once per visit), with "Making a code…" while it runs. No name to type. If it fails, the error and **"Try again"** (primary). — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
  - Success → `img "QR code that pairs your phone"` (a data:image/svg+xml base64 `src`), the text "Point your phone's camera at the code and open the link it shows. It works once, for five minutes.", and the status "Waiting for your phone…". — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
  - On disk: a pending entry in `<home>/.serve/pairing.json`. The code only exists inside the QR. — not tested: a note on the harness, not an action (the pretend tunnel keeps it in the server)
  - Errors (alert): — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
    - "The other door is not serving a phone yet; start it first" (the server stopped meanwhile, or "Pair your phone" after the processes died) — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
    - The device-name `ValueError` is unreachable: strong codes skip the duplicate check and an empty name falls back to "My phone". — not tested: unreachable
- **Close** (quiet), always shown. — ✓ closed before the scan: Pair your phone brings the code back; Disconnect asks, then unpairs and stops
- Polling every 2000 ms while a code shows and has not expired: — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
  - Each tick first checks `expires_at` against the window clock; if it has passed, the code is marked expired. — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
  - Otherwise it calls `phone_status`. A device with the same name whose `paired_at` differs from the baseline moves to step `home`. — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
  - The baseline is the devices in the `status` from Continue; via "Pair your phone" it is empty, so any "My phone" counts, even an old one; the row offers Pair your phone only when nothing is paired, so there is none.
  - Polling errors are swallowed. — not tested: not driven
  - A test can complete pairing without a phone by appending `{"device":"My phone","paired_at":"<now>","last_seen":null,…}` to `<home>/.serve/devices.json`, or by POSTing `/pair` to the serve port with the code decoded from the QR. — not tested: a note on the harness, not an action (phoneScans: <world>/phone-scanned)
- **Expired:** — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
  - "This code has expired. Make a new one and scan it within five minutes." + **"New code"** (primary). That calls `pair_phone` again. — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
  - Also shown immediately if the returned `expires_at` is already ≤ now (clock skew). — not tested: clock skew between the window and the server: not driven
  - The real TTL is 5 min. Playwright `page.clock` can fast-forward the renderer's `Date.now()` and `setInterval`; `expires_at` is server time. — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`

### Step `home`
- h3 "Add The other door to your home screen". — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
- "Your phone is paired. So that The other door opens like an app:" — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
- A list with "Android: in Chrome, open the menu (⋮) and tap Install app." and "iPhone: in Safari, tap Share, then Add to Home Screen." — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
- If not `status.lasting` (always so for cloudflare, and when there is no status): the muted line "When this computer restarts, set this up again and scan the new code. The address changes with it, so add it again to your home screen and remove the old one." — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired
- **"Done"** (primary) closes the dialog, and the row re-reads `phone_status`. It now shows `Serving at …` and **"Remove phone"**. — ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired

---

## 8. Switch (`Switch.tsx`)

Not used anywhere in Settings. It is used by the CV editor. It renders `role="switch"` with `aria-checked`, named by its label. Out of scope here. — not tested: out of scope

---

## 9. Data-driven variant checklist (to drive from a test world)

- **Claude row**: checking, not-installed, unknown (doctor failed / unreadable status), signed-in (email+plan, email only, plan only, neither, unknown plan string), api-key, signed-out. Plus the install dialog (cancel / install → incomplete / throw). — ✓ Settings shows who is signed in and the plan, with Use another account; ✓ the sidebar line opens Settings, where the row says Claude is not signed in; unit: `app/src/renderer/screens/Connections.test.tsx`; ✓ the row cannot read the sign-in and offers Check again, which recovers once doctor answers; api-key and plan/email variants: not tested (claude.py has one signed-in answer)
- **Sign-in**: idle, starting, waiting (canOpen false/true), code box (blank disabled, refused code, wrong code → failed 400, right code → done → signed in), cancel, failed (4 message sources), timeout (push), stale done, stuck "Checking the sign-in…", `--email` passed or not. — ✓ Sign in with Claude waits for the browser, with the profile’s email on claude’s page; unit: `app/src/main/claude-login.test.ts`; ✓ a wrong code fails the sign-in; Try again with the right one signs in and clears the sidebar line; unit: `app/src/main/claude-login.test.ts`; unit: `app/src/renderer/screens/SignIn.test.tsx`; ✓ (expected fail, BUG) claude says the sign-in worked but doctor cannot see it: the block says so instead of checking forever
- **Drive row**: demo, sandbox, checking, not configured (patch), off, connected (with or without account; last_synced null / valid / garbage; with or without last_error) and sidebar "Google Drive sync failed". Connect: waiting, success, and each error. Sync: each action, conflict → Keep this computer / Keep Drive / Not now, errors. Disconnect: cancel / confirm. — ✓ Connect waits for the browser, then syncs at once: this computer’s data goes to an empty Drive; unit: `app/src/renderer/screens/Connections.test.tsx`; ✓ opening the app syncs once: this computer’s data goes to an empty Drive, and the row says when; ✓ opening the app brings Drive’s data here, keeping this computer’s in backups/, and reads it again; ✓ opening the app replaces nothing: a line opens Settings, where the row asks which to keep; Not now puts it away; ✓ Keep this computer sends its data to Drive, replacing the copy there; ✓ Keep Drive brings Drive’s data here; this computer’s is kept in backups/; unit: `app/src/renderer/screens/Connections.test.tsx`; ✓ Disconnect asks first: Cancel keeps it; Disconnect sends the last changes, then forgets Drive and leaves the copy there; ✓ the sidebar says Google Drive sync failed and opens Settings, where the row says why
- **Phone row**: checking, error dead-end, not set up, not serving with devices, serving (lasting / not, paired or not), Disconnect (cancel / ok / error), Pair your phone. — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`; ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired; ✓ closed before the scan: Pair your phone brings the code back; Disconnect asks, then unpairs and stops; unit: `app/src/renderer/screens/PhoneSetup.test.tsx`
- **PhoneSetup**: how (Continue ok / each error / Cancel / Escape), pair (with or without the status line, the code made at once ok / error → Try again, expired → New code, paired → home), home (Done; lasting line absent / present). — unit: `app/src/renderer/screens/PhoneSetup.test.tsx`; ✓ Continue, the QR code at once, the phone scans it, Done: the row says it is paired; unit: `app/src/renderer/screens/PhoneSetup.test.tsx`; ✓ closed before the scan: Pair your phone brings the code back; Disconnect asks, then unpairs and stops
- **Data**: export cancel / exists / success (kB vs MB) / each Python error; import cancel / wrong extension / dialog cancel / success with or without backup and warnings / each Python error. — ✓ Export… writes an archive where the user says, and names it; unit: `tests/commands/test_archive_cli.py`; unit: `app/src/renderer/screens/DataMoves.test.tsx`; unit: `tests/commands/test_archive_cli.py`; ✓ Import… asks first; Cancel imports nothing; ✓ Import replaces the data and keeps what was here in backups/; ✓ Import… of something that is not an export is refused; nothing changes; unit: `app/src/main/archive-files.test.ts`; unit: `app/src/renderer/screens/DataMoves.test.tsx`
- **Theme**: system / light / dark, persistence, `data-theme` attribute. — unit: `app/src/renderer/theme.test.ts`; ✓ Dark turns the whole app dark and stays dark after a reload; Light turns it light
- **Where**: Drive unavailable in demo and sandbox. **The phone row is not guarded in the demo.** — ✓ Your data says where the data folder is; its path shows it; demo/sandbox: not tested (other windows)
- **Narrow**: no Sections nav, no sidebar problem lines on Settings. — ✓ Settings has no side nav and no sidebar lines; Matches says Claude is not signed in on top

---

## 10. Result shapes the renderer reads (to build a test world)

| Tool / channel | Args sent | Fields read |
|---|---|---|
| `doctor` | `{}` | `checks[]`: `name`, `status` (ok/missing/warn/drift), `required`, `detail`, `fix`, `details` (for `claude CLI`: `path`; for `claude login`: `loggedIn`, `authMethod`, `email`, `subscriptionType`, `doorConfigDir`; for `scraper: <s>`: `site`, `site_name`). `ok` is not read in Settings. Main's claude-login reads `details.path` and `details.doorConfigDir`. |
| `setup` (plan) | `{install:[...]}` | `plan[]`: `tool`, `commands` (array of strings or argv arrays), `note`. **`hint` is not read.** |
| `setup` (run) | `{install:[...], yes:true}` | `outcome` ('ok'/'incomplete'), `todo[]` |
| `status_summary` (App) | `{}` | `drive`: `connected` (must be boolean), `account`, `last_synced` (ISO), `last_error`, `configured` |
| `connect_drive` | `{}` | `account` |
| `sync_data` | `{}` / `{keep_local:true}` / `{keep_drive:true}` | `action` (push/pull/nothing/skipped); an error with `conflict:true` gives the conflict box |
| `disconnect_drive` | `{}` | nothing (`disconnected` is ignored) |
| `phone_status` | `{}` | `running`, `address`, `lasting`, `devices[]`: `device`, `paired_at` (`last_seen` is not read). `connection`, `web_built`, `tailscale_installed`, `port` and `started_at` are not read. |
| `phone_start` | `{connection:'cloudflare'}` | as `phone_status` (`address`, `lasting`, `devices`) |
| `pair_phone` | `{device}` | `device`, `qr_svg` (an SVG document string), `expires_at` (ISO) |
| `unpair_phone` | `{device}` | nothing |
| `phone_stop` | `{}` | nothing |
| `show_profile` (App) | `{}` | `config.email` (for SignIn), `config` null or not, `cv.exists` (sidebar CV line) |
| IPC `door:export-data` | none | `{ok:true, data:{path, files, bytes}}` / `{ok:false, canceled:true}` / `{ok:false, error}` |
| IPC `door:pick-archive` | none | `{token, name}` / `{canceled:true}` / `{error}` |
| IPC `door:import-data` | token | `{ok:true, data:{files, backup_dir, warnings[]}}` / `{ok:false, error}` |
| IPC `door:claude-login-state` and the pushed `door:claude-login` | none | `LoginState`: `{state:'idle'\|'starting'\|'done'\|'timeout'\|'cancelled'}`, `{state:'waiting', canOpen}`, `{state:'failed', message}` |
| IPC `door:claude-login-code` | code | `{ok, error?}` |
| IPC `door:info` (App) | none | `demo`, `sandbox` ('onboard'), `home`, `version`, `remote` |
