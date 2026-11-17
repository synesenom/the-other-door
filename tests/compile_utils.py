"""A stand-in for the Chromium print in tests of `compile` (#146): it records what was handed over and writes a real
PDF whose text is the page's text, so the read-back and the page renderer work on it."""

from __future__ import annotations

from pathlib import Path

from door.core import chromium
from door.render import html_doc, html_pdf
from pdf_utils import make_pdf


class FakePrint:
    """`calls`: one dict per print (``html``, ``assets``, ``folder``, ``files`` seen in the folder)."""

    def __init__(self, fail: str | None = None):
        self.calls: list[dict] = []
        self.fail = fail

    def __call__(self, folder, html, out_pdf, *, assets=None, timeout=60.0, launcher=None):
        folder = Path(folder)
        self.calls.append({"html": html, "assets": assets, "folder": folder,
                           "files": sorted(p.name for p in folder.iterdir())})
        if self.fail:
            raise html_pdf.PrintError(self.fail)
        body = html.split("<body>", 1)[-1]
        make_pdf(Path(out_pdf), [html_doc.text(body)])


def install(monkeypatch, fail: str | None = None) -> FakePrint:
    """Patch the print and make Chromium look installed; returns the recorder."""
    fake = FakePrint(fail)
    monkeypatch.setattr(html_pdf, "print_html", fake)
    monkeypatch.setattr(chromium, "find_chromium", lambda home=None: "/fake/chrome-headless-shell")
    return fake
