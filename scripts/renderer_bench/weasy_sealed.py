"""python weasy_sealed.py <folder> <page.html> <out.pdf>: WeasyPrint with a url_fetcher that reads only
files under <folder> and refuses every other file and address (#145: this folder only)."""
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from weasyprint import HTML, default_url_fetcher

folder, html, out = (Path(a).resolve() for a in sys.argv[1:4])


def fetch(url, *args, **kwargs):
    parsed = urlparse(url)
    if parsed.scheme == "file" and Path(unquote(parsed.path)).resolve().is_relative_to(folder):
        return default_url_fetcher(url, *args, **kwargs)
    raise ValueError(f"refused: {url}")


HTML(filename=str(html), url_fetcher=fetch).write_pdf(str(out))
