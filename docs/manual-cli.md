# The other door from the terminal

*The other door* is meant to be driven from a [Claude Code conversation](manual-claude.md), but every
step is also a shell command, for when you prefer a terminal, or want to script it. Both drive the same code: a command and its
MCP tool behave identically (see [architecture.md](architecture.md#two-modes-one-core)).

Every command runs as `./door <command>` from the repo checkout (on Windows,
`.\door <command>`). Add `--help` to any command for all its options. `./door --help` groups them:

```
Set up      init · doctor
Find        run
Your lists  jobs [show|add|status|summary|prepare] · companies [why|add|remove|merge]
Your CV     cv [enrich|gaps]
Move        data [export|import|connect|sync|disconnect]
```

`find` is the automatic part; `jobs` and `companies` are your two lists, viewed and edited by
hand with the same verbs (`jobs` and `companies` alone list them).

## Walkthrough

Set up as in [Getting started](../README.md#getting-started) (`./scripts/setup.sh`, then
`claude auth login`). Without `/onboard`, `init` asks the same questions in the terminal:

```bash
./door init          # the setup wizard
./door doctor        # anything still missing?
```

`init` follows the same three parts as the other two ways in, writing only at the end:

1. **Your sources**: your latest CV file (PDF, DOCX, Markdown), a LinkedIn "Save to PDF" export,
   your website or online portfolio. If Claude is missing or you are signed out, it offers to fix
   that first.
2. **Reading them**: `claude -p` calls draft the CV (nothing invented, gaps marked `TODO`), read your
   details and propose job titles and search terms. It asks only for what it could not find.
3. **One review**: everything found, with your titles (each with why it fits, the best ones ticked),
   one optional question about what matters to you in an employer or a job and what you rule out, in your own
   words (a sector, a smaller company, little travel, not banking; Enter skips; scoring uses it from the next run), and, for each of LinkedIn, profession.hu, Jobbsafari and HelloWork that serves your city, whether to find
   employers there (off unless you say yes; their terms forbid automated access, so it is your call:
   see the [legal disclaimer](../LEGAL_DISCLAIMER.md)). Edit any of it, then save: the profile is
   validated before `profile/config.json` is written, the old CV is kept as `cv.md.bak`, and the first
   run (search the boards, then score) starts at once. Where your city's country puts a photo on a CV
   (Denmark, France, Hungary, Sweden: optional), the review also asks once for a photo, the path of a
   JPEG or PNG (Enter skips it); it is checked, stripped of its camera and location data, scaled to CV size and
   kept as `profile/photo.jpg`. A CV carries it only for a job in a country that allows one.

Run `init` again to go through it with your answers filled in. Later, `./door cv enrich https://your-portfolio.example`
adds what your public pages evidence to the CV.

Then find and score jobs:

```bash
./door find
```

![./door find: a live line per step (search, discover, follow, collect, match), then the ranked matches](demo/find.gif)

This is five steps (see [How it works](how-it-works.md#the-five-steps)): it searches the job
boards in your profile with your keywords, asks LinkedIn which employers hire for them, finds
each new employer's own job feed, reads every followed employer's feed, and scores what is
new against your CV with `claude -p`. The first run takes a while (finding feeds is slow and
polite); after that it is mostly the new postings. It ends with your best matches. See them again any time with
`jobs`, and name a job in the next commands by a word or two from its company and title:

```bash
./door jobs
./door jobs show globex       # read the posting (several matches: pick one; no name: pick from all)
./door jobs prepare globex    # tailored CV + cover letter (a few minutes)
./door jobs show globex       # now also what was tailored, any claim (figure, skill, certification, degree) not in your cv.md + what an ATS would not read back from the PDFs (a "Read by an ATS" row) + paths to the PDFs (--open opens them)
```

![./door jobs show globex, then jobs prepare globex, then jobs status: the posting, then its description in the pager, the tailoring steps and the materials summary, then the posting and its new status picked from lists](demo/prepare.gif)

The PDFs are in `jobs/output/<job_id>/`. Not happy with the letter or the CV? Open Claude Code here (`claude`) and ask: "tighten the letter's second paragraph" — it edits and recompiles the PDF. There is no
command for editing: a `.tex` file is never changed by hand, so its PDF is always current.

Apply by hand, then record it:

```bash
./door jobs status      # pick the posting, then `applied`
```

What counts as "new" (`jobs list --new`, the "since last review" part of `jobs summary`) resets when
you tell Claude you're done reviewing.

## Running without a conversation

`find` works without a conversation: it scrapes only what's new, never scores a posting twice,
and holds a lock on `jobs/` so a review session started while it works fails cleanly
("a run is in progress") instead of racing it. Into a pipe or a log file it prints one line
per step and a summary line; the full record is in `jobs/runs/`. While it works, `jobs summary` from another terminal prints an
`In progress:` block (what it is doing now, read from `jobs/.progress.json`). `claude` must be logged in on that machine. Your next conversation (or `jobs summary`) then starts with "since last review: 1 run, N new matches".

## Command reference

Wherever a command takes a `JOB`, name it by words from its company and title, in any
case and without accents: `jobs show trustpilot`, `jobs status "novonesis head of ai" applied`.
Jobs you are applying to are searched first, then every other posting. One match is used;
several open a list of just those to pick from; where the job is optional (`jobs show`,
`jobs status`), leaving it out lists your jobs in play and your matches. The job id works too.

### Setup

| Command | What it does |
|---------|--------------|
| `doctor [--probe] [--fix [--yes] [--no-tex] [--no-claude]]` | Check prerequisites (and print the data folder in use, `DOOR_HOME` or the checkout), the profile, that `claude` is logged in to a Pro/Max plan (a dim `Connected as <email> (<plan>, <organisation>)` line under the check), and that Claude Code can start the MCP server; print the fix for anything missing (for an invalid `profile/config.json`, every error). `--probe` also checks each site live for [changes](job-sites.md#when-a-site-changes) (slow). `--fix` installs whatever is missing of Tectonic and the `claude` CLI (lists them, asks once), then checks that the MCP server answers; with `--probe` too it offers to fix a scraper that no longer fits its site. `./scripts/setup.sh` ends with `doctor --fix`. |
| `init [--name …] [--role-targets a,b] [--search-keywords a,b] [--topic-terms a,b] [--set KEY=VALUE …]` | Without flags, the setup wizard above (your sources, reading them, one review, a first run; on an existing profile, the same with your answers filled in). With flags it asks nothing and changes only the keys you name (`--set` takes any other config key, as JSON or a plain string: `--set preferences="a smaller company; not banking"` writes what matters to you). `init --show` writes nothing: it prints the configured details (or the `config.json` errors), the CV outline, and whether the CV, the two templates and the story bank are still `profile.example/`'s; it cannot be combined with field options. |

### Your CV over time: `cv`

| Command | What it does |
|---------|--------------|
| `cv enrich [URL ...] [--apply 1,3] [--all] [--model NAME]` | Propose additions to `profile/cv.md` from public pages (default: the profile's `enrich_sources`) with one `claude -p` call, show them numbered and ask which to add; `--apply 1,3` or `--all` adds the proposals of the last run without asking (what to use from a script or a pipe). The previous CV is kept as `cv.md.bak`. |
| `cv titles [TITLE ...] [--hint TEXT] [--languages a,b] [--model NAME]` | Propose job titles from your CV and career progression, each with why it fits and whether it is recommended, without writing anything. Titles you name are kept and more are found beside them. |
| `cv stories [list]` | List the stories in `profile/story_bank.md` (what the tailor draws on): title, the four CARL fields (context, action, result, learning). |
| `cv stories add [--title T --context … --action … --result … --learning …] [--replace OLD_TITLE] [--replace-example] [--from-text TEXT]` | Add a story, or with `--replace` swap the one with that title for this one (a new `--title` renames it). Fields you leave out are asked for in a terminal (in a pipe they are an error); `--from-text` drafts the story from your description (read beside your CV, the text winning, differences shown), asks for the gaps and confirms. A title already in the bank is refused without `--replace`; the made-up example bank (`profile.example/`'s) is refused too until `--replace-example` starts your own. All four texts are required. |
| `cv stories remove TITLE` | Remove the story with that title. |
| `cv stories draft [TEXT] [--from-cv] [--model NAME]` | Propose stories from some text, or with `--from-cv` one story from `profile/cv.md` as an example of what a story is (the bank holds what your CV does not say), with one `claude -p` call. With text, your CV is read beside it for what the text leaves out; where they differ the text wins and the difference is shown. A field the source does not support is left empty and named; nothing is saved. |
| `cv gaps [ROLE ...] [--job JOB ...] [--top N] [--model NAME]` | A skill-gap report for role names, postings (`--job trustpilot`, repeatable) and/or the top N matches: one `claude -p` call (minutes) diffs the CV against them, finds real resources with WebSearch and writes `upskill/report-<date>.md`. |

### What the ads ask for: `market`

| Command | What it does |
|---------|--------------|
| `market [--days N] [--scored-companies] [--no-save]` | Counts the last N days (default 30) of scraped ads, grouping skill names through `jobs/skill_aliases.json` (`{"variant": "Canonical"}`, hand-editable and your edit always wins; `null` marks a name that is not a skill, such as a location or a spoken language, and drops it). One Haiku call, only for names not in the file yet; if it fails the report still comes out, with a warning. The most requested skills (do you have them; a trend against the previous window once both have 50+ scored ads), near misses (what kept ads within 0.15 under `min_score` below it), titles in your matches that no search keyword covers, and companies posting repeatedly (over all scraped ads, or over scored ads with `--scored-companies`; the ones you already follow are marked "✓ followed"). Prints the report and saves it to `jobs/market/report-<date>.md`. |

### Asking about your data: `ask` and `jobs query`

| Command | What it does |
|---------|--------------|
| `ask "QUESTION" [--model M]` | Answers one question about your jobs data in a sentence or two ("how many jobs did I apply to last month?", "why am I following Pleo?"), and names the postings it means by title and company. One short Claude call (Haiku) on your plan that may only read: it calls *The other door*'s read tools (the dashboard, the matches, `jobs query`, the employers, your profile) and nothing else, not even your own MCP servers and can never change `profile/` or `jobs/`. When the data cannot answer, it says it does not know. |
| `jobs query [--since DAY] [--until DAY] [--site S] [--company C] [--status S] [--min-score X] [--max-score X] [--language L] [--has-materials\|--no-materials] [--limit N]` | Counts the postings matching every filter given (dates compare with when *The other door* first saw a posting; `--company` matches part of the name; `--status interview` is any round, `unapplied` the untracked ones), with the average score, the counts by site, status and month, and the best ones by title and company. Read only. |
| `jobs salary [JOB] [--refresh] [--model M]` | The salary range to expect for one job: low–high, currency, per month or year, gross, where your experience puts you in it (below, within or above) and why in one line, and the pages it was read from. The ad's own figure, when it states one, is shown first. One Haiku call with a web search, adjusted to your CV's years of experience against what the ad asks; the answer is saved in `jobs/salary.json`, so asking again about the same job costs nothing (`--refresh` asks anew). `jobs prepare` asks by itself once a job is prepared (again only when the saved estimate is over 90 days old, and not while the Claude plan is close to its limit), and `jobs show` prints a saved one as its Salary line; `find` never asks. When the search finds nothing it can cite, it says so and gives no number. An estimate from public pages, with its sources, not advice. |

### Following employers: `companies`

| Command | What it does |
|---------|--------------|
| `companies [list] [--status followed\|unfollowable\|unresolved\|dormant] [--found-via VIA]` | The employers you follow (`profile/companies.json`), one line each: `✓` followed, `✗` unfollowable, `?` unresolved, `·` dormant (no relevant job in `retire_after_days`), then name, `platform:id`, how it was found, and the reason when it is not followed, led by `(won't follow)` (its terms or robots.txt rule it out) or `(can't yet)` (no way in yet). |
| `companies add NAME_OR_URL ... [--dry-run] [--no-probe]` | Follow employers: a name ("Trustpilot"), a careers link or a career host. Finds the feed from public signals only (the link's shape, the host's DNS name, its careers page and the careers pages that page links to, each feed's public endpoint for the name's likely slugs), prints each result with its evidence and records it; a platform *The other door* can't follow, or no feed, is recorded too, with the reason. A feed found by the name alone needs a job in your `location` and is never a platform's demo account; a feed that answers an error (a dead HR-Manager alias) is not followed. A link is named by what its page calls the employer (`og:site_name`, the ads' `hiringOrganization`, the title), else by its host, and on a career platform's host by the customer's part (`dca` in `dca.career.emply.com`), never the platform's; two employers on different feeds stay two entries even under one name (`companies merge` lists them). `--dry-run` writes nothing. See [Following companies directly](configuration.md#following-companies-directly). |
| `companies remove NAME ...` | Unfollow: remove the employers from the list. |
| `companies merge [KEEP FOLD]` | Merge two entries that are one employer (LEGO and LEGO System A/S): FOLD's name and aliases become aliases of KEEP, evidence and dates are combined, and the followed one's feed wins; two employers followed on different feeds are refused. With no names it only lists the entries that share a feed or a name, so you confirm each merge yourself; nothing merges automatically. `companies` and `why` show an entry's aliases (`aka: ...`). |
| `companies why NAME` | Everything known about one employer: feed, status, reason or evidence, how and when it was found, and how many postings in `jobs/` came from it (and why the last `collect` could not read its feed, if it could not). |

### Moving to another computer: `data`

| Command | What it does |
|---------|--------------|
| `data export [PATH]` | Pack `profile/` and `jobs/` into `door-export-<date>.tar.gz` to take to another computer. |
| `data import ARCHIVE` | Replace `profile/` and `jobs/` with an export; the old ones move to `backups/<timestamp>/`. |
| `data connect` | Connect this computer to your Google Drive (a browser opens once). Afterwards every command that writes pulls before and pushes after, by itself, and ends with one line on stderr saying what moved (`↓ pulled`, `↑ synced`, or `⚠` when the sync was skipped). See [Your data](data.md#keeping-computers-in-step-with-google-drive). |
| `data sync [--keep-local \| --keep-drive]` | Push or pull now, whichever is needed. When both sides changed it refuses; `--keep-local` replaces Drive with this computer's data, `--keep-drive` the other way round (yours goes to `backups/`). |
| `data disconnect` | Forget this computer's connection and revoke the access; the archive on Drive stays. |
| `data report [PATH]` | Save a problem report, `door-report-<date>.zip`, to send to whoever helps you: the log of what went wrong (`logs/door.log`), the last five runs' counts and errors, `doctor`'s checks, the version and the OS. No CV, profile, postings or ledger; emails and home folders are masked. Never replaces a file. |

### Your phone: `serve`

*The other door* on your phone is the desktop app's screens as a web app, served by this computer. The phone
runs no model and holds no data; every call goes to `serve`, for paired phones only.

| Command | What it does |
|---------|--------------|
| `serve` (`serve start`) | Serve this data folder: the phone app and the tools it uses (finding, preparing, the applications), at `http://127.0.0.1:8765`. `--port` (one per person), `--host` (only this computer unless you say otherwise), `--name` (the installed app's name, "*The other door* — Anna"). A tunnel gives it the `https://` address a phone needs. |
| `serve pair --device NAME [--url https://…]` | A one-time code that pairs a phone (good once, for 10 minutes). With `--url`, also a link and a QR code to open on the phone. |
| `serve devices` | The paired phones, and when each was last seen. |
| `serve unpair NAME` | Revoke a phone; it shows the pairing screen again. |
| `serve install-agent [--port] [--name]` | macOS: start this data folder's server at login and restart it if it stops (a launch agent; its log is `<data folder>/logs/serve.log`). |
| `serve uninstall-agent [--name]` | macOS: remove that launch agent. |

Several people on one machine each run their own `serve`: their own data folder (`DOOR_HOME`), port
and Claude plan (`claude_config_dir`). `serve` refuses a port or a plan another person's instance
already uses, and `doctor` lists the instances, whether each answers, its paired phones and whether
the Mac sleeps. The Google Drive connection is per user account on the machine, so two people who both
sync with Drive need separate user accounts.

The server keeps only hashes of the codes and tokens, in `<data folder>/.serve/`. Wrong tokens or codes
lock that address out for 15 minutes after 10 tries.

### Finding and your postings: `find` and `jobs`

| Command | What it does |
|---------|--------------|
| `find [--boards a,b] [--skip STEPS]` | Fetch new postings and score them, in five steps: `search` (the job boards with your keywords), `discover` (LinkedIn: which employers hire for them, working in the background beside the other steps), `follow` (find each new employer's own job feed, record it in `profile/companies.json`), `collect` (every followed employer's feed, keeping only the postings whose title is on topic for your keywords), `match` (filter, dedup, score with Haiku via `claude -p`, print the ranked matches). The usual way to start; run it again to finish one that was interrupted. `--skip discover,collect` leaves steps out. Boards are read since their last search (at most `max_age_days` back), employers' feeds for whatever *The other door* has not seen, and matches are picked at your `min_score`. |
| `jobs [list]` | Show ranked matches you haven't acted on yet, each with its score drawn as a bar, its company and location, and its job id (✦ marks postings new since your last review). While no posting has yet reached your `min_score` (and no `--score` lower than what was scored is given), it lists the three best below it under a "weak matches found" line saying what would widen the search. |
| `jobs show JOB_ID [--open]` | Show one posting in full (score bar, why it scored that, the matching and missing skills side by side, a Work permit row when the ad says it will not sponsor a visa, requires an existing permit or offers sponsorship (set `needs_work_permit` and such ads score 0), its history: every status change with its date and note, each interview round with how it went; coloured on a terminal, plain into a pipe); a "Suspicious ad" block lists what the integrity gate removed (hidden text, lines aimed at a model); once prepared, also what was tailored, page counts and the PDF paths (`--open` opens the PDFs). On a terminal the card and history come first, then one key: `d` opens the description in your pager (`less`: arrows or space to scroll, `/` to search, `q` back), `m` shows the materials, `q` or Enter quits; into a pipe everything follows in full. |
| `jobs add URL` | Add an ad you found elsewhere: the page is fetched and Haiku reads its title, company and location (`--title`/`--company`/`--location` override), then scores it right away like `find` does; on a terminal each step (fetch, read, save, score) shows as it runs, then a card like `jobs show`'s without the ad text: score, why, skills, where it was saved and what to run next. A text/Markdown file or `-` (stdin) works too, with `--title T --company C`. |
| `jobs summary` | Two bars — all postings, the applicable ones (scored above 0) and those at or above `min_score`; then those matches split into unapplied, prepared and applied — plus your applications by status, how each stage has gone — the application itself (did it lead to an interview) and each kind of interview: passed, rejected, ghosted, withdrawn, pending, and the pass rate of the decided ones with its binomial error (a one-sigma Wilson interval: `67% (46–82%)`), what changed since your last review, and how full your Claude plan is: the window's use, when it resets and about how many more finds or prepares fit (`Claude plan: 42% of this 5-hour window used (resets 15:30) · room for about 6 finds or 2 prepares · as of 14:10`; see [How much of the plan is left](how-it-works.md#how-much-of-the-plan-is-left)). |

### Working a posting

| Command | What it does |
|---------|--------------|
| `jobs prepare [JOB_ID]` | Write a tailored CV and cover letter (PDFs in `jobs/output/<job_id>/`); without `JOB_ID`, for the best unapplied match. Afterwards *The other door* checks, offline and without a model call, every number, year, employer, skill or tool, certification and degree in the CV and letter against `profile/cv.md` and the story bank (the letter may also use the ad's figures and skills; `jobs/skill_aliases.json` tells it that `k8s` is `Kubernetes`); what it cannot find is listed by `jobs show` under "Not in your CV" with its line and kept in `jobs/output/<job_id>/facts.json`. It never blocks; single digits and the current year are skipped, and a figure you derived (a sum, a rounding) may be listed. The tailor runs the same check before it finishes, fixes what it can and records why an item that stays is true (shown beside it as "kept: ..."). `revise` re-runs the check. When your Claude plan's window has room for three prepares or fewer, or is close to its limit, it says so before it starts (`This window has room for about 2 more prepares (resets 15:30).`). Once the job is prepared it also estimates the salary (see `jobs salary`) and shows it with the materials. |
| `jobs status [JOB_ID] [STATUS] [--notes TEXT] [--at YYYY-MM-DD]` | Record progress, picked from lists: `jobs status` alone lists your postings (the ones in play first, then the matches you haven't acted on), then the statuses, then when it happened (Enter for now), then optional notes (why, or how an interview went). JOB_ID skips the first list, STATUS the second. The statuses: `unapplied`, `prepared`, `applied`, `interview:screening` (pre-screening, recruiter/HR), `interview:impression` (first non-technical interview), `interview:assessment` (personality or cognitive test), `interview:technical` (technical interview, case or take-home), `ghosted` (the company stopped answering mid-process), `rejected`, `offer`, `discarded` (hides a posting from `list`). Record one `interview:…` per round; `rejected`/`ghosted` ends the last one. Every change is kept, so `jobs show` lists a posting's whole history and `jobs summary` shows how each kind of interview has gone. `--at` dates a change you record afterwards ("I applied on the 3rd"): it is filed in date order, and one dated before the latest change leaves the current status. The first status that means the application was sent keeps a copy of the materials in `jobs/output/<id>/sent/` (what went out, whatever `revise` does later); a sent application whose ad is not on disk, or is only a snippet, gets a warning, as does one whose materials hold figures not in your `cv.md` (see `jobs prepare`). These are what an analysis of which applications pass needs. |

### Useful options

| Option | On | Effect |
|--------|----|--------|
| `--boards a,b` | `find` | Search only these boards (`jobindex`, `thehub`, `jobmaskinen`, `workable`). |
| `--skip a,b` | `find` | Leave these steps out of the full run. |
| `--new` | `jobs list` | Only postings first seen since you last told Claude you were done reviewing. |
| `--score X` | `jobs list` | Only matches scoring X or more (default: anything above 0; postings you've prepared, applied to or discarded, and those older than `max_age_days`, are never listed). |
| `--status S` | `jobs list` | Only postings with status S (one of the `jobs status` statuses) instead of the ones you haven't acted on; they stay listed however old, and `--score` defaults to anything above 0. |
| `--ongoing` | `jobs list` | Only postings still in play (`prepared`, `applied`, `interview:…`, `offer`); like `--status`, they stay listed however old and `--score` defaults to anything above 0. Not together with `--status`. |
| `--closed` | `jobs list` | Only applications that ended: `rejected`, `ghosted`, or `discarded` after you prepared or sent them (a match you dismissed without applying is not listed); listed like `--status`. Not together with `--status` or `--ongoing`. |
| `--force` | `jobs prepare` | Regenerate materials that already exist. |
| `--probe` | `doctor` | Also probe each configured site live for a scraper that no longer fits it. |

### Live progress

`find` takes minutes (`collect` the longest), so on a terminal it shows five lines, one per
step, redrawn in place:

```
✓ search    41 postings from 2 boards (12s)
– discover  skipped: LinkedIn resting until 14:20
✓ follow    40 candidates: 5 followed, 20 unfollowable, 15 unresolved (3m08s)
⠹ collect   ░░░░░░░░░░  0/158 employers · 640 postings · jobs.lego.com, careers.novo.com
○ match
```

`○` waits, a yellow spinner runs (with a bar and counts: searches done, candidates checked,
employers done with the postings so far and up to three hosts in flight, postings scored),
a green `✓` is done with its summary and elapsed time (a partial failure stays `✓` with
`N failed` in yellow), a red `✗` failed, a grey `–` skipped with the reason (`--skip`, or
LinkedIn resting). `discover` works beside the other
steps, so its line keeps spinning while they run, with the request it is on and the pause it is
waiting out (`⠹ discover  ██░░░░░░░░  page 3/15 · waiting 87 s`); when it ends after `follow`
and `collect` have, those two lines run again for the employers it found and end with
`+ late: …`, still five lines (in a pipe the late pass is a line of its own,
`[3/5] follow (late): …`, and discover's line comes when it ends). When stdout is a
pipe or a log file, one plain line is printed as each step ends, for example
`[4/5] collect: 158 employers, 2,431 postings, 2 failed (41m)`, and then the summary line.
A site that failed is named under the lines with its last recorded error. The run then shows the top matches like `jobs list`, and what to run next.

While a `find` holds the `jobs/` lock it keeps the latest event in
`jobs/.progress.json`, and `jobs summary` (or the `status_summary` tool) prints it as
`In progress: run (started 09:30, pid 4242)`; the file is deleted when the lock is released.

### Exit codes

`find` exits `2` when a site failed and `1` when postings were
left unscored (`./door find match` scores them). A site that returned no results at all, and whose page the scraper did not recognise as a "no hits" answer, is flagged with ⚠ in the
output and in `jobs summary` (it may have changed), but doesn't change the exit code; a platform
nobody follows an employer on is simply not collected. `doctor` exits non-zero when a required tool is missing.

### Where things are written

| Path | Contents |
|------|----------|
| `jobs/postings/<date>/<site>/<job_id>.json` | Scraped postings; `find`'s scoring adds the score to the same file. |
| `jobs/candidates.json` | The employers `search` and `discover` saw that `follow` has yet to look at. |
| `profile/companies.json` | The employers *The other door* follows, and the ones it found it cannot (`companies`). |
| `jobs/output/<job_id>/` | Tailored `cv.tex`, `cover_letter.tex` and their PDFs. |
| `jobs/applications.json` | Application status for each posting, with the history of every change (interview stages, notes, when each happened) and the hashes of the materials sent (copied to `jobs/output/<id>/sent/`). |
| `jobs/runs/` | One record per `find` (a block per step), plus `latest.log`. |
| `backups/<timestamp>/` | The `profile/` and `jobs/` a `data import` replaced. |
| `logs/door.log` | One line per thing that went wrong: a failed tool call or crash, a site that failed or came back empty, an ad left unscored, a warning (about 1 MB, then `door.log.1`, `door.log.2`). `data report` packs it. |

More on how scraping, freshness and scoring work: [How it works](how-it-works.md).
