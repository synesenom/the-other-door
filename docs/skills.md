# Claude Code skills and agents

Most of *The other door* is driven from a Claude Code conversation with plain sentences, which call
the [MCP tools](manual-claude.md) directly ("what's new?", "prepare the Trustpilot one"). A few flows are
scripted, multi-step **skills** you invoke with a slash command. Skills live in
`.claude/skills/<name>/SKILL.md`; the agents and prompts the code runs live in `src/door/prompts/<name>.md`, the developer agents in `.claude/agents/<name>.md`. How a change goes from an issue to `main` (the checker, auto-merge, what waits for you) is in the [development workflow](development/workflow.md).

## User skills

| Skill | What it does |
|-------|--------------|
| `/onboard` | Onboarding in a conversation, after `./scripts/setup.sh` has installed everything: takes your sources (CV, LinkedIn PDF, public pages), drafts `profile/cv.md`, infers your details, job titles and search terms, asks only for what it could not find, shows it all in one review, and writes `profile/config.json` and `profile/cv.md` only after you confirm. Offers to connect Google Drive first, so the profile follows you across computers. On a first set-up with a PDF CV that has a look to copy, the review has one line, off unless you change it, to make your tailored CVs look like that CV (built in the background; the pick comes later, in a review session). Then starts the first search. Installs nothing itself. Safe to re-run. |
| `/expand [url ...]` | Fetches public URLs (portfolio sites, publication lists, GitHub repos, course syllabi), proposes additions to `profile/cv.md`, and writes only after you confirm. URLs can be passed as arguments or listed under `enrich_sources` in `profile/config.json`. The work is the `enrich` tool's (two calls: propose, then apply the numbers you picked); `cv enrich` in a shell does the same, and the desktop app's "Add a page" and "Replace CV file…" (Profile → Master CV, Sources). |

Setup is split in two: `./scripts/setup.sh` (and the `doctor --fix` [command](manual-cli.md) it ends
with) installs everything and asks nothing about you; `/onboard` reads your sources, asks what
they did not say, and installs nothing. Its tools are the ones behind `init`'s wizard in a shell (`draft_cv`,
`infer_basics`, `suggest_titles`, `keywords`, `init_profile`, `save_cv`, `save_photo`, and `find_jobs`), so `./door init` does the same onboarding in a
terminal — see [*The other door* from the terminal](manual-cli.md#walkthrough). The desktop app's
first-launch wizard is the third twin of `/onboard` and `init`: the same three parts and the same
rules, behind the same tools — see [the app](manual-app.md#first-launch).

No skill is needed for:

- "Expand my search keywords" — the `keywords` tool proposes `search_keywords` and the
  `topic_terms` that make a job title relevant from your `role_targets` (the same call
  `/onboard`'s and `init`'s reading steps make) and saves them after you confirm.
- "Get me today's jobs" — calls the `find_jobs` tool (fetch, then score).
- "Run doctor" — calls *The other door*'s `doctor` tool. Don't type `/doctor` for this: that is
  Claude Code's own command, which checks Claude Code's install, not *The other door*'s.

## Developer skills

For working **on** *The other door* (see [CONTRIBUTING.md](../CONTRIBUTING.md)). They drive the
GitHub-issue workflow and are prefixed `dev-` to stay out of the way of the user skills; `/eli5`, a
conversation helper, is the one without the prefix.

| Skill | What it does |
|-------|--------------|
| `/dev-research <issue>` | Explore the codebase for an issue and write a research report to `thoughts/research/<issue>.md` (issue-researcher agent). |
| `/dev-plan <issue>` | Turn the research report into a step-by-step TDD plan in `thoughts/plan/<issue>.md` (issue-planner agent). |
| `/dev-implement <issue>` | Implement the plan test-first (issue-implementer agent); runs `/dev-research` and `/dev-plan` first if their outputs are missing. |
| `/dev-validate <issue>` | Run the suite and check TDD compliance; PASS/FAIL report in `thoughts/validate/<issue>.md` (issue-validator agent). |
| `/dev-resolve <issue>` | All of the above in one go, sized to the issue's complexity, then the review (gap, simplicity, design when the app's screens changed, then integration; each finding fixed or filed) and `/dev-pr` when validation passes: the pull request is part of resolving, not a separate step. It refuses an issue someone other than you opened. |
| `/dev-plan-epic <goal or epic>` | Plan an epic before building any of it: two architects (outcome-first, codebase-first) research the feature and the code and write competing plans; two critics (scope, approach) break them and answer each other; the surviving plan is the smallest that reaches the goal, uses a cheap model wherever the work is reading meaning (not heuristics), and starts with a spike on its riskiest assumption. Written to `thoughts/epic-plan/<slug>.md`, then filed as an epic with sub-issues once you agree. Run it with `/dev-epic`. |
| `/dev-epic <epic>` | Churn through a planned epic (one made by `/dev-plan-epic`; an unplanned one is planned first) in one run: its sub-issues one after another, each resolved by `/dev-resolve` (review included) and opened as its own small pull request into `main`, which the verifier checks and auto-merge lands; every epic checkbox tracked by a sub-issue (one filed when none is), findings outside a sub-issue filed as issues of their own only when they are bugs a user would hit (its scope stays fixed), boxes ticked as their PRs merge, until all are done. A screen change is looked at by the verifier (before/after shots in its PR); questions are asked together; one short report at the end. State in `thoughts/epic/<epic>.md`, so running it again picks up. It works only an epic you opened, and skips sub-issues and pull requests someone else opened. |
| `/dev-pr` | Check the branch is named for its kind (`feat/`, `fix/`, `change/`, `docs/`, or an internal `refactor/`, `test/`, `ci/`, `chore/`), merge the latest `main` into it, push, open a pull request whose body says what a user will notice (the release notes are built from it) and watch it in the background: CI, conflicts, then the `verifier`, then auto-merge once `verify` is success (a PR with a `Needs the maintainer:` line waits for you). Two failed verifications attack the premise before a third fix. |
| `/dev-file-issue <title>` | File one issue (a review finding, an epic's box, a gap a skill reports), after a duplicate check; it goes under an epic only when it is one of that epic's boxes (`epic=`). Every issue Claude files goes through it. Its `Done when:` checks say what to run, so the verifier can run them; one only you can run is marked `(by the maintainer)`. |
| `/dev-release [X.Y.Z] [pre-release]` | Maintainer only: check `main` is green, sort the PRs merged since the last release into Added / Changed / Fixed / Removed and suggest the version from them, set the version (through a PR that goes through the gate), dry-run `release.yml` on `main`, push the `vX.Y.Z` tag, watch `release.yml` build the installers into a draft release, have the `data-migrator` agent write the data upgrade a release needs, write the release notes and publish it when you say so ([releasing.md](development/releasing.md)). |
| `/dev-correct [since=<ref>]` | Turn the maintainer's repeated corrections of Claude into checks: read the typed turns of past sessions (`scripts/correct_evidence.py`), group the corrections by cause with one Haiku call (`correction-grouper`), keep a class only when its verbatim quotes come from two or more sessions, and give it an enforcer (a guard test shown failing on a past commit, or a change at the cause), one commit per class, at most five a sweep; the table "Rules and what enforces them" in `CLAUDE.md` is updated. `/dev-release` runs it with `since=<previous tag>`. |
| `/dev-add-scraper <site> [country]` | Build a scraper for a new job board test-first: module, unit/fixture/probe/live tests from saved real payloads, the registry entry and its doc rows (scraper-builder agent; see [adding-a-site.md](adding-a-site.md)). |
| `/dev-add-country <country>` | Add a whole country: research its job boards and their terms (you pick which to build), write its data files and the scrapers test-first, document the country, run the new live smoke tests, and validate it with two fake profiles in sandboxes (`scripts/country_smoke.py`, built on `scripts/sandbox.py`): one reading only English, one English plus the local language, since where someone lives doesn't decide which ad languages they want. State and every agent's report in `thoughts/country/<cc>/`, which the validator also checks the run against. |
| `/dev-add-profession <titles> <country>` | Make *The other door* work for one profession, given as one or more job titles (`"Reward Partner, C&B Specialist" dk`), in one country (the country needs its data file: `/dev-add-country` first): research the titles it is advertised under, what *The other door* finds today, and where its jobs are posted (boards, profession and union job banks, the ATS platforms of its employers, discovery sources) with each source's terms; you pick what to build; the sources are built test-first with live smoke tests that search for the profession, documented in the Sources by profession table, its *The other door* gaps filed as issues, and the result checked with a fake profile of the profession in a sandbox against the research baseline. State and reports in `thoughts/profession/<cc>-<slug>/`. |
| `/eli5 [part]` | Re-explain Claude's last message (or just the named part) in plain, short words: the point first, no jargon, paths or issue numbers unless you need one to act, what it needs from you last, nothing added. Runs only when you type it. |

The skills are tested end to end, locally and before a release (`./scripts/run-test.sh --model`, never
in CI): the real model runs `/onboard`, `/expand` and a review session against a test world,
a second small model plays the user, and the checks are on behaviour only (which tools, in which order,
what was written and when), never on wording, except that a thing that must go unsaid is checked unsaid
(a job marked ghosted unasked). They need a signed-in `claude`, `claude-agent-sdk`, `npm ci` in `app/`
and the pinned Chromium; they use the plan's quota. Run them before a release and when a skill or CLAUDE.md's
review-session rules change.

## Agents

Agents are not invoked directly; tools and skills run them.

| Agent | Run by | Role |
|-------|--------|------|
| `matcher` | `match` | The scoring rubric, used as the system prompt of one `claude -p` call per posting. |
| `scorer` | `door.matching.scorer` | The scoring prompt's wrapper: it fills in the matcher's rubric, the language and work-permit phrases, the profile and the CV. |
| `ask`, `cv-drafter`, `cv-enricher`, `page-reader`, `keywords`, `skill-grouper`, `reviser`, `salary`, `story-from-text`, `story-from-cv`, `titles`, `posting-reader` | `door.commands.ask`, `cv`, `enrich`, `door.core.page_reader`, `keywords`, `market`, `revise`, `salary`, `stories`, `titles`, `add` | One model prompt each: the file's body is the system prompt of one `claude -p` call, its frontmatter the model and tools (`claude_cli.prompt`). |
| `cv-reader`, `fact-checker`, `careers-finder`, `title-translator` | `door.core.cv_read`, `door.tailoring.facts`, `door.core.employers.careers_ai`, `door.matching.language` | The same, for the code below the commands. |
| `tailor-request`, `tailor-retry` | `door.commands.prepare` | Message files: the `-p` request that runs the tailor (and its retry), with the job filled in. |
| `tailor` | `prepare` | Writes the tailored CV and cover letter, compiles and checks page limits. |
| `reviewer` | the tailor agent | Critiques the draft for relevance, evidence, fabrication and tone. |
| `issue-researcher`, `issue-planner`, `issue-implementer`, `issue-validator` | the `dev-` skills | The developer issue workflow. |
| `gap-reviewer` | Claude, before it summarises a change it made (CLAUDE.md "Review") | Reviews the finished change for what it leaves missing: the issue's requirements not met, inconsistent siblings, untested cases, running processes and old data, false docs, follow-ups; each gap is then fixed in the change; one outside it is filed only when it is a bug a user would hit, otherwise named in the PR and dropped (CLAUDE.md "Review"). |
| `simplicity-reviewer` | Claude, beside `gap-reviewer` (CLAUDE.md "Review") | Reviews the new lines of a finished change for complexity they do not need: abstractions and options with one caller, dead code, old behaviour kept alive, a diff larger than its goal, a rule that fits only the input it was made for. |
| `design-reviewer` | Claude, beside `gap-reviewer` when the app's screens or `docs/design/` changed (CLAUDE.md "Review") | Reviews the change against `docs/design/README.md` (tokens, components, button order, words not ids, when an error is shown, phone and narrow layouts, dark mode), reading the diff and screenshots of the changed scenes in the preview, each beside the style card (`screens/style-tile.png` and `screens/style-tile-dark.png`). |
| `integration-reviewer` | Claude, last, after the other reviewers' findings are dealt with (CLAUDE.md "Review") | Maps where the change landed and its blast radius, then asks whether the whole solution would be smaller had the feature been in the codebase from the start, each refactor with its net lines. |
| `correction-grouper` | `/dev-correct` | Groups the maintainer's corrections of Claude, from the typed turns of past sessions, into classes of cause with verbatim quotes (Haiku, no tools). |
| `decider` | Claude, before it asks the maintainer to decide something (CLAUDE.md "Decisions") | Researches the question in the codebase, docs, issues, PRs and on the web, and returns one definite decision with its reasons; only when it cannot decide is the maintainer asked. |
| `verifier` | Claude, on a PR's head (or a past head, for a spike) | Runs the change at that head by checks it writes from the issue before reading the Test plan, posts the evidence and sets the `verify` status: FAIL (also for a goal it did not test), pending with reasons (a goal marked `(by the maintainer)` waits for you), or PASS (`scripts/decide.py` decides). Refuses a PR not opened by the maintainer. Never asks the maintainer and never edits the code, the PR's text or its issues. |
| `scraper-builder` | `/dev-add-scraper`, `/dev-add-country`, `/dev-add-profession` | Builds one site, feed platform or discovery source (or extends a site to a new country) test-first, from saved real payloads. |
| `country-researcher`, `country-data-writer`, `country-validator` | `/dev-add-country` | Research a country's boards and terms; write its `i18n` data files; validate the country end to end with a fake profile. |
| `profession-researcher`, `profession-validator` | `/dev-add-profession` | Research where a profession's jobs are posted in a country and what *The other door* misses; validate the built sources with a fake profile of the profession. |
| `data-migrator` | `/dev-release` | Before a tag: diffs everything `core/stored.py` names between the last release and `main`, and writes the step that upgrades a tester's data, test-first, or says why none is needed, item by item. |
