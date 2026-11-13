"""Save the real ads the country and language checks read offline (#19): `tests/i18n/corpus/`.

The only part of those checks that goes online. Run it now and then (a new country or language file, or a
check that starts failing because the ads moved on), then commit what it wrote:

- **countries/<cc>.json**: the places page 1 of a board serving the country names (`probe`, one request), from
  the row's city in `tests/live_matrix.COUNTRIES`; only the location strings, no ad text;
- **languages/<code>.json**: a few ads written in the language, from one search of the row's source in
  `tests/live_matrix.LANGUAGES` (one results page); their descriptions cut to `MAX_CHARS`, emails and phone
  numbers replaced with made-up ones (`tests/core/test_fixture_privacy_unit.py` checks them).

Usage:  poetry run python scripts/refresh_corpus.py [cc|code ...]   (none: every row)
"""

import datetime
import json
import pathlib
import re
import sys

_REPO = pathlib.Path(__file__).resolve().parent.parent
CORPUS = _REPO / "tests" / "i18n" / "corpus"
MAX_CHARS = 3000
MAX_ADS = 8
_MIN_TEXT = 300  # shorter than this, an ad says too little to tell its language

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# A phone number: an optional country code, then eight or more digits in groups ("22 33 44 55", "+36 30 123 4567").
_PHONE = re.compile(r"(?:\+|00)?\d{1,3}[\s.-]?(?:\d[\s.-]?){7,}\d|\b\d{2}[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}\b")


def scrub(text: str) -> str:
    """An ad's text as it is saved: contacts made up, cut to `MAX_CHARS`."""
    text = _EMAIL.sub("kontakt@example.com", text)
    text = _PHONE.sub("00 00 00 00", text)
    return text[:MAX_CHARS]


def country_places(postings: list[dict]) -> list[str]:
    return [p["location"] for p in postings if p.get("location")]


def language_texts(postings: list[dict]) -> list[str]:
    return [p["description"].strip() for p in postings if len((p.get("description") or "").strip()) >= _MIN_TEXT]


def _write(kind: str, key: str, data: dict) -> None:
    path = CORPUS / kind / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(_REPO)}")


def refresh_country(cc: str, run) -> None:
    from live_matrix import module

    config = {"location": run.city, "search_keywords": [run.keyword], "role_targets": [run.keyword]}
    result = module(run).probe(config)
    if not result or not result.get("structure_ok"):
        raise SystemExit(f"{cc}: {run.source} gave no results page for {run.keyword!r} in {run.city}; nothing written")
    _write("countries", cc, {"source": run.source, "city": run.city, "keyword": run.keyword,
                             "captured": datetime.date.today().isoformat(),
                             "places": country_places(result["postings"])})


def refresh_language(code: str, run) -> None:
    from live_matrix import module

    scraper = module(run)
    for knob in ("_MAX_PAGES", "_MAX_SEARCHES"):  # one results page, one search: a sample, not a crawl
        if hasattr(scraper, knob):
            setattr(scraper, knob, 1)
    config = {"location": run.city, "search_keywords": [run.keyword], "role_targets": [run.keyword],
              "max_pages_per_keyword": 1}
    texts = [scrub(t) for t in language_texts(scraper.scrape(config))][:MAX_ADS]
    if not texts:
        raise SystemExit(f"{code}: {run.source} gave no ad with a description for {run.keyword!r}; nothing written")
    _write("languages", code, {"source": run.source, "city": run.city, "keyword": run.keyword,
                               "captured": datetime.date.today().isoformat(), "texts": texts})


def main(argv: list[str]) -> None:
    sys.path[:0] = [str(_REPO / "src"), str(_REPO / "tests")]
    from live_matrix import COUNTRIES, LANGUAGES

    wanted = set(argv)
    for cc, run in sorted(COUNTRIES.items()):
        if not wanted or cc in wanted:
            refresh_country(cc, run)
    for code, run in sorted(LANGUAGES.items()):
        if not wanted or code in wanted:
            refresh_language(code, run)


if __name__ == "__main__":
    main(sys.argv[1:])
