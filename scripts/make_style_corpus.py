"""Build the made-up CVs of the style corpus (#148): tests/tailoring/fixtures/styles/*.pdf that no real tool wrote.

Three HTML designs (a Word-like two columns, a Canva-like coloured sidebar with
icons, a plain single column) plus a LinkedIn-like export (record 4) are printed by the pinned Chromium (`door.tailoring.html_pdf`),
set in the fonts of `profile.example/fonts` only (Figtree, Young Serif) so that nothing depends on the fonts of the
computer that runs this; the scan is the plain one rendered to a grey picture. Everything is made up: fake names,
`example.com` addresses. Not run in CI: the PDFs are committed, and `expected.json` beside them is what the
tests read them back as.

    DOOR_BIN=<folder with chromium> poetry run python scripts/make_style_corpus.py [--out DIR]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from html import escape
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from door.tailoring import html_pdf, pdf_render  # noqa: E402

FONT_DIR = REPO / "profile.example" / "fonts"
OUT = REPO / "tests" / "tailoring" / "fixtures" / "styles"
_FACES = [("Figtree", "Figtree-Regular.ttf", 400, "normal"), ("Figtree", "Figtree-Italic.ttf", 400, "italic"),
          ("Figtree", "Figtree-SemiBold.ttf", 600, "normal"), ("Figtree", "Figtree-SemiBoldItalic.ttf", 600, "italic"),
          ("Young Serif", "YoungSerif-Regular.ttf", 400, "normal")]

_PEOPLE = [
    ("Mira Valdis", "Data Engineer", "Copenhagen"), ("Jonas Brekke", "Product Designer", "Aarhus"),
    ("Lena Ortiz", "Backend Developer", "Odense"), ("Tomas Reyes", "Project Manager", "Malmo"),
    ("Ines Kovacs", "Test Engineer", "Aalborg"),
]
_COMPANIES = ["Northwind Labs", "Bluebird Systems", "Kestrel Analytics", "Fjord Software", "Linden Works",
              "Harbor Digital", "Quill & Co", "Maple Robotics", "Tidewater Data", "Ember Studio"]
_BULLETS = [
    "Built and maintained services used by about 40 000 people a month.",
    "Cut the nightly pipeline from 3 hours to 25 minutes by rewriting its slowest stage.",
    "Led a team of 4 through a migration with no downtime.",
    "Wrote the onboarding guide that new colleagues still start from.",
    "Introduced code review and automated checks across 6 repositories.",
    "Presented results to management every quarter and agreed the next priorities.",
]
_SKILLS = ["Python", "SQL", "Docker", "Git", "Project planning", "Data analysis", "Figma", "TypeScript",
           "Communication", "Statistics"]


def record(n: int) -> dict:
    """The made-up CV number *n* (1-5)."""
    name, title, city = _PEOPLE[n - 1]
    slug = name.lower().replace(" ", ".")
    jobs = [
        {"role": f"{title}", "company": _COMPANIES[(n + i) % len(_COMPANIES)],
         "dates": f"{2023 - 3 * i} - {'present' if i == 0 else 2023 - 3 * i + 3}",
         "bullets": [_BULLETS[(n + i + j) % len(_BULLETS)] for j in range(3)]}
        for i in range(3)
    ]
    return {
        "name": name, "title": title,
        "contact": {"phone": f"+45 20 30 40 {n}0", "email": f"{slug}@example.com",
                    "web": f"example.com/{slug}", "location": city},
        "summary": f"{title} with eight years of experience, who likes clear plans and small, steady steps.",
        "experience": jobs,
        "education": [{"degree": "MSc in Computer Science", "school": "Example University", "dates": "2013 - 2015"},
                      {"degree": "BSc in Mathematics", "school": "Example University", "dates": "2010 - 2013"}],
        "skills": [_SKILLS[(n + i) % len(_SKILLS)] for i in range(7)],
        "languages": ["English (fluent)", "Danish (native)", "French (basic)"],
    }


def e(text: str) -> str:
    return escape(str(text), quote=False)


# ---------- HTML designs (printed by Chromium; the fonts they name are swapped for the example profile's by `with_fonts`) ----------

def _html(css: str, body: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>@page{{size:A4;margin:0}}"
            f"*{{box-sizing:border-box}}body{{margin:0}}{css}</style></head><body>{body}</body></html>")


def _jobs_html(r):
    return "".join(
        f"<div class='job'><div class='row'><b>{e(j['role'])}</b><span class='dates'>{e(j['dates'])}</span></div>"
        f"<div class='co'>{e(j['company'])}</div><ul>{''.join(f'<li>{e(b)}</li>' for b in j['bullets'])}</ul></div>"
        for j in r["experience"])


def html_word_two_column(r: dict) -> str:
    c = r["contact"]
    css = ("body{font:10.5pt Calibri,'Helvetica Neue',Arial,sans-serif;color:#222;padding:40px}h1{font-size:26pt;margin:0;color:#1F3864}"
           "h2{font-size:12pt;color:#1F3864;border-bottom:1.5px solid #1F3864;margin:14px 0 6px;text-transform:uppercase}"
           ".cols{display:flex;gap:28px}.main{flex:2}.side{flex:1}.row{display:flex;justify-content:space-between}"
           ".co{color:#555;font-style:italic}ul{margin:4px 0 8px;padding-left:18px}.dates{color:#555}")
    side = (f"<h2>Contact</h2>{''.join(f'<div>{e(v)}</div>' for v in c.values())}<h2>Skills</h2>"
            f"{''.join(f'<div>{e(s)}</div>' for s in r['skills'])}<h2>Languages</h2>{''.join(f'<div>{e(s)}</div>' for s in r['languages'])}")
    main = (f"<h2>Profile</h2><p>{e(r['summary'])}</p><h2>Experience</h2>{_jobs_html(r)}<h2>Education</h2>"
            + "".join(f"<div><b>{e(x['degree'])}</b>, {e(x['school'])} <span class='dates'>{e(x['dates'])}</span></div>" for x in r["education"]))
    return _html(css, f"<h1>{e(r['name'])}</h1><div>{e(r['title'])}</div><div class='cols'><div class='main'>{main}</div><div class='side'>{side}</div></div>")


def html_equal_columns(r: dict) -> str:
    """Two columns of the same width, the skills, education and languages in the left one."""
    c = r["contact"]
    css = ("body{font:10.5pt Calibri,'Helvetica Neue',Arial,sans-serif;color:#222;padding:40px}h1{font-size:26pt;margin:0;color:#2E5E4E}"
           "h2{font-size:12pt;color:#2E5E4E;border-bottom:1.5px solid #2E5E4E;margin:14px 0 6px;text-transform:uppercase}"
           ".cols{display:flex;gap:28px}.left{flex:1}.right{flex:1}.row{display:flex;justify-content:space-between}"
           ".co{color:#555;font-style:italic}ul{margin:4px 0 8px;padding-left:18px}.dates{color:#555}")
    left = (f"<h2>About me</h2><p>{e(r['summary'])} I write things down, ask early when a plan is unclear and enjoy teaching colleagues what I have learned.</p><h2>Contact</h2>{''.join(f'<div>{e(v)}</div>' for v in c.values())}<h2>Skills</h2>"
            f"{''.join(f'<div>{e(s)}</div>' for s in r['skills'])}<h2>Education</h2>"
            + "".join(f"<div><b>{e(x['degree'])}</b>, {e(x['school'])} <span class='dates'>{e(x['dates'])}</span></div>" for x in r["education"])
            + f"<h2>Languages</h2>{''.join(f'<div>{e(s)}</div>' for s in r['languages'])}")
    right = f"<h2>Experience</h2>{_jobs_html(r)}"
    return _html(css, f"<h1>{e(r['name'])}</h1><div>{e(r['title'])}</div><div class='cols'><div class='left'>{left}</div><div class='right'>{right}</div></div>")


def html_three_columns(r: dict) -> str:
    """Three columns: contact, skills, languages and interests at the left, the experience in the middle, the
    education, projects and certifications at the right."""
    css = ("body{font:10pt Calibri,'Helvetica Neue',Arial,sans-serif;color:#222;padding:36px}h1{font-size:24pt;margin:0}"
           "h2{font-size:11pt;color:#a33;border-bottom:1px solid #a33}.cols{display:flex;gap:22px}.cols>div{flex:1}"
           ".mid{flex:1.4!important}ul{padding-left:14px}.row{display:flex;justify-content:space-between}.co{color:#555}")
    lines = lambda items: "".join(f"<div>{e(i)}</div>" for i in items)  # noqa: E731
    left = (f"<h2>Contact</h2>{lines(r['contact'].values())}<h2>Skills</h2>{lines(r['skills'])}"
            f"<h2>Languages</h2>{lines(r['languages'])}<h2>Interests</h2>{lines(['Chess', 'Hiking', 'Baking', 'Cycling', 'Reading'])}")
    mid = f"<h2>Experience</h2>{_jobs_html(r)}"
    right = ("<h2>Education</h2>"
             + "".join(f"<div><b>{e(x['degree'])}</b><div>{e(x['school'])}</div><div>{e(x['dates'])}</div></div>" for x in r["education"])
             + f"<h2>Projects</h2>{lines(f'Project {i}: a small tool for steady plans' for i in range(6))}"
             f"<h2>Certifications</h2>{lines(f'Certificate {i}, Example Institute' for i in range(4))}")
    return _html(css, f"<h1>{e(r['name'])}</h1><div class='cols'><div>{left}</div><div class='mid'>{mid}</div><div>{right}</div></div>")


_ICONS = {"phone": "M2 4h6l2 5-3 2a14 14 0 0 0 6 6l2-3 5 2v6a3 3 0 0 1-3 3A20 20 0 0 1 2 7a3 3 0 0 1 0-3z",
          "email": "M2 4h20v16H2zM2 5l10 8 10-8", "web": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM2 12h20M12 2c4 4 4 16 0 20",
          "location": "M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7zM12 7a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"}


def _icon(kind, color):
    return (f"<svg width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='{color}' stroke-width='2' "
            f"style='vertical-align:-2px;margin-right:6px'><path d='{_ICONS[kind]}'/></svg>")


def html_canva_icons(r: dict) -> str:
    c = r["contact"]
    css = ("body{font:10pt 'Avenir Next','Helvetica Neue',Arial,sans-serif;color:#2b2b2b;display:flex;min-height:297mm}"
           ".side{width:72mm;background:#E8625A;color:#fff;padding:36px 22px}.main{flex:1;padding:36px 30px}"
           "h1{font:700 24pt Georgia,serif;margin:0 0 4px}h2{font-size:11pt;letter-spacing:2px;text-transform:uppercase;margin:18px 0 6px}"
           ".side h2{border-bottom:1px solid #fff9}.main h2{color:#E8625A}.row{display:flex;justify-content:space-between}"
           ".co{color:#777}ul{padding-left:16px;margin:4px 0 8px}.chip{display:inline-block;background:#fff3;border-radius:10px;padding:2px 9px;margin:2px 2px 0 0}")
    side = (f"<h1>{e(r['name'])}</h1><div>{e(r['title'])}</div><h2>Contact</h2>"
            + "".join(f"<div style='margin:4px 0'>{_icon(k, '#fff')}{e(v)}</div>" for k, v in c.items())
            + "<h2>Skills</h2>" + "".join(f"<span class='chip'>{e(s)}</span>" for s in r["skills"])
            + "<h2>Languages</h2>" + "".join(f"<div>{e(s)}</div>" for s in r["languages"]))
    main = (f"<h2>About me</h2><p>{e(r['summary'])}</p><h2>Experience</h2>{_jobs_html(r)}<h2>Education</h2>"
            + "".join(f"<div><b>{e(x['degree'])}</b><br>{e(x['school'])}, {e(x['dates'])}</div>" for x in r["education"]))
    return _html(css, f"<div class='side'>{side}</div><div class='main'>{main}</div>")


def html_plain_single(r: dict) -> str:
    c = r["contact"]
    css = ("body{font:11pt Georgia,'Times New Roman',serif;color:#111;padding:48px 56px}h1{font-size:22pt;margin:0;text-align:center}"
           ".contact{text-align:center;color:#444;margin-bottom:10px}h2{font-size:12pt;border-bottom:1px solid #111;margin:16px 0 6px}"
           ".row{display:flex;justify-content:space-between}ul{margin:3px 0 8px;padding-left:20px}.co{font-style:italic}")
    body = (f"<h1>{e(r['name'])}</h1><div class='contact'>{e(' | '.join(c.values()))}</div><h2>Summary</h2><p>{e(r['summary'])}</p>"
            f"<h2>Experience</h2>{_jobs_html(r)}<h2>Education</h2>"
            + "".join(f"<div class='row'><span><b>{e(x['degree'])}</b>, {e(x['school'])}</span><span>{e(x['dates'])}</span></div>" for x in r["education"])
            + f"<h2>Skills</h2><p>{e(', '.join(r['skills']))}</p><h2>Languages</h2><p>{e(', '.join(r['languages']))}</p>")
    return _html(css, body)


DESIGNS = [
    ("html-word-two-column", html_word_two_column), ("html-canva-icons", html_canva_icons),
    ("html-plain-single", html_plain_single),
]


def source(n: int) -> str:
    """The HTML of CV number *n* (1-3)."""
    return DESIGNS[n - 1][1](record(n))



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
    job = lambda j: (f"<div class='job'><b>{e(j['company'])}</b><div>{e(j['role'])}</div>"  # noqa: E731
                     f"<div class='dates'>{e(j['dates'])}</div><p>{e(j['bullets'][0])}</p></div>")
    side = (f"<h2>Contact</h2><div>{e(c['phone'])}</div><div>{e(c['email'])}</div><div>{e(c['web'])}</div>"
            f"<h2>Top Skills</h2>{''.join(f'<div>{e(s)}</div>' for s in r['skills'][:3])}"
            f"<h2>Languages</h2>{''.join(f'<div>{e(s)}</div>' for s in r['languages'])}"
            f"<h2>Certifications</h2><div>Example Certificate</div><div>Another Certificate</div>")
    first = (f"<h1>{e(r['name'])}</h1><div class='headline'>{e(r['title'])}</div><div>{e(c['location'])}</div>"
             f"<h2>Summary</h2><p>{e(r['summary'])}</p><h2>Experience</h2>{job(r['experience'][0])}{job(r['experience'][1])}")
    second = (f"{job(r['experience'][2])}<h2>Education</h2>"
              + "".join(f"<div class='job'><b>{e(x['school'])}</b><div>{e(x['degree'])}</div><div class='dates'>{e(x['dates'])}</div></div>"
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
    """Write the corpus PDFs into *out*: the four HTML designs, the LinkedIn-like export and the scan."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    fonts = [FONT_DIR / name for _, name, _, _ in _FACES]
    pages = [("html-word-two-column", source(1)), ("html-canva-icons", source(2)),
             ("html-plain-single", source(3)), ("linkedin-like", linkedin_html(record(4))),
             ("html-equal-columns", html_equal_columns(record(5))),
             ("html-three-columns", html_three_columns(record(5)))]
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
