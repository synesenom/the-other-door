# Claude Code skills and agents

Most of *The other door* is driven from a Claude Code conversation with plain sentences, which call
the [MCP tools](manual-claude.md) directly ("what's new?", "prepare the Trustpilot one"). A few flows are
scripted, multi-step **skills** you invoke with a slash command. Skills live in
`.claude/skills/<name>/SKILL.md`; agents live in `.claude/agents/<name>.md`.

## User skills

| Skill | What it does |
|-------|--------------|
| `/onboard` | Onboarding in a conversation, after `./scripts/setup.sh` has installed everything: takes your sources (CV, LinkedIn PDF, public pages), drafts `profile/cv.md`, infers your details, job titles and search terms, asks only for what it could not find, shows it all in one review, and writes `profile/config.json` and `profile/cv.md` only after you confirm. Offers to connect Google Drive first, so the profile follows you across computers. Then starts the first search. Installs nothing itself. Safe to re-run. |
| `/expand [url ...]` | Fetches public URLs (portfolio sites, publication lists, GitHub repos, course syllabi), proposes additions to `profile/cv.md`, and writes only after you confirm. URLs can be passed as arguments or listed under `enrich_sources` in `profile/config.json`. The work is the `enrich` tool's (two calls: propose, then apply the numbers you picked); `cv enrich` in a shell does the same, and the desktop app's "Add from a page" (Profile, CV). |
| `/upskill [role, job or top N]` | Optional. Analyses skill gaps between your profile and a target role or some of your matches (`/upskill trustpilot`, `/upskill top 5`), and writes a WebSearch-cited learning plan to `upskill/report-YYYY-MM-DD.md`. The work is the `skill_gaps` tool's; `cv gaps` in a shell does the same, and the desktop app's "What should I learn?" (Profile, CV). |

Setup is split in two: `./scripts/setup.sh` (and the `doctor --fix` [command](manual-cli.md) it ends
with) installs everything and asks nothing about you; `/onboard` reads your sources, asks what
they did not say, and installs nothing. Its tools are the ones behind `init`'s wizard in a shell (`draft_cv`,
`infer_basics`, `suggest_titles`, `keywords`, `init_profile`, `save_cv`, `save_photo`, `find_jobs`), so `./door init` does the same onboarding in a
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
GitHub-issue workflow and are prefixed `dev-` to stay out of the way of the user skills.

| Skill | What it does |
|-------|--------------|
| `/dev-research <issue>` | Explore the codebase for an issue and write a research report to `thoughts/research/<issue>.md` (issue-researcher agent). |
| `/dev-plan <issue>` | Turn the research report into a step-by-step TDD plan in `thoughts/plan/<issue>.md` (issue-planner agent). |
| `/dev-implement <issue>` | Implement the plan test-first (issue-implementer agent); runs `/dev-research` and `/dev-plan` first if their outputs are missing. |
| `/dev-validate <issue>` | Run the suite and review the diff against the issue; PASS/FAIL report in `thoughts/validate/<issue>.md` (issue-validator agent). |
| `/dev-resolve <issue>` | All of the above in one go, sized to the issue's complexity. |
| `/dev-pr` | Check the branch is named for its kind (`feat/`, `fix/`, `change/`, `docs/`, or an internal `refactor/`, `test/`, `ci/`, `chore/`), merge the latest `main` into it, push, open a pull request whose body says what a user will notice (the release notes are built from it) and watch its CI and reviews. |
| `/dev-release [X.Y.Z] [pre-release]` | Maintainer only: check `main` is green, sort the PRs merged since the last release into Added / Changed / Fixed / Removed and suggest the version from them, set the version (through a PR), push the `vX.Y.Z` tag, watch `release.yml` build the installers into a draft release, write the release notes and publish it when you say so ([releasing.md](releasing.md)). |
| `/dev-add-scraper <site> [country]` | Build a scraper for a new job board test-first: module, unit/fixture/probe/live tests from saved real payloads, the registry entry and its doc rows (scraper-builder agent; see [adding-a-site.md](adding-a-site.md)). |
| `/dev-add-country <country>` | Add a whole country: research its job boards and their terms (you pick which to build), write its data files and the scrapers test-first, document the country, run the new live smoke tests, and validate it with two fake profiles in sandboxes (`scripts/country_smoke.py`, built on `scripts/sandbox.py`): one reading only English, one English plus the local language, since where someone lives doesn't decide which ad languages they want. State and every agent's report in `thoughts/country/<cc>/`, which the validator also checks the run against. |
| `/dev-add-profession <titles> <country>` | Make *The other door* work for one profession, given as one or more job titles (`"Reward Partner, C&B Specialist" dk`), in one country (the country needs its data file: `/dev-add-country` first): research the titles it is advertised under, what *The other door* finds today, and where its jobs are posted (boards, profession and union job banks, the ATS platforms of its employers, discovery sources) with each source's terms; you pick what to build; the sources are built test-first with live smoke tests that search for the profession, documented in the Sources by profession table, its *The other door* gaps filed as issues, and the result checked with a fake profile of the profession in a sandbox against the research baseline. State and reports in `thoughts/profession/<cc>-<slug>/`. |

## Agents

Agents are not invoked directly; tools and skills run them.

| Agent | Run by | Role |
|-------|--------|------|
| `matcher` | `match` | The scoring rubric, used as the system prompt of one `claude -p` call per posting. |
| `tailor` | `prepare` | Writes the tailored CV and cover letter, compiles and checks page limits. |
| `reviewer` | the tailor agent | Critiques the draft for relevance, evidence, fabrication and tone. |
| `scraper-fixer` | `doctor --probe --fix` / the `setup` tool (`fix scraper: <site>`) | Repairs a scraper whose site changed, test-first, on its own branch (see [job-sites.md](job-sites.md#when-a-site-changes)). |
| `issue-researcher`, `issue-planner`, `issue-implementer`, `issue-validator` | the `dev-` skills | The developer issue workflow. |
| `scraper-builder` | `/dev-add-scraper`, `/dev-add-country`, `/dev-add-profession` | Builds one site, feed platform or discovery source (or extends a site to a new country) test-first, from saved real payloads. |
| `country-researcher`, `country-data-writer`, `country-validator` | `/dev-add-country` | Research a country's boards and terms; write its `i18n` data files; validate the country end to end with a fake profile. |
| `profession-researcher`, `profession-validator` | `/dev-add-profession` | Research where a profession's jobs are posted in a country and what *The other door* misses; validate the built sources with a fake profile of the profession. |
