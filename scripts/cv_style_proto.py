"""Throwaway prototype of the CV style builder (#154, epic #144): not wired into any command or tool.

Does a model rebuild the look of a CV PDF as HTML/CSS + SVG, from the style read out of the PDF and a look at
its page, close enough to be recognisable? Per made-up CV (scripts/cv_style_proto/cvs.py): print the original,
read its style with pypdfium2, let the model write rebuild.html, print that with Chromium, compare element by
element (matched text) and by blurred image, feed the differences back, at most 5 rounds; then stress renders
(shorter, longer, an extra section, French) and a side by side: original | rebuild with its own text | the
shipped default look with the same text. Output goes to thoughts/research/154-proto/ (gitignored).

    DOOR_HOME=$TMPDIR/proto-home poetry run python scripts/cv_style_proto.py --cv 1
    DOOR_HOME=$TMPDIR/proto-home poetry run python scripts/cv_style_proto.py --cv 2-8 --stress
    poetry run python scripts/cv_style_proto.py --report

Model calls go through door.core.claude_cli (the plan, never an API key); DOOR_HOME keeps their usage log
out of the real jobs/ folder. The Chromium step is a small Node helper (render.mjs, Playwright from app/).
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import importlib.util
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import Image, ImageFilter

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

_spec = importlib.util.spec_from_file_location("cvs", REPO / "scripts" / "cv_style_proto" / "cvs.py")
cvs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cvs)

OUT = REPO / "thoughts" / "research" / "154-proto"
RENDER_MJS = REPO / "scripts" / "cv_style_proto" / "render.mjs"
MAX_ROUNDS = 5
# the go rule of #154
GO = {"recognisable": 5, "of": 8, "rounds": 5, "minutes": 10.0, "cost": 2.5}


# ---------- reading a PDF's style ----------

def _rgb(getter, obj) -> list[int]:
    r, g, b, a = (ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint())
    getter(obj.raw, r, g, b, a)
    return [r.value, g.value, b.value]


def _bbox(obj, height: float) -> list[float]:
    left, bottom, right, top = obj.get_bounds()
    return [round(left, 1), round(height - top, 1), round(right, 1), round(height - bottom, 1)]


def _path_d(obj, height: float) -> str:
    m = obj.get_matrix()
    pts = []
    for i in range(raw.FPDFPath_CountSegments(obj.raw)):
        seg = raw.FPDFPath_GetPathSegment(obj.raw, i)
        x, y = ctypes.c_float(), ctypes.c_float()
        raw.FPDFPathSegment_GetPoint(seg, x, y)
        pts.append((raw.FPDFPathSegment_GetType(seg), raw.FPDFPathSegment_GetClose(seg),
                    m.a * x.value + m.c * y.value + m.e, height - (m.b * x.value + m.d * y.value + m.f)))
    out, i = [], 0
    while i < len(pts):
        kind, close, x, y = pts[i]
        if kind == raw.FPDF_SEGMENT_MOVETO:
            out.append(f"M{x:.1f} {y:.1f}")
        elif kind == raw.FPDF_SEGMENT_BEZIERTO and i + 2 < len(pts):
            (_, _, x2, y2), (_, close, x3, y3) = pts[i + 1], pts[i + 2]
            out.append(f"C{x:.1f} {y:.1f} {x2:.1f} {y2:.1f} {x3:.1f} {y3:.1f}")
            i += 2
        else:
            out.append(f"L{x:.1f} {y:.1f}")
        if close:
            out.append("Z")
        i += 1
    return " ".join(out)


def merge_runs(texts: list[dict]) -> list[dict]:
    """Chromium and Skia write one text object per glyph or word: join those on one line with the same font, size
    and colour whose gap is under a word space (a gap over a fifth of the size becomes a space)."""
    out: list[dict] = []
    for t in sorted(texts, key=lambda t: (round(t["bbox"][3] / 3), t["bbox"][0])):
        last = out[-1] if out else None
        if last and (last["font"], last["size"], last["color"]) == (t["font"], t["size"], t["color"]):
            gap = t["bbox"][0] - last["bbox"][2]
            if abs(t["bbox"][3] - last["bbox"][3]) <= 0.3 * t["size"] and -0.3 * t["size"] <= gap <= 0.6 * t["size"]:
                joined = last["text"] + (" " if gap > 0.2 * t["size"] and not t["text"].startswith(" ") else "") + t["text"]
                last.update(text=joined, bbox=[last["bbox"][0], min(last["bbox"][1], t["bbox"][1]), t["bbox"][2],
                                               max(last["bbox"][3], t["bbox"][3])])
                continue
        out.append(dict(t))
    return out


def extract_style(pdf_path: Path) -> dict:
    """Per page: size, text runs (text, bbox, font, size, colour), shapes (fill, stroke, bbox, SVG path) and
    images (bbox), with the origin at the top left like the page image."""
    doc = pdfium.PdfDocument(str(pdf_path))
    pages = []
    try:
        for page in doc:
            width, height = page.get_size()
            textpage = page.get_textpage()
            texts, shapes, images = [], [], []
            for obj in page.get_objects():
                if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                    obj.textpage = textpage
                    text = obj.extract().strip()
                    if not text:
                        continue
                    font = obj.get_font()
                    texts.append({"text": text, "bbox": _bbox(obj, height), "font": font.get_base_name(),
                                  "size": round(obj.get_font_size(), 1), "color": _rgb(raw.FPDFPageObj_GetFillColor, obj)})
                elif obj.type == raw.FPDF_PAGEOBJ_PATH:
                    fill, stroke = ctypes.c_int(), ctypes.c_int()
                    raw.FPDFPath_GetDrawMode(obj.raw, fill, stroke)
                    width_pt = ctypes.c_float()
                    raw.FPDFPageObj_GetStrokeWidth(obj.raw, width_pt)
                    shapes.append({"bbox": _bbox(obj, height), "d": _path_d(obj, height),
                                   "fill": _rgb(raw.FPDFPageObj_GetFillColor, obj) if fill.value else None,
                                   "stroke": _rgb(raw.FPDFPageObj_GetStrokeColor, obj) if stroke.value else None,
                                   "stroke_width": round(width_pt.value, 2)})
                elif obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                    images.append({"bbox": _bbox(obj, height)})
            textpage.close()
            pages.append({"size": [round(width), round(height)], "texts": merge_runs(texts), "shapes": shapes, "images": images})
    finally:
        doc.close()
    return {"pages": pages}


# ---------- comparing two renders ----------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def match_elements(original: list[dict], rebuilt: list[dict]) -> dict:
    """Pair text runs of the two renders by their normalised text (first unused match, in order) and say how
    each pair differs (size, colour, position); runs with no partner are `missing` (only in the original) or
    `extra` (only in the rebuild)."""
    pool: dict[str, list[dict]] = {}
    for run in rebuilt:
        pool.setdefault(_norm(run["text"]), []).append(run)
    pairs, missing = [], []
    for run in original:
        candidates = pool.get(_norm(run["text"]))
        if not candidates:
            missing.append(run["text"])
            continue
        other = candidates.pop(0)
        pairs.append({"text": run["text"], "d_size": round(other["size"] - run["size"], 1),
                      "d_color": [b - a for a, b in zip(run["color"], other["color"])],
                      "d_x": round(other["bbox"][0] - run["bbox"][0], 1), "d_y": round(other["bbox"][1] - run["bbox"][1], 1)})
    # a run the other side split or joined differently: pair it with an unused run that contains it, or that it contains
    rest = [r for runs in pool.values() for r in runs]
    for text in list(missing):
        key = _norm(text)
        hit = next((r for r in rest if key in _norm(r["text"]) or _norm(r["text"]) in key), None)
        if hit:
            rest.remove(hit)
            missing.remove(text)
            pairs.append({"text": text, "d_size": 0.0, "d_color": [0, 0, 0], "d_x": 0.0, "d_y": 0.0, "split": True})
    extra = [r["text"] for r in rest]
    return {"pairs": pairs, "missing": missing, "extra": extra}


def blurred_score(a: Image.Image, b: Image.Image, radius: float = 4.0) -> float:
    """How alike two page images are, 0..1: both blurred (so a shift of a pixel costs little), then the mean
    squared difference against what a blank page would differ by (a mostly white page makes a plain MSE
    near 1 for any rebuild)."""
    size = (min(a.width, b.width), min(a.height, b.height))
    x, y = (np.asarray(im.convert("L").crop((0, 0, *size)).filter(ImageFilter.GaussianBlur(radius)), dtype=float) / 255
            for im in (a, b))
    blank = np.mean((x - 1.0) ** 2)  # what an empty page would score: the ink the original has
    return float(np.clip(1 - np.mean((x - y) ** 2) / max(blank, 0.005), 0, 1))


def feedback_text(match: dict, score: float, limit: int = 12) -> str:
    """What the next round tells the model: the blurred score and the largest element differences."""
    lines = [f"Blurred similarity to the original: {score:.2f} (1.00 = identical)."]
    off = [p for p in match["pairs"] if abs(p["d_size"]) >= 0.5 or max(map(abs, p["d_color"])) > 40
           or abs(p["d_x"]) > 6 or abs(p["d_y"]) > 6]
    off.sort(key=lambda p: -(abs(p["d_size"]) + abs(p["d_x"]) / 10 + abs(p["d_y"]) / 10))
    for p in off[:limit]:
        lines.append(f"- '{p['text'][:40]}': size {p['d_size']:+}, colour {p['d_color']}, x {p['d_x']:+}, y {p['d_y']:+} (points)")
    for label, texts in (("Missing from your rebuild", match["missing"]), ("Not in the original", match["extra"])):
        if texts:
            lines.append(f"{label}: " + "; ".join(t[:40] for t in texts[:limit]))
    return "\n".join(lines)


def side_by_side(images: list[Image.Image], gap: int = 24) -> Image.Image:
    sheet = Image.new("RGB", (sum(i.width for i in images) + gap * (len(images) - 1), max(i.height for i in images)), "#888888")
    x = 0
    for image in images:
        sheet.paste(image, (x, 0))
        x += image.width + gap
    return sheet


# ---------- stress, records, verdict ----------

_FRENCH = {"summary": "Profil polyvalent avec huit ans d'expérience, attaché à des plans clairs et à des étapes régulières.",
           "bullets": ["Conçu et maintenu des services utilisés chaque mois par environ 40 000 personnes.",
                       "Réduit le traitement de nuit de trois heures à vingt-cinq minutes.",
                       "Dirigé une équipe de quatre personnes lors d'une migration sans interruption."]}


def stress_variants(record: dict) -> dict[str, dict]:
    """The CV's own record made shorter, longer, with one more section and in French (copies)."""
    short, long_, extra, french = (copy.deepcopy(record) for _ in range(4))
    short["experience"] = short["experience"][:1]
    short["experience"][0]["bullets"] = short["experience"][0]["bullets"][:1]
    long_["experience"] = long_["experience"] + copy.deepcopy(long_["experience"])
    extra["extra_sections"] = [{"heading": "Publications", "items": ["A study of nightly pipelines (2021)", "Notes on small steady steps (2019)"]}]
    french["summary"] = _FRENCH["summary"]
    for job in french["experience"]:
        job["bullets"] = list(_FRENCH["bullets"])
    return {"short": short, "long": long_, "extra_section": extra, "french": french}


def extract_html(reply: str) -> str | None:
    """The one ```html block of the model's reply, or None (a reply cut off before its closing fence too)."""
    found = re.search(r"```html\s*\n(.*?)\n```", reply, re.S)
    return found.group(1).strip() if found else None


def cost_of(envelope: str | None) -> float:
    try:
        return float(json.loads(envelope or "")["total_cost_usd"])
    except (ValueError, KeyError, TypeError):
        return 0.0


def record_row(cv: str, *, rounds: int, minutes: float, cost: float, score: float, recognisable: bool,
               stress_holds: bool) -> dict:
    return {"cv": cv, "rounds": rounds, "minutes": round(minutes, 1), "cost": round(cost, 2), "score": round(score, 2),
            "recognisable": recognisable, "stress_holds": stress_holds}


def verdict(rows: list[dict]) -> dict:
    """#154's rule: go when at least 5 in 8 rows are recognisable, the medians are within 5 rounds, 10 minutes and
    $2.50 and the stress renders hold; `failed` names each threshold missed."""
    failed = []
    if sum(r["recognisable"] for r in rows) * GO["of"] < GO["recognisable"] * len(rows):
        failed.append(f"fewer than {GO['recognisable']} in {GO['of']} recognisable")
    for key, label in (("rounds", "rounds"), ("minutes", "minutes"), ("cost", "cost")):
        if statistics.median(r[key] for r in rows) > GO[key]:
            failed.append(f"median {label} above {GO[key]}")
    if not all(r["stress_holds"] for r in rows):
        failed.append("stress renders do not hold")
    return {"go": not failed, "failed": failed}


def markdown_table(rows: list[dict]) -> str:
    lines = ["| CV | rounds | minutes | cost $ | score | recognisable | stress holds |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['cv']} | {r['rounds']} | {r['minutes']} | {r['cost']} | {r['score']} | "
              f"{'yes' if r['recognisable'] else 'no'} | {'yes' if r['stress_holds'] else 'no'} |" for r in rows]
    return "\n".join(lines) + "\n"


# ---------- the live parts: Chromium, Tectonic, the model ----------

def _run(argv: list[str], **kw) -> None:
    result = subprocess.run(argv, capture_output=True, text=True, **kw)
    if result.returncode != 0:
        raise RuntimeError(f"{argv[0]} failed: {(result.stderr or result.stdout)[-800:]}")


def chromium(html: Path, out: Path) -> None:
    _run(["node", str(RENDER_MJS), str(html), str(out)])


def tectonic(tex: Path) -> Path:
    from door.core import installers
    _run([installers.find_tectonic() or "tectonic", "--keep-logs", tex.name], cwd=tex.parent)
    return tex.with_suffix(".pdf")


def pages_png(pdf: Path, out_dir: Path) -> list[Image.Image]:
    from door.tailoring import pdf_render
    return [Image.open(p).convert("RGB") for p in pdf_render.render_pdf_pages(pdf, out_dir)]


def make_original(n: int, work: Path, record: dict | None = None) -> Path:
    design, kind, text = cvs.source(n, record)
    work.mkdir(parents=True, exist_ok=True)
    if kind == "html":
        (work / "original.html").write_text(text, encoding="utf-8")
        chromium(work / "original.html", work / "original.pdf")
    else:
        (work / "original.tex").write_text(text, encoding="utf-8")
        tectonic(work / "original.tex")
    return work / "original.pdf"


PROMPT_FIRST = """You rebuild the look of a CV as one HTML file.
Files in the current folder: original_page_1.png (the CV page; open it with the Read tool and look at it),
style.json (fonts, sizes, colours, text positions and shapes as SVG paths read from its PDF; points, origin
top left, A4 = 595 x 842), text.txt (its text).
Reply with the complete page: HTML + CSS + inline SVG only, no external files, no JavaScript, one A4 page
(@page size A4, margin 0; use the style.json fonts or a close system font), with every word of text.txt.
Match layout, colours, fonts, sizes, icons and decorations. Do not write files or run commands. Your reply:
one line on what you see in the PNG (layout, colours), then the whole page in one ```html block, nothing after."""

PROMPT_NEXT = """Improve rebuild.html (in the current folder, read it). Look at original_page_1.png and at render_page_1.png,
your last render, with the Read tool. Measured differences, original -> your render:
{feedback}
Close the largest gaps and keep every word of the text. Do not write files or run commands. Your reply: one line
on what you changed, then the whole new page in one ```html block, nothing after."""


def rebuild(work: Path, original_pdf: Path) -> dict:
    """The loop for one CV: returns {rounds, minutes, cost, score, history, first_reply}."""
    from door.core import claude_cli
    from door.tailoring import pdf_render
    start = time.time()
    shot = pages_png(original_pdf, work)[0]
    shot.save(work / "original_page_1.png")
    style = extract_style(original_pdf)
    (work / "style.json").write_text(json.dumps(style), encoding="utf-8")
    (work / "text.txt").write_text("\n".join(pdf_render.page_texts(original_pdf)), encoding="utf-8")
    original_runs = [t for p in style["pages"] for t in p["texts"]]
    cost, history, best, best_html, first_reply = 0.0, [], -1.0, "", ""
    prompt = PROMPT_FIRST
    for round_no in range(1, MAX_ROUNDS + 1):
        envelope = claude_cli.run(["--model", "sonnet", "--allowedTools", "Read", *claude_cli.STREAM_ARGS,
                                   "--no-session-persistence"], feature="draft_cv", cwd=work, input=prompt, timeout_s=900)
        cost += cost_of(envelope)
        if round_no == 1:
            first_reply = str(claude_cli.envelope_result(envelope)).split("```")[0][:400]
        reply = str(claude_cli.envelope_result(envelope))
        page_html = extract_html(reply)
        if page_html is None:
            history.append({"round": round_no, "error": "no html block in the reply"})
            break
        html_path = work / "rebuild.html"
        html_path.write_text(page_html, encoding="utf-8")
        chromium(html_path, work / "render.pdf")
        render = pages_png(work / "render.pdf", work)[0]
        render.save(work / "render_page_1.png")
        match = match_elements(original_runs, [t for p in extract_style(work / "render.pdf")["pages"] for t in p["texts"]])
        score = blurred_score(shot, render)
        history.append({"round": round_no, "score": round(score, 3), "missing": len(match["missing"]),
                        "extra": len(match["extra"]), "cost": round(cost, 3)})
        if score > best + 0.005:
            best, best_html = score, page_html
            (work / "best.html").write_text(best_html, encoding="utf-8")
        else:
            break  # no real improvement: stop, keep the best
        prompt = PROMPT_NEXT.format(feedback=feedback_text(match, score))
    return {"rounds": len(history), "minutes": (time.time() - start) / 60, "cost": cost, "score": max(best, 0.0),
            "history": history, "first_reply": first_reply}


def pages_of(pdf: Path) -> int:
    from door.tailoring import pdf_render
    return pdf_render.get_page_count(pdf)


def stress(n: int, work: Path, best_html: str, base_pages: int) -> dict:
    """The best rebuild with CV n's stress variants as its text: the model swaps the text once per variant
    (its cost counted), keeping the design; holds when the page count grows by at most one."""
    from door.core import claude_cli
    results, cost = {}, 0.0
    for name, variant in stress_variants(cvs.record(n)).items():
        folder = work / f"stress-{name}"
        folder.mkdir(exist_ok=True)
        (folder / "rebuild.html").write_text(best_html, encoding="utf-8")
        (folder / "new_text.json").write_text(json.dumps(variant, ensure_ascii=False), encoding="utf-8")
        envelope = claude_cli.run(["--model", "sonnet", "--allowedTools", "Read", *claude_cli.STREAM_ARGS,
                                   "--no-session-persistence"], feature="draft_cv", cwd=folder, timeout_s=900,
                                  input="Replace the CV text in rebuild.html (in the current folder, read it) with the content of "
                                        "new_text.json (same record shape: name, title, contact, summary, experience, education, skills, "
                                        "languages, extra_sections). Keep the design, add a section in the same style for extra_sections, "
                                        "add or drop job blocks to fit. Do not write files or run commands. Reply with the whole new page "
                                        "in one ```html block, nothing after.")
        cost += cost_of(envelope)
        new_html = extract_html(str(claude_cli.envelope_result(envelope)))
        if new_html is None:
            results[name] = {"pages": 0, "holds": False, "error": "no html block in the reply"}
            continue
        (folder / "rebuild.html").write_text(new_html, encoding="utf-8")
        chromium(folder / "rebuild.html", folder / "stress.pdf")
        pages = pages_of(folder / "stress.pdf")
        pages_png(folder / "stress.pdf", folder)[0].save(folder / "stress.png")
        results[name] = {"pages": pages, "holds": pages <= base_pages + 1}
    return {"variants": results, "cost": cost, "holds": all(v["holds"] for v in results.values())}


def default_render(n: int, work: Path) -> Image.Image:
    tex = work / "default.tex"
    tex.write_text(cvs.to_default_tex(cvs.record(n)), encoding="utf-8")
    pdf = tectonic(tex)
    return pages_png(pdf, work)[0]


def finish(work: Path, original: Path, head: dict, stress_cv: int, with_stress: bool, extra: list) -> dict:
    """Rebuild, stress, then save the side-by-side (original | rebuild | extra panels) and record.json."""
    summary = {**head, **rebuild(work, original)}
    if with_stress and (work / "best.html").exists():
        # the stress renders are the test's overhead, not what a user pays: their cost stays in summary["stress"]
        summary["stress"] = stress(stress_cv, work, (work / "best.html").read_text(encoding="utf-8"), pages_of(original))
    orig_img = Image.open(work / "original_page_1.png")
    render = work / "render_page_1.png"
    side_by_side([orig_img, Image.open(render) if render.exists() else orig_img, *extra]).save(work / "side_by_side.png")
    (work / "record.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def run_cv(n: int, with_stress: bool) -> dict:
    design = cvs.DESIGNS[n - 1][0]
    work = OUT / f"cv{n}-{design}"
    original = make_original(n, work)
    return finish(work, original, {"cv": n, "design": design}, n, with_stress, [default_render(n, work)])


def pdf_work_dir(pdf: Path) -> Path:
    return OUT / f"pdf-{pdf.stem}"


def run_pdf(pdf: Path, with_stress: bool) -> dict:
    """A finished PDF as the original (a real layout with made-up text). It has no record, so the stress
    renders swap in CV 1's made-up record and the side-by-side has two panels: original | rebuild."""
    work = pdf_work_dir(pdf)
    work.mkdir(parents=True, exist_ok=True)
    original = work / "original.pdf"
    shutil.copyfile(pdf, original)
    return finish(work, original, {"cv": pdf.name, "design": work.name}, 1, with_stress, [])


def parse_cvs(text: str) -> list[int]:
    lo, _, hi = text.partition("-")
    return list(range(int(lo), int(hi or lo) + 1))


def report() -> str:
    """The table of every CV done so far; `recognisable` is judged by eye and read from judgement.json."""
    judged = json.loads((OUT / "judgement.json").read_text()) if (OUT / "judgement.json").exists() else {}
    rows = []
    for rec in sorted([*OUT.glob("cv*/record.json"), *OUT.glob("pdf-*/record.json")]):
        data = json.loads(rec.read_text())
        rows.append(record_row(data["design"], rounds=data["rounds"], minutes=data["minutes"], cost=data["cost"],
                               score=data["score"], recognisable=judged.get(data["design"], False),
                               stress_holds=data.get("stress", {}).get("holds", False)))
    text = markdown_table(rows) + "\n" + json.dumps(verdict(rows), indent=2) if rows else "no CV done yet"
    (OUT / "report.md").write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cv", help="a CV number or range, 1-8")
    ap.add_argument("--pdf", type=Path, help="rebuild this finished PDF as one more CV")
    ap.add_argument("--stress", action="store_true", help="also run the stress renders")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    if (args.cv or args.pdf) and not os.environ.get("DOOR_HOME"):
        raise SystemExit("set DOOR_HOME to a scratch folder: the model calls' usage would go into the real jobs/usage.jsonl")
    OUT.mkdir(parents=True, exist_ok=True)
    if args.cv:
        for n in parse_cvs(args.cv):
            print(json.dumps({k: v for k, v in run_cv(n, args.stress).items() if k != "history"}, indent=2))
    if args.pdf:
        print(json.dumps({k: v for k, v in run_pdf(args.pdf, args.stress).items() if k != "history"}, indent=2))
    if args.report:
        print(report())


if __name__ == "__main__":
    main()
