# Inventory: Profile and CV (desktop app renderer)

Sources read in full: `app/src/renderer/screens/{Profile,PageSections,SettingsFields,CvEditor,Market,Markdown,Hint,Dialog,todos}.tsx|ts`, `profile-form/{form.ts,fields.json}`, `onboarding/parts.tsx` (ChipInput, CityField, TextField, FieldLabel), `Switch.tsx`, `Spinner.tsx`, `AppName.tsx`, `api.ts`, the Profile wiring in `App.tsx`, `app/src/main/{ipc.ts,door-server.ts}` (error envelopes, timeouts, path refusals), and the Python side: `commands/profile.py` (`_init_core`, `_save_cv_core`, `_show_profile_core`, `_profile_field_specs`, `_profile_options`), `core/profile_loader.py` (the `Profile` model and its error lines), `commands/{keywords,enrich,gaps,market,companies}.py`, `core/{companies,claude_cli,lock,skill_aliases,discovery_sources}.py`, `mcp_server.py` (`_tool_errors`, `_EXPECTED_ERRORS`).

Conventions used below:
- **alert** means `role="alert"`. **status** means `role="status"`, which is always the `Spinner`: `<p role=status>` holding the message.
- `named(text)` swaps "The other door" for a styled `<span class="app-name">`. The text content stays the same, so `getByText` still matches.
- Every server error reaches the window as `ApiError.message`, and `errorText(e)` returns that message unchanged. There are three ways to fail:
  1. **Expected core error.** `{"error": str(exc)}` comes back from `_tool_errors` (ValueError, LookupError, FileNotFoundError, ConfigError, CompaniesError, LockHeldError, ClaudeError, DriveError, SyncConflict…). The message is the exception text.
  2. **FastMCP argument validation or an unexpected exception** (e.g. OSError). The result is `isError`, and the text is `Error executing tool <tool>: <pydantic or exception text>`, which can run to several lines.
  3. **Transport errors** (door-server.ts):
     - `The other door took too long to answer`: the timeout. The default is 60 s. Per-tool limits: keywords 150 s, enrich 660 s, skill_gaps 960 s, market 180 s, add_company 180 s.
     - `The other door's server stopped; try again`: the child process died.
     - `<tool> returned something that is not JSON`.
     - Main-process refusals: `unknown tool`, and `enrich takes web addresses only; files are chosen with the file picker.`
- Playwright name matching is a case-insensitive **substring** match by default. Many names here collide, so use `exact: true` where noted (e.g. `Follow` collides with `Stop following`, `CV` with `Draft … CV …`, `Name` with the hint button `About Name`, `Add` with `Add these titles…`).

---

## 0. How the screen is reached (App.tsx)

| Action | Control | Result |
|---|---|---|
| Open Profile | sidebar `nav "Main"` → `button "Profile"` (exact; it has an icon plus text) | Mounts `<Profile key={profileStart.n}>`. Starts on **Details** unless `start` says otherwise. | — ✓ opens on Details with every section and the saved values
| Open Profile from the problem line "You have no CV yet" | `group "Needs you"` → `button "You have no CV yet"` (sidebar foot; wide window only) | Profile opens on the **CV** view (`start={view:'cv'}`) and remounts (key n+1). The line shows only when `show_profile.config` is non-null **and** `cv.exists === false`. It is not shown in demo mode. The example CV gets no line. | — ✓ the sidebar line opens the CV, which says there is none
| Open Settings → Risky sources from Finding | Finding screen's "choose discovery" action (`discovery_unchosen` non-empty) | Settings opens scrolled to `#settings-risky` | — ✓ the sources never chosen are said under Discover, and Enable opens Settings on Risky sources
| `onDraft` (CV view buttons) | see §4 | `setUpAgain()`: calls `show_profile`, then the onboarding wizard opens prefilled with Cancel available (config exists). If `show_profile` fails, **nothing happens** (silent). | — unit: `app/src/renderer/screens/CvEditor.test.tsx`; the silent show_profile failure is not tested (nothing on screen to assert)
| `onSaved` (after a successful details Save) | — | App re-reads `show_profile` (sidebar lines, `discovery_unchosen`) and bumps `refreshKey`, which remounts Matches. **CV Save does not call it**, so the sidebar "You have no CV yet" line stays stale after the first CV is saved (until something else re-reads the profile). | — ✓ the sidebar line goes once the first CV is saved (BUG)
| Leave Profile (any nav button, Find new jobs) | — | Profile unmounts. **Unsaved details and unsaved CV text are dropped silently.** There is no prompt. | — ✓ unsaved CV text survives a look at the details (BUG)
| Remote (phone) | — | Profile is never rendered (`current === 'Profile' && !remote`). Not reachable in Electron. | — not tested: unreachable in Electron (the phone never renders Profile)

There is no gate into the wizard for an invalid config while the app runs. At launch, `config === null` opens the wizard (or remote-setup), so Profile's "could not be read" view is only reachable if config.json breaks **after** launch, or in the demo, where the wizard is not allowed.

---

## 1. Profile shell (Profile.tsx `Wrap`, switcher)

Always present: `heading level 1 "Profile"`.

### 1.1 Details / CV switcher
- `group "Part of the profile"` containing `button "Details"` and `button "CV"` (use exact). Each has `aria-pressed` true or false.
- Click **CV**: `view='cv'`, which renders `CvEditor`. Profile's own state (form values, errors) is kept. — unit: `app/src/renderer/screens/Profile.test.tsx`
- Click **Details**: `CvEditor` **unmounts**. Its unsaved text, open panels, the Market report and any proposals are lost, and reopening re-runs `show_profile`. — ✓ unsaved CV text survives a look at the details (BUG)
- The switcher is **only rendered** in the CV view and in the loaded Details view. It is **absent** in the Details load-error view, the spinner view and the invalid-config view, so from those views you cannot reach the CV except by leaving and re-entering through the sidebar CV line. — ✓ the CV can still be reached when the details cannot be read (BUG)

### 1.2 Details load states
| State | Visible |
|---|---|
| Loading | status "Reading your profile…" | — not tested: a passing spinner
| `show_profile` throws (timeout or server died) | `alert` (p.error) with the error text. There is no retry and no switcher. | — unit: `app/src/renderer/screens/Profile.test.tsx`
| `config === null` (invalid or missing config.json) | `alert` div: "profile/config.json could not be read:" plus `<ul>` of `errors` lines. Real wording examples: `<abs>/profile/config.json: invalid JSON — Expecting value: line 1 column 1 (char 0)`; `<abs>/profile/config.json: remote — Input should 'yes', 'no' or 'hybrid'`; `<abs>/profile/config.json: <key> — Extra inputs are not permitted`; missing file: `<abs>/profile/config.json not found`. The path is absolute, not "profile/config.json". | — ✓ a broken config.json lists what is wrong, with the file and the key; unit: `app/src/renderer/screens/Profile.test.tsx`; a missing file at launch opens the wizard (onboarding area)
| Loaded | Sections (below), the PageSections aside, the save bar | — ✓ opens on Details with every section and the saved values

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
| Boolean, Languages | Plain visible `p.small.muted` under the control | — ✓ opens on Details with every section and the saved values
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
| min_score | How close a match to show | `group` of three radios "Broad" (0.5), "Balanced" (0.65), "Strong" (0.75), plus "Your own (<n>)" checked when config.json holds another value; Hint "About How close a match to show" | number, sent by name | — | — ✓ Save writes the changed text, flag and number fields and nothing else; unit: `app/src/renderer/screens/Profile.test.tsx`

**region "What to skip"** (`profile-skip`). The `exclude` key's own label is never shown.

| Part | Control | Sent as |
|---|---|---|
| companies | ChipInput `textbox "Companies to skip"`, `list "Companies to skip, chosen"` (no hint) | `exclude_companies` (only if that part changed) | — unit: `app/src/renderer/screens/Profile.test.tsx`
| keywords | ChipInput `textbox "Words that rule an ad out"`, `list "Words that rule an ad out, chosen"` | `exclude_keywords` (only if changed) | — unit: `app/src/renderer/screens/Profile.test.tsx`

Errors for `exclude.*` appear under the **keywords** chips only. A real server cannot produce them from the UI (lists of strings). — not tested: unreachable (lists of strings)

Discovery switches are not on Profile: they are how the app works, in Settings (`SettingsFields.tsx`, Risky sources; saved at once) — ✓ `settings.journey.ts`; unit: `app/src/renderer/screens/SettingsFields.test.tsx`. "Ask Claude where a careers page is" and the Claude config folder are left to config.json.

**region "Other"** (`profile-advanced`)

| Key | Label | Control | Notes |
|---|---|---|---|
| enrich_sources | — | Not in the form: the CV part's pages (§4.3) remember and forget them | list | — | — ✓ the pages read before |


**Never shown:** the `config`-section keys (cv_template, cv_content, cover_letter_template, recheck_after_days, scrape_workers, verify_liveness, liveness_expiry_phrases, dedup_*, max_postings_per_site, max_pages_per_keyword, condense_max_chars, prescreen_*, translate_titles, translate_model, revise_model). The `case 'path'` branch of `control()` ("Not set" / "Change it in profile/config.json.") is **unreachable** with the current fields.json, because every path key is in `config`. — ✓ opens on Details with every section and the saved values; the path branch: not tested, unreachable

### 2.4 Chip inputs (all ChipInput instances)
- Typing then **Enter** adds the trimmed text, clears the box and prevents form submit. Enter on empty or whitespace only clears the box. — unit: `app/src/renderer/screens/Profile.test.tsx`
- A duplicate (exact match after trim) is silently ignored, and the box still clears. — unit: `app/src/renderer/screens/Profile.test.tsx`
- `button "Remove <v>"` drops the chip. A chip whose text is long is truncated with an ellipsis and has `title=<v>`. — unit: `app/src/renderer/screens/Profile.test.tsx` (the ellipsis of a long chip: not tested, visual only)
- The chips list is not rendered when empty. — ✓ opens on Details with every section and the saved values

### 2.5 Save bar (`.profile-save`, sticky at the bottom)

`button "Save"` is disabled when there are no changes or a save is running. — ✓ opens on Details with every section and the saved values

| Condition | Visible |
|---|---|
| Changes > 0 | `button "Undo changes"` (disabled while saving) and `p` "1 unsaved change" / "N unsaved changes". N counts **keys**: both exclude parts count as one, and a hidden discovery key that changed still counts. | — unit: `app/src/renderer/screens/Profile.test.tsx` (5 changes, the two skip lists one key)
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
  - **Side effect:** `_init_core` first copies any missing `profile.example/` file into `profile/` (never config.json, story_bank.md or companies.json). If `profile/cv.md` is missing, a details Save **re-creates it as the example CV**. Verified: `copied: ["cv.md"]`. It also restores missing `cv.template.tex` and `cover-letter.template.tex`. So after a details Save, a "no CV" state turns into "example CV". — ✓ saving the details does not make up a CV (BUG)
- Failure: error lines are split by `fieldErrors`: — ✓ each refusal is said under its field, and nothing is written; ✓ a failing save says why above the form; the next one goes through; unit: `app/src/renderer/screens/Profile.test.tsx`
  - A line `^.+?: <key>[.sub] — <why>$` whose key is a known spec goes **under that field** as `p.field-error`. This is **not an alert**.
  - Everything else goes to the top as `ul role=alert` (one `li` per line).
  - Values stay as typed. Errors are cleared only when the next Save starts, not by editing.
  - Nothing is written. Validation happens before the write.
- Server error lines have the form `profile/config.json: <key> — <msg>`. This literal prefix comes from `_init_core`, unlike show_profile's absolute path.
- A whole-model error (the path-exists check: `cv_content not found: /abs/...`, where `cv_template` or `cv_content` points to a missing **custom** path) has no key and no " — ", so it goes to the **general alert**. Default paths are restored by the copy step, so this needs a custom path. — not tested: unreachable from the form: a missing custom path already fails show_profile, so Details never renders
- After a successful init_profile, if the follow-up `show_profile` fails, the page switches to the **load-error alert** even though the save went through. — unit: `app/src/renderer/screens/Profile.test.tsx`
- `init_profile` takes **no ledger lock**, so it works during a run. — not tested: needs a run in progress (Finding area)
- **Undo changes** does `setValues(saved)`. Glitch: CityField's internal `other` flag is **not** reset. After choosing "Other…" and then Undo, the select still shows "Other…" and "Your city" shows the saved city. — unit: `app/src/renderer/screens/Profile.test.tsx`; ✓ puts the city back after Other… (BUG)
- **Unchosen discovery source:** `formValues` turns an absent `*_discovery` key into `false`. Ticking and then unticking is "no change", so it is not sent. **The Profile form cannot record "chosen: off"**, and the Finding screen's `discovery_unchosen` notice persists until the user saves it ticked once and then saves it unticked. — ✓ can record it as off (BUG)

### 2.6 The search terms

See the search_keywords row above: nothing on screen; Claude proposes the terms on Save.

### 2.7 PageSections aside (Details only, wide window)
- `navigation "Sections"` contains `list` → `link "<label>"` for each shown section: "About you", "What to look for", "What to skip", then "CV" and "Stories" (each opens its part; marked with the bar while shown). "In profile/config.json only" never appears. — ✓ opens on Details with every section and the saved values
- The current part has `aria-current="location"`. It is computed on scroll of `.main`: the last heading above a line that moves from 1/3 down the pane to the bottom as you scroll. — unit: `app/src/renderer/screens/Profile.test.tsx` (marking on scroll: not tested)
- Click → `preventDefault`, then smooth `scrollIntoView` of the heading. The link is marked current immediately and stays marked until `scrollend` (even when the section is too short to reach the line). It would also open a closed `<details>`, but there are none on Profile. — unit: `app/src/renderer/screens/Profile.test.tsx`
- **Narrow (<900 px):** `.page-aside{display:none}`, so it is not in the accessibility tree. — ✓ has no sections aside; the form and its save bar work the same

---

## 4. Profile → CV (CvEditor.tsx)

**Load:** `show_profile()` (its own call, separate from Details).

| State | Visible |
|---|---|
| Loading | status "Reading your CV…" | — not tested: a passing state
| Error | `alert` p.error with the text. No retry; the switcher above is still there. | — unit: `app/src/renderer/screens/CvEditor.test.tsx`

### 4.1 Banner variants (`role="note"`, `.cv-example`)

| Data | Note text | Button |
|---|---|---|
| `!cv.exists` | "You have no CV yet. Write it here, or " | inline link `button "Draft it from your CV file or pages"` → onDraft (wizard) | — ✓ the sidebar line opens the CV, which says there is none
| own CV (the example CV too: it is never copied in, so no user has it) | no note | — | — ✓ opens on the CV as saved, with no note

Other data-driven variants:
- **CV exists but unreadable** (`text: null`, e.g. not UTF-8): the editor is empty, there is no note, and Save would overwrite it. — ✓ a cv.md that cannot be read as text is said, not shown as an empty CV (BUG)
- **TODO gaps:** `CvEditor` passes no `onGap` to Markdown, so a `TODO` is **plain text** in the preview. There are no "to fill in" markers here (those exist only in the onboarding Review), and `todos.ts` has no effect in this area. — unit: `app/src/renderer/screens/CvEditor.test.tsx`; ✓ the preview marks each gap to fill in (BUG: the caller expects gaps highlighted; they are plain text)
- **Config invalid** (config null): this view still loads. `show_profile` falls back to `profile/cv.md`. Expand sources become `[]` and Gaps roles become `[]`. — not tested: reachable only through the no-CV sidebar line with a config broken after launch

### 4.2 Editor / preview
- Head: "Your CV" with an inline `button "Markdown"` (the cheatsheet), and on its right `switch "Preview"` (button role=switch, `aria-checked`). — unit: `app/src/renderer/screens/CvEditor.test.tsx`
  - Off: `textbox "Your CV (Markdown)"` (textarea, spellcheck on). — ✓ opens on the CV as saved, with no note
  - On: rendered Markdown (`.markdown.cv-preview`, see §7). The preview is of the **current unsaved text**. — unit: `app/src/renderer/screens/CvEditor.test.tsx`
- Typing clears the "Saved…" message. — ✓ Save writes cv.md and keeps the previous one as cv.md.bak
- **Added lines:** after "Add N to my CV" (§4.4) each added bullet (`- <text>`) is tinted (`.md-added`, the `accent-tint` token): in the preview the list item, in the editor a tinted copy of the text behind the textarea (`.cv-backdrop`, scrolled with it). The first one is brought into view after the add and on each Preview switch. Typing or a Save clears the tint. — ✓ Add puts the ticked ones in cv.md, keeps cv.md.bak and shows them in the editor
- Save bar:
  - `button "Save"` is disabled when the text is unchanged, a save is running, or the **text is empty or whitespace**. — unit: `app/src/renderer/screens/CvEditor.test.tsx`
  - `button "Undo changes"` shows only when dirty (disabled while saving) and restores the saved text. — unit: `app/src/renderer/screens/CvEditor.test.tsx`
  - Status line: status "Saving…" while saving, then "Saved. The previous version is kept as cv.md.bak.", otherwise "Unsaved changes" when dirty. — ✓ Save writes cv.md and keeps the previous one as cv.md.bak
- **Save:** `save_cv({markdown: text})`, then `show_profile` again (the banner can disappear once the text is no longer the example; the editor resets to the file). — ✓ Save writes cv.md and keeps the previous one as cv.md.bak
  - On disk: `profile/cv.md` = text; `profile/cv.md.bak` = the previous content (**only if a cv.md existed**; with no prior CV there is no .bak but the message still says it is kept); `profile/cv.draft.md` is deleted. — ✓ Save writes cv.md and keeps the previous one as cv.md.bak (cv.draft.md deleted); unit: `app/src/renderer/screens/CvEditor.test.tsx`; ✓ the first save does not speak of a backup (BUG)
  - `save_cv` takes no lock.
- **Save errors** (`alert` p.field-error in the save bar): — ✓ a failing save says why and keeps the text (through a tool fault; the empty-CV error is unreachable)
  - "the CV is empty; nothing was written" is **unreachable** (the button is disabled).
  - Permission errors (OSError is not "expected") → `Error executing tool save_cv: [Errno 13] Permission denied: '<path>'`.
  - Transport errors.
- **save_cv always writes `profile/cv.md`**, but `show_profile` reads `config.cv_content`. With a custom `cv_content` path, a Save "succeeds" and the editor then reloads the **other** file, so the edit appears to vanish. Edge case, needs a custom config. — not tested: needs a custom cv_content path, which the form cannot set

### 4.3 The pages, above the CV

- **`list "Pages your CV is read from"`** (only with remembered pages, after the label "Pages"): one chip per page, shown without `https://` (the full address on hover), each with `button "Forget <page>"`, which removes it at once (`init_profile`). — ✓ a page is forgotten by its ×
- Under it, two secondary buttons:

| Control | Enabled | Effect |
|---|---|---|
| `button "Add a page"` | Disabled while the editor has unsaved edits | Opens `dialog "Add a page"` (§4.4) | — unit: `app/src/renderer/screens/CvEditor.test.tsx`; ✓ reads the page asked for, remembers it, and proposes what the CV lacks, all ticked
| `button "Check again"` (only with remembered pages) | Disabled while the editor has unsaved edits | Opens `dialog "Check your pages again"` (§4.4) | — ✓ Check again reads them all and names the page of each proposal

- With the editor dirty, the line "Save or undo your changes before adding from a page." shows under them. — ✓ Save writes cv.md and keeps the previous one as cv.md.bak

### 4.4 The page dialogs: Add a page, Check your pages again

**`dialog "Add a page"`**
- `textbox "Which page?"` (placeholder "github.com/you, your portfolio, a publication list"); **Cancel** (quiet) and **Read it** (primary, disabled while empty; Enter reads too). An address with no scheme gets `https://` in front (the main process refuses anything but http(s)). — unit: `app/src/renderer/screens/CvEditor.test.tsx`; ✓ reads the page asked for…
- `enrich({urls: [page]})`, the spinner "Reading the page (a few minutes)…". A page it could read is remembered at once (`init_profile {other: {enrich_sources}}`); one in `unreachable` puts the field back with "Could not read <page>." under it and is not remembered. — unit: `app/src/renderer/screens/CvEditor.test.tsx`

**`dialog "Check your pages again"`**: every remembered page read at once (spinner "Reading your pages again (a few minutes)…"), each proposal named with " · from <page>" when there are several pages; nothing new: "Nothing new on your pages." — ✓ Check again reads them all and names the page of each proposal

**Both**
- Proposals: "What your CV does not have yet. Untick what should not go in.", then one `group` per CV section (a plain block named by the section, fixed gaps), a `checkbox` per proposal named by its text, all ticked. **Cancel**, **Add N to my CV** (primary; disabled at 0). — ✓ reads the page asked for…
- `enrich` proposes nothing the CV already says, even in other punctuation, Markdown or near wording (the words compared, a line 90% alike), so a second read adds nothing twice. — unit: `tests/commands/test_enrich_cli.py`
- Nothing on the page: "Nothing on that page is missing from your CV." and **Close**. — unit: `app/src/renderer/screens/CvEditor.test.tsx`
- Add: `enrich({apply})`, the spinner "Adding to your CV…" (Esc does not close it then); the dialog closes, the CV is read again and the added lines are tinted (§4.2). No message. — ✓ Add puts the ticked ones in cv.md, keeps cv.md.bak and shows them in the editor
- Errors: a `field-error` alert in the dialog (a read: back to the field; an add: "…cv.md changed since the proposals were made; run `enrich` again" when the CV was saved since). — ✓ a CV saved since the page was read is not overwritten; unit: `app/src/renderer/screens/CvEditor.test.tsx`

### 4.5 Gaps panel: `region "What should I learn?"`

Off in the app for now (`CvEditor`'s `extras`, false: it crowded the page); what follows is the code as it stands.

**Idle and error views**
- ChipInput `textbox "Roles or skills"` (placeholder "Add one and press Enter"), Hint "About Roles or skills" → "What you want to be ready for.", `list "Roles or skills, chosen"`. — ✓ makes a plan for the role targets, shows it and saves it in upskill/
  - Prefilled from `config.role_targets`, **or** from the market's missing skills when opened through "Make a plan for …".
- `checkbox "Also my three best matches"`. — ✓ makes a plan for the role targets, shows it and saves it in upskill/
- `button "Make my plan"` is disabled when there are no roles **and** the box is unticked. Next to it: "One Claude call on your plan, with web search for courses." — unit: `app/src/renderer/screens/CvEditor.test.tsx`

**Run**
- `skill_gaps({targets, top:3 if ticked})`. — unit: `app/src/renderer/screens/CvEditor.test.tsx` (top: 3); ✓ makes a plan for the role targets
- Status "Comparing your CV with the roles and looking for courses (several minutes)…". Timeout 960 s; the server's own is 900 s. — not tested: a passing state

**Done view**
- The report as Markdown (`.markdown.cv-report`, §7). Markdown **tables** in the report (Pass 1 and Pass 2) render as plain paragraphs of `| … |` text, because tables are not supported. — ✓ makes a plan for the role targets, shows it and saves it in upskill/ (tables: not tested, the world report has none)
- "Saved as report-YYYY-MM-DD.md in upskill/." — ✓ makes a plan for the role targets, shows it and saves it in upskill/
- `button "Make another plan"` → idle, with the roles kept. — ✓ makes a plan for the role targets, shows it and saves it in upskill/
- On disk: `<DOOR_HOME>/upskill/report-<today>.md`, overwritten on the same day. — ✓ makes a plan for the role targets, shows it and saves it in upskill/

**Errors** (alert):
- No CV → "<abs> not found (profile/cv.md): set up the profile first" — unit: `app/src/renderer/screens/CvEditor.test.tsx`
- Config missing or invalid — not tested: the CV view with a broken config is reached only through the no-CV line
- Roles removed + box ticked + **no matches** → "nothing to analyse: give a role name, a job (`--job trustpilot`), or top N" — not tested: needs a world with no matches; mette's has many
- Claude errors (stand-in → "claude exited 97: tests never call the real claude"; this is what `cv.e2e.ts` covers), "claude returned an empty report", "claude -p timed out after 900s" — unit: `app/src/renderer/screens/CvEditor.test.tsx` (the exit-code wording)
- Transport timeout — not tested: a 960 s wait
- Not refused for the example CV (only scoring and tailoring refuse it). — not tested: not pinned

**Interactions**
- "Make a plan for …" from Market while the Gaps panel is open or running → Gaps **remounts** (key = planFor.n). The in-flight result is dropped by the window; the server still writes the report. — unit: `app/src/renderer/screens/Market.test.tsx` (an in-flight result dropped: not tested)
- Clicking "What should I learn?" while it is open closes it. — unit: `app/src/renderer/screens/CvEditor.test.tsx`

---

## 5. Market (Market.tsx, at the foot of the CV view): `region` named by its fold button

Off in the app for now, with §4.5 (`extras`).

- Fold control: `button` with `id="cv-market"`, `aria-expanded`, text "What the ads asked for this month". — ✓ counts the ads when opened, once
  - **CSS `::before` adds "▸ " or "▾ "**, which Chromium includes in the accessible name. Match the name by substring, not exact.
  - Closed: "Counts the ads of the last 30 days. New skill names may need one short Claude call on your plan." — ✓ counts the ads when opened, once
- The first open calls `market({save:false})` and shows status "Counting the ads (new skill names may take one short Claude call)…". Timeout 180 s. — ✓ counts the ads when opened, once
- **Closing and reopening never re-asks.** The result or the error is sticky until the CV view remounts. There is no retry for an error. — ✓ counts the ads when opened, once; ✓ a report that failed is asked again when reopened (BUG)
- **Error** (alert p.field-error): — unit: `app/src/renderer/screens/Market.test.tsx` (through a tool fault)
  - ConfigError for an invalid config. A missing config gives defaults, not an error.
  - CompaniesError for a malformed companies.json.
  - Timeout.
  - `market` rarely errors otherwise.

**Done view** (`.market-body`)
- "<scraped> ads read, <scored> scored, <above_min_score> at your minimum score." — ✓ counts the ads when opened, once
- `warning` (p.small.muted) when non-null. Real texts:
  - Claude failed grouping names: "skill names not grouped for some ads (claude exited 97: tests never call the real claude); they are counted as written". **This is what the e2e stand-in produces whenever scored ads have skill names not yet in `jobs/skill_aliases.json`.** — unit: `tests/commands/test_market_cli.py`
  - Corrupt aliases file: "skill_aliases.json could not be read (<exc>); skill names are counted as written, nothing grouped or saved". — not tested: a corrupt skill_aliases.json: not pinned
  - Lock held while new names need saving (e.g. during a run): "another run of The other door holds the lock (a run is in progress (…); try again when it has finished); skill groups and report not saved". It may be appended to the first warning with "; ". — not tested: needs a run in progress (Finding area)
- `heading level 3 "Most asked for"` is **always** shown. The skills list (`.market-skills`) is empty when there are no scored ads; no empty-state text. — ✓ counts the ads when opened, once
  - Each `listitem "<skill>"` reads "<skill> · NN% of the ads · in your CV|not in your CV". — ✓ counts the ads when opened, once
  - `share` = count / scored. `have` = the skill appears in matching_skills more often than in missing_skills. Only the first 8 are shown.
- **Make a plan:** missing = the first 3 of the top 8 with `have:false`. Shown only if any exist. — unit: `app/src/renderer/screens/Market.test.tsx`
  - `button "Make a plan for A"` / "Make a plan for A and B" / "Make a plan for A, B and C". — unit: `app/src/renderer/screens/Market.test.tsx`
  - Click → the Gaps panel opens (remounted) with these skills as targets. Role targets are replaced, not merged. — unit: `app/src/renderer/screens/Market.test.tsx`
- `near_misses.rows` non-empty → "What kept <n> ads just under your minimum: s1, s2." Band = [min_score−0.15, min_score). — ✓ counts the ads when opened, once
- `uncovered_titles` non-empty (match titles at or above min_score containing no search keyword, case-insensitive substring): — ✓ counts the ads when opened, once
  - `heading level 3 "Titles your search does not cover"`
  - "T1 (3), T2 (1)"
  - `button "Add these titles to my search"` → Dialog `dialog "Add these titles to your search?"`, body "The job boards will also be searched for T1, T2.", `button "Cancel"`, `button "Add"` (exact). Escape or Cancel closes it. — ✓ Add these titles to my search asks first, then adds them to the search keywords
  - **Add:** the dialog closes, then `show_profile`, then `init_profile({search_keywords: current + titles not already present})`. — ✓ Add these titles to my search asks first, then adds them to the search keywords
    - `current` = `config.search_keywords` if non-empty, otherwise `config.role_targets`. So an empty search_keywords gets **seeded with the role targets** plus the titles. — unit: `tests/commands/test_market_cli.py`
    - Success: `p.small` "Added to your search keywords." On disk, config.json `search_keywords` is updated. — ✓ Add these titles to my search asks first, then adds them to the search keywords
    - Error: the raw error text in the same `p.small` (no alert, no `named`). For example, with an invalid config (null), it sends only the titles and init then fails with the file's validation lines joined in one paragraph. — unit: `app/src/renderer/screens/Market.test.tsx`
    - The button stays, and adding again is a no-op apart from the message. — not tested: a second Add: not pinned
    - **Stale:** the Details form (if already loaded in this Profile mount) still shows the old search keywords. A later details Save that touches search_keywords would overwrite them. `onSaved` is not called, so Matches are not refreshed. — ✓ titles added from the report show in the details (BUG)
- Side effect even with `save:false`: when new skill names were grouped successfully, `jobs/skill_aliases.json` is **written** (under the ledger lock). No `jobs/market/report-*.md` is written. — ✓ counts the ads when opened, once (skill_aliases.json written)
- `companies` and `trend` in the result are ignored by the window. — not tested: the window ignores `companies`: following a repeat employer from the market report is not in the app

---

## 6. Dialog (Dialog.tsx), used by Market

- `role=dialog`, `aria-modal=true`, named by its `h2` title, inside `.scrim`. — ✓ asks first; Cancel and Escape keep the employer
- Initial focus goes to the `initialFocus` selector if given, otherwise the first focusable element. Neither use here passes one, so focus goes to Cancel. — ✓ asks first; Cancel and Escape keep the employer
- Tab on the last control wraps to the first; Shift+Tab on the first wraps to the last. — not tested: Tab wrapping: not pinned
- Escape calls onClose and stops propagation. — ✓ asks first; Cancel and Escape keep the employer; ✓ Add these titles to my search asks first
- **Clicking the scrim does not close.** There is no close (×) button. — not tested: the scrim: not pinned
- Narrow: the width is `min(480px, 100vw − space-8)`.

## 7. Markdown (Markdown.tsx), used by the CV preview and the Gaps report

- `#`…`######` render as headings **one level down**: h1→h2 (`display-s`), and h3–h6 use `md-heading`, capped at h6. — unit: `app/src/renderer/screens/CvEditor.test.tsx`; ✓ makes a plan for the role targets (report headings)
- Blank lines separate paragraphs, and lines inside a paragraph are joined with a space.
- `- * +` give `ul` items; `1.` or `1)` give `ol` items. A list item continues on lines indented by 2 spaces. — ✓ makes a plan for the role targets, shows it and saves it in upskill/
- Inline formatting: `**bold**`, `*italic*`, `` `code` ``, `[label](url)`. Underscore emphasis and tables are not supported; table rows become paragraph text.
- Links:
  - `http(s)` → `button "<label>"` (`.link-inline`); click calls `window.door.openExternal(url)`, which opens the system browser. Stub `shell.openExternal` in e2e. — unit: `app/src/renderer/screens/CvEditor.test.tsx`
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

- The sidebar becomes a bottom tab bar (`nav "Main"`, the same `button "Profile"` with an icon). `.sidebar-foot` is `display:none`, so **Find new jobs and the "Needs you" problem lines (e.g. "You have no CV yet") are not reachable from Profile**. They show on top of Matches only. — ✓ has no sections aside; the form and its save bar work the same (the "Needs you" group hidden)
- PageSections (`navigation "Sections"`) is hidden. — ✓ has no sections aside; the form and its save bar work the same
- The rest is the same single column. The save bar is still sticky at the bottom; Dialog and Hint popups are constrained to the viewport. — ✓ has no sections aside; the form and its save bar work the same; unit: `app/src/renderer/screens/CvEditor.test.tsx`
- Profile is never "pushed", so the shell is never `.pushed` here.

---

## 10. Result shapes the renderer reads (to build a test world)

### show_profile (Profile Details, CvEditor, Market add-titles, App)
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
- `role_targets` (Gaps prefill and the search terms proposed on Save)

### init_profile (Details Save, Market add titles)
- Reads only success or throw. `{config_path, copied:[rel paths]}`.
- Error: `{"error": "profile/config.json: <key> — <msg>\n..."}`, or an isError text for bad named-argument types.

### keywords (on Save, after a change of role targets or languages)
`{ role_targets, keywords: [str], topic_terms: [str], saved: false }`. The window reads `keywords` and `topic_terms` (each `?? []`).

### save_cv
`{ cv_path, backup }` or `{error}`. Only success or throw is read.

### enrich
- Propose: `{ outcome: "proposed"|"nothing_new", urls, proposals: [{n, section, text, source}], unreachable: [str], proposals_path? }`. The window reads `proposals` and `unreachable` (each `?? []`).
- Apply: `{ outcome: "applied", added: [{n,section,text,source}] /* LIST, window expects number */, cv_path, backup }`.

### skill_gaps
`{ report_path, report: str (Markdown), targets: [{kind,label,job_id?}], plan_items }`. The window reads `report` (`?? ''`) and `report_path` (basename shown).

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

### list_companies
- `{ companies: [{ name, feed:{platform,id}|null, status: followed|unfollowable|unresolved|dormant, reason, refusal: must_not|cant_yet|null, found_via, evidence, aliases, first_seen, last_checked, collect_problem:{at, outcome: blocked|failed, reason}|null, last_relevant: iso|null }], counts }`.
- The window reads `name`, `status`, `last_relevant` and `collect_problem`; the rest come back through why_company.
- The file is `profile/companies.json`: `{"version":1,"companies":[...]}`, with `extra="forbid"`.

### why_company
`{ company: <same row>, postings: n, by_source }`. The window reads `postings`, `company.found_via`, `company.feed.platform`, `company.refusal` and `company.reason`. `postings` counts `jobs/postings/*/*/*.json` whose `employer` equals the name or whose `company` name_key matches.

### add_company
`{ dry_run:false, results:[{ input, name, status, platform, entry, reason, refusal, evidence, candidates, new }] }`. The window reads `results[0].name`, `.status`, `.reason` and `.refusal`.

### remove_company
`{ removed:[{name, feed}], not_found:[name] }`. Only success or throw is read.

---

## 11. Counts and surprises

**Counts**
- User actions: about **58** distinct actions (controls times action) across the shell, Details fields, Suggest keywords, the save bar, PageSections, the CV editor (Preview, Save, Undo, three tools, two draft buttons), Expand (chips, Read, tick, Add), Gaps (chips, tick, Make my plan, Make another plan), Market (fold, Make a plan, Add titles + dialog), Markdown link, Hint.
- Failure and edge branches: about **75**, as enumerated above.

**Surprises and bugs**
1. **Enrich apply message bug.** The server returns `added` as a list, so the window says "Added [object Object],… to your CV." The unit test mocks a number. — ✓ Add says how many it added (BUG)
2. **A details Save re-creates a missing `cv.md` as the example CV** (and restores templates) through `_init_core`'s copy step. — ✓ saving the details does not make up a CV (BUG)
3. **Bad number typed into "How close a match to show"** (or emptied) fails FastMCP argument validation. Four raw pydantic lines appear in the top alert instead of under the field. The other numeric fields go through `other` and get a clean under-field message. — ✓ a word for the minimum score is said plainly under its field (BUG)
4. **Switching CV → Details unmounts CvEditor**, losing unsaved CV text. Leaving Profile loses everything. Neither prompts. — ✓ unsaved CV text survives a look at the details (BUG)
5. **CV Save does not refresh App's profile**, so the "You have no CV yet" sidebar line stays stale. — ✓ the sidebar line goes once the first CV is saved (BUG)
6. **Market "Add these titles"** does not refresh the Details form (stale values that a later details Save can overwrite). It also seeds an empty `search_keywords` with the role targets. — ✓ titles added from the report show in the details (BUG); the seeding is right (the role targets are what an empty list searches for): unit: `tests/commands/test_market_cli.py`
7. **The Profile form cannot record a discovery source as "chosen: off"**, so `discovery_unchosen` cannot be cleared by leaving it off. — ✓ can record it as off (BUG)
8. The Details error, spinner and invalid-config views have **no Details/CV switcher**. — ✓ the CV can still be reached when the details cannot be read (BUG)

**Unreachable from a real server or the UI**
- The `path` field branch. — not tested: unreachable
- "Nothing was recorded." (add_company always returns one result). — not tested: unreachable
- save_cv "the CV is empty". — not tested: unreachable (Save is disabled)
- enrich "no URLs to read" and "no proposal X". — not tested: unreachable
- Language, remote and exclude server errors. — not tested: unreachable

**Network**
- Follow (`add_company`, probe=true) makes **real network requests**, so it needs stubbing for deterministic e2e. — the world (boot.py) sets `companies._session` to None: no request leaves, a link is told by its shape (Ashby, Teamtailor, HR-ON, Jobaffinity), a name finds no feed. Greenhouse and Lever links are not detected there (boot.py replaces those modules with the world feeds).
- Markdown links call `openExternal`. — unit: `app/src/renderer/screens/CvEditor.test.tsx`


**Found by the journeys, not in the list above**
- An unreadable (non-UTF-8) `cv.md` opens as an empty editor with no note — ✓ a cv.md that cannot be read as text is said, not shown as an empty CV (BUG)
- Saving the first CV says "The previous version is kept as cv.md.bak." when there was none — ✓ the first save does not speak of a backup (BUG)
- A Use these with no title words empties the saved title words — ✓ a proposal with no title words keeps the title words you have (BUG)
- A Why? error is never cleared — ✓ a Why? that works after one that failed shows only the answer (BUG)
- A failed market report is never asked again — ✓ a report that failed is asked again when reopened (BUG)
- Undo after Other… leaves the select on Other… — ✓ puts the city back after Other… (BUG)
- The CV preview marks no TODO gap — ✓ the preview marks each gap to fill in (BUG)
- Visual: the sticky Details save bar is drawn above the dialog scrim (see `profile-employers-stop-following.png`): not asserted.
