"""The tables of contents of the long Markdown docs (`scripts/toc.py`)."""

import importlib.util

from tests.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("toc", REPO_ROOT / "scripts" / "toc.py")
toc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(toc)


def test_every_long_doc_has_a_current_table_of_contents():
    """Fails when a doc grew past the bar or its headings changed: run `python3 scripts/toc.py`."""
    stale = toc.stale(REPO_ROOT)
    assert not stale, f"run `python3 scripts/toc.py`: these docs need their contents (re)written: {stale}"
