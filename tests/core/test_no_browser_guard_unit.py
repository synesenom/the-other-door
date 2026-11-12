"""No browser: The other door reads every site over plain HTTP, so nothing may import Playwright and the
dependency stays out of `pyproject.toml`."""

import re

from paths import REPO_ROOT

_IMPORT = re.compile(r"^\s*(?:from|import)\s+playwright\b", re.M)


def test_nothing_under_src_imports_playwright():
    offenders = [str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "src").rglob("*.py")
                 if _IMPORT.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_playwright_is_not_a_dependency():
    assert "playwright" not in (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
