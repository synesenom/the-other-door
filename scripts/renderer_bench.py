"""The renderer bench (#145): Chromium, WeasyPrint and Typst on two CVs, measured the same way.

CV1 is the default template's look with profile.example's text, CV2 a two-column design with icons (made-up
content); sources in scripts/renderer_bench/. Per candidate: render time (cold, then the warm median), the
blurred score against a Tectonic reference, what an ATS reads back (readability.problems), French typography and
hyphenation, whether only the template's own folder can be read (fonts and icons beside it load, a file outside it
and an address do not), whether the font files and SVG icons come out as drawn, and the install size. One markdown
table, one choice and a fallback, written to thoughts/research/145-bench/. A throwaway harness: nothing here is
product code.

    WEASYPRINT=<weasyprint executable> TYPST=<typst binary> FONTS=<folder with the Lato TTFs> \
        PYTHONPATH=src poetry run python scripts/renderer_bench.py

A candidate whose executable is missing is recorded as "not installed".
"""

from __future__ import annotations

import http.server
import importlib.util
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

_spec = importlib.util.spec_from_file_location("cv_style_proto", REPO / "scripts" / "cv_style_proto.py")
proto = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proto)

SOURCES = REPO / "scripts" / "renderer_bench"
OUT = REPO / "thoughts" / "research" / "145-bench"
ICON_SIZE = 12
ICON_FILL = [11, 114, 133]
SECRET_FILL = [255, 0, 255]
ICON_NAMES = ["mail", "phone", "web", "pin"]
PX_PER_PT = 150 / 72  # render_pdf_pages draws at 150 DPI


# ---------- the pure parts ----------

def timing(render: Callable[[], None], runs: int = 3) -> dict:
    """One cold run, then the median of `runs` warm ones, in seconds."""
    times = []
    for _ in range(1 + runs):
        start = time.perf_counter()
        render()
        times.append(time.perf_counter() - start)
    return {"cold": times[0], "warm": statistics.median(times[1:])}


_NBSP = "  "


def french_typography(text: str) -> list[str]:
    """What breaks French typography in a PDF's text: a plain space or none before : ; ! ?, a line that starts
    with one, plain spaces inside guillemets, straight quotes. A non-breaking (narrow) space is right."""
    found: list[str] = []

    def add(msg: str) -> None:
        if msg not in found:
            found.append(msg)

    for line in text.splitlines():
        if line.strip()[:1] in (":", ";", "!", "?"):
            add(f"line starts with {line.strip()[0]}")
    for i, c in enumerate(text):
        nxt = text[i + 1] if i + 1 < len(text) else "\n"
        prev = text[i - 1] if i else "\n"
        if c in ":;!?" and nxt.isspace() and prev not in "\r\n":
            if prev == " ":
                add(f"plain space before {c}")
            elif prev not in _NBSP and not (prev.isspace()):
                add(f"no space before {c}")
        elif c == "«" and nxt != "\n" and nxt not in _NBSP:
            add("plain space inside «" if nxt == " " else "no space inside «")
        elif c == "»" and prev not in "\r\n" and prev not in _NBSP:
            add("plain space inside »" if prev == " " else "no space inside »")
    if '"' in text:
        add("straight quotes")
    return found


def hyphenates(text: str) -> bool:
    """True when a word is broken at a line end: a soft hyphen (pdfium reads it as U+FFFE or U+00AD) or a hyphen."""
    return bool(re.search("[\ufffe\u00ad]", text)) or bool(re.search(r"[^\W\d_][-\u2010]\r?\n", text))


def hyphen_cell(row: dict) -> str:
    """The table's hyphenation cell: whether words break, and how many read back split."""
    if not row.get("hyphens"):
        return "no"
    split = row.get("split_words") or []
    return f"yes, {len(split)} words read back split" if split else "yes, words read back whole"


def split_words(text: str) -> list[str]:
    """Words broken by a hard hyphen at a line end: they read back as two halves (a keyword an ATS may miss).
    A soft hyphen is not one: the text reader joins the word again."""
    return [a + h + b for a, h, b in re.findall(r"([^\W\d_]+)([-\u2010])\r?\n([^\W\d_]+)", text)]


def descriptor_font_names(blobs: list[bytes]) -> list[str]:
    """The /FontName of every font descriptor in these PDF bytes: what a Type 3 font with no base name is called."""
    return sorted({m.decode("latin-1") for b in blobs for m in re.findall(rb"/FontName\s*/([^\s/<>\[\]()]+)", b)})


def _flat(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.split("+")[-1].lower())


def fonts_ok(embedded: list[str], wanted: str | list[str] = "Lato") -> bool:
    """Every wanted family is embedded and nothing else stands in (a subset prefix is fine)."""
    wanted = [wanted] if isinstance(wanted, str) else wanted
    flat = [_flat(n) for n in embedded]
    return bool(flat) and all(any(_flat(w) in n for n in flat) for w in wanted) \
        and all(any(_flat(w) in n for w in wanted) for n in flat)


def expected_icons() -> list[dict]:
    """The four icons of CV2 as placed in its sources: 12 pt squares at x 36, y 150 and every 22 pt."""
    return [{"name": n, "fill": ICON_FILL, "bbox": [36, 150 + 22 * i, 36 + ICON_SIZE, 150 + 22 * i + ICON_SIZE]}
            for i, n in enumerate(ICON_NAMES)]


def icons_ok(style: dict, expected: list[dict], tol: float = 1.0) -> list[str]:
    """What is wrong with the drawn icons: for each expected one a shape of its fill at its position and size."""
    shapes = [s for p in style["pages"] for s in p["shapes"] if s["fill"] is not None]
    problems = []
    for want in expected:
        near = [s for s in shapes if all(abs(a - b) <= tol for a, b in zip(s["bbox"], want["bbox"]))]
        if any(s["fill"] == want["fill"] for s in near):
            continue
        if near:
            problems.append(f"{want['name']}: wrong fill {near[0]['fill']}, expected {want['fill']}")
            continue
        same = [s for s in shapes if s["fill"] == want["fill"]]
        if same:
            cx, cy = (want["bbox"][0] + want["bbox"][2]) / 2, (want["bbox"][1] + want["bbox"][3]) / 2
            best = min(same, key=lambda s: abs((s["bbox"][0] + s["bbox"][2]) / 2 - cx) + abs((s["bbox"][1] + s["bbox"][3]) / 2 - cy))
            problems.append(f"{want['name']}: found {[round(v) for v in best['bbox']]}, expected {want['bbox']}")
        else:
            problems.append(f"{want['name']}: no shape drawn")
    return problems


def icon_crop_score(page: Image.Image, reference: Image.Image, boxes: list[list[float]], scale: float = PX_PER_PT,
                    pad: float = 2.0) -> float:
    """The mean blurred score of the icons' crops (boxes in points) of a page against the reference."""
    scores = []
    for x0, y0, x1, y1 in boxes:
        crop = tuple(int(round(v * scale)) for v in (x0 - pad, y0 - pad, x1 + pad, y1 + pad))
        scores.append(proto.blurred_score(page.crop(crop), reference.crop(crop), radius=1.0))
    return sum(scores) / len(scores)


def access_verdict(results: dict) -> dict:
    """Pass only when the sibling font and icon loaded and a file outside the folder and an address did not."""
    problems = []
    if not results["sibling_font"]:
        problems.append("the font beside the template did not load")
    if not results["sibling_icon"]:
        problems.append("the icon beside the template did not load")
    if results["outside_file"]:
        problems.append("a file outside the folder was read")
    if results["outside_url"]:
        problems.append("an address outside was fetched")
    return {"pass": not problems, "problems": problems}


def score_candidate(pdf: Path, reference_pngs: list[Image.Image], work: Path, *, name: str | None,
                    headings: list[str], keywords: list[str], wanted_font: str | list[str],
                    expected: list[dict] | None = None) -> dict:
    """One PDF, scored the same way for every candidate."""
    from door.tailoring import pdf_render, readability
    work.mkdir(parents=True, exist_ok=True)
    pages = pages_png(pdf, work)
    scores = [proto.blurred_score(pages[i], ref) if i < len(pages) else 0.0 for i, ref in enumerate(reference_pngs)]
    text = "\n".join(pdf_render.page_texts(pdf))
    found = embedded_fonts(pdf)
    icons = None
    if expected is not None:
        icons = icons_ok(proto.extract_style(pdf), expected)
    return {"pages": len(pages), "score": sum(scores) / len(scores), "fonts": fonts_ok(found, wanted_font),
            "fonts_found": found, "icons": icons,
            "readability": readability.problems(text, name=name, headings=headings, keywords=keywords, pages=len(pages))}


def pages_png(pdf: Path, out_dir: Path) -> list[Image.Image]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return proto.pages_png(pdf, out_dir)


def embedded_fonts(pdf: Path) -> list[str]:
    """The base names of the fonts the PDF's text uses."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    doc = pdfium.PdfDocument(str(pdf))
    try:
        names = {obj.get_font().get_base_name() for page in doc for obj in page.get_objects()
                 if obj.type == raw.FPDF_PAGEOBJ_TEXT}
    finally:
        doc.close()
    if "" in names:  # Chromium writes CFF (.otf) fonts as Type 3 with no base name: read their descriptors
        import zlib
        data = pdf.read_bytes()
        blobs = [data]
        for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
            try:
                blobs.append(zlib.decompress(m.group(1)))
            except zlib.error:
                pass
        names = (names - {""}) | set(descriptor_font_names(blobs))
    return sorted(names)


def choose(rows: list[dict]) -> dict:
    """The gates (access, fonts, icons), then the best mean score, a tie to the smaller install; the next is the fallback."""
    excluded: dict[str, str] = {}
    passing = []
    for r in rows:
        if not r.get("installed", True):
            excluded[r["candidate"]] = "not installed"
            continue
        failed = next((g for g in ("access", "fonts", "icons") if not r.get(g)), None)
        if failed:
            excluded[r["candidate"]] = failed
        else:
            passing.append(r)
    passing.sort(key=lambda r: (-round(sum(r["scores"]) / len(r["scores"]), 2), r["size_mb"] if r["size_mb"] is not None else 1e9))
    names = [r["candidate"] for r in passing] + [None, None]
    return {"choice": names[0], "fallback": names[1], "excluded": excluded}


def install_size_mb(path: Path) -> float | None:
    """Size on disk in MB (10^6 bytes) of a file or a folder; None when it is not there."""
    if not path.exists():
        return None
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    return round(sum(p.stat().st_size for p in files) / 1_000_000, 1)


_COLUMNS = ["candidate", "install MB", "cold s", "warm s", "score CV1", "score CV2", "ATS problems", "French",
            "hyphens", "access", "fonts", "icons", "docs only"]


def _yn(v) -> str:
    return "-" if v is None else ("yes" if v else "no")


def bench_table(rows: list[dict], docs: dict[str, dict[str, str]] | None = None) -> str:
    """The markdown table; `docs` ({candidate: {Windows: ..., Linux: ...}}) fills the cell nobody measured."""
    docs = docs or {}
    lines = ["| " + " | ".join(_COLUMNS) + " |", "|" + "---|" * len(_COLUMNS)]
    for r in rows:
        doc = "; ".join(f"{k}: {v}" for k, v in docs.get(r["candidate"], {}).items()) or "-"
        if not r.get("installed", True):
            cells = [r["candidate"], "not installed"] + ["-"] * (len(_COLUMNS) - 3) + [doc]
        else:
            scores = r.get("scores") or []
            cells = [r["candidate"], r.get("size_mb", "-"), f"{r['cold']:.2f}", f"{r['warm']:.2f}",
                     *[f"{s:.2f}" for s in scores], *["-"] * (2 - len(scores)),
                     "; ".join(f"{p['kind']}" for cv in r.get("readability", []) for p in cv) or "none",
                     "; ".join(r["french"]) or "ok", hyphen_cell(r), _yn(r.get("access")),
                     _yn(r.get("fonts")), _yn(r.get("icons")), doc]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


# ---------- the candidates ----------

class Candidate:
    """One renderer: `render(source, out_pdf)`, `sealed(folder, source, out_pdf)` (this folder only), the source
    extension, where it is installed (for the size) and how an address fetched shows ("log": a request reached the
    logging server; "compile": the compile itself fetched)."""

    def __init__(self, name, installed, render, sealed, ext, install_path=None, url_evidence="log"):
        self.name, self.installed, self.render, self.sealed, self.ext = name, installed, render, sealed, ext
        self.install_path, self.url_evidence = install_path, url_evidence


def _run(argv: list[str], **kw) -> None:
    proto._run([str(a) for a in argv], **kw)


def candidates(env: dict[str, str] | None = None) -> list[Candidate]:
    """Chromium (Playwright from app/node_modules), WeasyPrint (WEASYPRINT) and Typst (TYPST) at the places given."""
    env = os.environ if env is None else env
    node_ok = bool(shutil.which("node")) and (REPO / "app" / "node_modules" / "playwright").exists()
    cache = Path(env.get("CHROMIUM_DIR", Path.home() / "Library" / "Caches" / "ms-playwright"))
    chromium = Candidate(
        "chromium", node_ok, proto.chromium,
        lambda folder, html, out: _run(["node", SOURCES / "render_sealed.mjs", folder, html, out]), "html",
        cache if cache.exists() else None)
    weasy = Path(env.get("WEASYPRINT", "weasyprint"))
    weasy_ok = bool(shutil.which(str(weasy)))
    weasy_exe = Path(shutil.which(str(weasy)) or weasy)
    weasyprint = Candidate(
        "weasyprint", weasy_ok, lambda html, out: _run([weasy_exe, html, out]),
        lambda folder, html, out: _run([weasy_exe.parent / "python", SOURCES / "weasy_sealed.py", folder, html, out]),
        "html", weasy_exe.parent.parent if weasy_ok else None)
    typst_path = shutil.which(env.get("TYPST", "typst"))
    typst_exe = Path(typst_path) if typst_path else Path(env.get("TYPST", "typst"))

    def typst_render(typ: Path, out: Path) -> None:
        _run([typst_exe, "compile", "--ignore-system-fonts", "--font-path", typ.parent / "fonts", typ, out])

    typst = Candidate("typst", bool(typst_path), typst_render, lambda folder, typ, out: typst_render(typ, out), "typ",
                      typst_exe if typst_path else None, url_evidence="compile")
    return [chromium, weasyprint, typst]


# ---------- the live parts ----------

class _Log(http.server.SimpleHTTPRequestHandler):
    hits: list[str] = []

    def log_message(self, fmt, *args):
        self.hits.append(self.path)


def _secret_drawn(pdf: Path) -> bool:
    return any(s["fill"] == SECRET_FILL for p in proto.extract_style(pdf)["pages"] for s in p["shapes"])


def _stage(folder: Path, fonts: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    shutil.copytree(fonts, folder / "fonts")
    shutil.copytree(SOURCES / "icons", folder / "icons")


def probe_access(cand: Candidate, work: Path, fonts: Path) -> dict:
    """Render three probes with the candidate's sealed render: a sibling font and icon (must load), a file outside
    the folder and an address (must not). The address is a 127.0.0.1 server whose request log is the evidence."""
    outside = work / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    shutil.copy(SOURCES / "probe" / "secret.svg", outside)
    handler = type("Log", (_Log,), {"hits": [], "directory": str(outside)})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), lambda *a, **k: handler(*a, directory=str(outside), **k))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    results, errors = {}, {}
    try:
        for kind in ("ok", "file", "url"):
            folder = work / kind
            _stage(folder, fonts)
            text = (SOURCES / "probe" / f"probe_{kind}.{cand.ext}").read_text(encoding="utf-8")
            text = (text.replace("__OUTSIDE_FILE__", (outside / "secret.svg").as_uri())
                    .replace("__OUTSIDE_URL__", f"http://127.0.0.1:{server.server_address[1]}/secret.svg")
                    .replace("__OUTSIDE_REL__", os.path.relpath(outside / "secret.svg", folder)))
            source, pdf = folder / f"probe.{cand.ext}", folder / "probe.pdf"
            source.write_text(text, encoding="utf-8")
            rendered = True
            try:
                cand.sealed(folder, source, pdf)
            except Exception as exc:  # a refused read can fail the render: blocked
                rendered, errors[kind] = False, str(exc)[-300:]
            if kind == "ok":
                results["sibling_font"] = rendered and fonts_ok(embedded_fonts(pdf), "Lato")
                results["sibling_icon"] = rendered and not icons_ok(
                    proto.extract_style(pdf), [{"name": "pin", "fill": ICON_FILL, "bbox": [36, 36, 36 + ICON_SIZE, 36 + ICON_SIZE]}])
            elif kind == "file":
                results["outside_file"] = rendered and _secret_drawn(pdf)
            else:
                time.sleep(0.2)
                fetched = (rendered and _secret_drawn(pdf)) or bool(handler.hits) or (cand.url_evidence == "compile" and rendered)
                results["outside_url"] = fetched
    finally:
        server.shutdown()
    return {**access_verdict(results), "results": results, "errors": errors}


def french_probe(cand: Candidate, work: Path, fonts: Path) -> dict:
    from door.tailoring import pdf_render
    _stage(work, fonts)
    source, pdf = work / f"french.{cand.ext}", work / "french.pdf"
    shutil.copy(SOURCES / "probe" / f"french.{cand.ext}", source)
    cand.render(source, pdf)
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:  # pdfium's own text, before door's reader joins a soft-hyphenated word: the hyphen is what is measured
        raw = "\n".join(page.get_textpage().get_text_range() for page in doc)
    finally:
        doc.close()
    text = "\n".join(pdf_render.page_texts(pdf))
    return {"french": french_typography(text), "hyphens": hyphenates(raw), "split_words": split_words(raw)}


# what the sources say, for the readability check of each CV
JANE = {"name": "Jane Doe", "title": "", "contact": {"phone": "+45 00 00 00 00", "email": "jane.doe@example.com",
                                                      "web": "janedoe.example.com", "location": "Copenhagen"},
        "summary": "Financial controller with a strong background in group reporting, budgeting and process improvement across retail and banking.",
        "experience": [
            {"role": "Senior Financial Controller", "company": "Acme Corp", "dates": "2021 - present", "bullets": [
                "Built the group controlling function from scratch and defined the monthly reporting calendar.",
                "Cut the month-end close from ten working days to five by standardising reconciliations.",
                "Mentored two junior controllers and the finance trainees.",
                "Partnered with sales and operations leaders on budgets, forecasts and pricing decisions."]},
            {"role": "Financial Controller", "company": "Big Bank", "dates": "2018 - 2021", "bullets": [
                "Owned the IFRS reporting for three Nordic subsidiaries and the yearly external audit.",
                "Introduced a rolling forecast that replaced the annual budget for the retail division.",
                "Led the finance workstream of a core-system migration for a team of five."]},
            {"role": "Accountant", "company": "Example Retail", "dates": "2015 - 2018", "bullets": [
                "Ran accounts payable and receivable for 40 stores.",
                "Built monthly store KPI reports for regional managers."]}],
        "education": [{"degree": "MSc in Business Economics and Auditing", "school": "Copenhagen Business School", "dates": "2015"},
                      {"degree": "BSc in Business Administration", "school": "Aarhus University", "dates": "2013"}],
        "skills": ["IFRS and Danish GAAP", "group consolidation", "budgeting and forecasting", "SAP S/4HANA",
                   "Microsoft Dynamics 365", "Excel (advanced)", "Power BI", "internal controls", "stakeholder management"],
        "languages": ["English (fluent)"],
        "extra_sections": [{"heading": "Certifications", "items": ["Certified Management Accountant (CMA), 2019", "SAP S/4HANA Finance, 2022"]}]}

CVS = {
    1: {"name": "Jane Doe", "headings": ["Profile", "Work experience", "Education", "Skills", "Certifications", "Languages"],
        "keywords": ["IFRS", "SAP S/4HANA", "budgeting"], "wanted": ["Figtree", "Young Serif"], "expected": None},
    2: {"name": "Mira Valdis", "headings": ["Experience", "Education", "Skills", "Languages"],
        "keywords": ["Docker", "SQL", "TypeScript"], "wanted": "Lato", "expected": expected_icons()},
}

DOCS = {
    "chromium": {"macOS": "Playwright chromium 376 MB, headless shell 205 MB", "Windows": "same download per OS",
                 "Linux": "same download plus system libs", "packaged app": "Electron has one, nothing under app/ may run the CLI"},
    "weasyprint": {"macOS": "Homebrew pango + pip", "Windows": "MSYS2 or the standalone exe", "Linux": "distro pango libs + pip",
                   "packaged app": "bundling Pango into the app's Python is real work on all three"},
    "typst": {"macOS": "13-14 MB binary", "Windows": "20-21 MB exe", "Linux": "15-16 MB static binary",
              "packaged app": "one binary beside Tectonic, no native libs"},
}


def references(work: Path) -> dict[int, list[Image.Image]]:
    """The Tectonic render of each CV: the one reference every candidate is scored against."""
    jane = proto.cvs.to_default_tex(JANE)
    mira = proto.cvs.latex_altacv(proto.cvs.record(1))
    out = {}
    for n, tex in ((1, jane), (2, mira)):
        folder = work / f"ref{n}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "ref.tex").write_text(tex, encoding="utf-8")
        proto.tectonic(folder / "ref.tex")
        out[n] = pages_png(folder / "ref.pdf", folder / "png")
    return out


def run_candidate(cand: Candidate, refs: dict[int, list[Image.Image]], work: Path, fonts: Path) -> dict:
    if not cand.installed:
        return {"candidate": cand.name, "installed": False}
    row: dict = {"candidate": cand.name, "installed": True, "scores": [], "readability": [], "errors": [],
                 "size_mb": install_size_mb(cand.install_path) if cand.install_path else None}
    cold, warm = [], []
    for n, cv in CVS.items():
        folder = work / cand.name / f"cv{n}"
        _stage(folder, fonts)
        shutil.copy(SOURCES / f"cv{n}.{cand.ext}", folder / f"cv.{cand.ext}")
        pdf = folder / "cv.pdf"
        try:
            t = timing(lambda: cand.render(folder / f"cv.{cand.ext}", pdf))
            cold.append(t["cold"])
            warm.append(t["warm"])
            s = score_candidate(pdf, refs[n], folder / "png", name=cv["name"], headings=cv["headings"],
                                keywords=cv["keywords"], wanted_font=cv["wanted"], expected=cv["expected"])
        except Exception as exc:
            row["errors"].append(f"cv{n}: {str(exc)[-300:]}")
            row["scores"].append(0.0)
            row["readability"].append([{"kind": "render failed"}])
            row.setdefault("fonts_all", []).append(False)
            continue
        row["scores"].append(s["score"])
        row["readability"].append(s["readability"])
        row.setdefault("fonts_all", []).append(s["fonts"])
        if s["icons"] is not None:
            row["icons"] = not s["icons"]
            row["icon_problems"] = s["icons"]
            row["cv2_page"] = str(folder / "png" / f"{pdf.stem}_page_1.png")
    row["cold"], row["warm"] = (statistics.mean(cold), statistics.mean(warm)) if cold else (0.0, 0.0)
    row["fonts"] = bool(row.get("fonts_all")) and all(row["fonts_all"])
    row.setdefault("icons", False)
    try:
        access = probe_access(cand, work / cand.name / "access", fonts)
        row["access"], row["access_detail"] = access["pass"], access
        row.update(french_probe(cand, work / cand.name / "french", fonts))
    except Exception as exc:
        row["access"], row["french"], row["hyphens"] = False, [f"probe failed: {str(exc)[-200:]}"], None
        row["errors"].append(f"probe: {str(exc)[-300:]}")
    return row


def main(argv: list[str] | None = None) -> None:
    import json
    fonts_dir = Path(os.environ.get("FONTS", ""))
    if not (fonts_dir / "Lato-Regular.ttf").exists():
        sys.exit("FONTS must name a folder with Lato-Regular.ttf and Lato-Bold.ttf")
    work = OUT / "work"
    fonts = work / "fonts"
    shutil.rmtree(fonts, ignore_errors=True)
    shutil.copytree(REPO / "profile.example" / "fonts", fonts)
    for f in fonts_dir.glob("*.ttf"):
        shutil.copy(f, fonts)
    refs = references(work)
    rows = [run_candidate(c, refs, work, fonts) for c in candidates()]
    result = choose(rows)
    chrome = next((r for r in rows if r["candidate"] == "chromium" and r.get("cv2_page")), None)
    for r in rows:  # the reference has no icons: compare each candidate's icon crops with Chromium's
        if chrome and r.get("cv2_page") and r is not chrome:
            r["icon_crop_vs_chromium"] = icon_crop_score(Image.open(r["cv2_page"]).convert("RGB"),
                                                         Image.open(chrome["cv2_page"]).convert("RGB"),
                                                         [i["bbox"] for i in expected_icons()])
    OUT.mkdir(parents=True, exist_ok=True)
    for n in CVS:  # judged by eye: the LaTeX reference, then each candidate's page
        pages = [refs[n][0]] + [Image.open(f).convert("RGB") for c in rows if c.get("installed")
                                for f in [work / c["candidate"] / f"cv{n}" / "png" / "cv_page_1.png"] if f.exists()]
        proto.side_by_side(pages).save(OUT / f"cv{n}_side_by_side.png")
    report = (bench_table(rows, DOCS) + f"\nChoice: {result['choice']}; fallback: {result['fallback']}; "
              f"excluded: {result['excluded']}\n")
    (OUT / "table.md").write_text(report, encoding="utf-8")
    (OUT / "rows.json").write_text(json.dumps({"rows": rows, "choice": result}, indent=1, default=str), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
