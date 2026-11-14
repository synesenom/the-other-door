# E2E inventory: the app shell and the job screens

Source read in full: `app/src/renderer/{App,Splash}.tsx`, `api.ts`, `screens/{Matches,MatchRow,ReadingPane,Posting,StatusDialog,ImportDialog,Materials,Applications,Finding,Hint,Dialog,AppName,Spinner,Switch}.tsx`, `screens/{board,prepare-store,statusNotice,problems}.ts`, `useNarrow.ts`, `main/{run-board,notices,notifier,ipc,foreign-run}.ts`, plus the Python cores behind the tools (`mcp_server.py`, `commands/{add,matches,prepare,revise,status}.py`, `core/{lock,selection,tracker}.py`).

Conventions used below:
- **btn "X"** = `getByRole('button', { name: 'X' })`. **radio "X"**, **switch "X"**, **dialog "X"** and so on work the same way.
- **status** = `role="status"`, **alert** = `role="alert"`.
- "named()" means a string containing "The other door" is split around an `<span class="app-name">`. `getByText` on the whole `<p>` still matches the full text.
- Narrow means `(max-width: 899px)` (`useNarrow`). CSS hides `.sidebar-foot` there: the Find button, "Last run" and the problem lines.
- How errors reach the renderer: the server returns `{"error": msg, candidates?, conflict?}`. `door-server.ts` turns that into a `DoorError`, `ipc.ts` wraps it in the envelope `{ok:false,error,candidates?,stopped?,conflict?}`, and `api.call` throws `ApiError(message)`. `errorText(e)` is `e.message`. Other main-side messages: `"stopped"` (stopped=true), `"The other door took too long to answer"` (timedOut; for find_jobs it is replaced by `"The run stopped: The other door heard nothing for 15 minutes."` and the child is killed), `"The other door's server stopped; try again"`, `"could not start the door server: …"`, `"unknown tool"`.
- Call timeouts (main side, idle and restarted by progress where there is any): import_posting 180 s, prepare 180 s (it reports every 30 s), revise 420 s, find_jobs 900 s idle. Every other tool in this area (show, list_matches, set_status, mark_seen, status_summary, show_profile, doctor 600 s) uses the server default.

---

## 0. App shell (`App.tsx`, `Splash.tsx`)

### Start-up gate
| Condition | What shows |
|---|---|
| Waiting for `window.door.info()` and then `show_profile` | **Splash**: `status` named "Starting The other door" (an SVG logo and an animated bar, nothing else) |
| `show_profile` → `config === null` and `info.remote` | (phone only) h1 "Set up The other door first" and the body "The other door has no profile yet. Set it up on the computer where it is installed (open the desktop app there, or run its setup), then come back here." |
| `config === null` and (not demo, or `sandbox === 'onboard'`) | The onboarding Wizard (outside this area) |
| `config === null` in the demo | The shell (the demo never gets the wizard) |
| `show_profile` throws (server dead, version mismatch, …) | The shell. Its screens then show their own errors. |
| Otherwise | The shell |

Calls at start: `info` IPC, then `show_profile` {}. Once the shell is up: `status_summary` {}, re-run on every `refreshKey` bump, and `doctor` {}, skipped when remote.

`document.title`: "The other door"; "The other door (demo)" in the demo; "The other door (onboarding sandbox)" when `info.sandbox==='onboard'`.

### Sidebar (`aside` = role complementary). Hidden entirely when narrow and a posting is pushed.
- **Demo tag** (only when `info.demo`): `role=note`, aria-label "Demo data" with text "Demo" and title "Made-up jobs (app/.demo). Nothing here changes your real data or Drive.". In the onboarding sandbox: aria-label "Onboarding sandbox", text "Sandbox", title "Onboarding sandbox (app/.onboard). Nothing here changes your real data or Drive.".
- **nav "Main"**, buttons **"Matches"**, **"Applications"**, **"Profile"**, **"Settings"**. The phone (remote) has no Profile. The current one has `aria-current="page"`, but only while Finding jobs is not on screen. Clicking one sets current and leaves Finding (`finding=false`). Narrow adds a `.tab-dash` span to the current tab (aria-hidden). TabIcon SVGs are aria-hidden, so each name is just the word. — ✓ the nav goes to Applications and back to Matches, which reads the list again; ✓ lists the matches best first… (Matches current)
- **btn "Find new jobs" / "Finding jobs…"** (sidebar-foot; hidden by CSS when narrow): — ✓ Find new jobs runs the five steps against the boards, scores the new ads and sums the run up
  - Text is "Finding jobs…" when `own` (this window's run is running, or the board says active and own) or `foreign` (board active and not own). Otherwise "Find new jobs". — ✓ Find new jobs runs the five steps…; ✓ a run started in a terminal: the window jumps to Finding jobs…
  - Disabled when `foreign`, or `own && finding` (already on the Finding screen), or `!own && preparingNow` (a Prepare is running in this window). Only in that last case does it carry the title `"Preparing an application. Find new jobs again when it is done."`. — ✓ Find new jobs runs the five steps… (own on Finding); ✓ a run started in a terminal… (foreign); ✓ a Prepare in progress turns Find new jobs off until it is done
  - Click when own: shows Finding (no call). Otherwise: `startRun()` → `find_jobs` {} with progress (see §1). — unit: `app/src/renderer/App.test.tsx`; ✓ a second run reads the boards again and scores nothing twice
- **"Last run <Mon D, HH:MM>"** (`p.small.muted`). Shown when `status_summary.since_last_review.last_run.finished_at` parses as a date. Missing or unparsable: no line. `status_summary` failing: no line, silently. — unit: `app/src/renderer/App.test.tsx`; ✓ Find new jobs runs the five steps… (updated after a run); not tested: status_summary failing (the caption is silent; Matches area)
- **group "Needs you"** (`problems()`). One button per problem; on the phone they are plain `<p>`s:
  - "Claude is not installed": doctor's `claude CLI` check is not `ok` → Settings. — unit: `app/src/renderer/screens/problems.test.ts` (matches)
  - "Claude is not signed in": the `claude login` check failed, or a logged-in API key → Settings. — unit: `app/src/renderer/App.test.tsx` (matches)
  - "Claude's usage limit is reached, resets 15:30" / "Room for about N more applications this window, resets 15:30": `status_summary.plan` (`status: rejected`; or room for 3 prepares or fewer, or a `warning`; none once the window's reset has passed) → opens nothing, a `<p>` on desktop too; read on opening, after a run and after a Prepare, and once at the reset time. Also on the phone. — unit: `app/src/renderer/screens/problems.test.ts`, `app/src/renderer/App.test.tsx`, `app/src/preview/preview.test.tsx`
  - "You have no CV yet": `show_profile.cv.exists === false`, only with a config and never in the demo → Profile on its CV view. — unit: `app/src/renderer/App.test.tsx` (matches)
  - "Google Drive sync failed": `status_summary.drive.connected && last_error` → Settings. — unit: `app/src/renderer/App.test.tsx` (matches)
  - "Something keeps going wrong. Send a report": `status_summary.recurring_problem` (`door.core.recurring`: the same site failed in each of its last 3 runs, ads left unscored in each of the last 2 runs, the server stopped or would not start in the last 7 days, or the same tool failed 3 times in 24 hours; only what came after the last saved report) → Settings scrolled to Report a problem. Saving a report reads `status_summary` again and the line goes; it goes by itself once the failure stops. A one-off failure: no line. Not on the phone. — ✓ a board that failed in each of the last three runs: the line opens Report a problem, and a saved report takes it away (report.journey.ts); unit: `tests/core/test_recurring_unit.py` (and goes once a run scores them); ✓ a board that failed in one run is said nowhere; the phone: App.test.tsx; the server and tool conditions: tests/core/test_recurring_unit.py
  - doctor failing → `{ok:false,checks:[]}` → claudeRow "unknown" → **no** Claude line. A doctor that has not answered yet → no line either. — ✓ a home with nothing wrong has no Needs you lines (doctor answered); not tested: doctor failing (would need the doctor tool faulted at start-up; Settings area)
  - Note: the e2e stand-in claude answers `auth status` with loggedIn false, so expect "Claude is not signed in" in every e2e home unless `claude-signed-in` exists. — (the journeys world is signed in by default; signedIn:false gives the line)
- Narrow: the same "Needs you" group sits on top of Matches (`.narrow-top`), only while nothing is pushed. — unit: `app/src/renderer/App.test.tsx`

### Run board (`run-board.ts` → the `door:run-board` push and `runBoard()`)
- The board is `{active:false}`, or `{active:true, own, started_at, purpose, message, steps[]}`. It is active only while the pid in `jobs/.lock.json` is alive and `jobs/.progress.json` parses as an object. `own` means the pid is the app's own server child. Steps are filtered to objects with string `name` and `status`. Updates come from a file watch (100 ms debounce) plus a 1 s poll, and are sent only when changed.
- **A foreign run starting** (active and !own) → App calls `setFinding(true)`: the window **jumps to Finding jobs**, read only. **When it ends** → Finding closes and `refreshKey++` (Matches reloads, as does the Last run caption). — ✓ a run started in a terminal: the window jumps to Finding jobs, read only, and comes back when it ends; unit: `app/src/renderer/App.test.tsx`
- Test lever: a world can write `jobs/.lock.json` `{pid: <a live pid>, started_at, purpose:"run"}` and `.progress.json` `{message, steps:[…]}` to fake a foreign run **without** blocking the server. `lock_holder` and `ledger_lock` check an OS lock on `jobs/.lock`, not the json. To also make the server refuse, a helper has to hold the real `ledger_lock` (purpose "run" gives "a run is in progress (started HH:MM, pid N); try again when it has finished"). — used: helpers/finding.ts holdLedgerLock (the real lock from a child Python)

### Notification clicks (`onOpen`, channel `door:open`)
These only reach the window as IPC. They can be faked with `app.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].webContents.send('door:open', target))`.
- `{screen:'matches', newOnly?}` → Matches. New only is on iff `newOnly===true`; Matches is remounted. — ✓ "New jobs found" opens Matches on New only
- `{screen:'finding'}` → `setFinding(true)`. It only shows something if there is a run state or a foreign run; otherwise the current screen stays. — unit: `app/src/renderer/App.test.tsx`
- `{screen:'materials'|'posting', jobId:string, inPlay, document?}` → Applications if `inPlay`, else Matches. That screen opens the job pushed, on the materials or posting view. `document` picks the CV or the letter (default letter). The job need not be in the list. — unit: `app/src/renderer/App.test.tsx`; ✓ "Application ready" opens the materials on the document it names; unit: `app/src/renderer/App.test.tsx`
- Any target that is not an object, or a materials/posting target without a string jobId → ignored. — unit: `app/src/renderer/App.test.tsx`

### Notifications (`notices.ts` and `notifier.ts`; shown only while the window is **not focused**, deduped for 5 s)
| Event | Title / body | Click target |
|---|---|---|
| find_jobs ok, N>0 new | "New jobs found" / "N new match(es)" | matches newOnly | — not tested: OS notifications are shown only while the window is unfocused and are outside the journeys (README)
| find_jobs ok, 0 new | "No new matches" / "Nothing new this time" | finding | — not tested: OS notification
| prepare outcome prepared or skipped | "Application ready" / "<title> · <company>: the CV and letter are ready to send." (plain "The CV and letter are ready to send." when `show` fails) | materials, inPlay true |
| prepare outcome failed or no_matches | (none) | |
| revise revised, compile ok | "Revision done" / "…: the CV is updated." or "the letter is updated." | materials, document by file |
| revise revised with a compile error | "The PDF could not be rebuilt" / "Undo last change puts it back." | materials |
| revise undone | (none) | |
| import_posting **by url only** | "Ad imported" / "…: scored 0.72" or "…: not scored yet" (plain "Scored 0.72" / "Not scored yet") | posting |
| find_jobs error, timed out | "The search stopped" / "The other door heard nothing for 15 minutes. Nothing is lost; run it again." | finding | — not tested: OS notification (and a 15-minute idle wait)
| find_jobs error, other | "The search didn't finish" / first line of the error (max 200 chars) | finding | — not tested: OS notification
| prepare error | "Preparing didn't finish" / "<title> · <company>: <first line>" | posting, or matches when there is no job id |
| an error that is stopped, or matches `/is in progress\|another long-running tool/` | (none) | |
| foreign run ended | "A run finished" / "N new match(es)" when the summary's last_run started at or after it, else "Open The other door to see what it found." | matches newOnly | — not tested: OS notification

---

## 1. Run lifecycle (`App.startRun`, `api.findJobs`) and the Finding jobs screen (`Finding.tsx`)

### startRun(skip?)
1. Sets the run to `{kind:'running', startedAt: now}` and shows Finding.
2. Calls `find_jobs`: `{}`, or `{skip}` on the first run after the wizard (`['discover','follow','collect']`). Always with progress. — ✓ Find new jobs runs the five steps… ({} args); the first run after the wizard ({skip}) is the onboarding area
3. Outcome mapping in `findJobs`. Each branch depends on the error's wording:
   - **ok** → `{kind:'summary', record}`, refreshKey++. — ✓ Find new jobs runs the five steps…
   - **ApiError.stopped** (Stop pressed; main kills the child; message "stopped") → run null, Finding closed, refreshKey++. The user lands back where they were. No message. — ✓ Stop ends the run: back on Matches, no run record, the ads it found kept for the next run
   - **error text matches `/another long-running tool/`** → `preparing`: run null, Finding closed, no message. Server text: "another long-running tool (find_jobs or prepare) is already in progress; wait for it to finish before calling again". It only happens when a Prepare runs in the same server; the button is normally disabled then, so this is a race. — not tested: only a race (Find new jobs is off while a Prepare runs: ✓ a Prepare in progress turns Find new jobs off until it is done)
   - **error matches `/is in progress/`** → `busy`: run null, then `runBoard()` is re-read. If the board shows a foreign run, Finding shows it read only. Otherwise `showFinding` is false and the current screen shows. Server text: "a run is in progress (started HH:MM, pid N); try again when it has finished". — not tested: only a race (with a run elsewhere on the board the button is off; a lock-holder has written .progress.json before the user can click)
   - **any other error** → `{kind:'error', message}`. Examples: — ✓ find_jobs answering an error: the alert says why, nothing is written, and Find new jobs runs again
     - ConfigError "Your CV is still the example (Jane Doe's). Add your own CV first."
     - a lock held for a non-run purpose: "another process of The other door is writing the ledgers (<purpose>) (started …, pid …); try again in a moment". This does NOT match the busy regex. — ✓ another process writing the ledgers: the alert names it, and the run works once it is done
     - "The run stopped: The other door heard nothing for 15 minutes." — not tested: needs 15 minutes without progress
     - "The other door's server stopped; try again" — ✓ the server dying during the run: the alert says it stopped, and the next run starts a new one
4. The Matches `finding` prop is 'own' while own, 'elsewhere' while foreign. — ✓ narrow: the pill on Matches starts the run…; unit: `app/src/renderer/screens/Matches.test.tsx`

### Finding screen: visible when `finding && (findingState !== null || foreign)`
`findingState` = `{kind:'running'}` when the board is active and own but this window's run is not running (e.g. after a renderer reload); otherwise it is this window's run state.

- **h1 "Finding jobs"**
- **btn "Stop"** (title "Nothing is lost: the next run picks up where this one stopped."). Shown when running and not a foreign run. Click → the label becomes **"Stopping…"** and the button is disabled. It calls the IPC `stopRun`: the demo `demo.stop()`, or `server.stop()` when a find_jobs call is in flight; with none in flight it does nothing. "Stopping…" sticks until Finding unmounts, so if nothing is in flight it never ends. — ✓ Stop ends the run… ("Stopping…" is not asserted: the call ends at once and Finding unmounts; it sticks only with no find_jobs in flight, which a user reaches only after a renderer reload — not tested)
- Subtitle:
  - Foreign: `status` "A run started elsewhere is in progress (started HH:MM)". The "(started …)" part is dropped when `started_at` is empty. — ✓ a run started in a terminal… ("(started 10:30 AM)"); unit: `app/src/renderer/screens/Finding.test.tsx`
  - Own: "Started HH:MM · you can switch screens while it runs; quitting The other door stops it." The "Started … · " part is dropped when there is no startedAt. startedAt is the board's `started_at` when active, else the window's own start time. `clock()` falls back to the raw string when it cannot parse it. — ✓ Find new jobs runs the five steps… (with Started); the no-startedAt and unparsable forms cannot be reached by a user
- **list "Steps"** (`ol`): 5 `li`. Without an active board, or with empty steps: five waiting rows, Search, Discover, Follow, Collect, Match. — ✓ Find new jobs runs the five steps…; ✓ a run started in a terminal…
  - Each row has an **h2** with the step title ("Search", "Discover", "Follow", "Collect", "Match"; an unknown name is shown raw). Its mark is a check SVG (`.check-mark`) when done, else the index 1–5.
  - **waiting**: a muted line beside the title: — ✓ a run started in a terminal… (Collect, Match waiting lines)
    - Search: "Reads the job boards for your country"
    - Discover: "Finds employers hiring for your keywords"
    - Follow: "Finds those employers' career pages"
    - Collect: "Reads the career pages you follow"
    - Match: "Scores the new ads against your CV"
  - **skipped**: "Skipped" when every `; `-separated reason matches `^\w+_discovery not chosen$`. "Skipped: left out of this run" when the reason is `--skip` or empty. Otherwise "Skipped: <reason>". No time. — ✓ the sources never chosen are said under Discover… ("Skipped"); ✓ Find new jobs runs the five steps… ("Skipped: <reason>"); "left out of this run" is the first run after the wizard: onboarding area
  - **running**, detail = `runningLine`: — ✓ a run started in a terminal… ("1 of 4 candidates"); discover's requests lines not tested: the world has no LinkedIn stand-in
    - If `requests` (discover): "Reading job pages on <running item name>" when `request` starts with "job page", else "Searching <name>". Empty when no item is running.
    - Else the parts joined by " · ": "Reading <hosts[0]>"; `request`, or else `phase`. When the step has no items it adds "D of T <unit>" (total>0) or "D <unit>" (done>0). Units: search boards, follow candidates, collect employers, match scored; discover has none.
  - **done / failed**: `step.detail` verbatim (failed has no distinct mark beyond the number and CSS class `step-failed`). — ✓ Find new jobs runs the five steps… (done details); a failed step not tested: no world fault makes a whole step fail (a failing board leaves Search done)
  - **progressbar** "<Title> progress" (aria-valuenow = round(done/total·100)): only while running, with no items, and total>0. — ✓ a run started in a terminal… (Follow progress 25)
  - **list "<Title> sources"**: while running and some item is not done. Items are names with ` · <sites[id]>` counts and marks: done ✓, failed ✗, else blank. — not tested: the world's boards answer at once, so Search's sources list is never on screen long enough to be seen deterministically
  - **Unchosen discovery sources**: under the Discover row whenever its status is not waiting (running, done, skipped or failed), from `show_profile.discovery_unchosen` (not in the demo or remote). Each reads "<label> (not enabled, enable)" with **btn "Enable <label>"** → leaves Finding and opens Profile on its employers section. — ✓ the sources never chosen are said under Discover, and Enable opens Profile on Employers; unit: `app/src/renderer/screens/Finding.test.tsx`
  - `.step-sites`: "site N" spans for `sites` entries not listed as items, while running. — not tested: same as the sources list (boards answer at once)
  - Time on the right: "N s" / "N min" for running (live, 1 s tick), done and failed; it needs `started_at` (and `finished_at`). — ✓ (shown in finding-running / finding-elsewhere: the world's step times are real wall-clock, so they read "0 s")
- **Summary** (state summary and not watching), region **"Run summary"**:
  - h2 "No new matches" / "1 new match" / "N new matches" from `new_above_threshold.length`. — ✓ Find new jobs runs the five steps… (renders); ✗ BUG: the summary counts the new matches of this run and lists only them; ✗ BUG: a second run that found nothing new says No new matches
  - A list of `top` with title, company and a score with 2 decimals (omitted when `top` is empty). — ✓ Find new jobs runs the five steps…
  - "Took N s" / "Took N min" from `elapsed_s`. — ✓ Find new jobs runs the five steps…
  - **btn "View matches"** → Matches with **New only on** (remounted), refreshKey++. — ✓ View matches opens Matches on New only, with the ads the run found
  - **btn "Show run record"** → IPC `showRun(started_at)` → shows `jobs/runs/<started_at with [^A-Za-z0-9_-]→->.json` in the OS file manager. Failure ("that run record is not on disk") is silently ignored. Likely untestable beyond "no error". — unit: `app/src/renderer/screens/Finding.test.tsx`
  - **Not shown**: `failures`, per-site outcomes, `match.failed`, `skipped`. A run with failed sites looks the same as a clean one. — ✗ BUG: the summary says which board could not be read; ✗ BUG: the summary says the new ads could not be scored (disk: ✓ a board that fails…; ✓ scoring that fails…)
- **Error state** (not running, state error): **alert** "The other door could not start the run: <message>" and **btn "Find new jobs"** (primary) → startRun(). — ✓ find_jobs answering an error…; ✓ the server dying during the run…
- The idle "Find new jobs" button with no error is unreachable: the screen is hidden when the state is null. — not tested: unreachable
- While a summary is shown and a foreign run starts: the watching view replaces it. — unit: `app/src/renderer/App.test.tsx`
- Leaving Finding through the nav keeps the run going. The sidebar button then reads "Finding jobs…" and is enabled; it returns to Finding. — unit: `app/src/renderer/App.test.tsx`

---

## 2. Matches (`Matches.tsx`, `MatchRow.tsx`)

### Calls
- On mount and on every `tick`: `list_matches` with `{}`. The list is cleared first, so "Loading…" shows again on every refresh. New only calls nothing: it filters the list the window has. — ✓ New only lists only the new matches, and off again lists them all; unit: `app/src/renderer/screens/Matches.test.tsx`
- On mount and every tick: `status_summary` (shared in flight with the App's call). — unit: `app/src/renderer/screens/Matches.test.tsx`
- `mark_seen {job_id}` for each new match opened. Failures (e.g. the ledger lock is held during a run) stay queued and are re-sent on each later list load. Silent. — ✓ opens it full width, marks it seen, and back keeps the row marked; unit: `app/src/renderer/screens/Matches.test.tsx`; ✓ (expected fail) a match opened while another process runs is recorded as seen once the run ends — BUG: Matches is remounted when the run ends and forgets the refused id, so the match is new again

### List view
- **h1 "Matches"**, no subtitle: a new match is its blue dot. — ✓ lists the matches best first…
- **btn "Add a job"** → ImportDialog (§7). — unit: `app/src/renderer/screens/ImportDialog.test.tsx`
- Narrow only, when the App passes onFindJobs (always): **btn "Find new jobs" / "Finding jobs…"** (pill). Disabled when `finding==='elsewhere'` or `preparing`; title PREPARING_TIP only when preparing. "Finding jobs…" text whenever `finding` is set. Click: own → Finding; else startRun. — ✓ Matches has its own "Find new jobs"…; unit: `app/src/renderer/screens/Matches.test.tsx`
- **Spinner** (`status`) with `status_summary.in_progress.message`. This is read once per tick, not live. — unit: `app/src/renderer/screens/Matches.test.tsx`
- **switch "New only"** (aria-checked). Toggle → the rows that were new when it turned on (or the list was last read); a match opened under it stays listed without its dot until then. — ✓ New only lists only the new matches, and off again lists them all
- `p.notice.small` "Could not read the run summary: <err>" when `status_summary` failed. It has no role. — unit: `app/src/renderer/screens/Matches.test.tsx`
- **status "Loading…"** while `matches===null` and there is no error. — unit: `app/src/renderer/screens/Matches.test.tsx`
- **alert** <list_matches error> (named). E.g. an invalid config surfaces here. — ✓ a list that cannot be read says why, and reads again once it can
- Empty and no error: "Nothing scored yet, run The other door first". This also shows with **New only on and nothing new** (same copy), which is misleading. — unit: `app/src/renderer/screens/Matches.test.tsx`; ✓ (expected fail) New only with every new match seen says there is nothing new, not that nothing was scored — BUG
- `ul.rows` (role list). Each `li` holds **one button** (`.row`, `aria-current="true"|"false"`). Its accessible name is the concatenation of: — ✓ lists the matches best first, each with its title, English title, company, place and score
  - the new-dot `img` "New since your last review", when `is_new` — ✓ lists the matches best first…
  - the title
  - `title_en`, when present and different from the title — ✓ lists the matches best first… (Fjordpension row)
  - "company · location", or the company alone when location is empty — ✓ lists the matches best first… (company · location); the company alone: not tested in a row (every ad has a place; the posting's meta line covers it)
  - the status word, when the status is not unapplied — not tested: unreachable (§10.1)
  - the score with 2 decimals, or '' when null — ✓ lists the matches best first… (2 decimals); null: unreachable (§10.1)
- Row click → saves the scroll position, selects the row, view posting, clears the notice, pushes (full-width posting). If the row `is_new`: it is marked seen locally (dot gone, count drops) and `mark_seen` is sent. Writes `jobs/last_review.json` `seen`. — ✓ opens it full width, marks it seen, and back keeps the row marked
- Back from the pushed posting restores the list's scroll and keeps the row marked (aria-current true). — ✓ the list keeps its scroll position when a posting deep in it closes; ✓ opens it full width… (aria-current)
- **Notice lines** (after a status change; shown in the list or the pushed view):
  - `status` with `statusNotice(current ?? status, title_en || title || 'the job')` — ✓ Discard records the reason and opens the next match in its place; ✓ (expected fail) the notice names a job that is not in the list — BUG: "the job"
  - `<warning>` as a plain `p.notice` (no role) — unit: `app/src/renderer/screens/Matches.test.tsx`

### Pushed view (a row selected and pushed, or view === materials)
- Posting view only:
  - **btn "← Matches"** (title "Esc") → unpush. The selection stays. — ✓ opens it full width, marks it seen, and back keeps the row marked
  - **group "Previous and next match"**: shown when the selected job is in the list and the list has more than 1 entry. It holds the text "i of N", **btn "Previous match"** (title "Previous match (k)", disabled at the first) and **btn "Next match"** (title "Next match (j)", disabled at the last). A step clears the notice and selects the neighbour. A new neighbour is marked seen when `is_new`. — ✓ Next and Previous step through the list, and stop at its ends; hidden: unit: `app/src/renderer/screens/Matches.test.tsx` (1 match), unit: `app/src/renderer/App.test.tsx`
- **Keys** (window listener, only while pushed on the posting view):
  - `j` next, `k` previous, `Escape` back. — unit: `app/src/renderer/screens/Matches.test.tsx`
  - Ignored with Meta, Ctrl or Alt, or when the target is inside `input, textarea, select, [contenteditable], dialog`. Note: the app's dialogs are `div[role=dialog]`, **not** `<dialog>`. So `j`/`k` pressed while focus is on a dialog **button** (Cancel/Save) steps the posting behind it; the dialog unmounts with the posting (the key is jobId). Escape inside a Dialog is stopped by the Dialog's handler. Escape on the "Why this score" hint button closes the hint **and** goes back to the list (the hint does not stop propagation). — unit: `app/src/renderer/screens/Matches.test.tsx`; ✓ (expected fail) j pressed on a dialog’s button leaves the posting behind it alone — BUG; ✓ (expected fail) Esc on the score’s hint closes the hint and stays on the posting — BUG
- The stepper hides while the list reloads (`at=-1` until loaded) and for a job not in the list: an imported ad, a job just prepared, a notification-opened job. — unit: `app/src/renderer/App.test.tsx`; ✓ Open shows the imported ad, kept open though the list does not hold it; unit: `app/src/renderer/App.test.tsx`
- `ReadingPane`: Posting (§3) or Materials (§5) for the selected job id.

### Selection rules after a reload
- If the selected id is still in the list, or is the `opened` id (an imported or notification-opened job, or one switched to materials), it stays. — ✓ Open shows the imported ad, kept open…; unit: `app/src/renderer/App.test.tsx`
- Otherwise the row now at the same index is selected, clamped to the last row. If the list became empty → null, and the pushed view collapses into the list view. — ✓ Discard records the reason and opens the next match in its place (same index); unit: `app/src/renderer/screens/Matches.test.tsx`

### Status change (`changed`)
- The notice uses the row's `title_en || title`. If the job is not in the list (a prepared job, an imported ad, a notification-opened job) it uses the literal **"the job"**, e.g. "Applied: the job. It is in Applications now." — ✓ Applied through "Company site" records how it was sent (title_en); ✓ the notice names a job that is not in the list
- **discarded** → it stays pushed; the job leaves the list on refresh and the **next match opens in its place**, with the notice above it ("Not for me: <title>."). — ✓ Discard records the reason and opens the next match in its place; unit: `app/src/renderer/screens/StatusDialog.test.tsx`
- Any other status → back to the list view, with the notice. — ✓ Prepared moves the job to Applications…; unit: `app/src/renderer/screens/Matches.test.tsx`
- The Materials "I've applied" path goes through the same `changed`.

### Switching to materials (`switchView('materials')`)
`opened = selected` and a refresh. The job leaves the list once prepared but stays open.

### Opening (a notification) → see §0. It sets `opened`, the view, initialDoc and pushed, then refreshes.

---

## 3. Posting (`Posting.tsx`), inside Matches or Applications

### Calls
- `show {job_id}` on mount, after a status change (`version++`), and again when the job id changes. — ✓ a Danish ad: … (show on mount); unit: `app/src/renderer/screens/Posting.test.tsx` (again on a step)
- While `watching`: `show {job_id}` every 5 s. 'adopted' is set when a Prepare for this job is already in the module-level `preparing` map at mount; 'busy' is set after an in-progress refusal.
- Prepare: `prepare {job_id}` or `{job_id, force:true}`, with progress. — ✓ Prepare application on a new match tailors, compiles and opens Ready to send; ✓ Prepare again replaces the application with a new one

### States
- **alert** <show error> (named). E.g. "no posting found for job_id 'x'". An ambiguous ref has candidates, but the renderer ignores them and shows only the message. — unit: `app/src/renderer/screens/Posting.test.tsx`
- `p.muted` "Loading" (no ellipsis, no role) until `show` answers. — unit: `app/src/renderer/screens/Posting.test.tsx`
- The article:
  - **h2** `title` (class display-l). — ✓ a Danish ad: its title in English, where and when…
  - `title_en` as a muted p, when present and different from the title. — ✓ a Danish ad: its title in English…
  - Meta line: "Company · Location · posted <Mon D> · via <source_name>". Each part is dropped when missing, and an unparsable `posted_at` is dropped. — ✓ a Danish ad… (all parts); unit: `app/src/renderer/screens/Posting.test.tsx`
  - Score line, when the score is a number or `score_reason` is set: — unit: `app/src/renderer/screens/Posting.test.tsx`
    - `p.score-l` "0.72" (absent when the score is null) — ✓ a Danish ad…; unit: `app/src/renderer/screens/Posting.test.tsx`
    - **btn "Why this score"** (Hint). Hover or focus → **tooltip** with `score_reason`; Escape or blur hides it; the mouse-leave grace is 200 ms. — unit: `app/src/renderer/screens/Hint.test.tsx`; Escape: ✓ (expected fail) Esc on the score’s hint… — BUG
  - While running (`preparing.get(jobId)`): — ✓ while Prepare runs: the progress line, the elapsed time, locked actions and no Find new jobs
    - **status** spinner with the message: "Preparing…" first, then each progress message, e.g. "tailoring <label>", "verifying outputs…", "top match…" — ✓ while Prepare runs: the progress line, the elapsed time, locked actions and no Find new jobs (in this world the heartbeat reads "tailoring <title> — <company> · 0m03s elapsed")
    - "Elapsed m:ss" (1 s tick) — ✓ while Prepare runs: the progress line, the elapsed time, locked actions and no Find new jobs
    - "You can leave this open; it takes a few minutes." — ✓ while Prepare runs: the progress line, the elapsed time, locked actions and no Find new jobs
  - **status** "Another run is in progress. Try again when it finishes." (busyNotice). — unit: `app/src/renderer/screens/Posting.test.tsx`
  - **alert** <prepareError>. — ✓ a failing tailor: Prepare says what went wrong and the job stays unprepared; a server refusal: unit: `app/src/renderer/screens/Posting.test.tsx`
  - Action row (wide). Order: primary, Open, Status, Prepare again, Not for me.
    - **Primary** (none while running): — ✓ while Prepare runs: the progress line, the elapsed time, locked actions and no Find new jobs
      - materials exist → **btn "See the application"**, or **"See what you sent"** when `materials.sent` → view materials. — ✓ a prepared card opens its application and comes back through its posting; ✓ What you sent: the copy kept when it went out, read only, and saved from there
      - else status in [unapplied, prepared] → **btn "Prepare application"** → startPrepare(false). — ✓ Prepare application on a new match tailors, compiles and opens Ready to send
      - else none. — unit: `app/src/renderer/screens/Applications.test.tsx`
    - **Open**: **btn "Apply on <host>"** when `apply_url` is http(s), differs from `url`, and parses (`www.` is stripped from the host). Otherwise **btn "Open in browser"** when `url` exists. Absent with neither, or with only a non-http apply_url and no url. Disabled while preparing. Click → IPC openExternal(url) in the OS browser; a refused non-http URL is silent. — ✓ a separate application page: "Apply on <host>" opens it in the browser; unit: `app/src/renderer/screens/Posting.test.tsx`; disabled while preparing: Prepare area
    - **btn "Status"**: disabled while preparing → StatusDialog (full). — ✓ while Prepare runs: the progress line, the elapsed time, locked actions and no Find new jobs; ✓ opens on the current status, with every status to choose from
    - **btn "Prepare again"** (quiet): materials exist, status in [unapplied, prepared], not running → confirm dialog. — ✓ Prepare again asks first; Cancel and Escape leave the application as it is; ✓ What you sent: … (absent for a sent job)
    - **btn "Not for me"** (quiet): only when there are **no materials**. Disabled while preparing → StatusDialog preset discarded. — ✓ a prepared card opens its application and comes back through its posting (absent with materials); ✓ while Prepare runs: … (disabled); unit: `app/src/renderer/screens/StatusDialog.test.tsx`; unit: `app/src/renderer/screens/Posting.test.tsx`
  - **list "Why it fits"** (✓ marks) / **list "Gaps"** (✗ marks) from `matching_skills` / `missing_skills`, each only when non-empty. — ✓ a Danish ad…; unit: `app/src/renderer/screens/Posting.test.tsx`
  - Language line, when `language` is set: `Intl.DisplayNames('en')` name of the code, plus " — required" or " — an advantage" by `language_requirement`. "none" or null gives the name alone; an unknown code stays raw. — ✓ a Danish ad… (name alone); unit: `app/src/renderer/screens/Posting.test.tsx`; an unknown code: not tested (the server keeps only supported languages)
  - `description` paragraph (pre-wrapped text). — ✓ a Danish ad…
  - Narrow: no action row. Instead an `.action-bar` at the bottom: **Status**, **Not for me** (secondary, no materials only), **Prepare again**, **Open**, **primary**. The Open button is styled primary when there is no primary and nothing running. — unit: `app/src/renderer/screens/Applications.test.tsx` (the Open-as-primary styling is not tested); unit: `app/src/renderer/screens/Posting.test.tsx` (the ink is styling: not tested)
- **dialog "Prepare again?"**: "This replaces the tailored CV and letter, and any revisions." — ✓ Prepare again asks first; Cancel and Escape leave the application as it is
  - **btn "Cancel"** — ✓ Prepare again asks first; Cancel and Escape leave the application as it is
  - **btn "Prepare again"** → `prepare {job_id, force:true}` — ✓ Prepare again replaces the application with a new one
  - Scope it to the dialog: the page has a second "Prepare again".
  - Escape closes it. — ✓ Prepare again asks first; Cancel and Escape leave the application as it is

### startPrepare outcomes
- Start: the module map `preparing.set(jobId)`, so the App sidebar's Find button turns disabled with PREPARING_TIP, as does the narrow pill. The action buttons lock and the primary is hidden. — ✓ while Prepare runs: the progress line, the elapsed time, locked actions and no Find new jobs (the narrow pill: not tested here, §2's)
- **The call resolves (any `outcome`)** → `onOpenMaterials()`: the view switches to Materials. **The renderer never reads `outcome` or `error`.** So: — WRONG: door-server.ts turns any result carrying `error` into a thrown DoorError, so a `failed` outcome (which always carries `error`) throws and is shown as the posting's alert; only `prepared`/`skipped` resolve. ✓ Prepare application on a new match tailors, compiles and opens Ready to send
  - `prepared` / `skipped` → Materials with pages. Ledger `jobs/applications.json` → `prepared`; `jobs/output/<id>/` gets cv.tex, cover_letter.tex, cv.pdf, cover_letter.pdf, facts.json and PNGs. — ✓ Prepare application on a new match tailors, compiles and opens Ready to send (`skipped`: not tested: the posting offers Prepare only when there are no complete materials, so only a race reaches it)
  - **`failed`** → Materials says "There is nothing prepared for this job yet." when there were no materials before, or shows the **old** materials on a force re-prepare. Nothing tells the user what failed. Causes: — WRONG, see above: the error is shown as an alert on the posting, the view stays; ✓ a failing tailor: Prepare says what went wrong and the job stays unprepared; unit: `app/src/renderer/screens/Posting.test.tsx`
    - the tailor failed: the e2e stand-in claude exits 97, giving "tailor step failed for 'x': …; status left unchanged." — ✓ a failing tailor: Prepare says what went wrong and the job stays unprepared; unit: `tests/commands/test_prepare_cli.py`
    - the example CV: "Your CV is still the example (Jane Doe's). Add your own CV first." — unit: `tests/commands/test_prepare_cli.py`
    - claude not installed — unit: `tests/commands/test_prepare_cli.py`
    - **the ledger lock held by another process** ("a run is in progress …"): prepare returns failed, it does not throw — unit: `app/src/renderer/screens/Posting.test.tsx` (an alert: "another process of The other door is writing the ledgers (find) (started HH:MM, pid N); try again in a moment", not the busy notice)
    - missing outputs — unit: `tests/commands/test_prepare_cli.py`
    - "materials are ready but the status could not be recorded" — not tested: only a race (a lock taken between the tailor's end and the ledger write) or a ledger the user cannot reach from the posting
  - `no_matches` is unreachable here (a job_id is always passed). — not tested: unreachable (a job_id is always passed)
- **Throws, text matches `/in progress/i`** → busy notice plus 'busy' polling (every 5 s until `show` returns materials). The server's only thrown variant is `_BUSY` ("another long-running tool (find_jobs or prepare) is already in progress…"). Reachable by: — unit: `app/src/renderer/screens/Posting.test.tsx`
  - a Prepare on job B while job A's Prepare runs (the buttons on another job are not locked) — unit: `app/src/renderer/screens/Posting.test.tsx`
  - a Prepare while **this window's own find_jobs** runs (Prepare is not disabled during a run) — not tested here: the same _BUSY branch as above; a run is §1's
  - Polling for B never finds materials, so it polls until the pane unmounts. — unit: `app/src/renderer/screens/Posting.test.tsx` (the notice stays; Prepare application stays offered)
- **Throws otherwise** → **alert** with the text: — unit: `app/src/renderer/screens/Posting.test.tsx`
  - "no posting found for job_id …" — unit: `app/src/renderer/screens/Posting.test.tsx`
  - "The other door took too long to answer" (main timeout 180 s with no progress; prepare reports every 30 s) — not tested: 180 s with no progress, and Prepare reports a heartbeat (every 1 s in the world, 30 s for real), so a live Prepare never times out
  - "The other door's server stopped; try again" — ✓ the server dying during Prepare says so, and the next Prepare works
  - "stopped": Stop pressed during a run kills the server child, which also kills an in-flight Prepare. The text is literally "stopped". — not tested: unreachable: a run and a Prepare never overlap in one server (the second gets _BUSY), so Stop never kills a Prepare
- Finally: `preparing.delete`, so the sidebar Find button is enabled again. — unit: `app/src/renderer/screens/Posting.test.tsx`; ✓ while Prepare runs: …
- **Unmounted mid-prepare** (← Matches, step, another screen) → no navigation when it ends. On remount while still running: the spinner and elapsed time come back from the map, and the 'adopted' poll swaps in materials when `show` has them, which shows the "See the application" button; there is no automatic navigation. If the Prepare ended without materials, the poll stops silently at its next tick. — unit: `app/src/renderer/screens/Posting.test.tsx`

---

## 4. StatusDialog (`StatusDialog.tsx`)

Opened by the Posting's "Status" (full form) and the Posting's "Not for me" (`preset='discarded'`). Call: `set_status {job_id, status, notes?}`; `at` is never sent. Materials' "I've applied" records Applied with no dialog (§5).

### Quick "Not for me" form
- **dialog "Not for me: <title_en || title>"**. Focus starts in the textarea. — unit: `app/src/renderer/screens/StatusDialog.test.tsx`
- Textbox **"Why not?"** (label). — unit: `app/src/renderer/screens/StatusDialog.test.tsx`
- **btn "Cancel"**; **btn "Discard"**, disabled until the reason is non-blank and while busy. — unit: `app/src/renderer/screens/StatusDialog.test.tsx`; unit: `app/src/renderer/screens/Dialog.test.tsx` without saving
- Success → `onDone` (§2 or §6). Ledger: `status: discarded`, history notes = the reason. — ✓ Discard records the reason and opens the next match in its place

### Full form
- **dialog "Status: <title_en || title>"**. Focus starts on the checked radio, else the first radio. — ✓ opens on the current status… (unapplied: the first is the checked one); ✓ (expected fail) the dialog starts on the checked status — BUG: focus goes to the first radio, not the checked one
- **radiogroup "Status"**, radios **"Not yet applied"**, **"Prepared"**, **"Applied"**, **"Interview"**, **"Ghosted"**, **"Rejected"**, **"Offer"**, **"Not for me"**. — ✓ opens on the current status, with every status to choose from
  - The current status's group is pre-checked: unapplied → "Not yet applied"; `interview:*` → "Interview". — ✓ opens on the current status…; unit: `app/src/renderer/screens/StatusDialog.test.tsx`; unit: `tests/commands/test_status_cli.py`
  - A ledger status outside the list checks nothing. — not tested: unreachable (every tracker status maps to a radio)
- With **Interview** checked: a nested **radiogroup "Kind of interview"**. Each radio's accessible name joins word and meaning, so match them with regexes: — unit: `app/src/renderer/screens/StatusDialog.test.tsx`; ✓ Interview: screening/impression/assessment/technical needs the kind picked first
  - "Screening A pre-screening or recruiter call"
  - "First impression The first non-technical interview"
  - "Assessment A personality or cognitive test"
  - "Technical A technical interview, case or take-home"
  - The kind starts empty even when the current status is an interview, so Save stays disabled until a kind is picked. — unit: `app/src/renderer/screens/StatusDialog.test.tsx`
- Textbox **"Notes (optional)"**, or **"Why not?"** when "Not for me" is chosen; there the reason is required. — unit: `app/src/renderer/screens/StatusDialog.test.tsx`
- **btn "Cancel"**, **btn "Save"**. Save is disabled while busy, when no status is chosen, for Interview with no kind, and for Not for me with no reason. **Save is enabled at once on the current status**, so saving it unchanged is possible. — unit: `app/src/renderer/screens/Matches.test.tsx`; ✓ Interview: … needs the kind picked first; unit: `app/src/renderer/screens/StatusDialog.test.tsx`
- Escape closes. Tab is trapped inside. — unit: `app/src/renderer/screens/StatusDialog.test.tsx`

### Failure branches (**alert** inside the dialog, Save re-enabled)
- `"job 'x' was already applied to; use a different status to advance it"`: the current status is `applied` and Applied is saved again. The pre-check makes this one click. — unit: `tests/commands/test_status_cli.py`
- A lock held during a run: "a run is in progress (started …); try again when it has finished", or "another process … writing the ledgers …". — ✓ a run elsewhere holding the ledger is said in the dialog; unit: `app/src/renderer/screens/StatusDialog.test.tsx` ("another process … writing the ledgers")
- "no posting found …", server stopped, timeouts. — unit: `app/src/renderer/screens/StatusDialog.test.tsx`; no posting found / timeout: not tested (the dialog only opens on a posting that was read; a server-default timeout is too long for a journey)
- An unknown status is unreachable from the UI. — not tested: unreachable

### Success result
`{job_id, status, notes, at, current, label, sent_dir?, warning?}`
- First sent status with materials on disk → they are copied to `jobs/output/<id>/sent/` and the ledger gets `materials` hashes. — not tested here: Applications/materials area (no job with materials is in Matches)
- `warning`, only for sent statuses (applied, interview:*, offer):
  - "no ad text on disk for <id>: what passes can only be learned from the ads kept — import the ad with `jobs add` and record the status on that posting" — not tested: every job the UI can open has its ad on disk
  - or "the ad on disk for <id> is only N characters, too little to learn from; keep the whole ad when you can" (fewer than 400 characters; the e2e fixture's "Analyse things." triggers it) — unit: `app/src/renderer/screens/Matches.test.tsx`
  - and/or "K claim(s) in the sent materials are not in your cv.md: v1, v2 - check them before you rely on <id>"
  - joined with "; "
  - Shown as a second `p.notice` (no role) under the status notice in Matches or Applications. — unit: `app/src/renderer/screens/Matches.test.tsx` (Matches)

### `statusNotice(status, title)`
| Status | Text |
|---|---|
| unapplied | "Back in Matches." | — unit: `app/src/renderer/screens/Matches.test.tsx`
| prepared / applied / offer | "Prepared: T. It is in Applications now." (word from the list) | — ✓ Prepared moves the job…; ✓ Applied through …; unit: `app/src/renderer/screens/StatusDialog.test.tsx`
| interview:* | "Interview: T. It is in Applications now." | — ✓ Interview: screening needs the kind picked first; the other three kinds: unit: `app/src/renderer/screens/StatusDialog.test.tsx`
| ghosted / rejected | "Ghosted: T." / "Rejected: T." | — unit: `app/src/renderer/screens/StatusDialog.test.tsx`; Rejected: ✓ a rejection ends the last round and moves the card to Closed
| discarded | "Not for me: T." | — ✓ Discard records the reason and opens the next match in its place

---

## 5. Materials: "Ready to send" (`Materials.tsx`)

Reached through:
- the Posting's "See the application" / "See what you sent"
- the end of a Prepare call (any outcome)
- a notification `{screen:'materials'}`

### Calls
- `show {job_id}` on mount; again after a successful revise. — ✓ Revise changes the letter, shows the new pages, and Undo puts it back
- `revise {job_id, file: doc, instruction}` or `revise {job_id, file: doc, undo:true}`, where doc is `'cv'|'cover_letter'`. — ✓ Revise changes the letter, shows the new pages, and Undo puts it back; unit: `app/src/renderer/screens/Materials.test.tsx`
- IPC `saveMaterial(id, which, sent, file_names[which])`: the main process shows a native save dialog (default path Downloads/<name>) and copies the PDF. In e2e, stub `dialog.showSaveDialog` via `app.evaluate`. — ✓ Save letter writes the PDF where the save dialog says; unit: `app/src/renderer/screens/Materials.test.tsx`
- `set_status {job_id, status: 'applied'}` ("I've applied", no dialog). — ✓ I've applied records the application in one click and keeps a copy of what was sent

### States
- A load error: **btn "← Posting"** plus an **alert** with the error. — unit: `app/src/renderer/screens/Materials.test.tsx`
- `p.muted` "Loading". — not tested: transient
- **No materials** (`materials === null`): **btn "← Posting"** and "There is nothing prepared for this job yet." This is the branch a failed Prepare lands on. — not tested: no longer reachable from a Prepare (a failed Prepare throws and stays on the posting); "See the application" needs materials
- Full view:
  - **btn "← Posting"** → the posting view (in Matches still pushed: back to the posting, and the stepper hides when the job left the list). — ✓ Ready to send: the letter first, the CV behind the switch, every page loaded; ✓ a prepared card opens its application and comes back through its posting
  - **h1 "Ready to send"**, or **"What you sent"** when `materials.sent`. Subtitle "<title_en || title> · <company>". — ✓ Prepare application on a new match tailors, compiles and opens Ready to send; ✓ What you sent: the copy kept when it went out, read only, and saved from there
  - **btn "I've applied"** (primary, header): wide only, not remote, not sent. Disabled while busy or recording. One click records Applied (`set_status`), no dialog; a failure is an **alert** on the page and the job stays. Success → the parent's `changed` (in Matches the title is "the job", since a prepared job is not in the list). — ✓ I've applied records the application in one click and keeps a copy of what was sent; unit: `app/src/renderer/screens/Materials.test.tsx`; ✓ I've applied from Matches names the job in its notice (BUG: "Applied: the job.")
  - **status** notices (a revise or an undo that worked says nothing: the pages redraw and the box empties — ✓ Revise changes the letter, shows the new pages, and Undo puts it back):
    - "Saved as <file> in <folder>." (or "Saved as <file>." when the path has no folder) — ✓ Save letter writes the PDF where the save dialog says (the folder-less form: not tested, a save dialog always answers a full path)
    - "Nothing to undo." (only for an undo whose error matches `/nothing to undo/i`; server: "nothing to undo: no cover_letter.tex.bak for 'x'"). The e2e already covers this. — unit: `app/src/renderer/screens/Materials.test.tsx`
    - "The change was made but the PDF could not be rebuilt, so the pages still show the previous version. Undo last change puts it back." (`revise.compile[].status === 'error'`; no reload, the instruction is kept) — unit: `app/src/renderer/screens/Materials.test.tsx`
  - **alert** failures:
    - a revise error (stand-in claude: "…; file left unchanged"; "an instruction is required…" is unreachable because the button needs text; "…not found — prepare 'x' first"; timeouts at 420 s) — unit: `app/src/renderer/screens/Materials.test.tsx` ("an instruction is required": not tested, unreachable; "not found — prepare first": not tested, Revise shows only with materials; timeout: not tested, 420 s)
    - a save error: "that PDF is not on disk", "Could not save it: <err>", "saving is not available here", "unknown document"; when the error is missing, "Could not save the PDF." — unit: `app/src/renderer/screens/Materials.test.tsx` ("Could not save it"); "that PDF is not on disk": ✓ What you sent for a job whose sent copy is missing still shows and saves its pages (BUG); "saving is not available here"/"unknown document": not tested, unreachable in the desktop app
    - a cancelled save: nothing — unit: `app/src/renderer/screens/Materials.test.tsx`
  - A reload failure after a successful revise also lands in the failure alert (the show error text). — unit: `app/src/renderer/screens/Materials.test.tsx`
  - **status** spinner "Revising…" while busy. The pages get `aria-busy=true` and the `.dimmed` class. — ✓ Revise changes the letter, shows the new pages, and Undo puts it back
  - **group "Document"** with two pills (aria-pressed, disabled while busy). The letter is the default unless a notification asked for `document`. — ✓ Ready to send: the letter first, the CV behind the switch, every page loaded (a notification's document: §0's)
    - **btn "CV · N page(s)"** (`page_counts.cv`; "1 page" or "N pages"). — ✓ Ready to send: the letter first, the CV behind the switch, every page loaded; unit: `app/src/renderer/screens/Materials.test.tsx`
    - **btn "Letter · N words"** (`cover_letter_words`), or **"Letter · N page(s)"** when the words are null (no cover_letter.tex). — unit: `app/src/renderer/screens/Materials.test.tsx`
  - Pages: `img` alt **"CV, page i"** / **"Letter, page i"**, for `pngs[doc].slice(0, page_counts[doc])`. Stale extra PNGs are hidden. The src is `door-file://output/<id>/[sent/]<png>?v=<version>`; the version bumps after each revise to beat the cache. — ✓ Ready to send: the letter first, the CV behind the switch, every page loaded; ✓ Revise changes the letter, … (new pages after a revise)
  - **note** (figcaption) limit text:
    - CV with more than 2 pages: "(limit is 2)" — unit: `app/src/renderer/screens/Materials.test.tsx`
    - Letter with more than 1 page: "(limit is 1)" — unit: `app/src/renderer/screens/Materials.test.tsx`
    - Otherwise, a letter outside 250–350 words: "(aim for 250–350)" (en dash) — unit: `app/src/renderer/screens/Materials.test.tsx`
    - Within limits: none — ✓ Ready to send: the letter first, the CV behind the switch, every page loaded
  - **btn "Save CV"** / **"Save letter"** under the figure: wide only, disabled while busy. — unit: `app/src/renderer/screens/Materials.test.tsx`; ✓ Revise changes the letter, … (disabled while busy)
  - Revise aside (not when sent):
    - textbox **"Anything to change?"**, disabled while busy. Placeholder "Change the CV: lead with the dashboards project…" or "Change the letter: make it shorter and warmer…". — ✓ Ready to send: the letter first, the CV behind the switch, every page loaded (placeholders); ✓ Revise changes the letter, … (disabled while busy)
    - **btn "Revise"**, disabled while busy or with empty text. — ✓ Ready to send: the letter first, … (disabled empty); ✓ Revise changes the letter, …
    - **btn "Undo last change"**, disabled while busy. — ✓ Revise changes the letter, shows the new pages, and Undo puts it back
    - The switch decides which file Revise edits. — unit: `app/src/renderer/screens/Materials.test.tsx`
  - **Sent**: no aside, no I've applied; the images and Save read from `sent/`. — ✓ What you sent: the copy kept when it went out, read only, and saved from there
  - Narrow: no Save under the figure. An `.action-bar` holds **btn "Save CV"/"Save letter"** (for the current doc) and **btn "I've applied"** when not sent. The narrow variant **ignores `remote`**, so the phone also gets "I've applied" there. — ✓ narrow: Ready to send saves the shown document and has I’ve applied in the bar (remote: not tested here, the phone is another area)
- **Probable bug**: the job id comes from `jobIdOf(m)`, which drops the last path segment of `output_dir` when `sent`. If the job's history has a sent status but `jobs/output/<id>/sent/` has no PDFs (older data, or a sent status recorded before the materials existed), `show` falls back to the working dir and still says `sent:true`. `jobIdOf` then yields `"output"`. Result: broken page images (`door-file://output/output/sent/…`), and Save fails with "that PDF is not on disk". — ✓ What you sent for a job whose sent copy is missing still shows and saves its pages (test.fail BUG)

---

## 6. Applications (`Applications.tsx`, `board.ts`)

### Calls
`list_matches {ongoing:true}` and `list_matches {closed:true}` in parallel, on mount and every tick. If either fails → alert. — ✓ the board: five columns, a job in each, counts and how many are in play; ✓ a board that cannot load shows the error, and loads on the next visit

### Board view
- **h1 "Applications"**. Subtitle "N in play", with " · K in interviews" when K>0. Only when the ongoing list is non-empty. — ✓ the board: five columns, a job in each, counts and how many are in play; ✓ a rejection ends the last round and moves the card to Closed ("3 in play")
- **btn "Add a job"** → ImportDialog. Its "Open" pushes the imported job and refreshes. — not tested here: §7 (ImportDialog) is another area
- Notice lines, as in Matches (`status` and a plain warning `p`). — ✓ an interview round moves an applied card to Interviewing; ✓ Not yet applied takes a job off the board and back to Matches
- **status "Loading…"**; **alert** with the error. — ✓ a board that cannot load shows the error, and loads on the next visit (Loading…: not tested, transient)
- Empty (ongoing and closed both empty): "Nothing in play yet. Mark a match Prepared or Applied and it shows here." — unit: `app/src/renderer/screens/Applications.test.tsx`
- **group "Applications board"** (wide) / **"Applications"** (narrow). Its columns are `section`s labelled by an **h2**: "Prepared", "Applied", "Interviewing", "Offer", "Closed", each followed by " · N". — ✓ the board: five columns, a job in each, counts and how many are in play
  - Wide: all five, always, even when empty. — ✓ a rejection ends the last round and moves the card to Closed (Interviewing left empty, still shown)
  - Narrow: the non-empty ones in the order Offer, Interviewing, Applied, Prepared, then Closed last if non-empty. — unit: `app/src/renderer/screens/Applications.test.tsx`
  - Within a column the newest `updated_at` comes first. — ✓ Not for me on a prepared job, through Status, closes it as withdrawn (the newest first in Closed)
  - An ongoing row whose status fits no column is dropped. — not tested: unreachable: `list_matches(ongoing)` returns only the four statuses the columns hold
- **Card** = a button. Its accessible name is: — unit: `app/src/renderer/screens/board.test.ts`
  - `title_en || title` (note: Matches shows the original title, the board the English one)
  - the company
  - the note
  - for dots: hidden text "N round(s) passed, one under way: "
- Note variants (`cardNote`):
  - status rejected / ghosted / discarded → "rejected" / "ghosted" / "withdrawn", no dots — unit: `app/src/renderer/screens/board.test.ts` (rejected, ghosted); ✓ Not for me on a prepared job, through Status, closes it as withdrawn. NOTE: a match discarded before it was prepared or sent is not in `list_matches(closed)` at all (FULL_LEDGER's Kystbanken), right: it was never an application
  - offer → dots plus "offer" — unit: `app/src/renderer/screens/board.test.ts`
  - `interview:*` → dots plus the last round's `stage`, else the status suffix (e.g. "technical") — unit: `app/src/renderer/screens/board.test.ts`; ✓ an interview round moves an applied card to Interviewing
  - prepared / applied → "today", "yesterday", "N days ago" (2–6), "1 week ago", "N weeks ago" (2–3), else "Mon D", from `updated_at`; null or unparsable → no note — unit: `app/src/renderer/screens/board.test.ts` ("yesterday"; the other wordings are board.ts unit tests' job)
  - Dots come only from rounds with `result` passed (filled) or pending (outlined). Rejected, ghosted and withdrawn rounds get no dot. — unit: `app/src/renderer/screens/board.test.ts`
  - Hidden text examples: "1 round passed: ", "2 rounds passed, one under way: ", "one under way: ". — unit: `app/src/renderer/screens/board.test.ts` ("1 round passed, one under way: ", "2 rounds passed: "); ✓ an interview round moves … ("one under way: ")
- Card click → pushed posting. — unit: `app/src/renderer/screens/Applications.test.tsx`

### Pushed view
- **btn "← Applications"** (posting view only). No stepper and no j/k/Esc keys. — unit: `app/src/renderer/screens/Applications.test.tsx`; ✓ a prepared card opens its application and comes back through its posting
- ReadingPane → Posting (§3) / Materials (§5). — ✓ a prepared card opens its application and comes back through its posting
- Notice lines are **not** rendered in the pushed view. — not tested: a notice is set only when the view unpushes
- `changed` always unpushes back to the board with the notice. "Not for me" goes back too; there is no next card. The title comes from the ongoing rows; a closed or imported job gives "the job". — ✓ an interview round moves an applied card to Interviewing; ✓ I've applied records the application, …
- Transitions to test:
  - prepared → applied moves the card between columns. — ✓ I've applied records the application in one click and keeps a copy of what was sent
  - Discarding a prepared job puts it in Closed as "withdrawn", but the Posting's "Not for me" button is hidden for jobs with materials. Use Status → "Not for me". — ✓ Not for me on a prepared job, through Status, closes it as withdrawn
  - Setting "Not yet applied" removes it from the board with "Back in Matches." — ✓ Not yet applied takes a job off the board and back to Matches
- Opening a notification target with `inPlay:true` lands here (§0).

---

## 7. ImportDialog: "Add a job" (from Matches and Applications)

### Calls
- `import_posting`:
  - Link mode: `{url, title?, company?, location?, force?}` — ✓ a link is read, scored and shown; unit: `app/src/renderer/screens/ImportDialog.test.tsx`
  - Text mode: `{text, title, company, location?, force?}` — ✓ a pasted ad is scored and shown; ✓ the same ad twice is said… (force)
- Then `show {job_id}`; a failure there is swallowed. — ✓ a link is read, scored and shown (show); the swallowed failure: not tested (the import's own show is not told apart from others by the fault switch)

### Form
- **dialog "Add a job"**. Focus starts on the first input. — unit: `app/src/renderer/screens/ImportDialog.test.tsx`
- **btn "Link"** / **btn "Paste text"** (pills, `aria-pressed`). Link mode is the default. — unit: `app/src/renderer/screens/ImportDialog.test.tsx`; ✓ Paste text asks for the ad, a title and a company, and keeps what was typed
- Every field as in the other dialogs: its name above its own box (`.field.onb-field`, `label.field-label`, `.onb-input`).
- Link mode: textboxes **"Link"**, **"Title (optional)"**, **"Company (optional)"**. — unit: `app/src/renderer/screens/ImportDialog.test.tsx`
- Text mode: textbox **"Ad text"** (textarea), **"Title"**, **"Company"**. Use `exact: true`, since "Title (optional)" exists in the other mode. — ✓ Paste text asks for the ad, a title and a company…
- Both modes: **"Location (optional)"**. — unit: `app/src/renderer/screens/ImportDialog.test.tsx`; ✓ Paste text asks…
- Title, company and location are kept when switching modes. — ✓ Paste text asks for the ad, a title and a company, and keeps what was typed
- **btn "Cancel"** (quiet), then **btn "Import"** (primary), disabled while busy and until the form is ready: link needs a non-blank URL; text needs text, title and company. — unit: `app/src/renderer/screens/ImportDialog.test.tsx`; ✓ Paste text asks…; unit: `app/src/renderer/screens/Dialog.test.tsx`
- While busy: the spinner "Reading and scoring the ad…"; inputs disabled. Cancel stays enabled; the server call carries on after closing. — ✓ a link is read, scored and shown; unit: `app/src/renderer/screens/ImportDialog.test.tsx`

### Failure branches
- Error text matches `/already stored/i` → `p.notice` "You already imported this ad." plus **btn "Import again anyway"**, which resends with `force:true`. Server: "a posting with id 'manual.<sha>' is already stored at … — pass force to replace it". In text mode the id is the sha1 of the trimmed text, so the same text twice triggers it. — ✓ the same ad twice is said, and "Import again anyway" replaces it
- Any other error → **alert** (a `field-error` line, no box), named. Its text is CLI-flavoured, for example:
  - "could not fetch <url>: <exc>" — ✓ a link that cannot be fetched is said, and the form can be sent again
  - "could not fetch <url>: the page has no readable text" — unit: `tests/commands/test_add_cli.py`
  - "could not read the title and company from <url> (<claude error>) — pass --title and --company" (link without both title and company, and the stand-in claude failing) — unit: `app/src/renderer/screens/ImportDialog.test.tsx`
  - "could not read the title from <url> — pass --title" — unit: `tests/commands/test_add_cli.py`
  - "the ad is empty" (whitespace-only text can't reach it; Import needs text) — not tested: unreachable
  - Timeout: "The other door took too long to answer" (180 s) — not tested: a 180 s wait is too long for a journey

### Result: **dialog "Imported"**
- When `show` worked: `p` title and "company · location". — ✓ a link is read, scored and shown
- Score is a number → `p.score-l` "0.72" plus the `score_reason` paragraph. — ✓ a link is read, scored and shown; ✓ a pasted ad is scored and shown
- Score is null → "Not scored yet. It is scored on the next run.", plus a `details` "Why?" with `score_error`. Its text is e.g. "scoring failed; the next `find` scores it", or "Your CV is still the example (Jane Doe's). Add your own CV first.; the next `find` scores it". — unit: `app/src/renderer/screens/ImportDialog.test.tsx`
- **btn "Close"**. — unit: `app/src/renderer/screens/ImportDialog.test.tsx`
- **btn "Open"** → pushes the imported job. It is kept selected even when it is not in the list (below min_score, or unscored). — ✓ Open shows the imported ad, kept open though the list does not hold it
- Disk: `jobs/postings/<today>/manual/<id>.json`, scored in place. — ✓ a link is read, scored and shown

---

## 8. Shared primitives

- **Dialog**: `role=dialog`, `aria-modal`, named by its h2 title. Focus goes to `initialFocus` or the first focusable element. **Escape** calls onClose (and stops propagation). **Tab / Shift+Tab** wrap. There is no click-outside close.
- **Hint**: the button named by `label`, with an SVG icon. Hover or focus shows a **tooltip** (`aria-describedby` points at it while open). Escape or blur hides it at once; mouse-leave hides it after 200 ms.
- **Spinner**: `role=status`, the message with the app name styled.
- **Switch**: `role=switch`, `aria-checked`, named by its label.
- **AppName / named()**: purely presentational.
- **prepare-store**: a module-level `Map`. It survives screen switches but not a renderer reload: after a reload the Prepare is still running in main, but the UI forgets it. Find new jobs is then enabled, and clicking it gives the `preparing` outcome, so the run silently does nothing.

---

## 9. Narrow (`<900px`) differences, collected

- Sidebar foot hidden (Find button, Last run, Needs-you lines). The sidebar is entirely hidden while a posting is pushed (App `pushed`). — ✓ Matches has its own "Find new jobs", and the sidebar keeps only the tabs; unit: `app/src/renderer/screens/Posting.test.tsx`
- Matches: a "Find new jobs" pill in its head; the Needs-you group on top of the list (not pushed); a `.tab-dash` on the current tab. — ✓ Matches has its own "Find new jobs"…; unit: `app/src/renderer/App.test.tsx`; the tab dash: not tested (aria-hidden styling)
- Posting: the actions move to the bottom `.action-bar` in a different order. "Not for me" becomes secondary. "Open" is primary when there is no primary. — unit: `app/src/renderer/screens/Applications.test.tsx`; unit: `app/src/renderer/screens/Posting.test.tsx`
- Materials: Save goes from under the figure into the action bar (current doc only). "I've applied" moves from the header to the action bar, and shows even when remote. — ✓ narrow: Ready to send saves the shown document and has I’ve applied in the bar
- Applications: a list (`group "Applications"`), the non-empty columns furthest-along first, Closed last. — unit: `app/src/renderer/screens/Applications.test.tsx`
- Finding: no differences.

---

## 10. Branches believed unreachable or odd with a real server

1. MatchRow's status word: Matches lists only unapplied or untracked postings (`_ELIGIBLE_STATUSES`), and `statusWord('unapplied')` is null. **Unreachable.** A row score of null is also unreachable (`select_matches` needs score > 0).
2. Finding's idle "Find new jobs" without an error is unreachable: the screen hides when the state is null.
3. Posting's `/in progress/i` regex never sees the lock text. Prepare returns `{outcome:'failed', error:"a run is in progress…"}` rather than throwing, so a foreign CLI run lands on "There is nothing prepared for this job yet." Only `_BUSY` (same-server serialization) reaches the busy notice. — WRONG: the lock text comes back as `error`, which door-server.ts throws: the posting shows it as an alert (unit: `app/src/renderer/screens/Posting.test.tsx`)
4. `prepare` outcome `failed` and its `error` are never shown (§3). This is the most user-visible gap. — WRONG: shown as the posting's alert (see §3)
5. `PrepareResult.unsupported` and `materials.unsupported` are never shown in the renderer. They only reach the user as `set_status`'s warning on a sent status. `keywords`, `tailoring` and `rendered` are not shown either. — ✓ Ready to send names the claims the CV does not back (test.fail BUG); unit: `tests/commands/test_status_cli.py`
6. The run summary ignores `failures` and the per-site outcomes.
7. `ApiError.candidates` is never used in this area (an ambiguous job ref shows the message only; the UI always passes exact ids).
8. findJobs `preparing` / `busy` outcomes come only from races, since the buttons are disabled in those states. Exceptions: after a renderer reload mid-Prepare (preparing), or a lock held by a process whose pid the board considers dead.
9. `materials.sent` with no `sent/` copy → the job id becomes "output" (§5 bug). — ✓ What you sent for a job whose sent copy is missing still shows and saves its pages (test.fail BUG)
10. j/k from a focused dialog button steps the posting behind the dialog; Escape on the score hint also leaves the posting. — ✓ (expected fail) j pressed on a dialog’s button…; ✓ (expected fail) Esc on the score’s hint…
11. Empty-list copy "Nothing scored yet, run The other door first" also shows for "New only" with nothing new. — ✓ (expected fail) New only with every new match seen says there is nothing new…
12. `Stopping…` sticks forever if Stop is pressed when main has no find_jobs in flight.

---

## 11. Result shapes the renderer reads (for a test world)

**`show_profile`** (App): `config` (null → wizard or remote-setup; `config.email` goes to Settings), `cv.exists` (the "You have no CV yet" line), `discovery_unchosen: [{key, label}]` (Finding's Discover rows).

**`doctor`** (App, sidebar lines): `checks: [{name: 'claude CLI', status}, {name: 'claude login', status, details: {email?, subscriptionType?, loggedIn?, authMethod?}}]`.

**`status_summary`** (App and Matches):
- `since_last_review.last_run.finished_at` (the Last run caption)
- `in_progress.message` (the Matches spinner)
- `drive: {connected, last_error, account, last_synced, configured?}`. It is passed on only when `connected` is a boolean; `connected && last_error` gives the sidebar line.
- Foreign-run notice: `since_last_review.last_run.{started_at, new_above_threshold (a number)}`.

**`list_matches`** (Matches: `{}`; Applications: `{ongoing}` / `{closed}`): `matches: [{id, score, title, title_en, company, location, status, is_new, updated_at, rounds: [{stage, result}]}]`. Not read: `min_score`, `last_reviewed_at`. Matches reads id, score, title, title_en, company, location, status and is_new; Applications reads id, title, title_en, company, status, updated_at and rounds.

**`show`** (Posting, Materials, ImportDialog, notices):
- Posting fields: `id, title, title_en, company, location, url, apply_url, description, score, score_reason, posted_at, source_name, language, language_requirement ('required'|'advantage'|'none'|null), matching_skills[], missing_skills[], status`.
- `materials`: null, or `{output_dir, pngs: {cv[], cover_letter[]}, page_counts: {cv, cover_letter}, cover_letter_words (null when there is no .tex), sent, file_names: {cv, cover_letter}}`.
- Not read: `pdfs`, `keywords`, `tailoring`, `rendered`, `unsupported`, `history`, `source`.
- ImportDialog reads only title, company and location.
- Notices read title, company and status (inPlay).
- Materials only exist when both `cv.pdf` and `cover_letter.pdf` are in the dir. `show` renders missing PNGs itself (this needs the PDF renderer).

**`prepare`** (Posting): the result is ignored except to resolve or reject; any resolution goes to Materials. Notices read `outcome` (prepared or skipped → "Application ready") and `job_id`. Thrown errors (`{"error"}`) read: `_BUSY`, "no posting found…".

**`revise`** (Materials): `compile: [{status: 'compiled'|'skipped'|'error'}]`, where any 'error' gives the rebuild notice. Notices read `outcome` (only 'revised') and `file` (cover_letter… → letter). Thrown errors matching `/nothing to undo/i` give "Nothing to undo.".

**`set_status`** (StatusDialog → Matches / Applications): `job_id` (finds the row title), `current ?? status` (the notice text, and whether discarded moves on), `warning`. Errors: the alert in the dialog.

**`import_posting`** (ImportDialog): `job_id`, `score` (number or null), `score_reason`, `score_error`. Errors matching `/already stored/i` give the duplicate branch. Notices fire only when `args.url` is a string.

**`find_jobs`** (App / Finding): `started_at` (Show run record), `elapsed_s`, `new_above_threshold[]` (length only), `top: [{id, title, company, score}]`. Error text regexes: `/another long-running tool/`, `/is in progress/`; envelope `stopped`.

**`mark_seen`**: the result is ignored; a rejection keeps the id queued for the next list load.

**Run board files** (not a tool): `jobs/.lock.json` `{pid (alive), started_at, purpose}`; `jobs/.progress.json` `{message, steps: [{name, status, detail, started_at?, finished_at?, done?, total?, sites?: {id: n}, hosts?: [], phase?, request?, requests?: [n, m], items?: [{id, name, state}]}]}`.

**IPC (not tools)**:
- `openExternal(url)` → `{ok, error?}`, ignored.
- `saveMaterial` → `{ok, path?, canceled?, error?}`.
- `showRun` → ignored.
- `stopRun` → ignored.
- `info()` → `{demo, sandbox?, home?, checkout?, remote?, version?}`.
