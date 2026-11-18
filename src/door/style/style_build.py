"""Build a CV template from an uploaded CV (#149, epic #144): the builder core.

`build(pdf_path, ...)` reads the style of a CV PDF (`style_extract`), fetches the free fonts for it (`fonts`), writes its
icons as SVG files, and runs the stylist agent (`.claude/agents/stylist.md`) round by round: the agent writes a template
page, the builder checks it (`html_guard.template_problems`), prints a sample body in it with the pinned Chromium, reads
the print back and compares it with the original (`style_compare`) until the loop's rule says stop. A best round that scored under
`style_compare.FLOOR` does not look like the CV: the build fails there. Otherwise it is
stress-rendered with `profile/cv.md` made shorter, longer, French and with a photo (no model: `cv_body`), one more
round when that fails, and a second call writes the matching letter template. Only a build that passes is written, whole,
to `profile/style.next/`, the candidate; a failed one writes nothing there.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from PIL import Image
from pypdfium2 import PdfiumError

from door import i18n
from door.commands import _common as common
from door.core import claude_cli, pinned, progress as progress_mod, templates, utils, workspace
from door.style import fonts
from door.style import cv_body, font_measure, style_compare, style_extract, style_icons, style_preview, style_structure
from door.render import html_doc, html_guard, html_pdf, pdf_render, readability
from door.render import page as page_mod

STYLIST = "stylist"
_BLOCK = re.compile(r"^```(\w+)[ \t]*\n(.*?)\n```[ \t]*$", re.S | re.M)


def blocks(reply: str) -> dict[str, str]:
    """The fenced blocks of a stylist's reply by their name (```` ```template ````, ``body``, ``letter``): the first of
    each name. A block cut off before its closing fence is not one."""
    found: dict[str, str] = {}
    for name, text in _BLOCK.findall(reply):
        found.setdefault(name, text.strip())
    return found


# ---------- what the stylist is given: fonts, icons, manifest ----------

def _font_face_css(plan: list[dict]) -> str:
    """One `@font-face` rule per file of each entry of `fonts.plan`, under the family the file belongs to, served as
    `/fonts/<file>`; an entry with no files (no free copy of its kind) has none."""
    rules = []
    for entry in plan:
        for f in entry["files"]:
            style = "italic" if f["italic"] else "normal"
            rules.append(f'@font-face {{ font-family: "{entry["resolved"]}"; font-weight: {f["weight"]}; font-style: {style}; '
                         f'src: url(/fonts/{f["name"]}) format("truetype"); }}')
    return "\n".join(rules)


def _font_notes(plan: list[dict]) -> str:
    """What the stylist is told of each font the CV uses: which family stands for it and which faces are faked."""
    lines = []
    for entry in plan:
        if not entry["resolved"]:
            lines.append(f'- {entry["family"]}: no font for it; use a generic family ({entry["reason"]})')
            continue
        faked = "; ".join(f'weight {w}{" italic" if i else ""}' for w, i in entry["faked"])
        lines.append(f'- {entry["family"]} -> use "{entry["resolved"]}"' + (f" (no file for: {faked}; do not use)" if faked else ""))
    return "\n".join(lines)


_URL = re.compile(r"(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?")
_PHONE = re.compile(r"[\d\s()+.\-]{7,}")
_YEAR = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")
_PATH = re.compile(r"[MLHVCSQTAZmlhvcsqtaz\d\s.,\-]+")
_VIEWBOX = re.compile(r"[\d\s.\-]+")
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def icon_kind(near: str | None) -> str | None:
    """The kind of icon (one of `templates.ICON_KINDS`) that belongs beside `near`: a contact label in any supported
    language, else what the text looks like (a number, a link, a date, a place name); None when it is none of them."""
    text = " ".join((near or "").split())
    if not text:
        return None
    if kind := i18n.contact_kind(text):
        return kind
    lower = text.lower()
    if "@" in text:
        return "email"
    if "linkedin" in lower:
        return "linkedin"
    if "github" in lower:
        return "github"
    years = _YEAR.findall(text)
    if (len(years) >= 2 or (years and re.search(r"[^\W\d_]{3}", text))) and text[0] not in "+(":
        return "date"
    if _PHONE.fullmatch(text) and sum(c.isdigit() for c in text) >= 7:
        return "phone"
    if _URL.fullmatch(text):
        return "web"
    if i18n.known_city(text) or i18n.country_for_location(text):
        return "location"
    return None


def write_icons(icons: list[dict], folder: Path) -> tuple[dict[str, str], list[dict]]:
    """The icons `style_extract` traced as `<kind>.svg` files in `folder`, one per kind (the first in reading order),
    by what they sit beside. Returns ``({kind: file name}, dropped)``: an icon of no kind in `templates.ICON_KINDS`, or
    whose traced path is not plain path data, is dropped and named (``near``, ``reason``)."""
    files: dict[str, str] = {}
    dropped: list[dict] = []
    for icon in icons:
        near = (icon.get("near") or {}).get("text")
        kind = icon_kind(near)
        label = near[:30] if near else None
        if kind is None:
            dropped.append({"near": label, "reason": "no kind of contact detail or date recognised beside it"})
        elif not (_PATH.fullmatch(icon.get("d") or "") and _VIEWBOX.fullmatch(icon.get("viewBox") or "")):
            dropped.append({"near": label, "reason": "its path is not plain path data"})
        elif kind not in files:
            color = icon["color"] if _COLOR.fullmatch(icon.get("color") or "") else "#000000"
            Path(folder).mkdir(parents=True, exist_ok=True)
            (Path(folder) / f"{kind}.svg").write_text(
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{icon["viewBox"]}">'
                f'<path fill="{color}" fill-rule="{icon.get("fill_rule", "evenodd")}" d="{icon["d"]}"/></svg>\n', encoding="utf-8")
            files[kind] = f"{kind}.svg"
    return files, dropped


_FALLBACK_SIDE = ("skills", "languages", "interests")
_CV_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.M)


def _side_headings(style: dict) -> list[str]:
    """The texts of the original's headings that sit in a side band, in reading order, known to a section kind or not."""
    return [h["text"] for h in style["headings"] if h["band"] == "side"]


def _side_kinds(style: dict, cv_md: str) -> list[str]:
    """The section kinds of the side column: those whose headings in the original sit in its side band, in reading
    order (a heading no section kind names stays in the main column). When it has a side band but none of its headings
    names a kind, the kinds of skills, languages and interests that `cv_md` has: a tailored CV puts those there. Empty
    for a CV with no side band, or with nothing of those in `cv_md` (one column)."""
    kinds: list[str] = []
    for heading in (h for h in style["headings"] if h["band"] == "side"):
        kind = heading["kind"] if heading["kind"] in templates.SECTION_KINDS else None
        if kind and kind not in kinds:
            kinds.append(kind)
    if not kinds and _side_headings(style):
        own = {i18n.cv_section_kind(h, _FALLBACK_SIDE) for h in _CV_HEADING.findall(cv_md)}
        kinds = [k for k in _FALLBACK_SIDE if k in own]
    return kinds


def _manifest_data(style: dict, font_files: list[str], icon_files: dict[str, str], cv_md: str) -> dict:
    """The `template.json` of a build: its fonts and icons, the side column's kinds and the page limit (the original's
    page count within the 1 to 3 a template may name)."""
    data: dict = {"version": 1, "fonts": list(font_files), "icons": dict(icon_files),
                  "max_pages": min(templates.MAX_PAGES, max(1, style.get("page_count", 1)))}
    side, headings = _side_kinds(style, cv_md), _side_headings(style)
    if side or headings:
        data["columns"] = {"side": side, "headings": headings}
    return data


# ---------- the columns: where the original has them, and where a print puts them (#242) ----------

_ACROSS = "across the page"
_MIN_LINE = 20  # characters: a shorter line of the original (a date, a word) is not looked for in the sample body


def _has_side(style: dict) -> bool:
    """Whether the original has a side band (else it is one column)."""
    return any(b["kind"] == "side" for b in style["columns"]["bands"])


def _where(band: dict, bands: list[dict]) -> str:
    """`band` in words: its kind and where it is among the bands (on the left, on the right, in the middle)."""
    others = [b for b in bands if b is not band]
    place = ("on the left" if all(band["x0"] < b["x0"] for b in others) else
             "on the right" if all(band["x0"] > b["x0"] for b in others) else "in the middle")
    return f'{"side" if band["kind"] == "side" else "main"} column, {place}'


def _band_of(bbox: list[float], bands: list[dict]) -> dict | None:
    """The band a box stands in: the one its centre is in or nearest to; None when it spans two bands or there are
    none."""
    if not bands or sum(1 for b in bands if bbox[0] < b["x1"] - 2 and bbox[2] > b["x0"] + 2) > 1:
        return None
    centre = (bbox[0] + bbox[2]) / 2
    return min(bands, key=lambda b: max(b["x0"] - centre, centre - b["x1"], 0))


def _line_runs(runs: list[dict]) -> list[list[dict]]:
    """`runs` as lines, top to bottom, each left to right: runs whose vertical centres are within half their size.
    (`style_extract.line_groups` needs the baselines its result no longer carries.)"""
    lines: list[list[dict]] = []
    for run in sorted(runs, key=lambda r: ((r["bbox"][1] + r["bbox"][3]) / 2, r["bbox"][0])):
        centre = (run["bbox"][1] + run["bbox"][3]) / 2
        if lines and abs(centre - (lines[-1][0]["bbox"][1] + lines[-1][0]["bbox"][3]) / 2) <= run["size"] / 2:
            lines[-1].append(run)
        else:
            lines.append([run])
    return [sorted(line, key=lambda r: r["bbox"][0]) for line in lines]


def _pieces(line: list[dict]) -> list[list[dict]]:
    """A line's runs cut where two are more than a letter's size apart: the texts of two columns that share a line
    are two pieces, a drop cap or letter-spaced word one."""
    out = [[line[0]]]
    for prev, run in zip(line, line[1:]):
        if run["bbox"][0] - prev["bbox"][2] > run["size"]:
            out.append([run])
        else:
            out[-1].append(run)
    return out


def _box(line: list[dict]) -> list[float]:
    return [min(r["bbox"][0] for r in line), min(r["bbox"][1] for r in line),
            max(r["bbox"][2] for r in line), max(r["bbox"][3] for r in line)]


def _by_band(runs: list[dict], bands: list[dict]) -> dict[int, list[dict]]:
    """`runs` by the index in `bands` of the band each stands in, -1 for one across two bands."""
    groups: dict[int, list[dict]] = {}
    for run in runs:
        band = _band_of(run["bbox"], bands)
        groups.setdefault(-1 if band is None else bands.index(band), []).append(run)
    return groups


def _segments(line: list[dict], icon_fonts: set[str]) -> list[list[dict]]:
    """A line's runs cut at its icons (`style_icons.is_glyph`), the icons left out."""
    out: list[list[dict]] = [[]]
    for run in line:
        if style_icons.is_glyph(run, icon_fonts):
            out.append([])
        else:
            out[-1].append(run)
    return [s for s in out if s]


def original_text(style: dict, pdf: Path) -> str:
    """The text of the original `pdf` for the stylist (`text.txt`), its icons left out (#248). On a CV with a side
    band, each page's lines across the page, then each column's from left to right, under a ``[page N, side column, on
    the left]`` label, so a section that goes on in its column on the next page is not read as part of the other
    column's; on a CV of one column, its lines, page after page.

    Each line is read again from the page within its box: `style_extract`'s runs no longer say where a word ends, and
    only the PDF's own text tells a drop cap (``A`` + ``TROTTOIR``) from two words."""
    bands = style["columns"]["bands"] if _has_side(style) else []
    icon_fonts = style_icons.icon_fonts(style["runs"])
    out: list[str] = []
    doc = pdf_render.open_pdf(pdf)
    try:
        for number, page in enumerate(doc, 1):
            height, textpage = page.get_height(), page.get_textpage()
            groups = _by_band([r for r in style["runs"] if r["page"] == number], bands)
            for index in [-1, *range(len(bands))]:
                lines = []
                for line in _line_runs(groups.get(index, [])):
                    parts = []
                    for segment in _segments(line, icon_fonts):
                        x0, y0, x1, y1 = _box(segment)
                        parts.append(textpage.get_text_bounded(left=x0 - 1, bottom=height - y1, right=x1 + 1, top=height - y0))
                    if text := " ".join(" ".join(parts).split()):
                        lines.append(text)
                if lines:
                    out += ([f"[page {number}, {_ACROSS if index < 0 else _where(bands[index], bands)}]"] if bands else []) + lines
    finally:
        doc.close()
    return "\n".join(out)


def column_problems(style: dict, render: dict, placed: str) -> list[str]:
    """Where the print (`render`, `style_extract` of it) of the body `placed` (as `page.place_columns` wrapped it)
    puts its columns against the original's (`style`): each section heading of `div.side` printed nearer a main band
    of the original or across two bands, and each of `div.main` nearer a side band or across two, with where it
    printed and where its column is. A heading is found as a piece of a printed line (`_pieces`: its runs joined,
    `readability.squash`d), so a drop cap or wide letter-spacing does not hide it. `[]` when the original has one column, the body no side, or each heading is in
    its column's place; a heading the print does not show is left out."""
    cols = html_doc.columns(placed)
    if cols is None or not _has_side(style):
        return []
    bands = style["columns"]["bands"]
    runs = render.get("runs", [])
    lines = [(readability.squash("".join(r["text"] for r in piece)), _box(piece))
             for page in sorted({r["page"] for r in runs})
             for line in _line_runs([r for r in runs if r["page"] == page])
             for piece in _pieces(line)]
    found: list[str] = []
    for kind, part in (("main", cols[1]), ("side", cols[2])):
        for heading in html_doc.headings(part):
            boxes = [box for text, box in lines if text == readability.squash(heading)]
            homes = [_band_of(box, bands) for box in boxes]
            if not boxes or any(h is not None and (h["kind"] == "side") == (kind == "side") for h in homes):
                continue
            own = next(b for b in bands if (b["kind"] == "side") == (kind == "side"))
            box = boxes[0]
            where = "across both columns" if homes[0] is None else "in the place of the original's other column"
            found.append(f'the {kind} column\'s section "{heading}" printed at x {box[0]:.0f}-{box[2]:.0f} pt, {where}; '
                         f'the original\'s {_where(own, bands)} is at x {own["x0"]:.0f}-{own["x1"]:.0f} pt')
    return found


def body_column_problems(style: dict, body: str, columns: templates.Columns | None) -> list[str]:
    """What the sample `body`, placed in `columns`, puts in the other column than the original has it: each line of
    the original (of `_MIN_LINE` characters or more) found in the body's side column that the original has in a main
    band, or in its main column that it has in a side band. `[]` without a side band or a side column."""
    cols = html_doc.columns(page_mod.place_columns(body, columns))
    if cols is None or not _has_side(style):
        return []
    texts = {"main": readability.normalise(html_doc.text(cols[1])), "side": readability.normalise(html_doc.text(cols[2]))}
    bands = style["columns"]["bands"]
    found: list[str] = []
    for run in style["runs"]:
        band = _band_of(run["bbox"], bands)
        line = readability.normalise(run["text"])
        if band is None or len(line) < _MIN_LINE:
            continue
        own, other = ("side", "main") if band["kind"] == "side" else ("main", "side")
        if line in texts[other] and line not in texts[own]:
            found.append(f'"{run["text"].strip()[:60]}" is in the {own} column of the original (page {run["page"]}), '
                         f'but your body puts it under a heading of the {other} column')
    return found


def photo_box_problems(style: dict, painted: list[dict]) -> list[str]:
    """A box a print with no photo (`painted`, `style_extract.painted` of it) draws where the original's photo is
    (#246): a path on its page, of any kind (a disc or a rounded box too), that covers half the photo's box or more,
    is no more than twice its size (a side band's background is far larger) and shows: a stroke, or a fill unlike
    the page's background and the fill of any larger path under it. `compile` places `<img class="photo">` only when
    there is a photo, so anything drawn there without it is the template's own and prints on every CV (or letter).
    `[]` when the original has no photo or nothing shows there."""
    photo = style.get("photo")
    if not photo or len(painted) < photo["page"]:
        return []
    page = painted[photo["page"] - 1]
    x0, y0, x1, y1 = photo["bbox"]
    area = (x1 - x0) * (y1 - y0)

    def size(box):
        return (box[2] - box[0]) * (box[3] - box[1])

    def under(path):  # the fills a path stands on: the page's and those of larger paths around it
        a, b, c, d = path["bbox"]
        return {page["background"] or "#ffffff"} | {
            o["fill"] for o in page["paths"] if o["fill"] and size(o["bbox"]) > size(path["bbox"])
            and o["bbox"][0] <= a and o["bbox"][1] <= b and o["bbox"][2] >= c and o["bbox"][3] >= d}

    for path in page["paths"]:
        a, b, c, d = path["bbox"]
        if size(path["bbox"]) > 2 * area or not (path.get("stroke") or (path.get("fill") and path["fill"] not in under(path))):
            continue
        if max(0, min(c, x1) - max(a, x0)) * max(0, min(d, y1) - max(b, y0)) >= area / 2:
            return [f"with no photo, the page still draws a box at x {a:.0f}-{c:.0f} pt, y {b:.0f}-{d:.0f} pt, where the "
                    f"original's photo is: the photo's place is the img.photo alone (size it in .photo; no background, "
                    f"border or shape drawn for it on another element)"]
    return []


# ---------- the stress variants ----------

_LONG_ROLE = "Senior Principal Engineering Manager for Distributed Data Platforms and Cross-Functional Delivery Programmes"
_FRENCH = ("Professionnel polyvalent, fort de huit années d'expérience dans des environnements exigeants, attaché à des plans "
           "clairs, à des étapes régulières et à une communication ouverte avec les équipes, les clients et les partenaires, "
           "capable de conduire des projets complexes de leur cadrage jusqu'à leur mise en production, en tenant les délais "
           "comme les budgets et en formant les collègues qui rejoignent l'équipe en cours de route : toujours avec soin !")


def _section_at(lines: list[str]) -> int:
    return next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))


def _fewer(lines: list[str]) -> list[str]:
    """`lines` with only the first `###` entry of each section."""
    out, entries, skipping = [], 0, False
    for line in lines:
        if line.startswith("## "):
            entries, skipping = 0, False
        elif line.startswith("### "):
            entries += 1
            skipping = entries > 1
        if not skipping:
            out.append(line)
    return out


def _long_title(lines: list[str]) -> list[str]:
    for i, line in enumerate(lines):
        if line.startswith("### "):
            rest = line[4:].partition("|")[2]
            return [*lines[:i], f"### {_LONG_ROLE} |{rest}" if rest else f"### {_LONG_ROLE}", *lines[i + 1:]]
    return [*lines, "", "## Experience", "", f"### {_LONG_ROLE} | Example Company — 2020 - 2023", "", "- A bullet.", ""]


def _stress_variants(cv_md: str) -> dict[str, dict]:
    """The CV in `cv_md` made into the texts a template must hold (no model): ``photo`` (the same, printed with a
    photo), ``fewer`` (one entry a section), ``long_title`` (a very long job title), ``extra_section`` (one more
    section) and ``french`` (a long French paragraph first, `lang` "fr"). Each is ``{"md", "lang", "photo"}``."""
    lines = cv_md.rstrip("\n").splitlines()
    at = _section_at(lines)
    variants = {
        "photo": lines, "fewer": _fewer(lines), "long_title": _long_title(lines),
        "extra_section": [*lines, "", "## Publications", "", "- A study of nightly pipelines (2021)", "- Notes on small steady steps (2019)"],
        "french": [*lines[:at], "## Profil", "", _FRENCH, "", *lines[at:]],
    }
    return {name: {"md": cv_md if name == "photo" else "\n".join(v) + "\n", "lang": "fr" if name == "french" else "en",
                   "photo": name == "photo"} for name, v in variants.items()}


# ---------- the loop ----------

TIMEOUT_S = 900  # one stylist call
_CV_FILE, _LETTER_FILE = templates.FILES["cv_template"], templates.FILES["cover_letter_template"]
_NAME = re.compile(r"^#\s+(.+)$", re.M)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_TITLE = re.compile(r"<title>.*?</title>", re.S | re.I)
_TITLES = {"cv": "CV", "letter": "Cover letter"}


class _Stop(Exception):
    """The build cannot go on: what is said is a problem of the result."""


def _task(files: str, feedback: str | None, reply: str) -> str:
    return "\n\n".join(part for part in (files, feedback, reply) if part)


def _ask(run, task: str, work: Path, profile_dir: Path | None) -> str:
    """One stylist call (a `claude -p` session in `work`, read-only: the agent's own tools, `--restricted`, no tool
    server of the user's) and its reply text."""
    definition = claude_cli.agent_definition(STYLIST)
    args = ["--restricted", "--agents", json.dumps({STYLIST: definition}), "--agent", STYLIST,
            "--allowedTools", ",".join(definition["tools"]), "--strict-mcp-config", "--no-session-persistence",
            *claude_cli.STREAM_ARGS]
    envelope = run(args, feature="style", input=task, timeout_s=TIMEOUT_S, profile_dir=profile_dir, cwd=work)
    return str(claude_cli.envelope_result(envelope))


def _shipped_plan(style_fonts: list[dict], font_dir: Path) -> list[dict]:
    """The font plan when the free fonts could not be fetched: `fonts.plan` over only the families the code ships
    (`profile.example/fonts/`), copied into `font_dir`; any other font of the CV has no stand-in."""
    shipped = workspace.PROFILE_EXAMPLE_DIR / "fonts"
    data = fonts.pin()
    data["families"] = {name: f for name, f in data["families"].items() if (shipped / f["files"][0]["name"]).is_file()}
    plan = fonts.plan(style_fonts, data=data)
    font_dir.mkdir(parents=True, exist_ok=True)
    for entry in plan:
        for name in [f["name"] for f in entry["files"]] + ([entry["licence"]["name"]] if entry["licence"] else []):
            shutil.copyfile(shipped / name, font_dir / name)
    return plan


def _get_fonts(pdf: Path, style: dict, font_dir: Path, fetch) -> tuple[list[dict], str | None]:
    """The font plan for the CV and its files in `font_dir`; a fetch that fails (`fonts.FontsError`) falls back to the
    shipped fonts and is named in the second value."""
    plan = fonts.plan(style["fonts"], font_measure.measure(pdf, style["fonts"]))
    try:
        (fetch or fonts.fetch)(plan, font_dir)
        return plan, None
    except fonts.FontsError as exc:
        shutil.rmtree(font_dir, ignore_errors=True)
        return _shipped_plan(style["fonts"], font_dir), str(exc)


def _agent_style(style: dict, icon_files: dict[str, str]) -> dict:
    """`style` as the stylist reads and `profile/style/style.json` keeps it: only the icons of a kind `write_icons` wrote
    a file for, each with its ``file`` (a dropped one has nothing to draw, #248), their traced paths in the SVG files."""
    icons = [{**{k: v for k, v in icon.items() if k not in ("d", "viewBox", "fill_rule")}, "file": icon_files[kind]}
             for icon in style["icons"] if (kind := icon_kind((icon.get("near") or {}).get("text"))) in icon_files]
    return {**style, "icons": icons}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _clean(template: str, kind: str) -> str:
    """`template` as it is published: the model wrote it, so its comments are not kept. The first comment is the
    vocabulary header of the shipped template of its `kind` (the code's own text), every other HTML or CSS comment is
    dropped and the title is a fixed one."""
    shipped = (workspace.PROFILE_EXAMPLE_DIR / (_CV_FILE if kind == "cv" else _LETTER_FILE)).read_text(encoding="utf-8")
    header = iter([_HTML_COMMENT.search(shipped).group(0)])
    text = _HTML_COMMENT.sub(lambda m: next(header, ""), _CSS_COMMENT.sub("", template))
    return _TITLE.sub(f"<title>{_TITLES[kind]}</title>", text)


def _photo_stand_in(style: dict, images: list, work: Path) -> Path | None:
    """The original's photo cut from its page image, as `work/original-photo.png`, for the sample prints compared with
    the original (#262: a photo box printed empty, or not at all, cost the score though the template held its place);
    None when the original has no photo."""
    photo = style.get("photo")
    if not photo:
        return None
    page = images[photo["page"] - 1]
    scale = page.width / style["page"]["size"][0]
    path = work / "original-photo.png"
    page.crop(tuple(round(v * scale) for v in photo["bbox"])).save(path, "PNG")
    return path


class _Session:
    """One build's state: the original's style and page images, the folder it works in, the manifest and the model seam."""

    def __init__(self, style: dict, pdf: Path, work: Path, manifest: templates.Manifest, run, profile_dir: Path | None) -> None:
        self.style, self.work, self.manifest, self.run, self.profile_dir = style, work, manifest, run, profile_dir
        self.images = style_compare.page_images(pdf, work)  # also leaves original_page_N.png beside the files it reads
        self.rounds = 0
        self.photo = _photo_stand_in(style, self.images, work)

    def ask(self, task: str, *, count: bool = True) -> str:
        """One stylist call; the letter's (`count` False) are not rounds of the CV template."""
        self.rounds += count
        return _ask(self.run, task, self.work, self.profile_dir)

    def sample(self, template: str, body: str) -> tuple[dict, float, float, list[str], list[str]]:
        """The sample `body` printed in `template` (with the original's own photo when it has one: `_photo_stand_in`),
        read back and compared with the original: the diffs, the blurred score, the worst offset in points, the
        sections printed in the other column's place (`column_problems`) and the words read back as letters apart
        (`readability.spaced_problems`, #267).

        Raises:
            _Stop: the print has no text to read back.
        """
        pdf, placed, _ = page_mod.print_page(
            body, template, self.work / _CV_FILE, "en", self.work, "render", columns=self.manifest.columns, photo=self.photo)
        render = style_extract.extract(pdf)
        if not render["verdict"]["copyable"]:
            raise _Stop("the print has no text to read back")
        diffs = style_compare.match(self.style, render)
        score = style_compare.pages_score(self.images, style_compare.page_images(pdf, self.work))
        spaced = [p["detail"] for p in readability.spaced_problems(readability.extract(pdf)[0], placed)]
        return diffs, score, style_compare.worst_offset_pt(diffs), column_problems(self.style, render, placed), spaced


_REPLY_FIRST = ("Reply with one line on what you see (layout, colours), then the ```template block and the ```body block, "
                "nothing after them.")
_REPLY_NEXT = "Reply with one line on what you changed and the whole new template in one ```template block, nothing after it."
_REPLY_LETTER = "Reply with one line and the whole letter template in one ```letter block, nothing after it."
_LIMIT = 12  # problems one message to the stylist names


def _page_size(style: dict) -> str:
    """The original's page size in words: A4 or US Letter, else the points."""
    width, height = ((style.get("page") or {}).get("size") or [0, 0])
    for name, (w, h) in (("A4", (595.3, 841.9)), ("US Letter", (612.0, 792.0))):
        if abs(width - w) <= 3 and abs(height - h) <= 3:
            return name
    return f"{width:g} x {height:g} pt"


def _files_text(s: _Session, notes: str, icon_files: dict[str, str]) -> str:
    pages = len(s.images)
    icons = ", ".join(f"{kind} -> /icons/{name}" for kind, name in icon_files.items()) or "none"
    cols = s.manifest.columns
    if not cols:
        columns = "none: one column, no .main or .side"
    else:
        parts = []
        if cols.side:
            parts.append("the kinds " + ", ".join(cols.side))
        if cols.headings:
            parts.append("the sections headed " + ", ".join(cols.headings))
        columns = (
            " and ".join(parts) + " (the code wraps the sections into div.main and div.side and your CSS styles them; "
            "the sample body is plain sections with no div, no class on a div). The page has div.main first, then "
            "div.side; in the original, " + ", ".join(f'the {_where(b, s.style["columns"]["bands"])} is at x '
                                                       f'{b["x0"]:.0f}-{b["x1"]:.0f} pt' for b in s.style["columns"]["bands"])
            + ": place each there with CSS"
        )
    return (
        f"Rebuild the look of the CV in this folder as a template. Files here: original_page_1.png to original_page_{pages}.png "
        f"(the CV; look at them with the Read tool), style.json, text.txt, fonts.css, template.json. "
        f"Your last template, when there is one, is cv.template.html and the print of the last one that printed is "
        f"render_page_1.png and on (render_page_N.png for the other pages).\n"
        f"Fonts (use only these; the @font-face rules are in fonts.css):\n{notes or '- none: use generic families'}\n"
        f"Icons you may draw, by kind: {icons}.\nSide column: {columns}. Page limit: {s.manifest.max_pages}. "
        f"Page size: {_page_size(s.style)}, set it with @page size."
    )


def _list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items[:_LIMIT])


def _draft(s: _Session, files: str, cap: int) -> tuple[str | None, str | None, list[float], str | None]:
    """The comparison rounds: the stylist writes a template (and, in the first round that has one, the sample body),
    the guard reads it, it is printed and compared. A round whose print puts a section in the other column's place
    (`column_problems`) is not kept. Returns the best template (None when none was kept), the sample body, the blurred
    scores of the rounds kept and the last feedback."""
    template = body = feedback = None
    kept: list[str] = []
    scores: list[float] = []
    for number in range(1, cap + 1):
        progress_mod.report(f"building the template, round {number}", done=number, total=cap, stage="style")
        first = body is None
        reply = blocks(s.ask(_task(files, feedback, _REPLY_FIRST if first else _REPLY_NEXT)))
        template = reply.get("template")
        if template is None:
            feedback = "Your reply had no ```template block: the whole page in one fenced block named template."
            continue
        if first:
            sample = reply.get("body")
            if sample is None:
                feedback = "Your reply had no ```body block: the sample body in one fenced block named body."
            elif bad := html_guard.unsafe(sample):
                feedback = "The guard refused your sample body (it may hold only the building blocks):\n" + _list(bad)
            elif bad := body_column_problems(s.style, sample, s.manifest.columns):
                feedback = ("Your sample body puts text under a heading of the other column (text.txt gives each page's "
                            "text column by column: a section goes on in its own column on the next page):\n" + _list(bad))
            elif s.photo and "<<photo>>" not in sample:
                feedback = ("Your sample body has no <<photo>>: the original has a photo, so the token goes first in "
                            "the header (the print puts the original's photo there).")
            else:
                body = sample
                _write(s.work / "sample_body.html", body)
            if body is None:
                continue
        _write(s.work / _CV_FILE, template)
        if problems := html_guard.template_problems(template, s.manifest):
            feedback = "The guard refused your template, so it was not printed. Fix these:\n" + _list(problems)
            continue
        try:
            diffs, score, worst, misplaced, spaced = s.sample(template, body)
        except (html_pdf.PrintError, _Stop, ValueError) as exc:
            feedback = f"Printing your template failed: {exc}"
            continue
        if misplaced:
            feedback = ("Your template prints the columns in the wrong place, so this round is not kept:\n"
                        + _list(misplaced) + "\n\n" + style_compare.feedback(diffs, score))
            continue
        if spaced:
            feedback = ("Your template prints letters apart, so this round is not kept: a reader takes them as single "
                        "letters. Their letter-spacing is too wide for their size (a parent's spacing inherited by smaller "
                        "text, or a justified line spread per character):\n" + _list(spaced) + "\n\n"
                        + style_compare.feedback(diffs, score))
            continue
        kept.append(template)
        scores.append(score)
        feedback = style_compare.feedback(diffs, score)
        if style_compare.should_stop(scores, worst, cap):
            break
    return (kept[style_compare.best_round(scores)] if scores else None), body, scores, feedback


def _stress(s: _Session, template: str, cv_md: str) -> list[str]:
    """The failures of the template printed with the variants of `cv_md` (`_stress_variants`), through the same placing,
    photo and typography steps `compile` takes, no model: a print that fails, text lost off the page (`readability`'s
    checks, a last page nearly empty excepted), a section in the other column's place (`column_problems`), a box drawn where the original's photo is in a print with
    no photo (`photo_box_problems`), a photo not placed, too many pages (the compact variant must fit the
    manifest's `max_pages`, the rest `templates.MAX_PAGES`)."""
    name = (_NAME.search(cv_md) or [None, None])[1]
    picture = s.work / "stress-photo.jpg"
    Image.new("RGB", (350, 450), "tan").save(picture, "JPEG")
    failures: list[str] = []
    for variant, v in _stress_variants(cv_md).items():
        progress_mod.report(f"stress render: {variant}", stage="style")
        try:
            pdf, placed, photo = page_mod.print_page(
                cv_body.body(v["md"], v["lang"]), template, s.work / _CV_FILE, v["lang"], s.work / "stress" / variant, "cv",
                columns=s.manifest.columns, photo=picture if v["photo"] else None)
            found = [f"{p['kind']}: {p['detail']}" for p in readability.check_pdf(pdf, placed, name, cv=True) if p["kind"] != "sparse"]
            found += column_problems(s.style, style_extract.extract(pdf), placed) + (
                [] if v["photo"] else photo_box_problems(s.style, style_extract.painted(pdf)))
            pages = pdf_render.get_page_count(pdf)
        except (html_pdf.PrintError, ValueError) as exc:
            failures.append(f"{variant}: printing failed: {exc}")
            continue
        if v["photo"] and photo is None:
            found.append("the photo was not placed")
        limit = s.manifest.max_pages if variant == "fewer" else templates.MAX_PAGES
        if pages > limit:
            found.append(f"{pages} pages, at most {limit}")
        failures += [f"{variant}: {f}" for f in found]
    return failures


def _letter(s: _Session, template: str, cv_md: str) -> tuple[str | None, list[str]]:
    """The letter template for the final CV `template`: a second stylist call given the CV template and the default
    letter template, its page guarded, printed with a sample letter (readable, one page); one more call when it fails."""
    shutil.copyfile(workspace.PROFILE_EXAMPLE_DIR / _LETTER_FILE, s.work / f"default.{_LETTER_FILE}")
    _write(s.work / _CV_FILE, template)
    files = (f"Write the cover letter template that matches the CV template. Files here: cv.template.html (the CV template "
             f"you wrote: its fonts, colours, margins and header), default.{_LETTER_FILE} (the default letter template: its "
             f"building blocks and structure), template.json, fonts.css. Read the first two with the Read tool.")
    body = style_preview.sample_letter(cv_md)
    feedback, problems = None, []
    for _ in range(2):
        progress_mod.report("building the letter template", stage="style")
        candidate = blocks(s.ask(_task(files, feedback, _REPLY_LETTER), count=False)).get("letter")
        if candidate is None:
            problems = ["no ```letter block: the whole page in one fenced block named letter"]
        elif not (problems := html_guard.template_problems(candidate, s.manifest, "letter")):
            candidate = _clean(candidate, "letter")
            try:
                pdf = page_mod.print_page(body, candidate, s.work / _CV_FILE, "en", s.work / "letter", "letter")[0]
                problems = [f"{p['kind']}: {p['detail']}" for p in readability.check_pdf(pdf, body, None)]
                problems += photo_box_problems(s.style, style_extract.painted(pdf))
                if (pages := pdf_render.get_page_count(pdf)) != 1:
                    problems.append(f"the sample letter prints on {pages} pages, it must be one")
            except (html_pdf.PrintError, ValueError) as exc:
                problems = [f"printing failed: {exc}"]
        if not problems:
            return candidate, []
        feedback = "Problems with your letter template. Fix these:\n" + _list(problems)
    return None, [f"letter template: {p}" for p in problems]


def restore(profile_dir: Path) -> None:
    """Put back the style a swap that was interrupted set aside (`move_in` moves the earlier one to `.<name>.old`
    before it moves the new one in), for the candidate and for the style in use."""
    for name in (templates.CANDIDATE, templates.STYLE):
        dest, old = profile_dir / name, profile_dir / f".{name}.old"
        if old.is_dir() and not dest.exists():
            old.rename(dest)


def move_in(source: Path, profile_dir: Path, name: str) -> None:
    """Rename the folder `source` (beside `profile_dir/name`, on the same disk) to `profile_dir/name`, the earlier one
    set aside as `.<name>.old` until the new one is there (`restore` puts it back after an interruption)."""
    dest, old = profile_dir / name, profile_dir / f".{name}.old"
    shutil.rmtree(old, ignore_errors=True)
    if dest.exists():
        dest.rename(old)
    source.rename(dest)
    shutil.rmtree(old, ignore_errors=True)


def end(candidate: Path, profile_dir: Path) -> None:
    """Delete the candidate: renamed to a staging name first, so an interrupted delete never leaves a
    `style.next/` that could be chosen (the stale-staging sweep of the next build removes the rest)."""
    gone = profile_dir / ".style.ended.part"
    shutil.rmtree(gone, ignore_errors=True)
    candidate.rename(gone)
    shutil.rmtree(gone, ignore_errors=True)


def _publish(profile_dir: Path, work: Path, pdf: Path, cv: str, letter: str) -> None:
    """Write `profile_dir/style.next/` whole, the candidate: staged beside it and moved in, an earlier one set aside
    until the new one is there (`restore` puts it back after an interruption). `profile_dir/style/`, the style in use,
    is never touched here. No ledger lock (nothing else writes there).

    Raises:
        OSError: the files could not be written or moved.
    """
    with utils.staging(profile_dir, ".style.") as staging:
        _write(staging / _CV_FILE, cv)
        _write(staging / _LETTER_FILE, letter)
        for name in ("style.json", templates.MANIFEST_FILE):
            shutil.copyfile(work / name, staging / name)
        shutil.copyfile(pdf, staging / "source.pdf")
        for folder in ("fonts", "icons"):
            if (work / folder).is_dir():
                shutil.copytree(work / folder, staging / folder, ignore=shutil.ignore_patterns("*.part"))
        move_in(staging, profile_dir, templates.CANDIDATE)


def _build(pdf_path: Path, work: Path, profile_dir: Path, run, fonts_fetch, cap: int, result: dict) -> None:
    refused = style_extract.not_pdf(pdf_path)
    if refused:
        raise _Stop(f"{pdf_path.name} {refused['detail']}")
    try:
        style = style_structure.extract(pdf_path)  # the one model call per original; `style` has made it already
    except style_structure.StructureError as exc:
        raise _Stop(str(exc)) from None
    if not style["verdict"]["copyable"]:
        raise _Stop(f"{pdf_path.name} {style['verdict']['detail']}")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    pdf = work / "original.pdf"
    shutil.copyfile(pdf_path, pdf)
    progress_mod.report("reading the CV's style", stage="style")
    _write(work / "text.txt", original_text(style, pdf))
    progress_mod.report("fetching the fonts", stage="style")
    plan, result["font_error"] = _get_fonts(pdf, style, work / "fonts", fonts_fetch)
    result["fonts"] = [{k: e[k] for k in ("family", "source", "reason", "faked", "resolved")} for e in plan]
    _write(work / "fonts.css", _font_face_css(plan))
    icon_files, result["dropped_icons"] = write_icons(style["icons"], work / "icons")
    _write(work / "style.json", json.dumps(_agent_style(style, icon_files), ensure_ascii=False, indent=1))
    cv_md = style_preview.cv_text(profile_dir, common._load_config_or_defaults(profile_dir))
    data = _manifest_data(style, list(dict.fromkeys(f["name"] for e in plan for f in e["files"])), icon_files, cv_md)
    _write(work / templates.MANIFEST_FILE, json.dumps(data, indent=1))
    s = _Session(style, pdf, work, templates.Manifest(**data), run, profile_dir)
    try:
        _rounds(s, plan, icon_files, pdf, style, profile_dir, cap, result)
    finally:
        result["rounds"] = s.rounds


def _rounds(s: _Session, plan: list[dict], icon_files: dict[str, str], pdf: Path, style: dict, profile_dir: Path, cap: int,
            result: dict) -> None:
    files = _files_text(s, _font_notes(plan), icon_files)
    template, body, result["scores"], feedback = _draft(s, files, cap)
    if body is None:
        raise _Stop(f"no sample body of the stylist's was accepted in {s.rounds} rounds: {feedback}")
    if template is None:
        raise _Stop(f"no template of the stylist's was kept in {s.rounds} rounds: {feedback}")
    if (best := max(result["scores"])) < style_compare.FLOOR:
        cause = f"the fonts could not be downloaded ({result['font_error']}): try again later; " if result["font_error"] else ""
        raise _Stop(f"{cause}the rebuild did not come close to your CV's look in {s.rounds} rounds: its best print "
                    f"scored {best:.2f}, at least {style_compare.FLOOR} is needed")
    template = _clean(template, "cv")
    cv_md = style_preview.cv_text(profile_dir, common._load_config_or_defaults(profile_dir))
    if failures := _stress(s, template, cv_md):
        progress_mod.report("one more round for the stress renders", stage="style")
        _write(s.work / _CV_FILE, template)
        reply = blocks(s.ask(_task(files, "Printed with other texts, your template fails:\n" + _list(failures), _REPLY_NEXT)))
        template = reply.get("template") or ""
        if problems := (html_guard.template_problems(template, s.manifest) if template else ["no ```template block in the reply"]):
            raise _Stop("the stress renders failed and the extra round's template was refused: " + "; ".join(problems[:3]))
        template = _clean(template, "cv")
        if failures := _stress(s, template, cv_md):
            raise _Stop("the stress renders still fail after the extra round: " + "; ".join(failures[:_LIMIT]))
    letter, problems = _letter(s, template, cv_md)
    if letter is None:
        raise _Stop("; ".join(problems))
    _publish(profile_dir, s.work, pdf, template, letter)
    result["state"] = "ready"


def build(pdf_path, *, work_dir, profile_dir=None, run=None, fonts_fetch=None, progress=None, cap: int = style_compare.CAP) -> dict:
    """Build a CV template from the CV PDF at `pdf_path` (see the module's docstring) and write it to
    `profile_dir/style.next/` (default the profile) when it is ready; a failed build writes nothing there.

    `work_dir` is the build's own folder (emptied first): the files the stylist reads, its drafts and the stress
    prints. `run` is the model call (default `claude_cli.run`: tests give a stand-in), `fonts_fetch(plan, dest)` the font
    download (default `fonts.fetch`), `progress` a `progress.Reporter`; `cap` bounds the comparison rounds.

    Returns ``{"state": "ready" | "failed", "rounds", "scores", "fonts": [{family, source, reason, faked, resolved}],
    "dropped_icons": [{near, reason}], "font_error", "problems": [str]}``: ``scores`` the blurred score of each
    comparison round kept (1 is the original's own page), ``font_error`` why the fonts were not fetched (only
    the fonts the code ships stood in), ``problems`` why it failed. A model, print or file error is a failed result,
    not an exception.
    """
    result: dict = {"state": "failed", "rounds": 0, "scores": [], "fonts": [], "dropped_icons": [], "font_error": None,
                    "problems": []}
    profile = Path(profile_dir) if profile_dir else workspace.PROFILE_DIR
    with progress_mod.activate(progress):
        try:
            restore(profile)
            _build(Path(pdf_path), Path(work_dir), profile, run or claude_cli.run, fonts_fetch, cap, result)
        except _Stop as exc:
            result["problems"] = [str(exc)]
        except (claude_cli.ClaudeError, html_pdf.PrintError, OSError, ValueError, PdfiumError) as exc:
            result["problems"] = [f"{type(exc).__name__}: {exc}"]
    return result
