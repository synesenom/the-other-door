# The other door in Claude Code

The usual way to use *The other door* is a [Claude Code](https://docs.claude.com/en/docs/claude-code)
conversation in this repo: you say what you want in plain sentences and Claude calls
*The other door*'s tools. This page is what to say; the second half is the
[MCP](https://modelcontextprotocol.io) server that makes it work. Everything here is also a
[shell command](manual-cli.md) with the same options.

## Onboarding

After `./scripts/setup.sh` and `claude auth login` ([Getting started](../README.md#getting-started)),
say `/onboard` in a conversation. It takes your sources (a CV in PDF, DOCX or Markdown, a LinkedIn
PDF export, your website or online portfolio), drafts `profile/cv.md` from them, infers your details,
job titles and search terms, and asks only for what it could not find, plus one optional question: what
matters to you in an employer or a job and what you rule out, in your own words. Say "change what matters to me"
later and `init_profile` saves the new text in `other` (`{"preferences": ...}`); it applies from the next run. Everything comes together in
one review, written only after you confirm; then the first search starts. Each step is a tool
(`draft_cv`, `infer_basics`, `suggest_titles`, `keywords`, `preview_matches`, `init_profile`, `save_cv`,
`find_jobs`), so you can also ask for any one of them on its own: "here's my old CV, draft the new
one", "what titles should I look for?", "expand my search keywords".

Later, `/expand` adds to the CV what your public pages evidence (the `enrich` tool), and
`/upskill` writes a learning plan for the gaps between your CV and a role or some matches
(the `skill_gaps` tool) — see [Skills](skills.md).

## A typical review session

A Claude Code session in this repo is a few minutes of fetching and deciding, with no job
ids and no file paths:

![A review session in Claude Code: what's new, discard one, show the Head of Finance one, prepare it, done](demo/claude.gif)

Things you can say:

- "Get me today's jobs." → `find_jobs` (search → discover → follow → collect → match: the boards, the
  employers LinkedIn shows, their own feeds, then scoring; only what is new). "Just look at the boards" → `find_jobs` with
  `step="search"`; "read my followed employers" → `step="collect"` (`company=["BEC"]` for one);
  "what feeds would you add?" → `step="follow"` with `dry_run=True`.
- "What's new?" → `status_summary`, then `list_matches(new_only=True)`, best first. From then
  on name a job any way you like: "the Trustpilot one", "the data role at Novonesis".
- "Show me the Trustpilot one." → `show`; "not the Aarhus one, too far" → `set_status` `discarded` with the reason as `notes`.
- "Here's an ad I found: …" → `import_posting` with the pasted text (or just its `url`:
  the page is fetched and Haiku reads its title and company); it is scored right away, so
  you hear its score and can say "prepare it" or "not this one".
- "Prepare the Trustpilot one." → `prepare` (minutes — the tailor agent runs); "prepare the best one" → `prepare` with no job.
- "Let me see it." → `show`: once prepared, it adds both PDFs, page images, keywords, what was tailored, page counts, letter length.
- "Tighten the letter's second paragraph." → `revise`; "undo that" → `revise` with `undo`.
- "Mark Trustpilot applied." → `set_status` (Claude asks how you sent it — easy apply, the company's site, a referral, or they came to you — unless you said); "I applied to Trustpilot on the 3rd" → the same with `at`, so the history keeps when it happened; "Pleo never answered after the interview" → `set_status` `ghosted`. The first time an application is marked sent, the materials are copied to `jobs/output/<id>/sent/`; if its ad is not on disk or is only a snippet, Claude says so.
- "I have a technical interview with Trustpilot on Friday" → `set_status` `interview:technical`, one call per round; "they turned me down" → `rejected` (it ends the last round). The interview statuses are `interview:screening` (pre-screening, HR), `interview:impression` (first non-technical interview), `interview:assessment` (personality/cognitive test) and `interview:technical`; when you don't say which, Claude asks with the four as options. "How do my interviews go?" → `status_summary`'s `interviews`: each kind, passed / rejected / ghosted / withdrawn / pending; "what are my pass rates?" → its `pass_rates`: for the application (did it lead to an interview) and each kind of interview, the decided rounds passed, the rate and its one-sigma Wilson interval (`low`, `high`).
- "I'm done." → `mark_reviewed`, so next time "new" means new since now.
- "Set me up." → asks for your details, then `init_profile`; `doctor` to confirm.
- "Here's my old CV, draft the new one." → `draft_cv` with the file (put it in *The other door*'s folder first: the tools that take a file refuse one outside it) and any public pages;
  the draft is shown before it goes into `profile/cv.md`.
- "Add Trustpilot" / "follow careers.trackman.com" → `add_company` with `dry_run` first, shown with
  its evidence, then `add_company` on your yes.
- "Are any of my companies the same employer?" → `merge_companies` (proposes; merges only what you confirm).
- "Which companies do I follow?" / "which couldn't be followed?" → `list_companies`;
  "why don't I follow Danske Bank?" → `why_company`; "stop following Trustpilot" → `remove_company`.
- "Expand my search keywords." → `keywords` proposes `search_keywords` from your
  `role_targets`, in English and each of your job-ad `languages`, and the `topic_terms` that make a job title
  relevant to you; after you confirm, `init_profile` saves them.
- "Add what's on my website to my CV." (or `/expand`) → `enrich` proposes bullets from the
  pages; after you pick, `enrich` again with `apply` writes them.
- "Add a story about …" / "what stories do I have?" → `list_stories` shows the bank; `draft_stories` (with `text`; `from_cv` gives only one story, an example: the bank is for what the CV does not say, so ask the user for their stories) proposes stories and writes nothing: show them and any `conflicts` (the text won), fill what is empty with the user (never invent it), and after a yes `save_story` for each; "change the Trustpilot story" → `save_story` with `replace` (the old title); "drop that story" → `remove_story` after a yes. The made-up example bank is refused until the user agrees to start their own (`replace_example`).
- "What salary can I expect for the Trustpilot one?" → `salary_estimate` gives the range in the local currency with its period, where your experience puts you in it and the pages it was read from (one Haiku call with a web search, saved in `jobs/salary.json`, so a second look makes no call; `refresh` asks again). It is an estimate from public pages, not advice; with no source to cite it gives no number. `prepare` asks by itself for the job it prepared (reused while under 90 days old, skipped when the plan is close to its limit), and `show` carries the saved one as `salary`.
- "How does the market look?" → `market` counts the last 30 days of scraped ads (seconds; one Haiku call, only for skill names not yet in `jobs/skill_aliases.json`, groups variants such as "Excel" and "Microsoft Excel" and drops non-skills):
  the most requested skills and whether you have them, near misses (what kept ads just under
  `min_score` below it), titles in your matches that no search keyword covers, and companies posting
  repeatedly (marked when you already follow them; `scored_companies=True` counts only scored ads). "Follow Pleo" on an unfollowed repeat employer → `add_company`. Then "make a plan for the top 3 gaps" → `skill_gaps` with those skills as targets;
  "add those titles" → after you confirm, `init_profile` with `search_keywords` (your current keywords plus those titles).
- "What should I learn for the Trustpilot job?" (or `/upskill trustpilot`) → `skill_gaps` writes the learning plan
  (minutes).

## The MCP server behind it

### Registering it

Opening this repo in Claude Code registers the server automatically through the committed
`.mcp.json` (check with `/mcp`):

```json
{
  "mcpServers": {
    "door": {
      "command": ".venv/bin/python",
      "args": ["-m", "door.mcp_server"]
    }
  }
}
```

The server speaks the standard `stdio` transport (`./door serve` also serves it over HTTP for a paired phone; see [the CLI manual](manual-cli.md#your-phone-serve)). Other MCP clients can point their own
config at the same `command`/`args`. To run it by hand:

```bash
PYTHONPATH=src poetry run python -m door.mcp_server
```

The entry runs the interpreter of the in-project virtualenv directly (Poetry creates it
in `.venv/`, see `poetry.toml`), so Claude Code does not need Poetry on its PATH — a GUI-launched
app rarely has it. The server needs the Python dependencies installed (`./scripts/setup.sh`
or `poetry install`); until then Claude Code reports it as failed to connect, and
`./door doctor` says so in its `mcp server` line. On Windows the
interpreter is `.venv/Scripts/python.exe`, so `doctor --fix` registers a local-scope entry for it
(`claude mcp add --scope local door -- …`), which takes precedence over `.mcp.json`'s.
`.claude/settings.json` pre-approves the server (`enabledMcpjsonServers`), so Claude Code
starts it without asking. `doctor --fix` ends by starting the server once and checking it answers.
In a Claude Code **cloud session** (claude.ai/code), which starts from a fresh clone with no
`.venv/`, the `SessionStart` hook in the same file (`.claude/hooks/session-start.sh`) runs
`poetry install` first, so the server connects there too; it does nothing in a local
session, where `./scripts/setup.sh` is the install.

### Tools

| CLI command | MCP tool | Returns |
|-------------|----------|---------|
| `find [--boards ...] [--skip STEPS]` | `find_jobs` (the five steps, minus `skip`) | the run record (also written under `jobs/runs/`): a block per step that ran (counts, per-site outcomes, a one-line `summary`; `skipped` says why a step did not run), scored / failed counts and the top matches |
| `jobs [list]` | `list_matches` | ranked matches at or above `score` (default: your `min_score`): id, score, title, `title_en` (the English translation of a title in another language), company, location, status, `is_new` (never descriptions); `scored` is how many postings the model scored whatever the filters (0: nothing yet); `weak` is null, or, until a posting has first reached `min_score` (default view only), the 3 best below it (`matches`, rows like the others) with a `hint` (`sources`: discovery sources serving your city are off, named in `sources`; `keywords`: broaden the search keywords): present them as weak matches, never as matches, and say the hint; `new_only=True` for "what's new?"; `status="applied"` (or another status) for the postings you have taken that far; `ongoing=True` for everything still in play (prepared, applied, interview:…, offer); `closed=True` for the applications that ended (rejected, ghosted, withdrawn); each row also has `updated_at` and its interview `rounds` |
| `jobs show <job_id> [--open]` | `show` (`open=True` opens the PDFs on the server's desktop) | one posting in full, plus its status, its `history` (every status change with its date and note, from prepared and applied on; each interview round also with its `result` — passed, rejected, ghosted, withdrawn or pending), the language it is written in and what it says about language (`language_requirement`) and about a visa or work permit (`work_permit`; `list_matches` rows carry it too) — the only tool that returns a description; `materials.readability` lists what an ATS would not read back from the PDFs (name, headings in order, keywords, garbled or empty text; `[]` clean); `integrity` says whether the integrity gate found hidden text or lines aimed at a model in the ad (`verdict` `suspicious`, with the `findings` it removed: tell the user); once prepared, `materials`: PDF and page-PNG paths, emphasised keywords, what was tailored (cut, kept or condensed per section), page counts, letter word count, and `unsupported`: the numbers, years, employers, skills, certifications and degrees of the CV or letter that your `cv.md` and story bank do not contain, each with the line it is in (`[]` clean, `null` not checked because there is no `cv.md`) |
| `jobs add <file, - or URL> [--title] [--company]` | `import_posting` | the new posting's id, path and score (it is scored right away); the tool also takes pasted `text`, and either surface fetches a URL given alone |
| — (ask Claude) | `revise` | `revised` / `undone`, the file, its `.bak`, compile and render results |
| `jobs summary` | `status_summary` | pipeline counts, ledger breakdown, `interviews` (each kind: passed, rejected, ghosted, withdrawn, pending), `application` (the same for the application itself: did it lead to an interview), `pass_rates` (per stage: `passed`, `decided`, `rate`, `low`, `high`, a one-sigma Wilson interval), `since_last_review` (runs, new matches, failed sites) and `employers` (how many are followed, unfollowable, unresolved) and `drive` (`connected`, `account`, `last_synced`, `last_error` of the Google Drive sync) and `plan` (how full the Claude plan's 5-hour and 7-day windows are, about how many more finds and prepares fit, and what used the plan this week; null until a call has read it) |
| `jobs status [<job_id>] [<status>] [--notes] [--at]` | `set_status` | the new status and its `notes` (why, or how an interview went: what was covered and said, your impressions; `discarded` is "not this one"; an interview round is `interview:<kind>`), `at` (when it happened), `current` (the status now: a change dated before the latest one leaves it), `sent_dir` (the copy of the materials taken when it was first sent) and a `warning` when the ad is missing or a snippet, or the materials sent hold figures not in your `cv.md` |
| `jobs prepare [job_id]` | `prepare` | `prepared` / `skipped` / `failed`, the material files, any missing ones, `readability` (what an ATS would not read back from the PDFs) with a `warning` when something remains after the one automatic retry of the tailor for a missing name, heading or keyword; with no job, the top unapplied match (or `no_matches`) |
| — (the tailor agent's) | `check_facts` | `{round, rounds_left, unsupported}`: the offline fact check of the finished CV and letter (what `show` lists under "Not in your CV"), two rounds a prepare run; `keep` records why an item that stays is true |
| — (the tailor agent's) | `compile` | per-file compile result; with `render`, PNG paths and `page_count` per PDF |
| `init [--name …] [--set KEY=VALUE]` | `init_profile` | the written config path and copied example files (`--set` ↔ the tool's `other`) |
| `init --show` | `show_profile` | no arguments: `config` (the validated profile, or `None` with `errors` lines when it is invalid or missing), `cv` (`path`, `exists`, `is_example`, `text`, `headline`, `sections` with `title`, `roles`, `bullets`), `templates` (`cv`, `cover_letter`) and `story_bank` (`path`, `exists`, `is_example`: still `profile.example/`'s file), `enrich_sources`, and `options` for a profile form (`cities` with `country` and `boards`, the supported `languages`, the `worldwide_boards`); writes nothing |
| `init` (the wizard's reading step) | `draft_cv` | the draft's path (or the CV path and its `.bak` with `write=True`), the sources read, what each contributed (`provenance`), the `todos` left and the draft text (`markdown`) |
| `init` (the wizard's save) | `save_cv` | `cv_path` and `backup`: the reviewed CV text put in place as `profile/cv.md` (the old one kept as `.bak`, the draft removed); empty text is refused |
| `init` (the photo question) | `save_photo`, `remove_photo` | `photo_path` of the CV photo kept as `profile/photo.jpg` (a JPEG or PNG inside the data folder, checked, EXIF and GPS dropped, scaled), or an `error` with the reason; `remove_photo` answers `removed`. `/onboard` asks once, only where the city's country has a photo `optional` or `expected` |
| `cv enrich [URL ...] [--apply 1,3] [--all] [--model …]` | `enrich` | with `urls` (or none, for `enrich_sources`): numbered `proposals` (section, text, source) and `unreachable` URLs, nothing written; with `apply=[n, …]` or `all=True`: the `added` items, the CV path and its `.bak` |
| `cv stories [list]` | `list_stories` | `path`, `exists`, `is_example` and `stories`: `title`, `context`, `action`, `result`, `learning` |
| `cv stories add …` | `save_story` | `title`, `context`, `action`, `result`, `learning` (all required: an empty one is named in the `error`), optional `replace` (the old title: replaces that story, a new `title` renames it) and `replace_example`: `outcome` `added` or `replaced`, `story`, `count`. A title already in the bank, or the example bank, is an `error` |
| `cv stories remove TITLE` | `remove_story` | `outcome` `removed`, or an `error` listing the titles |
| `cv stories draft [TEXT] [--from-cv] [--model …]` | `draft_stories` | exactly one of `text` and `from_cv`: `outcome` `proposed` or `nothing_new` and `stories` (as `list_stories`, plus `missing`, the empty fields, and `conflicts`, the facts on which the text and `cv.md` differ; the text wins); with `text`, `cv.md` is read beside it; one sonnet call, nothing written |
| `ask "QUESTION"` | `ask` | `answer` (a sentence or two), `go_to` (`screen`: matches, posting, applications, employers or cv, with `job_ids`; or null) and `sources` (the tools it read). One Haiku call with the read tools only; in a conversation, call the read tools directly instead: `ask` serves the desktop app and the shell |
| `jobs query [filters]` | `query_jobs` | `count`, `average_score`, `by_site`, `by_company`, `by_status`, `by_month` and the best `rows` (`id`, `title`, `company`, `score`, `status`, `site`, dates) for postings matching `since`, `until`, `site`, `company`, `status` (or `interview` for any round), `min_score`, `max_score`, `language`, `has_materials`; read only — for questions no other tool answers |
| `jobs salary [JOB] [--refresh] [--model M]` | `salary_estimate` | `job_id`, `title`, `company`, `found`; when found `low`, `high`, `currency`, `period` (`month`/`year`), `gross`, `position` (`below`/`within`/`above`), `basis`, `sources` (`title`, `url`), `ad_salary`, `as_of`, `cached`; else a `message` and no number |
| `market [--days N] [--scored-companies] [--no-save]` | `market` | `window`, `counts` (scraped, scored, above `min_score`), `skills` (name, count, share, `have`, `trend`), `near_misses`, `uncovered_titles`, `companies` (`population`, and per row `followed`), a `warning` (text when the grouping call failed, else null) and the `report_path` (`jobs/market/report-<date>.md`) |
| `cv gaps [TARGET ...] [--top N] [--model …]` | `skill_gaps` | the report path (`upskill/report-<date>.md`), the targets analysed and the number of plan items |
| `init` (the wizard's reading step) | `infer_basics` | what a CV says: `name`, `email`, `location` (a known city; `unsupported_location` names any other), `languages`, `remote`, and `missing`, the only things to ask |
| `cv titles [TITLE ...] [--hint …] [--languages …] [--model …]` | `suggest_titles` | `titles`: each `title` with its `reason` and whether it is `recommended`; writes nothing |
| — (a wizard's first look) | `preview_matches` | a few ads of one job board scored against the CV, from answers not saved yet (`board`, `matches`, or a `warning`); writes nothing |
| `init` (the wizard's reading step) | `keywords` | the role targets used, the 8–15 proposed `search_keywords` per language and the `topic_terms` (`saved` and the config path with `save=True`) |
| `doctor [--probe]` | `doctor` | every prerequisite check with its fix (the `profile` check lists every `profile/config.json` error), the last run, each site's last scrape; the `claude CLI` check carries `details.path`; the `claude login` check carries `details` (`loggedIn`, `authMethod`, `apiProvider`, `configDirectory`, and `email`, `orgName`, `subscriptionType` for a plan login; never the organisation id); `probe=True` adds a live `scraper: <site>` probe per site |
| `doctor --fix [--probe]` | `setup` | the install plan and `needs_confirmation`; with `yes=True` the per-tool results, `doctor` after, and what's left to do. `probe=True` probes the sites so `fixes` can offer a drifted scraper; `fix_scrapers=[site]` (with `yes`) repairs one on a branch and opens a PR |
| — ("I'm done") | `mark_reviewed` | the new review timestamp (and the previous one) |
| — (the desktop app's) | `mark_seen` | the job opened, no longer new |
| `companies [list] [--status …] [--found-via …]` | `list_companies` | the employers (`name`, `feed`, `status`, `reason`, `found_via`, `evidence`, dates) and the `counts` per status |
| `companies add NAME_OR_URL ... [--dry-run] [--no-probe]` | `add_company` | per input: the `status` (followed, unfollowable, unresolved), the platform and entry or the `reason`, the `evidence` or the slugs tried, and whether it is `new`; nothing written with `dry_run=True` |
| `companies remove NAME ...` | `remove_company` | the employers `removed` and the names `not_found` |
| `companies merge [KEEP FOLD]` | `merge_companies` | no names: the `candidates` (groups of entries sharing a feed or a name, with the `reason`), nothing written; two names: the `merged` entry and the `removed` name. Claude proposes the groups and merges only the pairs you confirm |
| `companies why NAME` | `why_company` | the list entry and how many postings in `jobs/` came from it (`postings`, `by_source`), or an `error` when it is not on the list |
| `data export [PATH]` | `export_data` | the archive's path, file count and size |
| `data import ARCHIVE` | `import_data` | file count, the backup folder, any config path this computer lacks or failed upgrade (warnings), and `data_versions` (what the archive carried); an archive from a newer version or an older major is refused with nothing changed |
| `data connect` | `connect_drive` | the Google account connected (a browser opens for the user; waits up to five minutes) |
| `data sync [--keep-local \| --keep-drive]` | `sync_data` | `action` (`push`, `pull`, `nothing`); an `error` naming both options when Drive and this computer both changed |
| `data disconnect` | `disconnect_drive` | whether it was connected |
| `data report [PATH]` | `report_problem` | the report's path, the names in it and its size ("something is broken, make a report") |

The tools marked — have no command: `revise` and `mark_reviewed` are things you say to
Claude, `mark_seen` is the desktop app opening a posting, `preview_matches` is what a wizard shows while you check your answers, `compile` and `check_facts` are the tailor agent's (`revise` recompiles on its own, so a `.tex`
never changes without its PDF).

Every tool that takes a `job_id` also accepts words from the job's company and title
(`"trustpilot"`): one match is used; several come back as `candidates`, and Claude asks you
which. A tool takes the same parameters as its command (`find_jobs`'s `boards`,
`show`'s `open`, …).

Expected failures (an invalid job id, an invalid `profile/config.json`, …) come back as `{"error": "..."}` with the same wording the CLI prints. While a `find`
holds the `jobs/` lock, tools that write the ledgers return "a run is in progress".

`status_summary` also returns `in_progress`: `null` when nothing is running, otherwise
`{purpose, pid, started_at, message, done, total, site, stage, updated_at}`, the latest
progress event of the `find` that holds the lock (read from `jobs/.progress.json`,
so it works for a run started from another terminal too).

### Long-running tools

`find_jobs` and `prepare` take minutes and stream progress: while they work the server sends MCP progress
notifications (a message such as `jobindex: 'accountant': 12 results` or
`tailoring job-a · 3m20s elapsed`, with a count that only goes up), which clients such as
Claude Code show as the call's status. The notifications also count as activity for the
idle timeout, so the 30-minute limit below only applies to a step that is silent that long.
Both run in a worker thread, so the server stays responsive: `status_summary`
answers during a `find` and reports how far it is (`in_progress`, see above, from
`jobs/.progress.json`). Only one of the two runs at a time; a second call returns an
`{"error": "another long-running tool ... is already in progress"}` at once, so wait
for the first rather than retrying in a loop. Claude Code aborts a
call to a stdio server after 30 minutes without a response
(`CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`, milliseconds); the overall limit is
`MCP_TOOL_TIMEOUT`, or a per-server `timeout` in `.mcp.json`. Start a very large unbounded
`find` [from a shell](manual-cli.md) instead.

For the shell commands behind the tools, see [*The other door* from the terminal](manual-cli.md).
For how the CLI, MCP tools and skills/agents share one core, see
[architecture.md](architecture.md#two-modes-one-core).
