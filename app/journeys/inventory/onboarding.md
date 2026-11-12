# Onboarding wizard and drafting again: e2e inventory

Sources read in full: `app/src/renderer/screens/onboarding/{Wizard,Connect,Sources,Reading,Review,parts}.tsx`,
`reducer.ts`, `save.ts`, `testing.tsx`; `app/src/renderer/{App.tsx,api.ts,Splash.tsx}`, `screens/{SignIn,Hint,Switch,Dialog,Spinner,AppName,Markdown(words),Documentation(DocDialog),todos}.tsx/ts`;
`app/src/main/{cv-sources.ts,claude-login.ts,demo.ts (onboard*),demo-run.ts}`, the relevant parts of `ipc.ts`, `door-server.ts`, `index.ts`, `preload`;
Python `commands/cv.py`, `commands/profile.py` (`_save_cv_core`, `_init_core`, `_show_profile_core`, `_profile_options`), `commands/titles.py`, `commands/keywords.py`, `commands/preview.py`, `core/discovery_sources.py`, `core/claude_cli.py`, `core/profile_loader.py`, `mcp_server.py` wrappers; `app/e2e/onboarding.e2e.ts`, `app/test/home-fixture.ts`.

Conventions below: **role "name"** is what `getByRole(role, { name })` finds. `named()` only swaps the words "The other door" for a styled span: text matching still works on the plain words.

---

## 0. How the wizard is reached (gate) and what frames it

| Entry | Condition | Mode | Notes |
|---|---|---|---|
| First launch | `show_profile.config === null` and (`!info.demo` or `info.sandbox === 'onboard'`) and not `info.remote` | `fresh` | `config` is null both when `profile/config.json` is **absent** and when it **exists but is invalid** (bad JSON, unknown key, out-of-range value): an invalid config opens the wizard as *fresh*, with no Back/Cancel and no "Keep my CV". — unit: `app/src/renderer/screens/onboarding/Wizard.test.tsx` |
| Demo (`dev:demo`) with no config | never gets the wizard (shell instead) | — | — not tested: the demo is not a world; the journeys always run the real server on a world |
| Phone (`info.remote`) with no config | `main.onb` with h1 "Set up The other door first" and body text; no wizard | — | not in this area beyond the gate — not tested: the phone app is another area (no wizard there) |
| `show_profile` throws | shell, no wizard | — | — not tested: show_profile is the first call of the window; a tool fault there is the shell's area, not the wizard's |
| Profile → CV part: button "Draft it from your CV file or pages" (example / missing CV note) | always (desktop) | `redo` (config non-null) or `fresh` (config invalid → null) | `setUpAgain` re-reads `show_profile`; if that call fails nothing happens (Profile says it cannot read the profile). — ✓ Set up again opens the sources with the answers kept, Back and Keep my CV |

Sandbox: `DOOR_ONBOARD_DIR=<tmp>` on an unpackaged app (or `--mode onboard`) → `onboardModeFor` returns 'onboard', `resetOnboard` empties the folder at launch (refuses the checkout, its `jobs/`, `profile/`), `info = {demo: true, sandbox: 'onboard'}`. Window title "The other door (onboarding sandbox)". Only `find_jobs` is simulated (`demo-run.ts`); **every other tool, including draft_cv/infer_basics/suggest_titles/keywords, runs the real server and the `claude` first on PATH**. `DOOR_ONBOARD_SIGNED_OUT=1` sets `CLAUDE_CONFIG_DIR=<dir>/.claude`. `DOOR_DEMO_RUN_MS` shortens the simulated run.

Frame of every step (in `div.shell-bare > main.main > div.onb`): no sidebar, no `navigation` landmark.
- `list "Progress"` (`<ol aria-label="Progress">`), items `listitem "Step i of N"`; the current one has `aria-current="step"`, earlier ones class `segment-done`. N = 3 always (sources, reading, review): Connect Claude comes before them and shows the three with none current.
- Each step: `region "<title>"` (`section aria-label`) with `heading level 1 "<title>"`, optional lead `p.subtitle`, optional top error list `list` with `role="alert"`, the body, then the action row: primary button (if any), then `button "Back"` (quiet), then the skip button, then the disabled-reason `p.onb-reason` (only while the primary is disabled and a reason is given). `busy` disables primary, Back and Skip.
- Before `doctor` answers: `status "Starting The other door"` (Splash).

Narrow window (< 900 px, `(max-width: 899px)`): only `.onb` padding changes (`--space-6` / phone gutter). Same controls, same order; the wizard ignores `useNarrow`. Max content width 620 px everywhere. No tab bar, no pushed screens. Dialogs (Install Claude?, Legal disclaimer) are the same modal.

---

## 1. Step: Connect Claude (only when Claude is missing or signed out)

Decided by `doctor` (called once on mount, `call('doctor')` with no args; on any failure the wizard uses `{ok:false, checks:[]}`):
- `claudeMissing`: a check named `claude CLI` with status ≠ `ok`. — unit: `app/src/renderer/screens/onboarding/Connect.test.tsx`
- `claudeLogin(..).connected`: check `claude login` with status `ok` and `details.loggedIn !== false`. — ✓ a first launch signed out opens on Connect Claude, before the three steps, with nothing written
- `claudeReady = !missing && connected`. A failed `doctor` call ⇒ not missing, not connected ⇒ **sign-in variant** shown. — not tested: a failed doctor call needs the server to fail at start; a doctor tool fault would also break the shell's checks — the signed-out variant itself is covered
- A `claude login` check of status `warn` (doctor could not read `claude auth status --json`: non-JSON output or no `loggedIn` key) ⇒ not connected ⇒ Connect shown even if actually signed in. — not tested: the stand-in claude always prints JSON with loggedIn

Also on mount (not in the sandbox): if a `latex` check has status ≠ `ok`, `call('setup', {install:['latex'], yes:true})` once, quietly, errors ignored. **Hazard for a non-sandbox e2e (e.g. Set up again on a `buildHome` app): it would really install Tectonic.** — not tested: the world has the stand-in tectonic on PATH, so latex is ok and nothing installs (by design: never run a real installer)

### 1a. Claude missing variant
- `heading 1 "Connect Claude"`; lead "The other door works through Claude, on your Pro or Max plan. Claude is not on this computer yet." — unit: `app/src/renderer/screens/onboarding/Connect.test.tsx`
- `button "Install Claude"` (primary; disabled while installing) → opens `dialog "Install Claude?"` (focus on first control; Escape closes; Tab trapped): text "This installs the Claude command line on this computer, without asking for a password.", `button "Cancel"` (closes), `button "Install"`. — unit: `app/src/renderer/screens/onboarding/Connect.test.tsx`
- Install → `call('setup', {install:['claude'], yes:true})`, `status "Installing…"` while working, then `doctor` again (still busy until it answers). — ✓ an install that fails says why and offers Check again; installed by hand, Check again moves on
  - `results[]` entry with `tool:'claude'` and `ok:false` → `alert`: its `error`, or "The install did not finish." when it has none. — not tested: needs the real setup to run (it would install); a tool fault can only make the call fail
  - setup call throws → `alert` with the error text. — ✓ an install that fails says why and offers Check again; installed by hand, Check again moves on
  - success but doctor still says missing → `alert` "The install finished, but Claude still can't be found. Try again, or close and reopen The other door." — not tested: needs a successful real install
  - In each of those three: "Installed it yourself?" + `button "Check again"` (re-runs `doctor`). — ✓ an install that fails says why and offers Check again; installed by hand, Check again moves on
  - success and doctor now finds claude → same component re-renders as the sign-in variant (or moves on if already signed in). — ✓ an install that fails says why and offers Check again; installed by hand, Check again moves on (Check again after installing by hand)
- `button "Back"` only in a redo (calls onCancel → back to the shell, nothing written). — not tested: a redo on a noClaude world: the shell's sidebar would show the missing-Claude line; Back is covered on the signed-out redo
- **Hazard:** reaching this needs a PATH without `claude`; pressing Install then runs the real installer (network). Only the dialog's Cancel / Escape and "Check again" are safe in e2e. — unit: `app/src/renderer/screens/onboarding/Connect.test.tsx` (the real installer is never run: `setup` answers from a tool fault)

### 1b. Signed-out variant (SignIn component)
- `heading 1 "Connect Claude"`; lead "The other door works through Claude, on your Pro or Max plan. It never uses an API key." — ✓ a first launch signed out opens on Connect Claude, before the three steps, with nothing written
- Below SignIn always: "Signed in some other way?" + `button "Check again"` (→ `doctor`; if ready, the wizard moves on to Sources by itself). — unit: `app/src/renderer/screens/onboarding/Connect.test.tsx`
- `button "Back"` only in a redo. — unit: `app/src/renderer/screens/onboarding/Wizard.test.tsx`

SignIn states (main process `claude-login.ts`, pushed on IPC `door:claude-login`; renderer reads the current one on mount via `door:claude-login-state`):

| State | UI |
|---|---|
| idle / cancelled | `button "Sign in with Claude"` — unit: `app/src/main/claude-login.test.ts` |
| starting | `status "Starting the sign-in…"` — not tested: lasts only while the main process asks doctor (well under a frame here) |
| waiting | `status "Finish signing in in your browser. The other door waits here."`, `button "Open the sign-in page again"` (disabled until claude printed an `https://*.claude.ai|claude.com` URL, `canOpen`), `button "Cancel"`, `button "The page showed a code?"` → replaced by a form: `textbox "Sign-in code"` (label), `button "Send code"` (type submit; disabled while the box is blank; **Enter submits**). — ✓ a wrong code fails…; unit: `app/src/renderer/screens/SignIn.test.tsx`; Open the sign-in page again… |
| done (live) | `status "Checking the sign-in…"` and `onDone` → `doctor` — ✓ a sign-in claude reports done but doctor does not confirm says so instead of checking forever (BUG, expected fail) |
| done carried from before this screen mounted (`stale`) | `alert` "claude said the sign-in worked, but The other door still can't see the sign-in." + `button "Try again"` — unit: `app/src/renderer/screens/SignIn.test.tsx` |
| failed | `alert` "The sign-in didn't go through: <message>" + `button "Try again"` — ✓ a wrong code fails with claude’s reason, Try again and the right code signs in and moves on to the sources |
| timeout (5 min, `LOGIN_TIMEOUT_MS`, not configurable) | `alert` "The sign-in waited five minutes for the browser and stopped." + `button "Try again"` — not tested: the five minutes are fixed in the main process; no journey waits five minutes |

IPC: Sign in → `door:claude-login-start` (no email from the wizard: args are exactly `auth login --claudeai`); Open again → `door:claude-login-open` (main calls `shell.openExternal(url)` — **stub it in e2e**, it opens a real browser); Cancel → `door:claude-login-cancel` (kills claude, state `cancelled` → "Sign in with Claude" again); Send code → `door:claude-login-code`. — ✓ a wrong code fails… (login args are exactly `auth login --claudeai`); Open the sign-in page again opens the page claude printed

Failure messages (`failed.message`), main-process wording:
- `Login failed: <x>` printed by claude (stderr then stdout) → `<x>` (stand-in wrong code: "Request failed with status code 400"). — ✓ a wrong code fails with claude’s reason, Try again and the right code signs in and moves on to the sources
- non-zero exit without that line → `claude stopped (exit <code>)`. — not tested: the stand-in always prints Login failed
- spawn error → `claude could not start: <e>`. — not tested: needs claude to vanish between doctor and the spawn
- doctor has no `claude CLI` path → `The claude app is not installed.` — not tested: the wizard shows the install variant then, not the Sign in button
- the main process's `doctor` call throws → `The other door could not check claude: <e>`. — not tested: needs the server to die during the sign-in
- Send code with a code that fails `^[A-Za-z0-9#_.~+/=-]{1,512}$` after trim (e.g. contains a space or `!`) or with no sign-in running → `alert` under the box: "That is not a sign-in code." (state stays waiting). — unit: `app/src/main/claude-login.test.ts`

**Surprising branch:** if claude's login exits 0 ("Login successful") but `doctor` still says signed out (e.g. a stand-in whose `auth status` still prints `loggedIn:false`, or a `warn` login check), the screen stays on `status "Checking the sign-in…"` indefinitely: the stale message only appears when SignIn mounts with a `done` already there (leave the wizard and reopen it). Only "Check again" and Back remain. — ✓ a sign-in claude reports done but doctor does not confirm says so instead of checking forever (BUG, expected fail)

After the doctor says ready, the wizard shows Sources, "Step 1 of 3" current. — ✓ a wrong code fails…; unit: `app/src/renderer/screens/onboarding/Connect.test.tsx`

---

## 2. Step: Sources — `heading 1 "Tell me about yourself"`

Lead: redo "Your answers stay."; fresh none.

Controls:
1. `button "Drop relevant documents here (CV or LinkedIn PDF)"` — click → IPC `door:pick-cv-files` → main `dialog.showOpenDialog({properties:['openFile','multiSelections'], filters:[{name:'CV files', extensions:['pdf','docx','md','markdown','txt']}]})`. E2E stubs `dialog.showOpenDialog` via `app.evaluate` (the existing test does). Cancel → `{files:[], refused:[]}` (also clears the refused alerts shown). — ✓ picking files lists them as chips and enables Continue; unit: `app/src/main/cv-sources.test.ts`
2. Drop on the area (`div.onb-drop-area`, also when dropped on the hint icon): dragover adds class `onb-drop-over`; drop → `window.door.dropCvFiles(files)` → preload `webUtils.getPathForFile` → IPC `door:drop-cv-files`. **Synthetic Playwright drops carry no OS path (`getPathForFile` → ''), are filtered out, and add nothing and refuse nothing**: dropping is effectively not e2e-reachable without a real OS drag. — not tested: a synthetic Playwright drop carries no OS path (getPathForFile is ''); dragging from Finder cannot be driven
3. `button "About the documents"` (Hint): hover/focus shows `tooltip` "PDF, DOCX, Markdown or text, up to 25 MB each. On LinkedIn: More → Save to PDF."; Escape or blur hides; 200 ms grace on mouse leave. — unit: `app/src/renderer/screens/onboarding/Sources.test.tsx`
4. `textbox "Any relevant URL"` (aria-label; placeholder "Any relevant URL, then press Enter"): **Enter** adds (preventDefault), **blur** adds too. Blank → nothing. Typing clears the URL error. — unit: `app/src/renderer/screens/onboarding/reducer.test.ts`; unit: `app/src/renderer/screens/onboarding/Sources.test.tsx`
5. `button "About the URL"`: tooltip "A personal site, GitHub, a publication list: anything public." — unit: `app/src/renderer/screens/onboarding/Sources.test.tsx`
6. Chosen list `list "Sources, chosen"` (only when ≥1): files first (by name), then URLs (whole address); each `listitem` with text and `button "Remove <name or url>"`. — unit: `app/src/renderer/screens/onboarding/Sources.test.tsx`
7. `button "Continue"` (primary): disabled until ≥1 file or URL. No reason line. — unit: `app/src/renderer/screens/onboarding/Wizard.test.tsx`
8. `button "Back"`: only in a redo (onCancel: back to the shell where it was, nothing written, CV tokens cleared by the unmount). — unit: `app/src/renderer/screens/onboarding/Wizard.test.tsx`

Refused files (main `cv-sources.ts`; each shown as its own `alert` "<basename>: <reason>"; the list is replaced on each pick/drop):
- extension not in `.pdf .docx .md .markdown .txt` (case-insensitive): "Only PDF, DOCX, Markdown and text files can be read." — ✓ files of other types, missing files and files over 25 MB are refused, each with its reason
- name OK but `realpath` (symlink target) has another extension: same message. — not tested: a symlink case of the same message; the extension check is covered
- `realpath`/`stat` fails (missing file, broken link): "That file could not be read." — ✓ files of other types, missing files and files over 25 MB are refused, each with its reason
- size > 25 MB (25 × 1024 × 1024 bytes): "That file is over 25 MB." — ✓ files of other types, missing files and files over 25 MB are refused, each with its reason
- Mixed picks: accepted ones become chips, refused ones alerts, in the same pick. — unit: `app/src/main/cv-sources.test.ts` the good one in the same pick is kept
- The dialog's filter normally prevents other types; a stubbed dialog can return anything.

Duplicates: a file with the same name and size as one already listed is ignored (a new token is still registered in main). The same URL twice is ignored. — unit: `app/src/main/cv-sources.test.ts`; the same file twice is listed once; Enter adds a page address…; the same address twice is listed once

URL refusals (renderer, `alert` under the box, text stays in the box):
- not parseable, or protocol not http/https (e.g. `ada.dev`, `ftp://x`, `mailto:`): "That is not a web page address (it starts with http:// or https://)." — unit: `app/src/renderer/screens/onboarding/Sources.test.tsx`
- host `linkedin.com` or `*.linkedin.com`: "LinkedIn pages can't be read; save your profile as a PDF (More → Save to PDF) and add that file." — unit: `app/src/renderer/screens/onboarding/Sources.test.tsx`
- `https://linkedin.com./in/x` (trailing dot) is LinkedIn too (`reducer.isLinkedIn` strips the dot, as the main process's `checkUrls` does) → the LinkedIn message in the box. — ✓ a LinkedIn address written with a trailing dot is refused in the box too

Edge: URL typed but not entered, then Continue clicked: a typed address counts as a source, so Continue is enabled; the blur adds it first, and Continue adds it too when it is still in the box (refused: the message, no step). — ✓ an address typed as the only source, then Continue clicked, is read

---

## 3. Step: Reading — `heading 1 "Reading your CV…"`, lead "It should take a few minutes."

No input. `list "Reading"` with four `listitem`s, each `heading 2`: "Drafting your CV", "Reading your details", "Finding titles that fit", "Choosing search terms"; a first set-up with sources has a fifth, "Writing an example story" (`draft_stories {from_cv: true}`, started once the draft is written and run beside the other three; the step is current only when the story is the last to come). One that fails or proposes none is said nowhere: the review goes without it. — unit: `app/src/renderer/screens/onboarding/Reading.test.tsx` The running one has `aria-current="step"`, a numbered ring (class `step-running step-working` while working) and a clock in `.step-time` ("N s", then "M min S s", ticking each second); done ones show a check mark; waiting ones show their number. `button "Back"` (→ Sources; see race below). — ✓ Reading shows the four steps, the running one with its clock, while a slow draft is made; unit: `app/src/renderer/screens/onboarding/Reading.test.tsx`

Calls, in order (all through `door:call` except the draft):
1. Draft (only when there are files or URLs; the UI always has some): IPC `door:draft-cv` with `{files: [tokens], urls: [...]}`. Main: re-checks URLs (`checkUrls`), resolves tokens to real paths (re-running the file checks), then `server.call('draft_cv', {sources: [...paths, ...urls]}, timeout 960 s)`. Python writes `profile/cv.draft.md` (creates `profile/`). Success → `draftDone` (cvText = markdown; `cvDraft.sources`; the non-LinkedIn URLs added to `enrichSources`, replacing a previous draft's). — unit: `app/src/renderer/screens/onboarding/Reading.test.tsx`; unit: `app/src/renderer/screens/onboarding/reducer.test.ts`
2. `infer_basics` with `{markdown}` (the draft), or `{}` after "Go on without a draft" (Python then reads `profile/cv.draft.md`, else the config's `cv_content`, else `profile/cv.md`; the example CV counts as none). — ✓ Go on without a draft: the review asks for everything and for the CV itself (infer_basics called with no markdown)
3. `suggest_titles` with `{titles: state.roleTargets, languages}` (`languages` = basics' languages on fresh, the state's on redo). Python reads the CV **from disk** (draft, else cv.md), never from the argument. — ✓ a redo with new sources reads them… (suggest_titles gets the saved titles)
4. `keywords` with `{role_targets: [...picked, ...recommended new titles], languages}` — only when that list is non-empty; else straight to done. — ✓ léa’s French CV… (keywords asked with English and French); no titles suggested: … no search terms were chosen
5. Phase done → the review opens by itself. — ✓ Reading shows the four steps… (then the review opens by itself)

Branches:
- **draft fails** (any error): ring stops; `alert` region containing "Your sources could not be read: <error>", `button "Try again"` (re-runs the draft with the same sources) and `button "Go on without a draft"` (→ step 2 with no markdown). Error texts a real stack can produce: — ✓ a failed draft says the sources could not be read, with Try again and Go on without a draft
  - from the main process: "A chosen file is no longer available; add it again." (token unknown — practically unreachable), "<name>: That file could not be read." (file deleted/moved after picking — **easy e2e**), "<name>: That file is over 25 MB." (file grew), "<name>: Only PDF, DOCX, …" (link retargeted), the LinkedIn hint (trailing-dot case), "<url> is not a web page address (http or https)." (unreachable: renderer checks first), "Add a file or a web page to draft from." (unreachable), "The other door took too long to answer" (960 s), "The other door's server stopped; try again". — unit: `app/src/main/cv-sources.test.ts`; the trailing-dot LinkedIn case; the others are unreachable or need a 960 s wait
  - from Python (`{"error"}`, expected exceptions): any `ClaudeError` — "claude exited 97: tests never call the real claude" (stand-in without an answer file), "claude exited <n>: <stderr>", "claude -p timed out after 900s", "claude returned no JSON envelope: …", "claude reported an error: '<result>'" (`is_error: true`), "claude's answer is not JSON: …", "claude's answer is not a JSON object", "claude's answer has no `cv_markdown`" (empty or whitespace `cv_markdown`); `ConfigError` lines when `profile/config.json` exists and is invalid (**no claude call at all**, e.g. "/…/profile/config.json: foo — Extra inputs are not permitted", or "/…/config.json: invalid JSON — Expecting value: line 1 column 1 (char 0)"); a `.txt`/`.md` that is not UTF-8 → `UnicodeDecodeError` (a ValueError): "'utf-8' codec can't decode byte 0x… in position …: invalid start byte"; a `.docx` that is a zip without `word/document.xml` → KeyError: "\"There is no item named 'word/document.xml' in the archive\"". — ✓ a failed draft says the sources could not be read… (a ClaudeError); an invalid config.json … reading says what is wrong with it (ConfigError)
  - from Python, **unexpected** exceptions (MCP `isError`, prefixed): a `.docx` that is not a zip → "Error executing tool draft_cv: File is not a zip file"; a corrupt `.pdf` → "Error executing tool draft_cv: Failed to load document (PDFium: Data format error).". — not tested: the corrupt-file texts come from pypdfium2/zipfile; covered by the Python tests, not a separate screen state
- **A file with no text** (e.g. an empty `.txt`, a scanned PDF): `sources[].chars === 0`. Reading shows "<full source path>: no text found in this file (a scanned PDF?)" (full path, only for the moment until the review opens); the review shows the basename under the CV fold (see §4). The draft still goes on. — unit: `app/src/renderer/screens/onboarding/Review.test.tsx` (the Reading line shows only for a moment)
- **infer_basics fails** (call throws; from a real server only on an invalid config.json, a timeout of 150 s or a crashed server — a failed model call is NOT an error, see below): basics = all null, languages and remote unchanged ⇒ missing name, email, city. — unit: `app/src/renderer/screens/onboarding/Reading.test.tsx`
- **infer_basics with `warning`** (claude failed or answered garbage): a success: the parsed header values only; anything else lands in `missing`; `languages` stays `["English"]` on fresh. The review's You part says "Claude could not read your details: <warning>" (a thrown call too: its error). — unit: `tests/commands/test_basics_cli.py`; when Claude cannot read the details, the review says so
- **suggest_titles fails** (throws: invalid config, timeout 150 s, server down) → no titles. **With `warning`** (model failed, answered nothing, or no CV on disk: "no CV of yours to suggest titles from yet", "claude suggested no titles", the ClaudeError text): success with only the user's own titles (`roleTargets`, reason "You named this title" or the model's reason) — on fresh that is `[]` ⇒ missing "job titles", no keywords call. The review's Titles part says "Claude could not suggest titles: <warning or error>". — unit: `app/src/renderer/screens/onboarding/Reading.test.tsx`; when Claude cannot suggest titles, the review says so
- **keywords fails** (any ClaudeError: "claude proposed no keywords", "claude's answer has no `keywords` list", exit/timeout/envelope texts; or ConfigError): the review's Search fold opens with "Claude could not propose search terms, so your titles are searched as they are: <error>" (`warnings.terms`, gone once terms are proposed); state `skipKeywords` (keywords [], topic terms [] ⇒ Save sends `search_keywords = role_targets`). — unit: `app/src/renderer/screens/onboarding/Reading.test.tsx`; when no search terms could be proposed, the review says why
- **No sources** branch (`understand(null)` without a draft): unreachable from the UI (Continue needs a source). — not tested: unreachable from the UI (Continue needs a source)
- **Back during reading** (Back is enabled throughout): goes to Sources at once and stops the reading: the call in flight finishes on the server, but its answer lands nowhere and nothing more is asked. Continue again starts a new full reading. — unit: `app/src/renderer/screens/onboarding/Wizard.test.tsx`; Back during reading stops it: reading again asks each question once
- Back from the review and Continue again re-reads everything: the CV text is replaced by the new draft (edits lost), name/email/city typed stay (existing values win), title suggestions are replaced, the picks kept plus newly recommended. — unit: `app/src/renderer/screens/onboarding/Wizard.test.tsx`

Nothing is written but `profile/cv.draft.md` (and the `profile/` folder) during reading. `config.json` is absent until Save on a fresh home. — ✓ Reading shows the four steps… (only cv.draft.md on disk before Save)

---

## 4. Step: Review — `heading 1 "Check your answers"`

Lead: fresh "Nothing is saved yet. Save puts it in place and starts your first search."; redo "Nothing is saved yet. Save puts it in place." — ✓ Save writes config.json and cv.md with exactly the reviewed answers…; Keep my CV goes straight to a prefilled review
Primary: fresh `button "Save and start searching"`, redo `button "Save"`. `button "Back"` → Sources (skips Reading; files and URLs still listed). No skip button.

Top notice (`p.notice`, no role) while anything the reading could not find is still unfilled: "These could not be found in your sources: <list>. Fill them in below to finish." with list items in this order and words: "your name", "your email", "your city", "job titles" (each disappears as it is filled; email counts only when valid). Shown only for keys reading put in `missing` (a redo that already had them asks nothing). — ✓ Go on without a draft: the review asks for everything…; jonas’ CV names no city: the review asks for it

Save disabled (`p.onb-reason` beside it gives the first reason, in this order):
1. "Choosing search terms for your titles…" (a re-proposal is pending/in flight; overrides the rest) — ✓ titles: … proposes new search terms, Save waiting meanwhile
2. "Your name is needed." — unit: `app/src/renderer/screens/onboarding/Review.test.tsx`
3. "A valid email is needed." (`/^[^\s@]+@[^\s@]+\.[^\s@]+$/` on the trimmed value) — unit: `app/src/renderer/screens/onboarding/Review.test.tsx`
4. "A city is needed." — unit: `app/src/renderer/screens/onboarding/Review.test.tsx`; jonas’ CV names no city
5. "Choose at least one language." — unit: `app/src/renderer/screens/onboarding/Review.test.tsx`
6. "Choose at least one title." — unit: `app/src/renderer/screens/onboarding/Reading.test.tsx`; with every title unticked, Save says a title is needed
7. "Your CV is needed: paste it above." (no CV text and no own `cv.md`; the example CV does not count) — unit: `app/src/renderer/screens/onboarding/reducer.test.ts`

### Part "You" (`region "You"`, `heading 2 "You"`)
- `textbox "Name"` (autocomplete name). — ✓ You: name, email, city, where to work and the ad languages are all changed in place and saved as changed
- `textbox "Email"` (type email). — ✓ You: name, email, city, …
- `combobox "City"`: options "Choose a city" (value ''), every known city (36, see §6), "Other…". Choosing "Other…" clears the location and shows `textbox "Your city"`; a typed city not in the list shows `p.notice` "<city> isn't in a supported country yet, so only the worldwide job boards are searched. Adding a country and its job sites is described in docs/adding-a-site.md." (typing a known name there keeps "Other…" selected but hides the notice). "Choose a city" → empty → "A city is needed." — unit: `app/src/renderer/screens/onboarding/Review.test.tsx`
- When `infer_basics` returned `unsupported_location` and the city is empty: `p.notice` "Your CV says <place>, which isn't covered yet. Choose a city, or keep yours under Other…: only the worldwide job boards are searched then." — not tested: none of the world's people names an uncovered place; the Other… notice is covered
- Radio group `group "Where you would work"` (fieldset/legend): `radio "Hybrid"`, `radio "Remote only"`, `radio "On site"` (values hybrid/yes/no). Default hybrid (fresh: infer_basics always answers hybrid). — ✓ You: … (On site); unit: `app/src/renderer/screens/onboarding/reducer.test.ts`
- `group "Languages of the job ads"`: `checkbox` per supported language: "English", "Danish", "French", "Hungarian", "Swedish". — ✓ You: … (Danish off, Swedish on)

### Part "Titles" (`region "Titles"`, lead "The job titles to look for")
- When there are suggestions: `group "The job titles to look for"` with one `checkbox "<title> <reason>"` each (the reason is in the label; use a regex). Recommended ones start ticked. Untick/tick toggles the pick. — ✓ titles: the recommended ones start ticked; unticking one and ticking another proposes new search terms
- `textbox "Add your own title"` (aria-label; placeholder "Add your own title and press Enter"): Enter adds (trimmed; empty ignored; a case-insensitive match of a suggestion ticks that suggestion instead of adding a chip; a duplicate pick is ignored). — unit: `app/src/renderer/screens/onboarding/reducer.test.ts`
- Own titles (picked, not a suggestion): `list "Add your own title, chosen"`, each with `button "Remove <title>"` (removing does not clear a Titles error message). — ✓ a title of your own is added with Enter, listed with a Remove button, and saved

### Fold "Search" (`<details>` with `<summary>`: "Search" + summary text) — closed by default
Open only when a Save error is routed to it. Click the summary to open (Playwright: `locator('summary', { hasText: 'Search' })`). Summary text: "Choosing them…" while proposing; "<k> search terms, <t> title terms" when keywords exist; else "Your titles, as they are". — unit: `app/src/renderer/screens/onboarding/reducer.test.ts`; init_profile refusing a field … (the fold opens)
- `textbox "Search terms"` (visible label + `button "About Search terms"` → tooltip "What the job boards are searched for."; placeholder "Add a term and press Enter"); chips `list "Search terms, chosen"`, `button "Remove <term>"`. — unit: `app/src/renderer/screens/onboarding/reducer.test.ts`
- `textbox "Title terms"` (+ `button "About Title terms"` → "Words that make a job title on topic, in every ad language."; placeholder "Add a word and press Enter"); chips `list "Title terms, chosen"`. — unit: `app/src/renderer/screens/onboarding/reducer.test.ts`
- Adds are trimmed, empty and case-insensitive duplicates ignored. Remove buttons are named only by the term: the same word in both lists, or as an own title, gives duplicate `Remove …` names (scope with `within`). — ✓ Search: … (trimmed, a case-insensitive duplicate ignored)
- A failed re-proposal (below) shows here only: "Claude could not propose search terms, so your titles are searched as they are: <error>" (invisible while the fold is closed). — ✓ a failed new proposal empties the terms and says so in the Search fold

Re-proposal (`useTermsFollowTitles`): whenever the picked titles differ from those at mount (or the last proposal), after 800 ms of no change → `keywords {role_targets, languages: state.languages}`; Save disabled meanwhile. Success **replaces** both term lists (hand edits lost). Failure empties both (`skipKeywords`) and shows the message above. Returning to the same picks before the timer cancels it. A late answer for older picks is dropped. Changing languages does not re-propose. Unpicking every title stops the wait (a late answer is dropped): the reason is "Choose at least one title." — ✓ titles: … proposes new search terms, Save waiting meanwhile; a failed new proposal empties the terms…; with every title unticked…

### Fold "CV" (`<details>`, summary "CV" + overview)
Open at mount when the user has no own CV (no draft text and no own `cv.md`), stays open while typing; also opens on a CV error (never produced: `routeErrors` routes nothing to `cv`). Overview: "Ready" (text, no TODO), "<n> thing(s) to fill in" (count of whole-word `TODO`), "Kept as it is" (no text, own cv.md), "Still the example CV", "No CV yet". — ✓ Go on without a draft: … the CV itself; CV: the draft is shown formatted…; jonas’ CV has three things to fill in; Keep my CV … Kept as it is
- `switch "Preview"` (aria-checked = preview on). Starts in preview when there is draft text, else on the text box. — ✓ CV: the draft is shown formatted, edited in the box, and the edited text is what cv.md holds
- Preview: the Markdown rendered; each `TODO` is a `button "to fill in"` → switches to the box with that TODO selected and focused (the box scrolls to it). With no text: "Nothing here yet." — ✓ jonas’ CV has three things to fill in: each marker opens the box on its gap, and what is typed there is saved; emptying the CV box… (Nothing here yet.)
- Box: `textbox "Your CV"` (label for `#cv-text`, 16 rows). When the profile already has an own cv.md: `button "About Your CV"` → tooltip "The CV you have now is kept as cv.md.bak." (box has text) / "Leave this empty to keep the CV you have." (box empty). Emptying the box sets the CV to "keep the one on disk". — ✓ a redo with new sources reads them… (About Your CV: kept as cv.md.bak); the empty-box variant: not tested (a redo emptying the box)
- Files with no text: `list "Files without text"`, items "<basename>: no text found in this file (a scanned PDF?)". — unit: `app/src/renderer/screens/onboarding/Review.test.tsx`

### Part "Your story bank" (`region "Your story bank"`; first set-up, when an example story was drafted)
Lead: "Your CV lists what you did. A story tells what was behind it, and the tailor draws on it when it writes an application. Here is one from your CV: fill in what the CV could not say. Add more later in Profile → Stories." `checkbox "Keep this story"` (ticked), then the story's Title, Context, Action, Result and Learning fields (gone when unticked). Kept with an empty part, Save waits: "Fill in the <parts> of your story, or untick it." Save calls `save_story` after the photo; a refusal goes under the part (`storyFailed`), the rest saved. — unit: `app/src/renderer/screens/onboarding/Review.test.tsx`, `save.test.ts`, `reducer.test.ts`

### Part "Where to find employers" (`region "Where to find employers"`)
Shown whenever the city has ≥1 source (always: LinkedIn works anywhere; an empty or unknown city gets the worldwide list = LinkedIn). Lead: "The other door can read these sites' public job search, logged out and slowly, to find employers. Their terms forbid automated access, so this is at your own risk: read the legal disclaimer." with `button "legal disclaimer"` → `dialog "Legal disclaimer"` (the repo's LEGAL_DISCLAIMER.md without its first heading; `button "Close"`; Escape closes; answers stay). — ✓ Where to find employers: Copenhagen offers LinkedIn…; unit: `app/src/renderer/screens/onboarding/Review.test.tsx`
- `group "Find employers on"`: one `checkbox "<label>"` per source of the city's country (§6). Fresh: all unticked. Redo: each from the config's `<key>` boolean. The list follows the city as it changes. — ✓ Where to find employers: … ticking it saves it on (the list follows the city); saving a redo … (from the config)

### Save (`saveProfile`)
Click → `status "Saving…"`, Save/Back disabled. Calls in order: — unit: `app/src/renderer/screens/onboarding/Review.test.tsx`
1. `init_profile` with: `name`, `email`, `location` (trimmed), `languages`, `role_targets`, `search_keywords` (the terms, or the titles when there are none), `topic_terms`, `remote`; fresh only: `exclude_companies: []`, `exclude_keywords: []`; `other`: `{<each shown discovery key>: bool, enrich_sources?: [...] (only when non-empty)}`. — ✓ Save writes config.json and cv.md with exactly the reviewed answers, then the first run starts with only search and match
2. `save_cv {markdown}` — only when the CV text is non-blank. — ✓ CV: the draft is shown formatted, edited in the box, and the edited text is what cv.md holds
3. `show_profile`. — ✓ a failed read-back after a good Save is not reported as an unsaved CV
Then `onFinish(run)`: run = fresh mode and (a CV of the user's) and (sandbox or Claude signed in per the wizard's last doctor). App: `show_profile` again, shell; fresh → `find_jobs {skip: ['discover','follow','collect']}` and the "Finding jobs" screen (`heading 1 "Finding jobs"`; sandbox: the simulated run writes two postings, Finance Controller / Tyrell Maritime and Senior Business Controller / Wonka Pharma, and a run record; then `button "View matches"`); redo → Matches with new-only. — ✓ Save writes config.json and cv.md … the first run starts (find_jobs skip discover, follow, collect); saving a redo … opens Matches without a run

Written at Save (fresh): `_init_core` copies every missing `profile.example/` file except `config.json`, `story_bank.md`, `companies.json` (so `cv.md` (example), `cv.template.tex`, `cover-letter.template.tex`), then writes `profile/config.json` = example config merged with the args (keeps `cv_template`, `cv_content`, `cover_letter_template`, `min_score 0.65`, `recheck_after_days 30`, `verify_liveness false`, `prescreen_top_n 40`, `prescreen_min 0.15`; `exclude` becomes `{companies: [], keywords: []}`; discovery keys of the city's sources set true/false; others absent). `save_cv` then writes `cv.md`, saves the example as `cv.md.bak`, deletes `cv.draft.md`. If the user emptied the CV box on a redo, `cv.md` is untouched and `cv.draft.md` (if a draft was made) stays behind. — ✓ a CV that could not be saved … (the example cv.md init_profile copied); Save writes config.json and cv.md…

Redo: no `exclude_*`; keys the wizard does not send (min_score, exclude, discovery keys of other countries, …) are kept. — ✓ saving a redo changes only what was changed, keeps the CV and opens Matches without a run

Save failures:
- `init_profile` → `{error}` (kind `fields`): the review stays; each line `profile/config.json: <key> — <msg>` goes under its section (`role="alert"` list inside the part): name/email/location/languages/remote → "You"; role_targets → "Titles"; search_keywords/topic_terms → "Search" (fold opens); `*_discovery` → "Where to find employers"; anything else (unknown key, `exclude.*`, `min_score`, …) and lines not of that form → the top list under the title as "<key>: <msg>" or the whole line. Editing a field of a section clears that section's messages (`set`, `add`, `drop`, `discovery`, `toggleTitle`, `addTitle`, `keywords`); the top list is cleared only by the next Save. Reachable from a real server only when the existing config.json has something the wizard does not overwrite: — ✓ init_profile refusing a field puts its message under the part that owns it; unit: `app/src/renderer/screens/onboarding/reducer.test.ts`
  - invalid existing config (wizard opens as fresh, Save merges over it): unknown key `"foo": 1` → top "foo: Extra inputs are not permitted"; `"min_score": 5` → top "min_score: min_score must be between 0.0 and 1.0"; `"hellowork_discovery": "x"` with a Copenhagen city → under "Where to find employers": "Input should be a valid boolean" (the section shows only LinkedIn); invalid JSON → top whole line "/…/profile/config.json: invalid JSON — …" (the reading calls fail too, see §3). Save drops the invalid keys the wizard does not send (`init_profile`'s `dropped`), so only invalid JSON is still a dead end. — ✓ an invalid config.json opens the wizard as a first launch…; Save on that first launch replaces the unreadable config.json
  - valid config whose `cv_template` / `cv_content` / `cover_letter_template` names a missing non-default file (show_profile does not check paths; `init_profile` does) → redo; top "profile/config.json: cv_template not found: /…" (whole line, no " — "). — not tested: the same top-list routing as the refused-field journey; a missing template file is the profile area's
  - name/email/location/languages/role_targets/remote errors: unreachable from the UI (guarded by the disabled Save and fixed lists). — not tested: unreachable from the UI (routing covered with a tool fault)
- `save_cv` fails (kind `cv`): `alert` "Your answers are saved, but the CV was not: <error>" (config.json already written). From a real server: empty text is guarded in the UI ("the CV is empty; nothing was written" unreachable); a read-only `profile/cv.md` on a redo → "Error executing tool save_cv: [Errno 13] Permission denied: '/…/profile/cv.md'". Saving again re-runs both calls. — ✓ a CV that could not be saved says the answers are saved but the CV is not; Save again saves it and starts the run
- `show_profile` after the save fails (kind `read`, practically unreachable): "Your answers and CV are saved, but they could not be read back: <error>". — ✓ a failed read-back after a good Save is not reported as an unsaved CV
- Transport errors on any of the three: "The other door took too long to answer" (default 60 s), "The other door's server stopped; try again". — not tested: a timeout needs 60 s; the server crash is the shell's area

---

## 5. Drafting again (redo) differences, summarised
Reached only from Profile → CV's note while the CV is the example one or missing ("Draft it from your CV file or pages").
- Prefilled: name, email, city, languages (or ["English"] when empty), remote, titles (each "In your profile", all ticked), search terms and title terms, every `*_discovery` boolean in the config, `enrich_sources`. — ✓ a redo reads the new sources: the saved answers stay…
- Sources: lead "Your answers stay."; `button "Back"` (leave the wizard, nothing written). — ✓ Draft it again opens the sources with the answers kept, and Back
- Reading runs; basics only fill empty fields (languages and remote kept); title suggestions come with the saved titles first (reason "You named this title" or the model's), recommended ones added to the picks; **keywords are always proposed again and replace the saved terms**. Save `button "Save"` writes the config and the CV (the example kept as cv.md.bak), then Matches, no run. — ✓ a redo reads the new sources: the saved answers stay, the new CV replaces the example, kept as cv.md.bak, and no run starts (the terms being replaced is not asserted)
- Review CV fold open "Still the example CV" / "No CV yet" until read; Save needs a CV. — unit: `app/src/renderer/screens/onboarding/Wizard.test.tsx`
- Connect step can appear in a redo (signed out) and has Back. — unit: `app/src/renderer/screens/onboarding/Wizard.test.tsx`
- The review's Back goes to Sources; Sources' Back leaves. — unit: `app/src/renderer/screens/onboarding/Wizard.test.tsx`

## 6. Data-driven variants

### Cities (`show_profile.options.cities`, the City combobox, in this order) and the employer sources each one offers
| Country (`i18n/country`) | Cities (as listed, title-cased canonical keys) | "Find employers on" checkboxes (config key) |
|---|---|---|
| Denmark (dk) | Copenhagen, Aarhus, Odense, Aalborg | LinkedIn (`linkedin_discovery`) — ✓ mette’s CV fills in everything…; jonas’ CV names no city… (Aarhus) |
| France (fr) | Paris, Lyon, Toulouse, Marseille, Lille, Bordeaux, Nantes, Nice, Strasbourg, Rennes, Grenoble, Montpellier | LinkedIn, HelloWork (`hellowork_discovery`) — ✓ léa’s French CV: French ads ticked, Lyon’s sources LinkedIn and HelloWork offered, unticked |
| Hungary (hu) | Budapest, Debrecen, Szeged, Miskolc, Pecs, Gyor, Szekesfehervar, Kecskemet, Nyiregyhaza, Szombathely (no accents) | LinkedIn, profession.hu (`profession_discovery`) — ✓ bence’s CV: Hungarian ads ticked, Budapest’s sources LinkedIn and profession.hu offered, unticked |
| Sweden (se) | Stockholm, Göteborg, Malmö, Uppsala, Linköping, Västerås, Örebro, Norrköping, Jönköping, Umeå | LinkedIn, Jobbsafari (`jobbsafari_discovery`) — not tested: no Swedish person in the world |
| none (Other…, or empty) | — | LinkedIn only (`worldwide_discovery`) — unit: `app/src/renderer/screens/onboarding/Review.test.tsx`; jonas before a city is chosen (LinkedIn only) |

Location parsing (`infer_basics`, no model needed when the header gives name, email and a place): `**Location:** <x>` (a `Location` line or `|`-separated part). An alias resolves to its city: "København S" / "Frederiksberg" / "Hellerup" → Copenhagen; "Århus" → Aarhus; "Gothenburg" / "Mölndal" → Göteborg; "Lund" → Malmö; "Pécs" → Pecs; "La Défense" → Paris; "Budaörs" → Budapest. A place naming only a country ("Denmark", "Magyarország") → no city and no unsupported place → the model is asked for `city`. A place in no known country ("Berlin") → `unsupported_location` "Berlin", city missing, the unsupported notice; the model is not asked for it.

### Languages
`languages` from infer_basics: English always, plus each supported language the model lists at level native / fluent / working (case-insensitive; names "Danish"/"danish" or codes "da"; "Dansk" does not resolve and is dropped; conversational/basic dropped). Supported: English, Danish, French, Hungarian, Swedish. The model is asked whenever the CV text contains a non-English language word: danish, dansk*, french, français, francais, francophone, hungarian, magyar, magyarul, swedish, svenska, svensk* (word match) — or when name/email/place is missing. — ✓ mette (Swedish at reading level dropped), léa, bence: the ad languages ticked from the CV

### Name / email from the model
Accepted only when found in the CV text (name: case-insensitive substring; email: exact substring and a full email match); a value containing "TODO" is ignored. A header `# TODO` gives no name.

### CV with TODOs
Overview "<n> things to fill in" / "1 thing to fill in"; `button "to fill in"` per TODO in the preview. TODOs in a Skills/Certifications-type section (`i18n` `cv_sections` "skills") are removed by Python before the wizard sees them (a skills section left with nothing is dropped), and their `todos` entries too. — ✓ jonas’ CV has three things to fill in: each marker opens the box on its gap…

### Titles
- Model marks some recommended → those ticked, the others listed unticked.
- Marks none → Python ticks the first three.
- More than 10 → only 10 (plus own titles).
- Empty list → `warning`, no titles ⇒ "job titles" missing; review shows no title group, only the add box.
- Duplicate titles (case-insensitive) collapsed; whitespace normalised.

### Terms
keywords + topic_terms; empty `topic_terms` is fine ("<k> search terms, 0 title terms"); empty `keywords` is an error ⇒ "Your titles, as they are".

### Sources
PDF, DOCX, .md, .markdown, .txt (any case). URLs (any non-LinkedIn http/https) → stored in `enrich_sources` after a successful draft. File with no text → the "no text found" lines.

---

## 7. What already has e2e coverage (`app/e2e/onboarding.e2e.ts`)
1. Signed out → Connect: Sign in, wrong code ("didn't go through: Request failed with status code 400"), Try again, right code `stand-in-code#ok`, moves on; login args contain `auth login --claudeai`. Sources: stubbed dialog pick of `my-cv.md`, LinkedIn URL refused ("Save to PDF"), `https://ada.dev` added. Review: Name/Email/City from the parsed header, Data Scientist ticked, Quant unticked, LinkedIn unticked; tick LinkedIn; Save and start searching → Finding jobs; `cv.md` equals the draft; config keys checked; View matches → Matches with "Finance Controller"; `note "Onboarding sandbox"`; real data folders unchanged.
2. Signed in; CV without city but "Taler dansk" → notice "…: your city."; Save disabled; pick Aarhus → notice gone; Danish ticked.
3. Every model call fails (no answers folder) → draft alert "could not be read" → Go on without a draft → fill Name, Email, City, own title; Save disabled until `textbox "Your CV"` filled → run; config `search_keywords` = the title.

Not covered: Install path, Cancel/Open again/timeout/stale sign-in, Check again, refused files, chip removal, URL blur, Back from reading/review, Try again, scanned/empty file lines, TODO markers and the switch, title add/untick and the debounced re-proposal (and its failure), terms editing, Other… city and both notices, remote radios, languages unticked, legal disclaimer dialog, Save errors (fields routing, CV save failure), every redo path (Set up again, Keep my CV, Back to leave), fr/hu/se cities and their sources, keywords failure, titles empty/none recommended, invalid-config fresh mode.

---

## 8. Unreachable or surprising from a real server (summary)
- Reading's no-sources branch; IPC "Add a file or a web page to draft from." and "<url> is not a web page address"; `save_cv` "the CV is empty"; `keywords` "no role targets"; Review CV-section errors (nothing routes to `cv`); `init_profile` errors on fields the wizard validates.
- `infer_basics` / `suggest_titles` model failures are successes with a `warning` (the review shows it); their catch branches need a ConfigError, a timeout or a dead server.
- An invalid existing config.json opens the wizard as fresh and makes every reading call fail without calling claude; Save drops its invalid keys (an invalid JSON file stays a dead end).
- `show_profile` failure after Save is reported with the CV wording.
- A live sign-in that doctor does not confirm hangs on "Checking the sign-in…".
- Drag and drop cannot be driven with synthetic files.
- A redo with new sources always overwrites the saved search terms.
- The sign-in timeout is a fixed 5 minutes.
- `preview_matches` is not called by the app wizard at all (only `/onboard`); no "first look" in the app.
- Reading's "no text found" line shows the full path, the review's the basename.

---

## 9. Model answers (for a scripted stand-in `claude`)

How Python calls claude (`claude_cli.ask`): argv `claude -p --model <m> --system-prompt <rules> --json-schema <schema> --output-format json (--allowedTools WebFetch | --tools "") --no-session-persistence`; the input on stdin. The system prompt is in argv, so the stand-in can match `"$*"` against its first words (as `home-fixture.ts` does). Stdout must be an envelope `{"result": "<the answer as a JSON string>"}` (or `"result": {…}` already an object). `{"is_error": true, "result": "x"}` → "claude reported an error: 'x'". Non-JSON stdout → "claude returned no JSON envelope: …". A result string that is not JSON → "claude's answer is not JSON: …"; JSON but not an object → "claude's answer is not a JSON object". Non-zero exit → "claude exited <n>: <stderr or 'exit code n'>". Each answer below is what goes inside `result`.

Also called by the app around the wizard: `claude auth status --json` (doctor; `{"loggedIn": true, "authMethod": "claude.ai", "email": "...", "subscriptionType": "max"}` signed in; `{"loggedIn": false, ...}` signed out; anything without `loggedIn` → a `warn` check, treated as signed out) and `claude auth login --claudeai [--email …]` (prints a `https://claude.com/...` or `https://*.claude.ai/...` URL to stdout, reads a code on stdin, prints "Login successful" and exits 0, or prints "Login failed: <reason>" and exits non-zero). Outside the sandbox the first run would also call the matcher/scorer and title translation (not covered here).

### draft_cv — model sonnet, `--allowedTools WebFetch`, timeout 900 s
Identifying words: `You draft a job seeker's CV as Markdown from the sources you are given`.
Stdin: the template (profile.example/cv.md), optional "Profile fields: {…}" (redo), each file's text between `<<<`/`>>>`, then "Pages to read:" and the URLs.
```json
{"cv_markdown": "# Ada Lovelace\n\n**Email:** ada@example.com | **Location:** Copenhagen\n\n## Experience\n\n### Data Scientist | Acme — 2020–present\n- TODO\n",
 "provenance": [{"source": "https://ada.dev", "contributed": "two projects"}],
 "todos": ["phone number"]}
```
Required: `cv_markdown` (non-blank string; else "claude's answer has no `cv_markdown`"), `provenance`, `todos` (schema; Python tolerates them missing). Variants: a header with/without `**Location:**`, `**Email:**`, `# Name`; `TODO`s in the body (counted by the review) or in a `## Skills` section (stripped); a language word ("Taler dansk", "Native French") to force the basics model call.

### infer_basics — model haiku, `--tools ""`, timeout 120 s (app limit 150 s)
Identifying words: `You read a job seeker's CV and fill in what it says about them`.
Called only when the parsed header lacks name, email or a place, or the text has a non-English language word. Stdin: `CV:\n<<<\n…\n>>>`.
```json
{"name": "Ada Lovelace", "email": "ada@example.com", "city": "Aarhus",
 "languages": [{"language": "English", "level": "native"}, {"language": "Danish", "level": "fluent"}]}
```
All four keys required by the schema; `null` allowed for name/email/city. Variants: `city` a known city or alias (→ city filled), a country only (→ nothing), an uncovered place ("Berlin" → unsupported notice), null (→ missing city); `name`/`email` not present in the CV text (ignored → missing); languages with level conversational/basic (dropped), unsupported names (dropped), French/Hungarian/Swedish at working level (ticked). A failure here is never an error in the UI: the header's values stand, the rest is missing.

### suggest_titles — model haiku, `--tools ""`, timeout 120 s (app limit 150 s)
Identifying words: `You suggest the job titles a job seeker should search for, from their CV`.
Needs a CV on disk (`cv.draft.md` or own `cv.md`), else no call and `warning`. Stdin: `CV:` block, "Ad languages: English, …", "Titles they named: a; b" (redo).
```json
{"titles": [{"title": "Data Scientist", "reason": "your latest title", "recommended": true},
            {"title": "Quant", "reason": "your maths", "recommended": false}]}
```
Variants: none recommended (first three get ticked), `[]` (no titles → "job titles" missing; no keywords call), > 10 titles (cut to 10), duplicates, a title equal to a saved one (its reason replaces "You named this title").

### keywords — model haiku, `--tools ""`, timeout 120 s (app limit 150 s)
Identifying words: `You propose search terms for job boards`.
Stdin: `Role targets: A; B\nAd languages: English, Danish`. Called from Reading once, and from the review after each title change (800 ms debounce).
```json
{"keywords": ["data scientist", "ml engineer"], "topic_terms": ["data"]}
```
`keywords` must be a non-empty list (else "claude's answer has no `keywords` list" / "claude proposed no keywords"); `topic_terms` may be empty or missing. To vary the answer between the Reading call and a review re-proposal, a stand-in can match on the stdin role targets (it is on stdin, not argv: read stdin in the script).

### Not called by the app wizard
`preview_matches` (`/onboard` only; its scoring would be the matcher prompt), `enrich`, `skill_gaps`, `market`.

---

## Journeys

`journeys/onboarding-{connect,sources,reading,review,personas,redo}.journey.ts`, helpers in `journeys/helpers/onboarding.ts`.
Harness additions: `WorldOptions.noClaude` with `world.installClaude()` (test/world/build.ts), and the stand-in claude's
`{"claude": {"login": {"stay_signed_out": true}}}` fault (a sign-in claude reports done that `auth status` does not confirm).
Not reachable in a journey: dragging a file from the OS (a synthetic drop has no path), the real installer (never run),
the five-minute sign-in timeout, the 60 s / 960 s transport timeouts.
