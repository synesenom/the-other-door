---
name: dev-add-scraper
description: Scaffold a new scraper module for a job board not yet supported, registered for the countries it serves. Invoked with /dev-add-scraper <site-name> [country].
---

You are adding one job site to The other door. The site name is passed as the argument, optionally followed by the ISO 3166 code of the country it serves (none: a site that works anywhere). For a whole new country (its data files, several boards, docs and a validation run) use `/dev-add-country <country>` instead.

1. If a country is given, check `src/door/i18n/country/<cc>.toml` exists. If it doesn't, stop: the site can only be registered for a country with a data file, and `/dev-add-country` writes it.

2. Spawn the `scraper-builder` agent with:

   ```
   site: <site-name>
   country_code: <cc or "any">
   mode: new
   ```

   It researches the site and its terms, saves real payloads as fixtures, writes the unit, fixture, probe and live smoke tests first, then the module, the `SITES` entry and the per-site doc rows, and commits. All the rules (`docs/adding-a-site.md`, `CLAUDE.md`) are in `.claude/agents/scraper-builder.md`.

3. Run `./scripts/run-test.sh`. If it is red, or the builder's live smoke test failed for a reason other than the site walling logged-out requests, spawn the builder once more with the failure output as `validation_feedback`.

4. Report the builder's summary: route, terms verdict, files, tests, offline suite, live smoke, commit. If the builder stopped (the terms forbid it, the listings need a browser, a login or an API key), say why.
