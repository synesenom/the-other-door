---
name: dev-add-country
description: Add a whole country to The other door — research its job boards, write its data files and the scrapers test-first, document them, add the live smoke tests, and validate the country with throwaway fake profiles (English only, and English plus the local language). Invoked with /dev-add-country <country> (a name or an ISO 3166 code).
---

You are the country orchestrator for The other door. The country is passed as the argument. You run the agents below in order and keep the state between them in `thoughts/country/<cc>/` (gitignored), so a stopped run picks up where it left off. Every agent's report is saved there too (the files below), so the run can be checked afterwards without its conversation: the validator reads them. `docs/adding-a-site.md` is the reference for what a country and a site need.

**Country is not language.** A country decides which boards a profile's `location` gets; the profile's `languages` decides which ads survive, from each ad's detected language. Someone in Denmark may want English ads only, someone in Hungary English and Hungarian. Every step serves both seekers: boards are judged on their English ads too, scrapers never filter by language, the language file carries English-phrased requirement lines ("Hungarian required"), and validation runs an English-only profile next to an English-plus-local one.

**Decision policy:** decide everything yourself, documenting the choice, except at the one checkpoint in step 2 (which boards to build), and stop to ask if a board's terms are unclear in a way the rules in `docs/adding-a-site.md` don't settle.

---

## Step 0: Set up

1. Resolve the argument to an ISO 3166-1 alpha-2 code (lower case) and English name. If it is ambiguous, ask with AskUserQuestion.
2. Look at what exists: `src/door/i18n/country/<cc>.toml`, and the sites in `src/door/core/sites.py` with `<cc>` in `countries`. Tell the user in one line (`Germany (de): no country file, no sites yet`).
3. The working tree must be clean (`git status --porcelain`); if it isn't, stop and say so. Unless the current branch is already `feat/country-<cc>`, branch from the default branch: `git fetch origin && git checkout -b feat/country-<cc> origin/main`.
4. `mkdir -p thoughts/country/<cc>`.

## Step 1: Research

If `thoughts/country/<cc>/research.md` exists, read it and skip the agent. Otherwise spawn `country-researcher` with:

```
country_code: <cc>
country_name: <name>
report_path: thoughts/country/<cc>/research.md
```

Make sure the report landed at that path (write it there from the agent's answer if not), with its Requests section.

## Step 2: Checkpoint — pick the boards

Show the user the report's Boards table and its Recommendation in a few lines. Terms verdicts are `allowed`, `unsure` or `reserved` (`docs/job-sites.md`, "How The other door fetches"); never ask for robots.txt to be obeyed or the User-Agent to be changed. A board whose terms verdict is `unsure` (its terms forbid automated access) is offered only as an employer discovery source with its own switch and the disclaimer (a module like `scrapers/discovery/profession.py`, not a `Site`), clearly labelled as such: a site that can't be a board (terms, a key-only API, pages too hard to parse) is still worth reading for its employers, whose own feeds `follow` then finds. No option ever needs credentials (an API key, an OAuth client, an account). Then ask with one AskUserQuestion (`multiSelect: true`): the recommended boards as options, best first, each described by its access route, English ads share, terms verdict and effort (at most four; the user names others under "Other"). Put an extension of an existing site or source in as an option when the research says it serves the country. An `unsure` board is never an option as a board; `reserved` ones only with "(registered reserved: never fetched)" in the description. A board whose terms weren't found is `allowed`, described as "no terms found"; the builder still looks for them before anything else and records the verdict, its one-sentence summary and the quoted terms in the module docstring.

Write the choice to `thoughts/country/<cc>/plan.md`: first the question exactly as asked (its text, and each option's label and description), then the answer, then the boards in build order, the extended sites, and the capital and the country's languages (local, besides English) for validation. If nothing was picked, stop.

## Step 3: Country data

Skip if the country file exists and every language the country's ads are written in has a lang file. The lang file matters even when you expect mostly English-reading users: its English-phrased requirement lines are what flag an English ad that demands the local language. Otherwise spawn `country-data-writer` with:

```
country_code: <cc>
country_name: <name>
country_data: <the "### Country data" section of research.md>
```

The country file also carries what employer feed detection reads: `tlds`, `career_hosts` and `job_boards` (whole domains); check them in the report, and that its `[cv]` block (photo, date of birth, pages, date format) matches the research report's `### CV conventions`. The agent also adds the country's rows (English only, and English plus the local language) to `COUNTRIES` in `tests/pipeline/test_pipeline_countries_end_to_end.py`, the offline `find` run per country, and to `PROFILES` in `scripts/country_smoke.py`, the live one (`tests/scripts/test_country_smoke_unit.py` checks the row names against `COUNTRIES`); check they are there. Save its report to `thoughts/country/<cc>/data.md`. It must come back with a green suite and a commit. If it doesn't, run it once more with its report as `validation_feedback` (append the second report to `data.md`); if it still fails, stop and report. The scrapers need the country file, so nothing below runs without it.

## Step 4: Scrapers, one at a time

The builders all edit `sites.py` and the same doc tables, so run them sequentially. For each board in `plan.md`, spawn `scraper-builder` with:

```
site: <module>
country_code: <cc>
mode: new
research: <that board's "#### <module>" section of research.md>
```

and for each extended site or source (a site: its `countries`; a discovery source: its `COUNTRIES`), `mode: extend` with the research's Already covered section.

Save each report to `thoughts/country/<cc>/scraper-<site>.md` (a second attempt's report appended below the first). After each: `./scripts/run-test.sh` must be green and the agent must have committed. If the suite is red or the live smoke test failed for a reason that isn't the site walling logged-out requests, run the builder once more with the failure output as `validation_feedback`. If the builder stopped (terms, a browser-only site, a wall), record why in `plan.md` and go on to the next board.

## Step 5: Country docs

The builders added their per-site rows. Write the country-level ones yourself:

- `docs/job-sites.md` → the Supported countries table: a row for the country naming its boards ("— plus every worldwide site", like Denmark's), and the boards list in the paragraph under it.
- `README.md` → its Supported countries table, the same row.
- `src/door/commands/find.py` → the `find` docstring's "every job board of your country (…)" list, if it names boards.
- A new language: check the supported-language lists in `docs/configuration.md`, `docs/job-sites.md` and `docs/how-it-works.md` (the data writer should have done it).

Check every new site has its rows in `docs/job-sites.md` and `docs/architecture.md`; add any that are missing (no test compares the doc tables with `SITES`, so read them). Run `./scripts/run-test.sh` and commit (`"Document <country>'s job boards"`).

## Step 6: Live smoke

Each new site's live file has one probe-sized test per mode that applies to it (`listing`, `page2`, `details`, `zero_hits` for a board, `detection` for a feed platform, `employers` for a discovery source; `NO_PAGE2`/`NO_DETAILS` say why one does not apply), which `tests/scrapers/test_live_modes_unit.py` checks offline; a failure names the site and the mode (`<site> [details]: ...`). The weekly live-smoke workflow already runs every `tests/**/test_*_live.py`, and `scripts/smoke_report.py` lists each dimension on its own (boards, employer feeds, employer discovery), so the new sites join `docs/badges/live-smoke.md` and the README's per-dimension badges on its next run: don't edit those generated files. Run them now, and save the country's and its new languages' real ads for the offline checks (`tests/i18n/corpus/`), then run those:

```bash
./scripts/run-test.sh --live tests/scrapers/<pkg>test_<site>_live.py …   # every new and extended site; <pkg>: boards/, discovery/ or feeds/
poetry run python scripts/refresh_corpus.py <cc> <code> …                # the country and each new language
poetry run pytest tests/i18n/test_country_corpus.py tests/i18n/test_language_corpus.py
```

Commit what `refresh_corpus.py` wrote.

A site's failure goes back to that site's builder once, as in step 4; a country's or a language's to `country-data-writer` once, with the failure as `validation_feedback`.

## Step 7: Validate

Spawn `country-validator` with:

```
country_code: <cc>
country_name: <name>
capital: <from plan.md>
local_languages: <the country's languages, from plan.md>
new_sites: <the boards built>
extended_sites: <the sites extended, or none>
base_branch: main
state_dir: thoughts/country/<cc>
report_path: thoughts/country/<cc>/validate.md
```

**On FAIL:** route each gap in the report to its owner once — `country-data-writer` (cities, language words), `scraper-builder` for that site (parsing, outcomes, tests), or fix docs gaps yourself — passing the gaps as `validation_feedback`; then validate once more. Process gaps (owner `country-researcher` or `skill`: the research or the checkpoint fell short) can't be fixed after the fact: don't re-run anything for them, carry them into the report. Report whatever the second verdict is; don't loop further.

## Step 8: Report

```
Country:     <name> (<cc>)
Branch:      feat/country-<cc>
Boards:      <built> built, <extended> extended, <skipped> skipped
Validation:  PASS | FAIL (attempts: 1 | 2)
Commits:     <short hashes>
```

Then a table, one row per site: kind, route, terms verdict, offline tests, live smoke, sandbox outcome and count. Then the validator's process gaps, if any. Then the follow-ups: the skipped boards and why, the research's common ATS platforms without a door feed, and any `site-side` failures. If FAIL, a paragraph saying what is missing and why.

End by offering `/dev-pr` to open the pull request.
