# tests

The folders mirror the package, so a module's tests are easy to find:

```
tests/
├── conftest.py, paths.py, cli_utils.py, profile_utils.py, professions.py (the six profession profiles of the profession suite), pipeline_utils.py, golden_utils.py
├── scrapers/              # the shared helpers' tests, and fixtures/robots/ (saved robots.txt files)
│   ├── boards/            # the keyword boards' test_<site>_{unit,scrape,live}.py, with their fixtures/<site>/
│   ├── discovery/         # the discovery sources' tests, with their fixtures/<source>/
│   └── feeds/             # the employer feed platforms' tests, with their fixtures/<site>/
├── commands/              # one test_<command>_cli.py per CLI command, plus the MCP tool list
├── core/                  # src/door/core/: doctor, installers, sites, history, lock, candidates, runs, …
├── pipeline/              # src/door/pipeline/: `find`'s five steps (search, discover, follow, collect, match), the step display, and all of them together (`test_pipeline_countries_end_to_end.py`: one `find` per country and ad languages)
├── i18n/                  # src/door/i18n/: every language and country data file, detection
├── matching/              # prefilter, dedup, condense, language, prescreen, scorer; fixtures/golden/
├── tailoring/
├── skills/                # the skills under .claude/: the tools they name exist (offline), and each run by the real model on the test world (`./scripts/run-test.sh --skills`, before a release)
└── scripts/               # scripts/smoke_report.py (the live-smoke status page), scripts/country_smoke.py (the live country run; its pure parts are tested in tests/scripts/test_country_smoke_unit.py, the live run is not part of the suite)
```

A scraper's tests and fixtures mirror the package: `src/door/scrapers/feeds/<site>.py` is tested in
`scrapers/feeds/`, its saved responses in `scrapers/feeds/fixtures/<site>/`; the same for `boards/`
and `discovery/`. Shared paths (`REPO_ROOT`, `TESTS_DIR`,
`GOLDEN_DIR`) come from `paths.py`, so a test never depends on its own depth. The
helpers here import by name: pytest puts `tests/` on the path (`pythonpath` in
`pyproject.toml`). No offline test can reach the network: `conftest.py` refuses every real
HTTP request (`responses` takes over where a test mocks one) and the command and pipeline
conftests refuse a real browser.

## Three layers

Matching `CLAUDE.md` → *Testing*; the layer is in the file name:

| Layer | What it covers | Network? | Files |
|-------|----------------|----------|-------|
| **Unit** | Pure helpers and the data model in isolation (`make_job_id`, `_location_text`, `_parse_date`, `_area_for_profile`, `_country_code`, …). | No | `test_*_unit.py`, `core/test_models.py` |
| **Fixture** | The full `scrape(config)` path — pagination, dedup, mapping — with the HTTP layer mocked from saved real responses in `scrapers/<kind>/fixtures/<site>/`; commands end to end with the scrapers, `claude -p` and LaTeX faked. | No (mocked) | `test_*_scrape.py`, `test_*_cli.py` |
| **Corpus** | Each country file and each language file against saved real ads (`i18n/test_country_corpus.py`, `i18n/test_language_corpus.py` on `i18n/corpus/`; `scripts/refresh_corpus.py` saves them from the rows of `live_matrix.py`, the only part online). Offline, in every run. | No | `i18n/test_*_corpus.py` |
| **Smoke** | A thin contract check against the *live* site: returns ≥1 valid `JobPosting`; each feed platform's careers page still detected (`live_employers.py`), each discovery source still yields employers. Verdicts and messages from `live_utils.py`. Each profession also has a run of its own (`pipeline/test_professions_live.py`, the offline half is `matching/test_professions_unit.py`; both read `professions.py`). Marked `@pytest.mark.live`, opt-in. | Yes | `test_*_live.py` |

## Running

```bash
./scripts/run-test.sh                         # offline suite in parallel (-n auto) + coverage + regenerate badge
poetry run pytest -n auto                     # the offline suite in parallel, no coverage (as CI runs it)
./scripts/run-test.sh --live                  # smoke tests against real sites (network)
poetry run pytest tests/scrapers/dk           # one folder
```

Fixtures are saved real responses. To refresh one, capture a live response and
overwrite the file — keep them small (a handful of postings is enough to exercise
parsing).
