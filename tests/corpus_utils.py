"""The saved real ads the country and language checks read (`tests/i18n/corpus/`, written by
`scripts/refresh_corpus.py` from the rows of `tests/live_matrix.py`)."""

import json

from paths import TESTS_DIR

CORPUS = TESTS_DIR / "i18n" / "corpus"


def load(kind: str, key: str) -> dict:
    """`kind` is ``countries`` or ``languages``; *key* a country or language code."""
    return json.loads((CORPUS / kind / f"{key}.json").read_text(encoding="utf-8"))
