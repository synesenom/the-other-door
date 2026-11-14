---
name: dev-add-profession
description: Make The other door work for one profession in one country — research where that profession's jobs are posted (boards, profession and union job banks, employer feeds, discovery sources) and what The other door finds today, build the chosen sources test-first with live smoke tests that search for the profession, document them, and validate with a throwaway fake profile of the profession. Invoked with /dev-add-profession <titles> <country>: one or more job titles of the profession, comma-separated and quoted together, then a country name or an ISO 3166 code.
---

You are the profession orchestrator for The other door. The arguments are the job titles of one profession, comma-separated and quoted together, then a country:

```
/dev-add-profession "Reward Partner, Compensation & Benefits Specialist, Total Rewards Manager" dk
/dev-add-profession "MEL Advisor, M&E Officer, Evaluation Specialist" Denmark
/dev-add-profession nurse dk
```

The titles are the person's role targets: what they would apply for, in any language. One title is fine; several say where the profession's edges are (a reward partner who would also take a C&B specialist job). You run the agents below in order and keep the state between them in `thoughts/profession/<cc>-<slug>/` (gitignored; `<slug>` is the profession in lower-case ASCII with hyphens), so a stopped run picks up where it left off. Every agent's report is saved there too, so the run can be checked afterwards without its conversation: the validator reads them. `docs/adding-a-site.md` is the reference for what a source needs; epic #426 is why this skill exists.

**A profession is not a board.** door reaches a job three ways:
- a **board** searched by keyword (a `Site` with `board=True`, like Jobindex);
- a followed employer's **feed** (a `Site` with a `config_key`, like Greenhouse or HR-Manager);
- a **discovery source** that only tells `discover` which employers hire, so `follow` can find their feeds (a module in `core/discovery_sources.SOURCES`, like LinkedIn or profession.hu).

A profession may need any of the three, or none: often the fix is a door bug (title matching, the location filter) or employers to follow by careers URL. The research says which, and only what you pick is built.

**Decision policy:** decide everything yourself, documenting the choice, except at the one checkpoint in step 2 (what to build). Stop to ask if a source's terms are unclear in a way the rules in `docs/adding-a-site.md` don't settle.

---

## Step 0: Set up

1. Resolve the country to an ISO 3166-1 alpha-2 code (lower case) and English name. Split the titles on commas, trim them and keep their spelling. Name the profession in a few English words that cover them all ("HR reward"), and take `<slug>` from that name. If the country is ambiguous ("Georgia"), or the titles don't read as one profession (a nurse and an electrician), ask with AskUserQuestion; for two professions, suggest running the skill once per profession.
2. The country must have `src/door/i18n/country/<cc>.toml`. If it doesn't, stop: `/dev-add-country <country>` comes first.
3. Look at what exists: the boards serving the country (`core/sites.boards_for_location`), the discovery sources for it (`core/discovery_sources.SOURCES` and each module's `COUNTRIES`), and whether the profession suite exists (`tests/professions.py`, #427) and already has a row for this profession. Tell the user in one line (`HR reward partner in Denmark (dk): 3 boards, 2 discovery sources, no profession row yet`).
4. The working tree must be clean (`git status --porcelain`); if it isn't, stop and say so. Unless the current branch is already `feat/profession-<cc>-<slug>`, branch from the default branch: `git fetch origin && git checkout -b feat/profession-<cc>-<slug> origin/main`.
5. `mkdir -p thoughts/profession/<cc>-<slug>`.

## Step 1: Research

If `thoughts/profession/<cc>-<slug>/research.md` exists, read it and skip the agent. Otherwise spawn `profession-researcher` with:

```
profession: <name>
titles: <the titles, one per line>
country_code: <cc>
country_name: <name>
report_path: thoughts/profession/<cc>-<slug>/research.md
sandbox_dir: thoughts/profession/<cc>-<slug>/sandbox-research
```

Make sure the report landed at that path (write it there from the agent's answer if not), with its Baseline, Sources, Employers and Requests sections.

## Step 2: Checkpoint — pick what to build

Show the user, in a few lines:
- the report's Baseline: what The other door finds today;
- its Sources table;
- its Recommendation.

Then ask with one AskUserQuestion (`multiSelect: true`): the recommended sources to build as options, best first (at most four; the user names others under "Other"). Describe each by its kind (board, feed platform, discovery source), access route, terms verdict, the on-topic postings or employers it showed for the profession, and effort.

- Terms verdicts are `allowed`, `unsure` or `reserved` (`docs/job-sites.md`, "How The other door fetches"); never ask for robots.txt to be obeyed or the User-Agent to be changed.
- An `unsure` source (its terms forbid automated access) is never a board or a feed. It may be an option only as a discovery source, labelled as such, with its own switch and the disclaimer.
- `reserved` sources are offered only with "(registered reserved: never fetched)" in the description.
- A source whose terms weren't found is `allowed`, described as "no terms found". The builder records every source's verdict, its one-sentence summary and the quoted terms in the module docstring.
- Sources the research found walled (login, CAPTCHA, bot challenge, API key) are never boards; they are options only as discovery sources, when the report says their logged-out pages name the employers, and otherwise go in the follow-ups.

Write the choice to `thoughts/profession/<cc>-<slug>/plan.md`:
1. the question exactly as asked (its text, and each option's label and description), then the answer;
2. the sources in build order, each with its kind, module name and country code (`any` for a worldwide one);
3. the profession's fake profile from the report (role targets: the given titles; search keywords and topic terms per language; `remote`; the city), and its on-topic and off-topic titles;
4. the report's non-build recommendations: employers to follow by careers URL, door gaps to file as issues.

If nothing was picked, go to step 5 with the profile and the gaps alone (the profession row and the issues are still worth having).

## Step 3: Build, one at a time

The builders all edit `sites.py` (or `discovery_sources.py`) and the same doc tables, so run them sequentially. For each source in `plan.md`, spawn `scraper-builder` with:

```
site: <module>
country_code: <cc | any>
mode: new
kind: board | feed | discovery
keyword: <the profession's main search keyword, from plan.md>
research: <that source's "#### <module>" section of research.md>
```

For an existing site that should also serve the country, pass `mode: extend` with the research's Already covered section.

Save each report to `thoughts/profession/<cc>-<slug>/scraper-<module>.md` (a second attempt's report appended below the first). After each: `./scripts/run-test.sh` must be green and the agent must have committed. If the suite is red, or the live smoke test failed for a reason that isn't the site walling logged-out requests, run the builder once more with the failure output as `validation_feedback`. If the builder stopped (terms, a browser-only site, a wall), record why in `plan.md` and go on to the next source.

## Step 4: Live smoke

Each new source's live file has one probe-sized test per mode that applies (`listing`, `page2`, `details`, `zero_hits`, `detection` or `employers`; `tests/scrapers/test_live_modes_unit.py` checks offline that none is missing), each searching for the profession's keyword. The weekly live-smoke workflow runs every `tests/**/test_*_live.py`, so the new tests join it. Run them now:

```bash
./scripts/run-test.sh --live tests/scrapers/<pkg>test_<module>_live.py …   # every new and extended source; <pkg>: boards/, discovery/ or feeds/
```

A failure goes back to that source's builder once, as in step 3.

## Step 5: The profession's tests and docs

1. **The profession suite.** If `tests/professions.py` exists (#427), add or update the profession's row from `plan.md`: the config for `<cc>`, the on-topic and off-topic titles, and the postings for the pre-filter and prescreen. A title the research found The other door gets wrong is marked `xfail(strict=True)` naming the issue filed in step 6, never left out. Run `./scripts/run-test.sh`. If the suite doesn't exist yet, put the row in `plan.md` under "For #427" and say so in the report.
2. **Docs, profession-level** (the builders added their per-site rows):
   - `docs/job-sites.md` → the "Sources by profession" table (add the section after Supported countries if it isn't there yet: Profession, Country, Boards, Feeds worth following, Discovery, Notes). One row for this profession and country naming what reaches its jobs, built or already there, and the employers to follow by careers URL.
   - A new discovery source: its key in `docs/configuration.md`'s Keys table (the builder adds it; check).

   Check every new source has its rows in `docs/job-sites.md` and `docs/architecture.md`, and add any that are missing (no test compares the doc tables with the registries, so read them). Run `./scripts/run-test.sh` and commit (`"<Profession> in <country>: sources and tests"`).

## Step 6: Issues for the gaps

For each door gap in `plan.md` (title matching, locality, seniority words, naming, a platform refused):
1. search the open issues (`mcp__github__search_issues`) for it;
2. add the profession's example to a matching issue, or open a new one under epic #426 (`parent_issue_number`).

Each issue gets the concrete failing input and the expected result, ready for a failing test. Note each issue number in `plan.md`. Don't fix them here: this skill adds sources.

## Step 7: Validate

Spawn `profession-validator` with:

```
profession: <name>
titles: <the titles>
country_code: <cc>
country_name: <name>
profile: <the fake profile from plan.md>
new_sources: <each source built, with its kind>
extended_sites: <the sites extended, or none>
base_branch: main
state_dir: thoughts/profession/<cc>-<slug>
report_path: thoughts/profession/<cc>-<slug>/validate.md
```

**On FAIL:** route each gap in the report to its owner once — `scraper-builder` for that source (parsing, outcomes, tests, its live smoke), or fix the docs and the profession row yourself — passing the gaps as `validation_feedback`; then validate once more.

Gaps whose owner is `profession-researcher` or `skill` (the research or the checkpoint fell short), and door gaps already filed in step 6, can't be fixed in this run: don't re-run anything for them, carry them into the report. Report whatever the second verdict is; don't loop further.

## Step 8: Report

```
Profession:  <name> in <country> (<cc>): <the titles>
Branch:      feat/profession-<cc>-<slug>
Sources:     <built> built, <extended> extended, <skipped> skipped
Baseline:    <on-topic postings / employers before>  →  after: <on-topic postings / employers in the validation run>
Validation:  PASS | FAIL (attempts: 1 | 2)
Commits:     <short hashes>
Issues:      <numbers filed or updated>
```

Then a table, one row per source: kind, route, terms verdict, offline tests, live smoke, on-topic postings or employers in the sandbox run. Then the validator's process gaps, if any. Then the follow-ups:
- the skipped sources and why;
- the walled sources;
- the employers to follow by careers URL;
- the ATS platforms without a door feed that the research counted.

If FAIL, a paragraph saying what is missing and why.

End by offering `/dev-pr` to open the pull request.
