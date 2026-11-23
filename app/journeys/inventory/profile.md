# Inventory: Profile and CV (desktop app renderer)

Sources read in full: `app/src/renderer/screens/{Profile,PageSections,SettingsFields,CvEditor,Markdown,Hint,Dialog,todos}.tsx|ts`, `profile-form/{form.ts,fields.json}`, `onboarding/parts.tsx` (ChipInput, CityField, TextField, FieldLabel), `CvStyle.tsx`, `Switch.tsx`, `Spinner.tsx`, `AppName.tsx`, `api.ts`, the Profile wiring in `App.tsx`, `app/src/main/{ipc.ts,door-server.ts}` (error envelopes, timeouts, path refusals), and the Python side: `commands/profile.py` (`_init_core`, `_save_cv_core`, `_show_profile_core`, `_profile_field_specs`, `_profile_options`), `core/profile_loader.py` (the `Profile` model and its error lines), `commands/{keywords,enrich,market,companies}.py`, `core/{companies,claude_cli,lock,skill_aliases,discovery_sources}.py`, `mcp_server.py` (`_tool_errors`, `_EXPECTED_ERRORS`).

Conventions used below:
- **alert** means `role="alert"`. **status** means `role="status"`, which is always the `Spinner`: `<p role=status>` holding the message.
- `named(text)` swaps "The other door" for a styled `<span class="app-name">`. The text content stays the same, so `getByText` still matches.
- Every server error reaches the window as `ApiError.message`, and `errorText(e)` returns that message unchanged. There are three ways to fail:
  1. **Expected core error.** `{"error": str(exc)}` comes back from `_tool_errors` (ValueError, LookupError, FileNotFoundError, ConfigError, CompaniesError, LockHeldError, ClaudeError, DriveError, SyncConflict…). The message is the exception text.
  2. **MCPServer argument validation or an unexpected exception** (e.g. OSError). The result is `isError`, and the text is `Error executing tool <tool>: <pydantic or exception text>`, which can run to several lines.
  3. **Transport errors** (door-server.ts):
     - `The other door took too long to answer`: the timeout. The default is 60 s. Per-tool limits: keywords 150 s, enrich 660 s, market 180 s.
     - `The other door's server stopped; try again`: the child process died.
     - `<tool> returned something that is not JSON`.
     - Main-process refusals: `unknown tool`, `enrich takes web addresses only; files are chosen with the file picker.` (its `urls`), and `enrich cannot take a file path from the window; files are chosen with a file dialog.` (its `files`: a CV file goes by token, the `tokens` of `door:call`)
- Playwright name matching is a case-insensitive **substring** match by default. Many names here collide, so use `exact: true` where noted (e.g. `CV` with `Draft … CV …`, `Name` with the hint button `About Name`, `Add` with `Add these titles…`).

---

## 0. How the screen is reached (App.tsx)

| Action | Control | Result |
|---|---|---|
| Open Profile | sidebar `nav "Main"` → `button "Profile"` (exact; it has an icon plus text) | Mounts `<Profile key={profileStart.n}>`: one page, the details, the CV and the Stories; scrolled to `start.section` when given. | — ✓ opens with every section and the saved values
| Open Profile from the problem line "You have no CV yet" | `group "Needs you"` → `button "You have no CV yet"` (own block under the sidebar's menu; wide window only) | Profile opens scrolled to the **CV** section (`start={section:'cv'}`) and remounts (key n+1). The line shows only when `show_profile.config` is non-null **and** `cv.exists === false`. It is not shown in demo mode. The example CV gets no line. | — ✓ the sidebar line opens the CV, which says there is none
| Open Settings → Where to find employers from Finding | Finding screen's "choose discovery" action (`discovery_unchosen` non-empty) | Settings opens scrolled to `#settings-risky` | — ✓ the sources never chosen are said under Discover, and Enable opens Settings on Where to find employers
| `onDraft` (the CV section's buttons) | see §4 | `setUpAgain()`: calls `show_profile`, then the onboarding wizard opens prefilled with Cancel available (config exists). If `show_profile` fails, **nothing happens** (silent). | — unit: `app/src/renderer/screens/CvEditor.test.tsx`; the silent show_profile failure is not tested (nothing on screen to assert)
| `onSaved` (after a details Save, the first CV written, or the editor left after a write) | — | App re-reads `show_profile` (sidebar lines, `discovery_unchosen`) and bumps `refreshKey`, which remounts Matches. | — ✓ the first CV saves itself, with no backup, and the sidebar line goes
| Leave Profile (any nav button, Find new jobs) | — | Profile unmounts. **Unsaved details are dropped silently**; CV text typed since the last pause is written as the editor goes. | — not tested: nothing on screen to assert
| Close the window or quit the app | — | The window waits (at most 3 s, `main/close-flush.ts`) while the editor writes the text typed since the last pause, then closes. | — ✓ text typed just before the window is closed is written first |
| Remote (phone) | — | Profile is never rendered (`current === 'Profile' && !remote`). Not reachable in Electron. | — not tested: unreachable in Electron (the phone never renders Profile)

There is no gate into the wizard for an invalid config while the app runs. At launch, `config === null` opens the wizard (or remote-setup), so Profile's "could not be read" view is only reachable if config.json breaks **after** launch, or in the demo, where the wizard is not allowed.

---

## 1. Profile shell (Profile.tsx `Wrap`)

Always present: `heading level 1 "Profile"`.

### 1.1 One page
- No switch between parts: the details' sections with their save bar (only while changed) at the details' foot, then `region "Master CV"` (the CV file, the pages, the editor), and `region "Stories"`, each with its `heading level 2`. — ✓ opens with every section and the saved values; unit: `app/src/renderer/screens/Profile.test.tsx`
- `region "CV style"` sits between Master CV and Stories (listed beside the page only when the details could be read): the sample of the CV, a Colour row of nine radios (Blue is the default) and a Fonts row of four; a pick is saved at once with only its key (`init_profile` `other.cv_accent` / `cv_fonts`) and the sample is printed again (`cv_style_sample`); a CV that cannot be read is one line under the sample; a print failure is said nowhere; a pick that cannot be saved is said under its row. — ✓ shows a sample of the CV, and a pick is saved at once and printed again; unit: `app/src/renderer/screens/CvStyle.test.tsx`
- The CV and the Stories read their own data: a details part that cannot be read (error, spinner, invalid config) leaves them on the page. — ✓ a part that could not be read says so, and the rest of the page is there

### 1.2 Details load states
| State | Visible |
|---|---|
| Loading | status "Reading your profile…" | — not tested: a passing spinner
| `show_profile` throws (timeout or server died) | `alert` (p.error) with the error text in place of the details' sections. There is no retry. | — unit: `app/src/renderer/screens/Profile.test.tsx`
| `config === null` (invalid or missing config.json) | `alert` div: "profile/config.json could not be read:" plus `<ul>` of `errors` lines. Real wording examples: `<abs>/profile/config.json: invalid JSON — Expecting value: line 1 column 1 (char 0)`; `<abs>/profile/config.json: remote — Input should 'yes', 'no' or 'hybrid'`; `<abs>/profile/config.json: <key> — Extra inputs are not permitted`; missing file: `<abs>/profile/config.json not found`. The path is absolute, not "profile/config.json". | — ✓ a broken config.json lists what is wrong, with the file and the key; unit: `app/src/renderer/screens/Profile.test.tsx`; a missing file at launch opens the wizard (onboarding area)
| Loaded | Sections (below), the PageSections aside, the save bar | — ✓ opens with every section and the saved values

---

## 2. Profile → Details form

### 2.1 Field model
- `show_profile.options.fields` (from `_profile_field_specs`, the Profile model in model order) gives each key `{key,type,required,nullable,default,min?,max?,choices?}`.
- `fields.json` gives each key's section, label and help. A key is rendered only if it is both in `fields.json` (in a non-`config` section) **and** in `options.fields`. Within a section, keys follow `fields.json` order.
- A discovery key is hidden when its source does not serve the city currently typed in the form (it reacts live to edits of City).
- Initial values (`formValues`):
  - Present in config → that value. Absent → the spec default.
  - Strings and numbers become text; `null` becomes `''`.
  - Lists are kept. Booleans become `Boolean`. `exclude` becomes `{companies,keywords}`.

### 2.2 Help text rendering
| Field kind | Where its help appears |
|---|---|
| Text, number, city, chips | Behind a **Hint**: `button "About <label>"`. Hover or focus opens `tooltip` with the help. See §8. | — unit: `app/src/renderer/screens/Hint.test.tsx`
| Boolean, Languages | Plain visible `p.small.muted` under the control | — ✓ opens with every section and the saved values
| Choice (remote) | No help |

### 2.3 Sections, fields and controls (in render order)

The sections are rendered as `<section aria-labelledby="profile-<id>">`, i.e. **`region "<label>"`**, with an `h2` heading of that label.

**region "About you"** (`profile-about`)

| Key | Label | Control (role / name) | Spec | Notes |
|---|---|---|---|---|
| name | Name | `textbox "Name"`. Name has no help, so it has no Hint button; still use `getByLabel('Name',{exact:true})`. | string, required | `''` is accepted by the server (no error). | — ✓ Save writes the changed text, flag and number fields and nothing else ('' accepted: not tested)
| email | Email | `textbox "Email"` (type=text, not email) | string, required | No format validation anywhere. | — ✓ Save writes the changed text, flag and number fields and nothing else
| location | City | `combobox "City"` (select). A Hint "About City" carries the help "Every job board of the city's country is searched." | string, required | Options: "Choose a city" (value ''), every `options.cities[].name`, then "Other…". Picking Other… shows `textbox "Your city"` (value = location, starts ''). A typed city not in the list shows `p.notice`: "<city> isn't in a supported country yet, so only the worldwide job boards are searched. Adding a country and its job sites is described in docs/adding-a-site.md." "Choose a city" sets `''`, which the server accepts. | — unit: `app/src/renderer/screens/profile-form/form.test.ts`; unit: `app/src/renderer/screens/Profile.test.tsx` (the notice); "Choose a city" not tested (the same path as any city)
| needs_work_permit | I need a visa or work permit | `checkbox "I need a visa or work permit"`, no help | bool | — | — ✓ Save writes the changed text, flag and number fields and nothing else
| remote | Where you would work | `group "Where you would work"` (fieldset legend) with `radio "Remote only"` (yes), `radio "On site"` (no), `radio "Hybrid"` (hybrid), in the model's enum order yes, no, hybrid | choice | Errors appear under the radios. Unreachable from the UI (only valid choices). | — unit: `app/src/renderer/screens/profile-form/form.test.ts` (its errors: unreachable)
| languages | Languages of the job ads | `group "Languages of the job ads"` containing one `checkbox` per `options.languages` (English, Danish, French, Hungarian, Swedish), plus one per **chosen value not among them** (case-insensitive) | list | Three columns, no help line. A config holding a **code** such as `"da"` shows an extra checked `checkbox "da"` next to an unchecked "Danish". Unticking everything is valid (= English). A server language error is unreachable from the UI. | — unit: `app/src/renderer/screens/profile-form/form.test.ts`; unit: `app/src/renderer/screens/Profile.test.tsx` (its errors: unreachable)

**region "What to look for"** (`profile-search`)

| Key | Label | Control | Spec / server bounds | Errors (exact server wording, under the field) |
|---|---|---|---|---|
| role_targets | Role targets | ChipInput: `textbox "Role targets"` (placeholder "Type, then press Enter"), Hint "About Role targets" ("The job titles you are after."), `list "Role targets, chosen"`, each chip with `button "Remove <v>"` | list, required, min 1 | Remove all chips and Save → "role_targets must contain at least one entry". | — unit: `app/src/renderer/screens/Profile.test.tsx`; ✓ each refusal is said under its field, and nothing is written
| search_keywords, topic_terms | — | Not shown. On Save, a change of role targets or languages calls `keywords({role_targets, languages, save: true})` after init_profile, the bar saying "Updating what we search for (up to two minutes)…"; a failure keeps the terms saved before and says nothing. | list | — | — ✓ a change of role targets has Claude propose the search terms again on Save; ✓ a save that leaves the role targets and languages alone asks Claude nothing
| min_score | Match fit | `group` of three radios "Broad" (0.5), "Balanced" (0.65), "Strong" (0.75), plus "Your own (<n>)" checked when config.json holds another value; Hint "About Match fit" | number, sent by name | — | — ✓ Save writes the changed text, flag and number fields and nothing else; unit: `app/src/renderer/screens/Profile.test.tsx`

**region "What to skip"** (`profile-skip`). The `exclude` key's own label is never shown.

| Part | Control | Sent as |
|---|---|---|
| companies | ChipInput `textbox "Companies to skip"`, `list "Companies to skip, chosen"` (no hint) | `exclude_companies` (only if that part changed) | — unit: `app/src/renderer/screens/Profile.test.tsx`
| keywords | ChipInput `textbox "Words that rule an ad out"`, `list "Words that rule an ad out, chosen"` | `exclude_keywords` (only if changed) | — unit: `app/src/renderer/screens/Profile.test.tsx`

Errors for `exclude.*` appear under the **keywords** chips only. A real server cannot produce them from the UI (lists of strings). — not tested: unreachable (lists of strings)

Discovery switches are not on Profile: they are how the app works, in Settings (`SettingsFields.tsx`, Where to find employers; saved at once) — ✓ offers the sources serving the city; a tick is saved at once (Copenhagen: LinkedIn only; ticked and unticked, `linkedin_discovery` follows); unit: `app/src/renderer/screens/SettingsFields.test.tsx`. "Ask Claude where a careers page is" and the Claude config folder are left to config.json.

**region "Other"** (`profile-advanced`)

| Key | Label | Control | Notes |
|---|---|---|---|
| enrich_sources | — | Not in the form: the CV part's pages (§4.3) remember and forget them | list | — | — ✓ Check again reads them all and names the page of each proposal |


**Never shown:** the `config`-section keys (cv_template, cv_content, cover_letter_template, recheck_after_days, scrape_workers, verify_liveness, liveness_expiry_phrases, dedup_*, max_postings_per_site, max_pages_per_keyword, condense_max_chars, prescreen_*, translate_titles, translate_model, revise_model). The `case 'path'` branch of `control()` ("Not set" / "Change it in profile/config.json.") is **unreachable** with the current fields.json, because every path key is in `config`. — ✓ opens with every section and the saved values; the path branch: not tested, unreachable

### 2.4 Chip inputs (all ChipInput instances)
- Typing then **Enter** adds the trimmed text, clears the box and prevents form submit. Enter on empty or whitespace only clears the box. — unit: `app/src/renderer/screens/Profile.test.tsx`
- A duplicate (exact match after trim) is silently ignored, and the box still clears. — unit: `app/src/renderer/screens/Profile.test.tsx`
- `button "Remove <v>"` drops the chip. A chip whose text is long is truncated with an ellipsis and has `title=<v>`. — unit: `app/src/renderer/screens/Profile.test.tsx` (the ellipsis of a long chip: not tested, visual only)
- The chips list is not rendered when empty. — ✓ opens with every section and the saved values

### 2.5 Save bar (`.profile-save`, sticky at the bottom of the details)

The details' bar, inside the details and shown only while they have unsaved changes (or are saving, or just saved), so it never sits over the CV and the Stories, which save themselves (§4.2). With no changes there is no `button "Save"` and no `button "Undo changes"`. — ✓ opens with every section and the saved values

| Condition | Visible |
|---|---|
| Changes > 0 | `button "Save"`, `button "Undo changes"` (both disabled while saving) and `p` "1 unsaved change" / "N unsaved changes". N counts **keys** (the CV saves itself and is not counted): both exclude parts count as one, and a hidden discovery key that changed still counts. | — unit: `app/src/renderer/screens/Profile.test.tsx` (5 changes, the two skip lists one key)
| Saving | status "Saving…" | — not tested: a passing state
| After success, with no further edits | `p` "Saved." (not a status role). It is cleared by the next edit. | — ✓ Save writes the changed text, flag and number fields and nothing else

**Save flow**
- The call is `init_profile(toInitArgs(saved, values, specs))`: — ✓ Save writes the changed text, flag and number fields and nothing else (init_profile arguments)
  - Named keys go by name: name, email, location, languages, role_targets, search_keywords, topic_terms, remote, min_score.
  - Exclude goes as `exclude_companies` / `exclude_keywords`.
  - Everything else goes in `other: {key: value}`.
  - Numbers are parsed. Empty number fields become `null` if the key is nullable, otherwise `''`. An empty optional string becomes `null`.
  - Path keys are never sent.
- Success:
  - `show_profile` is re-read, the form resets to it, "Saved." shows and `onSaved()` fires. — ✓ Save writes the changed text, flag and number fields and nothing else (Matches' refresh: Matches area)
  - On disk, `profile/config.json` is rewritten as the **merged** config (`json.dumps(indent=2)`; the key order of the base config is kept and new keys are appended). — ✓ Save writes the changed text, flag and number fields and nothing else
  - **Side effect:** `_init_core` first copies any missing `profile.example/` file into `profile/` (never config.json, story_bank.md or companies.json). If `profile/cv.md` is missing, a details Save **re-creates it as the example CV**. Verified: `copied: ["cv.md"]`. It also restores missing `cv.template.html` and `cover-letter.template.html`. So after a details Save, a "no CV" state turns into "example CV". — ✓ saving the details does not make up a CV
- Failure: error lines are split by `fieldErrors`: — ✓ each refusal is said under its field, and nothing is written; ✓ a failing save says why above the form; the next one goes through; unit: `app/src/renderer/screens/Profile.test.tsx`
  - A line `^.+?: <key>[.sub] — <why>$` whose key is a known spec goes **under that field** as `p.field-error`. This is **not an alert**.
  - Everything else goes to the top as `ul role=alert` (one `li` per line).
  - Values stay as typed. Errors are cleared only when the next Save starts, not by editing.
  - Nothing is written. Validation happens before the write.
- Server error lines have the form `profile/config.json: <key> — <msg>`. This literal prefix comes from `_init_core`, unlike show_profile's absolute path.
- A whole-model error (the path-exists check: `cv_content not found: /abs/...`, where `cv_template` or `cv_content` points to a missing **custom** path) has no key and no " — ", so it goes to the **general alert**. Default paths are restored by the copy step, so this needs a custom path. — not tested: unreachable from the form: a missing custom path already fails show_profile, so Details never renders
- After a successful init_profile, if the follow-up `show_profile` fails, the page switches to the **load-error alert** even though the save went through. — unit: `app/src/renderer/screens/Profile.test.tsx`
- `init_profile` takes **no ledger lock**, so it works during a run. — not tested: needs a run in progress (Finding area)
- **Undo changes** does `setValues(saved)`. Glitch: CityField's internal `other` flag is **not** reset. After choosing "Other…" and then Undo, the select still shows "Other…" and "Your city" shows the saved city. — unit: `app/src/renderer/screens/Profile.test.tsx`; ✓ puts the city back after Other…
- **Unchosen discovery source:** `formValues` turns an absent `*_discovery` key into `false`. Ticking and then unticking is "no change", so it is not sent. **The Profile form cannot record "chosen: off"**, and the Finding screen's `discovery_unchosen` notice persists until the user saves it ticked once and then saves it unticked. — not covered by a journey

### 2.6 The search terms

See the search_keywords row above: nothing on screen; Claude proposes the terms on Save.

### 2.7 PageSections aside (wide window)
- `navigation "Sections"` contains `list` → `link "<label>"` for each shown section: "About you", "What to look for", "What to skip", then "CV" with its groups indented under it ("Sources", "CV content"), and "Stories", scrolled to like the others. "In profile/config.json only" never appears. — ✓ opens with every section and the saved values
- The current part has `aria-current="location"`. It is computed on scroll of `.main`: the last heading above a line that moves from 1/3 down the pane to the bottom as you scroll. — unit: `app/src/renderer/screens/Profile.test.tsx` (marking on scroll: not tested)
- Click → `preventDefault`, then smooth `scrollIntoView` of the heading. The link is marked current immediately and stays marked until `scrollend` (even when the section is too short to reach the line). It would also open a closed `<details>`, but there are none on Profile. — unit: `app/src/renderer/screens/Profile.test.tsx`
- **Narrow (<900 px):** `.page-aside{display:none}`, so it is not in the accessibility tree. — ✓ has no sections aside; the form and its save bar work the same

---

## 4. Profile → CV (CvEditor.tsx)

**Load:** `show_profile()` (its own call, separate from Details).

| State | Visible |
|---|---|
| Loading | status "Reading your CV…" | — not tested: a passing state
| Error | `alert` p.error with the text in place of the CV. No retry; the rest of the page is there. | — unit: `app/src/renderer/screens/CvEditor.test.tsx`

### 4.1 Banner variants (`role="note"`, `.cv-example`)

| Data | Note text | Button |
|---|---|---|
| `!cv.exists` | "You have no CV yet. Choose your CV file, write it below, or " | inline link `button "Draft it from your CV file or pages"` → onDraft (wizard) | — ✓ the sidebar line opens the CV, which says there is none; ✓ Draft it from your CV file or pages opens the set-up wizard (h1 "Tell me about yourself")
| own CV (the example CV too: it is never copied in, so no user has it) | no note | — | — ✓ opens on the CV as saved, as it reads; Preview off shows its text

Other data-driven variants:
- **CV exists but unreadable** (`text: null`, e.g. not UTF-8): the editor is empty, there is no note, and Save would overwrite it. — ✓ a cv.md that cannot be read as text is said, not shown as an empty CV
- **TODO gaps:** each `TODO` is a "to fill in" marker in the CV as it reads (§4.2). — ✓ the CV as it reads marks each gap to fill in
- **Config invalid** (config null): this view still loads. `show_profile` falls back to `profile/cv.md`. Expand sources become `[]`. — not tested: reachable only through the no-CV sidebar line with a config broken after launch

### 4.2 The CV as it reads / the editor
- Head: "Text" with its info bubble, and on its right `switch "Preview"` (button role=switch, `aria-checked`), on when Profile opens. — ✓ opens on the CV as saved, as it reads; Preview off shows its text
  - Preview on (the default): rendered Markdown (`.markdown.cv-preview`, see §7), each `TODO` a "to fill in" marker that opens the editor with it selected. — ✓ the CV as it reads marks each gap to fill in
  - Preview off: `textbox "Your CV (Markdown)"` (textarea, spellcheck on), the label with an inline `button "Markdown"` (the cheatsheet). A CV that opens empty opens with Preview off. — unit: `app/src/renderer/screens/CvEditor.test.tsx`
- **Added lines:** after "Add N to my Master CV" (§4.4) each added bullet (`- <text>`) is tinted (`.md-added`, the `accent-tint` token): in the preview the list item, in the editor a tinted copy of the text behind the textarea (`.cv-backdrop`, scrolled with it). The first one is brought into view after the add and on each Preview switch. Typing or a Save clears the tint. — ✓ Add puts the ticked ones in cv.md, keeps cv.md.bak and marks them in the CV as it reads and in its text
- No Save: the text is written a second after typing stops and when the editor is left (`save_cv`, `backup: true` only on the visit's first write, so `cv.md.bak` is the CV as Profile opened it); `status` "Saving…" then "Saved" beside Preview; an emptied CV is never written; a failed write is the error box under the editor, tried again at the next pause. — ✓ the text saves itself; cv.md.bak keeps the CV as it was when Profile opened; ✓ a failing save says why, keeps the text, and is tried again; unit: `app/src/renderer/screens/CvEditor.test.tsx`
- **The write:** `save_cv({markdown, backup})`; the editor keeps its text (no read-back while typing). — ✓ the text saves itself; cv.md.bak keeps the CV as it was when Profile opened
  - On disk: `profile/cv.md` = text; `profile/cv.md.bak` = the CV as Profile opened it (**only if a cv.md existed**); `profile/cv.draft.md` is deleted. — ✓ the text saves itself; cv.md.bak keeps the CV as it was when Profile opened; ✓ the first CV saves itself, with no backup, and the sidebar line goes
  - `save_cv` takes no lock.
- **Write errors** (under the Text field as `field-error`, tried again at the next pause): — ✓ a failing save says why, keeps the text, and is tried again (through a tool fault; the empty-CV error is unreachable: an empty CV is never written)
  - "the CV is empty; nothing was written" is **unreachable** (the button is disabled).
  - Permission errors (OSError is not "expected") → `Error executing tool save_cv: [Errno 13] Permission denied: '<path>'`.
  - Transport errors.
- **save_cv always writes `profile/cv.md`**, but `show_profile` reads `config.cv_content`. With a custom `cv_content` path, a Save "succeeds" and the editor then reloads the **other** file, so the edit appears to vanish. Edge case, needs a custom config. — not tested: needs a custom cv_content path, which the form cannot set

### 4.3 Master CV: the CV file and the pages

The CV is one part, `heading "Master CV"` (a muted line under it: everything about the user's work, never sent as it is, each application's CV picked from it and tailored; then the field Sources, then the CV). Each field is a form field: its name with an info bubble (`button "About <name>"`), 4 px above its control, what belongs to it under it, an error under it as `field-error`. Replace…, Add a page and Check again first write what was typed.

- **`group "Sources"`**: `button "Replace CV file…"` (`"Add a CV file…"` with no CV file known), `button "Add a page"` (opens `dialog "Add a page"`, §4.4) and, with remembered pages, `button "Check again"` (opens `dialog "Check your pages again"`), then under them `list "What your Master CV is read from"`: the CV file a draft or a read last took (`door:cv-file`, from the path the main process keeps; no ×), then one chip per page, shown without `https://` (the full address on hover), each with `button "Forget <page>"`, which removes it at once (`init_profile`); a page that could not be forgotten is said under the field and its chip stays. — ✓ reads the page asked for, remembers it, and proposes what the CV lacks, all ticked; ✓ Check again reads them all and names the page of each proposal; ✓ a page is forgotten by its ×; unit: `app/src/renderer/screens/CvEditor.test.tsx`
- A CV file chosen (`pick-cv-files`): with a Master CV, `dialog "Replace your CV file"` reads it (`door:call` `enrich` with its token, `enrich {files}` in main, the spinner "Reading <name> (a minute or two)…"), proposes what it adds as a page's read does (or "Nothing in <name> is missing from your Master CV."), and adds the ticked ones, tinted; the file is the CV file from then on; a failed read is said in the dialog, the CV and the CV file as they were. With no Master CV, `draft_cv` through `door:call` with the token (spinner "Reading your CV file (a minute or two)…") drafts it whole, saved; a refused file is said under the field. — ✓ a new CV file proposes what it adds, and adding keeps everything the Master CV had; unit: `CvEditor.test.tsx`

### 4.4 The page dialogs: Add a page, Check your pages again

**`dialog "Add a page"`**
- `textbox "Which page?"` (placeholder "github.com/you, your portfolio, a publication list"); **Cancel** (quiet) and **Read it** (primary, disabled while empty; Enter reads too). An address with no scheme gets `https://` in front (the main process refuses anything but http(s)). — unit: `app/src/renderer/screens/CvEditor.test.tsx`; ✓ reads the page asked for…
- `enrich({urls: [page]})`, the spinner "Reading the page (a few minutes)…". A page it could read is remembered at once (`init_profile {other: {enrich_sources}}`); one in `unreachable` puts the field back with "Could not read <page>." under it and is not remembered. — unit: `app/src/renderer/screens/CvEditor.test.tsx`

**`dialog "Check your pages again"`**: every remembered page read at once (spinner "Reading your pages again (a few minutes)…"), each proposal named with " · from <page>" when there are several pages; nothing new: "Nothing new on your pages." — ✓ Check again reads them all and names the page of each proposal

**Both**
- Proposals: "What your Master CV does not have yet. Untick what should not go in.", then one `group` per CV section (a plain block named by the section, fixed gaps), a `checkbox` per proposal named by its text, all ticked. **Cancel**, **Add N to my Master CV** (primary; disabled at 0). — ✓ reads the page asked for…
- `enrich` proposes nothing the CV already says, even in other punctuation, Markdown or near wording (the words compared, a line 90% alike), so a second read adds nothing twice. — unit: `tests/commands/test_enrich_cli.py`
- Nothing on the page: "Nothing on that page is missing from your Master CV." and **Close**. — unit: `app/src/renderer/screens/CvEditor.test.tsx`
- Add: `enrich({apply})`, the spinner "Adding to your Master CV…" (Esc does not close it then); the dialog closes, the CV is read again and the added lines are tinted (§4.2). No message. — ✓ Add puts the ticked ones in cv.md, keeps cv.md.bak and marks them in the CV as it reads and in its text
- Errors: a `field-error` alert in the dialog (a read: back to the field; an add: "…cv.md changed since the proposals were made; run `enrich` again" when the CV was saved since). — not covered by a journey; the refusal: unit: `tests/commands/test_enrich_cli.py`; the dialog showing it: no test

---

## 6. Dialog (Dialog.tsx), used by Market (now in Analytics)

- `role=dialog`, `aria-modal=true`, named by its `h2` title, inside `.scrim`. — ✓ Prepare again asks first…; unit: `app/src/renderer/screens/Dialog.test.tsx`
- Initial focus goes to the `initialFocus` selector if given, otherwise the first focusable element. Neither use here passes one, so focus goes to Cancel. — ✓ Prepare again asks first…; unit: `app/src/renderer/screens/Dialog.test.tsx`
- Tab on the last control wraps to the first; Shift+Tab on the first wraps to the last. — not tested: Tab wrapping: not pinned
- Escape calls onClose and stops propagation. — ✓ Prepare again asks first…; unit: `app/src/renderer/screens/Dialog.test.tsx`
- **Clicking the scrim does not close.** There is no close (×) button. — not tested: the scrim: not pinned
- Narrow: the width is `min(480px, 100vw − space-8)`.

## 7. Markdown (Markdown.tsx), used by the CV preview

- `#`…`######` render as headings **one level down**: h1→h2 (`display-s`), and h3–h6 use `md-heading`, capped at h6. — unit: `app/src/renderer/screens/Markdown.test.tsx`
- Blank lines separate paragraphs, and lines inside a paragraph are joined with a space.
- `- * +` give `ul` items; `1.` or `1)` give `ol` items. A list item continues on lines indented by 2 spaces. — unit: `app/src/renderer/screens/Markdown.test.tsx`
- Inline formatting: `**bold**`, `*italic*`, `` `code` ``, `[label](url)`. Underscore emphasis and tables are not supported; table rows become paragraph text.
- Links:
  - `http(s)` → `button "<label>"` (`.link-inline`); click calls `window.door.invoke('open-external', url)`, which opens the system browser. Stub `shell.openExternal` in e2e. — unit: `app/src/renderer/screens/CvEditor.test.tsx`
  - Another scheme (`mailto:`) → the raw `[label](mailto:…)` text.
  - A relative or file link → the label text only. — not tested: mailto: and relative links: not pinned
- The text is never rendered as HTML: `<b>x</b>` shows literally. — unit: `app/src/renderer/screens/CvEditor.test.tsx`
- `TODO` markers only appear with `onGap`, which nothing in this area passes. — unit: `app/src/renderer/screens/CvEditor.test.tsx`

## 8. Hint (Hint.tsx)

- `button "About <label>"` (`.hint-icon`). — unit: `app/src/renderer/screens/Hint.test.tsx`
- Opens on mouse enter, closes 200 ms after the mouse leaves. Moving onto the popup keeps it open. — unit: `app/src/renderer/screens/Hint.test.tsx`
- Focus opens it; blur or **Escape** closes it. — unit: `app/src/renderer/screens/Hint.test.tsx`
- Open → `role=tooltip` (span) with the help text, and the button gets `aria-describedby` pointing at it. — unit: `app/src/renderer/screens/Hint.test.tsx`
- There is **no click toggle**: clicking just focuses the button, which opens the popup.

---

## 9. Narrow window (<900 px) differences

- The sidebar becomes a bottom tab bar (`nav "Main"`, the same `button "Profile"` with an icon). `.sidebar-foot` and the problem lines' block are `display:none`, so **Find new jobs and the "Needs you" problem lines (e.g. "You have no CV yet") are not reachable from Profile**. They show on top of Matches only. — ✓ has no sections aside; the form and its save bar work the same (the "Needs you" group hidden)
- PageSections (`navigation "Sections"`) is hidden. — ✓ has no sections aside; the form and its save bar work the same
- The rest is the same single column. The save bar is still sticky at the bottom; Dialog and Hint popups are constrained to the viewport. — ✓ has no sections aside; the form and its save bar work the same; unit: `app/src/renderer/screens/CvEditor.test.tsx`
- Profile is never "pushed", so the shell is never `.pushed` here.

---

## 10. Result shapes the renderer reads (to build a test world)

### show_profile (Profile Details, CvEditor, App; Market's add-titles is in analytics.md)
```
{
  path: str,
  config: { ...validated config.json keys as set (exclude_unset; paths made absolute) } | null,
  errors: [str],                         // when config is null: "<abs>/config.json: <key> — <why>" | "<abs>/config.json not found" | "...: invalid JSON — ..."
  cv: { path, exists: bool, is_example: bool, text: str|null, headline, sections },
  options: {
    cities: [{ name, country, boards: [..], discovery: [{key,label}] }],
    languages: ["English","Danish","French","Hungarian","Swedish"],
    worldwide_boards: [..],
    worldwide_discovery: [{key:"linkedin_discovery",label}],
    board_names: {..},
    fields: [{ key, type: string|path|choice|boolean|integer|number|list|exclude, required, nullable, default?, min?, max?, choices? }]
  },
  enrich_sources: [str],
  discovery_unchosen: [{key,label}],
  templates, story_bank                  // not read here
}
```
Variants to drive:
- config null (Details error view)
- `cv.exists=false` (no-CV note, sidebar line) / `text:null`
- config keys present vs. absent (absent → defaults: min_score 0.65, max_age_days 30, retire_after_days 90, follow_ai_fallback true, translate_titles true; discovery keys false)
- location in dk/hu/fr/se/other (which discovery switches show)
- `languages` holding a code
- `enrich_sources` (the pages above the CV, §4.3)
- `role_targets` (the search terms proposed on Save)

### init_profile (Details Save; Market's add titles is in analytics.md)
- Reads only success or throw. `{config_path, copied:[rel paths]}`.
- Error: `{"error": "profile/config.json: <key> — <msg>\n..."}`, or an isError text for bad named-argument types.

### keywords (on Save, after a change of role targets or languages)
`{ role_targets, keywords: [str], topic_terms: [str], saved: false }`. The window reads `keywords` and `topic_terms` (each `?? []`).

### save_cv
`save_cv({markdown, backup})` (`backup` false after a visit's first save): `{ cv_path, backup }` or `{error}`. Only success or throw is read.

### enrich
- Propose (`urls`, or `files` by the `tokens` of `door:call`): `{ outcome: "proposed"|"nothing_new", urls, files, proposals: [{n, section, text, source}], unreachable: [str], proposals_path? }`. The window reads `proposals` and `unreachable` (each `?? []`).
- Apply: `{ outcome: "applied", added: [{n,section,text,source}] /* LIST, window expects number */, cv_path, backup }`.

### market (save:false)
```
{ window:{days,start,end},
  counts:{scraped, scored, above_min_score},
  skills:[{name, count, share, have, trend}],         // window: name, share, have; first 8
  near_misses:{n, rows:[{skill, count}]},              // window: n, rows[].skill
  uncovered_titles:[{title, count}],
  companies:{population, rows:[{name,count,followed}]}, // ignored
  warning: str|null,
  report_path: null }
```
How the test world produces each part:
- Postings scored inside the window (`jobs/postings/<date>/<site>/<id>.json` with `score`, `matching_skills`, `missing_skills`, `scraped_at` or `posted_at`) drive `skills`, `near_misses` and `uncovered_titles`.
- A pre-filled `jobs/skill_aliases.json` covering every skill name **avoids the Haiku call** (no warning). Leaving names out with the stand-in claude produces the grouping-failed warning.

---

## 11. Counts and surprises

**Counts**
- User actions: about **58** distinct actions (controls times action) across the shell, Details fields, Suggest keywords, the save bar, PageSections, the Master CV (Preview, Sources' three buttons and its chips, the draft link), Expand (chips, Read, tick, Add), Markdown link, Hint.
- Failure and edge branches: about **75**, as enumerated above.

**Surprises and bugs**
1. **Enrich apply message bug.** The server returns `added` as a list, so the window says "Added [object Object],… to your CV." The unit test mocks a number. — not covered by a journey
2. **A details Save re-creates a missing `cv.md` as the example CV** (and restores templates) through `_init_core`'s copy step. — ✓ saving the details does not make up a CV
3. **Bad number typed into "Match fit"** (or emptied) fails MCPServer argument validation. Four raw pydantic lines appear in the top alert instead of under the field. The other numeric fields go through `other` and get a clean under-field message. — not covered by a journey
4. Leaving Profile loses unsaved details and CV text. It does not prompt. — not tested: nothing on screen to assert
5. The first CV written refreshes App's profile, so the "You have no CV yet" line goes. — ✓ the first CV saves itself, with no backup, and the sidebar line goes
6. **Market "Add these titles"** does not refresh the Details form (stale values that a later details Save can overwrite). It also seeds an empty `search_keywords` with the role targets. — not covered by a journey; the seeding is right (the role targets are what an empty list searches for): unit: `tests/commands/test_market_cli.py`
7. **The Profile form cannot record a discovery source as "chosen: off"**, so `discovery_unchosen` cannot be cleared by leaving it off. — not covered by a journey
8. A details part that cannot be read leaves the CV and the Stories on the page. — ✓ a part that could not be read says so, and the rest of the page is there

**Unreachable from a real server or the UI**
- The `path` field branch. — not tested: unreachable
- save_cv "the CV is empty". — not tested: unreachable (Save is disabled)
- enrich "no URLs to read" and "no proposal X". — not tested: unreachable
- Language, remote and exclude server errors. — not tested: unreachable

**Network**
- Markdown links call the `open-external` action. — unit: `app/src/renderer/screens/CvEditor.test.tsx`


**Found by the journeys, not in the list above**
- An unreadable (non-UTF-8) `cv.md` opens as an empty editor with no note — ✓ a cv.md that cannot be read as text is said, not shown as an empty CV
- The first CV written leaves no `cv.md.bak` — ✓ the first CV saves itself, with no backup, and the sidebar line goes
- A Use these with no title words empties the saved title words — not covered by a journey
- A Why? error is never cleared — not covered by a journey
- A failed market report is never asked again — not covered by a journey
- Undo after Other… leaves the select on Other… — ✓ puts the city back after Other…
