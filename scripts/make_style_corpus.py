"""Build the made-up CVs of the style corpus (#148): tests/tailoring/fixtures/styles/*.pdf that no real tool wrote.

Three HTML designs of `scripts/cv_style_proto/cvs.py` (a Word-like two columns, a Canva-like coloured sidebar with
icons, a plain single column) plus a LinkedIn-like export (record 4) are printed by the pinned Chromium (`door.tailoring.html_pdf`),
set in the fonts of `profile.example/fonts` only (Figtree, Young Serif) so that nothing depends on the fonts of the
computer that runs this; the scan is the plain one rendered to a grey picture. Everything is made up: fake names,
`example.com` addresses. Not run in CI: the PDFs are committed, and `expected.json` beside them is what the
tests read them back as.

    DOOR_BIN=<folder with chromium> poetry run python scripts/make_style_corpus.py [--out DIR]
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from door.tailoring import html_pdf, pdf_render  # noqa: E402

_spec = importlib.util.spec_from_file_location("cvs", REPO / "scripts" / "cv_style_proto" / "cvs.py")
cvs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cvs)

FONT_DIR = REPO / "profile.example" / "fonts"
OUT = REPO / "tests" / "tailoring" / "fixtures" / "styles"
_FACES = [("Figtree", "Figtree-Regular.ttf", 400, "normal"), ("Figtree", "Figtree-Italic.ttf", 400, "italic"),
          ("Figtree", "Figtree-SemiBold.ttf", 600, "normal"), ("Figtree", "Figtree-SemiBoldItalic.ttf", 600, "italic"),
          ("Young Serif", "YoungSerif-Regular.ttf", 400, "normal")]


def with_fonts(html: str) -> str:
    """*html* with the example profile's fonts: Figtree for everything and Young Serif for the name."""
    faces = "".join(f"@font-face{{font-family:'{family}';src:url(/fonts/{name});font-weight:{weight};font-style:{style}}}"
                    for family, name, weight, style in _FACES)
    override = f"<style>{faces}body{{font-family:Figtree,sans-serif !important}}h1{{font-family:'Young Serif',serif !important}}</style>"
    return html.replace("</head>", override + "</head>", 1)


def linkedin_html(r: dict) -> str:
    """A made-up export in the layout of LinkedIn's: a side column of Contact, Top Skills, Languages and
    Certifications, a main one of Summary, Experience and Education, two fixed pages with `Page N of 2` in the foot."""
    c = r["contact"]
    job = lambda j: (f"<div class='job'><b>{cvs.e(j['company'])}</b><div>{cvs.e(j['role'])}</div>"  # noqa: E731
                     f"<div class='dates'>{cvs.e(j['dates'])}</div><p>{cvs.e(j['bullets'][0])}</p></div>")
    side = (f"<h2>Contact</h2><div>{cvs.e(c['phone'])}</div><div>{cvs.e(c['email'])}</div><div>{cvs.e(c['web'])}</div>"
            f"<h2>Top Skills</h2>{''.join(f'<div>{cvs.e(s)}</div>' for s in r['skills'][:3])}"
            f"<h2>Languages</h2>{''.join(f'<div>{cvs.e(s)}</div>' for s in r['languages'])}"
            f"<h2>Certifications</h2><div>Example Certificate</div><div>Another Certificate</div>")
    first = (f"<h1>{cvs.e(r['name'])}</h1><div class='headline'>{cvs.e(r['title'])}</div><div>{cvs.e(c['location'])}</div>"
             f"<h2>Summary</h2><p>{cvs.e(r['summary'])}</p><h2>Experience</h2>{job(r['experience'][0])}{job(r['experience'][1])}")
    second = (f"{job(r['experience'][2])}<h2>Education</h2>"
              + "".join(f"<div class='job'><b>{cvs.e(x['school'])}</b><div>{cvs.e(x['degree'])}</div><div class='dates'>{cvs.e(x['dates'])}</div></div>"
                        for x in r["education"]))
    css = ("@page{size:A4;margin:0}*{box-sizing:border-box}body{margin:0;font:10pt Arial,sans-serif;color:#262626}"
           ".page{width:210mm;height:297mm;position:relative;overflow:hidden;page-break-after:always;padding:40px}"
           ".side{position:absolute;left:40px;top:40px;width:55mm}.main{margin-left:66mm}h1{font-size:22pt;margin:0}"
           "h2{font-size:12pt;margin:18px 0 6px}.headline{color:#555}.dates{color:#777}.job{margin-bottom:10px}"
           ".foot{position:absolute;bottom:14mm;left:0;right:0;text-align:center;color:#777;font-size:8pt}")
    page = lambda inner, n, extra="": f"<div class='page'>{extra}<div class='main'>{inner}</div><div class='foot'>Page {n} of 2</div></div>"  # noqa: E731
    body = page(first, 1, f"<div class='side'>{side}</div>") + page(second, 2)
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"


def scan_pdf(image: Image.Image, out: Path) -> None:
    """A scan: *image* as grey pixels, the only thing on one page, no text."""
    image.convert("L").convert("RGB").save(out, "PDF", resolution=100.0)


def build(out: Path, printer=html_pdf.print_html) -> None:
    """Write the corpus PDFs into *out*: the three HTML designs, the LinkedIn-like export and the scan."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    fonts = [FONT_DIR / name for _, name, _, _ in _FACES]
    pages = [("html-word-two-column", cvs.source(1)), ("html-canva-icons", cvs.source(2)),
             ("html-plain-single", cvs.source(3)), ("linkedin-like", linkedin_html(cvs.record(4)))]
    with tempfile.TemporaryDirectory() as folder:
        for stem, html in pages:
            printer(Path(folder), with_fonts(html), out / f"{stem}.pdf", assets={"fonts": fonts})
    plain = out / "html-plain-single.pdf"
    scan_pdf(_first_page_image(plain), out / "scan.pdf")


def _first_page_image(pdf: Path) -> Image.Image:
    doc = pdf_render.open_pdf(pdf)
    try:
        return doc[0].render(scale=100 / 72).to_pil()
    finally:
        doc.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    build(parser.parse_args().out)


if __name__ == "__main__":
    main()
