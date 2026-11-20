"""A CV's structure (#343, epic #342): its name, section headings, entry titles and columns, read by one Haiku call
per uploaded original instead of by rules.

`rows(pages)` lists the CV's text as visual lines (what the model reads), `check(answer, rows, pages)` holds the
model's answer to what the code can verify and works out what the code can do better (a heading's column from its
x), and `structure_for(pdf_path)` is the one call: made once per original (cached by the file's sha256 under
`HOME/.style/structure/`, so `draft_cv`, the `build_style` intake and the build share it), a failed call or a broken
answer a `StructureError`, never a fallback to rules. `extract(pdf_path)` is `style_extract.extract` given that
structure. Everything but the call is offline and deterministic.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from door.core import ask_cached, claude_cli, templates, workspace
from door.style import style_extract

PROMPT_VERSION = 3  # bump with the prompt, the schema or `rows`: a cached answer of another version is asked again
KINDS = ["experience", "education", "skills", "languages", "certifications", "interests", "summary", "contact",
         "projects", "other"]
_MAX_HEADING_WORDS = 6
_MAX_HEADING_STYLES = 2
_STRAY = 2  # rows at the far side of a side column that are still no column
_SIDE_SHARE = 0.6  # a side column is narrower than this share of the text's width
_NEAR = 2.0  # pt of slack where a box is compared with a column
_CONTINUES = 1.6  # a heading's next line is its second line within this many sizes below
_FURNITURE_BAND = 0.08  # share of the page height at its top and foot where a footer or header can be
_KEEP_CACHED = 20  # answers kept in the cache folder, the most recently written

SYSTEM = """You read the structure of a CV from its text lines, as a typesetter would. The input lists each text style (font family, size in pt, weight, italic, colour, characters set in it) and each visual line of text with its page, baseline y, left and right x and style. Most text is body text in the most used style.

Answer with:
- linkedin_export: true when this is LinkedIn's "Save to PDF" profile export, whatever its fonts: a narrow left column headed "Contact", then "Top Skills" (LinkedIn's own wording; also "Languages", "Certifications"), a main column with "Summary", "Experience", "Education", and a "Page N of M" footer on every page. A CV that merely has a page footer or common section names is false.
- layout: how many columns of text the page body has under any header. A column is a stack of many lines at its own x-range, running down the page beside another; a date or note at the right of a line, or a line of contact details, is no column. For two columns, the side column is the narrower one (the sidebar; when equal, the one holding contact/skills/languages rather than experience) and side_x0/side_x1 its x-range.
- name: the id of the line with the candidate's name.
- headings: every section heading line, by id, with its `kind`.
- entry_titles: the ids of the entry title lines (a job title, employer, degree or school heading one entry).
- contacts: every line that holds one contact detail or a date, by id, with its `kind` (phone, email, web, linkedin, github, location, or date for the dates of an entry or a period). A line is a contact detail by what it holds (a number, an address, a link, a place), not by its position; a section heading or a line of running text is none. List each line once.
- footers: the ids of the lines that are page furniture and no content: a page number, a "Page N of M" line, a running footer or header repeated on the pages.

A section heading names a section of the CV (in any language, also unknown words): it starts a section and the CV has a handful of them, set in one consistent style that stands out from the body. Entry titles repeat within a section, usually carry a date on their line or next to them, and are often in a style close to the headings: tell them apart by position (a heading comes first and groups several entries), by count and by wording, not by style alone. A heading may contain a year ("Projekte 2020"). Text in another column on the same baseline belongs to that column, not to the heading."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["linkedin_export", "layout", "name", "headings", "entry_titles", "contacts", "footers"],
    "properties": {
        "linkedin_export": {"type": "boolean"},
        "layout": {"type": "object", "additionalProperties": False, "required": ["columns"],
                   "properties": {"columns": {"enum": ["one", "two", "three_or_more"]},
                                  "side_x0": {"type": "number"}, "side_x1": {"type": "number"}}},
        "name": {"type": "integer"},
        "headings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "kind"],
            "properties": {"id": {"type": "integer"}, "kind": {"enum": KINDS}}}},
        "entry_titles": {"type": "array", "items": {"type": "integer"}},
        "contacts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "kind"],
            "properties": {"id": {"type": "integer"}, "kind": {"enum": list(templates.ICON_KINDS)}}}},
        "footers": {"type": "array", "items": {"type": "integer"}},
    },
}


class StructureError(ValueError):
    """The structure of a CV could not be read: the call failed or its answer does not hold. The message is for the
    user, in plain words; `detail` is what went wrong, for the problem log."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail

    @classmethod
    def unreached(cls, exc: Exception) -> StructureError:
        return cls("Claude could not be reached, or Claude's usage limit is reached. Try again later.", str(exc))


# ---------- the input ----------

def _pieces(runs: list[dict]) -> list[list[dict]]:
    """The text runs as pieces, one per visual piece of a line: a gap wider than a word or two, or a change of style
    with a change of baseline or size, starts another."""
    out = []
    for line in style_extract.line_groups([r for r in runs if not r["rotated"] and not r["icon"]]):
        piece = [line[0]]
        for run in line[1:]:
            prev = piece[-1]
            same = (run["family"], run["weight"], run["italic"], run["color"]) == (
                prev["family"], prev["weight"], prev["italic"], prev["color"])
            restyled = not same and (abs(run["baseline"] - prev["baseline"]) > 0.15 * run["size"] or run["size"] != prev["size"])
            if run["bbox"][0] - prev["bbox"][2] > 1.2 * run["size"] or restyled:
                out.append(piece)
                piece = []
            piece.append(run)
        out.append(piece)
    return out


def rows(pages: list[dict]) -> tuple[str, list[dict]]:
    """The model's input and the rows it names: ``(text, rows)``. A row is a piece of a line (`_pieces`) as
    ``{id, page, x0, x1, y, bbox, style, text, main, runs}`` (``id`` from 1 in reading order, ``y`` the baseline, ``style``
    the id of the style of its largest run, ``*`` after it when the row mixes styles, ``main`` that run); the text
    opens with the page count and size and the table of styles, then one line per row."""
    styles: dict[tuple, str] = {}
    chars: dict[str, int] = {}
    out = []
    for piece in _pieces([r for p in pages for r in p["runs"]]):
        main = max(piece, key=lambda r: (r["size"], len(r["text"])))
        key = (main["family"] or main["font"], main["size"], main["weight"], main["italic"], main["color"])
        sid = styles.setdefault(key, f"S{len(styles) + 1}")
        chars[sid] = chars.get(sid, 0) + sum(len(r["text"]) for r in piece)
        mixed = len({(r["family"], r["size"], r["weight"], r["italic"], r["color"]) for r in piece}) > 1
        out.append({"id": len(out) + 1, "page": piece[0]["page"], "x0": round(min(r["bbox"][0] for r in piece)),
                    "x1": round(max(r["bbox"][2] for r in piece)), "y": round(piece[0]["baseline"]),
                    "bbox": [min(r["bbox"][0] for r in piece), min(r["bbox"][1] for r in piece),
                             max(r["bbox"][2] for r in piece), max(r["bbox"][3] for r in piece)],
                    "style": sid + ("*" if mixed else ""), "text": style_extract.joined(piece), "main": main, "runs": piece})
    width, height = pages[0]["size"] if pages else (0, 0)
    lines = [f"pages {len(pages)}, size {width:.0f}x{height:.0f} pt, y grows downward",
             "styles (id family size weight italic colour chars):"]
    for (family, size, weight, italic, color), sid in styles.items():
        lines.append(f"{sid} {family} {size} {weight} {'i' if italic else '-'} {color} {chars[sid]}")
    lines.append("lines (id page y x0 x1 style text; style* = mixed styles, the largest run's given):")
    lines += [f"{r['id']} {r['page']} {r['y']} {r['x0']} {r['x1']} {r['style']} {r['text']}" for r in out]
    return "\n".join(lines), out


# ---------- the answer ----------

def _fail(why: str) -> StructureError:
    return StructureError("The look of this CV could not be read.", f"the model's answer does not hold: {why}")


def _ids(values, rows_by_id: dict, what: str) -> list[int]:
    if not isinstance(values, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        raise _fail(f"{what} is not a list of line ids")
    unknown = [v for v in values if v not in rows_by_id]
    if unknown:
        raise _fail(f"{what} names line {unknown[0]}, which does not exist")
    if len(set(values)) != len(values):
        raise _fail(f"{what} names a line twice")
    return values


def _contacts(given, rows_by_id: dict) -> list[dict]:
    """The model's contact lines as ``[{row, kind}]``: each a line that exists, once, of a kind an icon has."""
    if not isinstance(given, list) or not all(isinstance(c, dict) for c in given):
        raise _fail("the contacts are not a list")
    ids = _ids([c.get("id") for c in given], rows_by_id, "the contacts")
    out = []
    for c, i in zip(given, ids):
        if c.get("kind") not in templates.ICON_KINDS:
            raise _fail(f"contact line {i} has no kind of contact detail")
        out.append({"row": rows_by_id[i], "kind": c["kind"]})
    return out


def _in_foot_or_head(row: dict, pages: list[dict]) -> bool:
    """Whether the row sits in the top or bottom `_FURNITURE_BAND` of its page: page furniture stands nowhere else, so
    a footer the model names in the body is dropped."""
    height = pages[row["page"] - 1]["size"][1]
    return row["bbox"][3] <= _FURNITURE_BAND * height or row["bbox"][1] >= (1 - _FURNITURE_BAND) * height


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _side_range(layout: dict, rows_list: list[dict], size: list[float]) -> tuple[float, float]:
    """The side column of a two-column layout as the model gave it, held to the page and to the text: inside the
    page, narrower than `_SIDE_SHARE` of the text's width, and snapped to the extent of the rows whose centre is in it
    (the model's numbers are read off a list, so a few points out)."""
    x0, x1 = layout.get("side_x0"), layout.get("side_x1")
    if not (_number(x0) and _number(x1)):
        raise _fail("two columns but no side column's x-range")
    if not 0 <= x0 < x1 <= size[0] + _NEAR:
        raise _fail("the side column is not inside the page")
    left, right = min(r["x0"] for r in rows_list), max(r["x1"] for r in rows_list)
    if x1 - x0 >= _SIDE_SHARE * (right - left):
        raise _fail("the side column is not narrower than the main text")
    slack = 0.2 * (x1 - x0)
    inside = [r for r in rows_list if x0 <= (r["x0"] + r["x1"]) / 2 <= x1 and r["x0"] >= x0 - slack and r["x1"] <= x1 + slack]
    if not inside:
        raise _fail("there is no text in the side column")
    return float(min(r["x0"] for r in inside)), float(max(r["x1"] for r in inside))


def _text_both_sides(rows_list: list[dict], side: tuple[float, float]) -> bool:
    """Whether text stands wholly left and wholly right of `side`, more than `_STRAY` rows each: then the side range is
    the middle of three columns, not a sidebar (one stray page number or note at its far side is no column). Rows that
    overlap the range are not counted."""
    left = sum(1 for r in rows_list if r["x1"] <= side[0] + _NEAR)
    right = sum(1 for r in rows_list if r["x0"] >= side[1] - _NEAR)
    return left > _STRAY and right > _STRAY


def _column_of(row: dict, side: tuple[float, float] | None) -> str:
    """`side` when the row stands inside the side range, `across` when it spans into it from the main column, else
    `main`."""
    if side is None:
        return "main"
    if row["x0"] >= side[0] - _NEAR and row["x1"] <= side[1] + _NEAR:
        return "side"
    return "across" if row["x0"] < side[1] - _NEAR and row["x1"] > side[0] + _NEAR else "main"


def _continues(heading: dict, others: list[dict], column: str, side) -> dict | None:
    """The second line of a heading that wraps: a row below it within `_CONTINUES` sizes, in its column, set in its
    colour, weight and family, unless the heading is set like the body (then the next line is body text)."""
    main = heading["main"]
    for other in others:
        if other["page"] != heading["page"] or other is heading:
            continue
        below = other["y"] - heading["y"]
        o = other["main"]
        if (0 < below <= _CONTINUES * main["size"] and _column_of(other, side) == column
                and (o["color"], o["weight"], o["family"], o["size"], o["italic"]) == (
                    main["color"], main["weight"], main["family"], main["size"], main["italic"])
                and abs(other["x0"] - heading["x0"]) <= 2 * _NEAR):
            return other
    return None


def check(answer: dict, rows_list: list[dict], pages: list[dict]) -> dict:
    """The model's `answer` held to the code's checks, as the structure `style_extract.extract` reads.

    ``{linkedin, columns: "one" | "two" | "three", side_range: (x0, x1) | None, name, headings: [{kind, column,
    row, text, bbox}], entry_titles: [id], contacts: [{row, kind}], footers: [row]}``, `name`, each heading's,
    contact's and footer's `row` the rows of `rows_list` (a footer outside the top and bottom 8% of its page is dropped). A heading's column is worked out from its x and the side range
    (the model's is not used), its `kind` is the model's, and a heading that wraps takes its second line in. LinkedIn
    is believed only with a footer line the model named on every page.

    Raises:
        StructureError: an id that does not exist or is used twice, a name that is a heading, a heading of more than six
            words, fewer than two headings or more than two styles of them, two columns with no usable side range.
    """
    if not isinstance(answer, dict):
        raise _fail("it is not an object")
    by_id = {r["id"]: r for r in rows_list}
    name = answer.get("name")
    if not isinstance(name, int) or isinstance(name, bool) or name not in by_id:
        raise _fail("the name's line does not exist")
    given = answer.get("headings")
    if not isinstance(given, list) or not all(isinstance(h, dict) for h in given):
        raise _fail("the headings are not a list")
    ids = _ids([h.get("id") for h in given], by_id, "the headings")
    entries = _ids(answer.get("entry_titles", []), by_id, "the entry titles")
    if name in ids:
        raise _fail("the name's line is also a heading")
    for i in ids:
        if len(by_id[i]["text"].split()) > _MAX_HEADING_WORDS:
            raise _fail(f'"{by_id[i]["text"][:40]}" is a heading of more than {_MAX_HEADING_WORDS} words')
    if len(ids) < 2:
        raise _fail("fewer than two section headings")
    if len({by_id[i]["style"].rstrip("*") for i in ids}) > _MAX_HEADING_STYLES:
        raise _fail(f"the headings are set in more than {_MAX_HEADING_STYLES} styles")
    layout = answer.get("layout")
    if not isinstance(layout, dict) or layout.get("columns") not in ("one", "two", "three_or_more"):
        raise _fail("the layout is missing")
    columns = {"one": "one", "two": "two", "three_or_more": "three"}[layout["columns"]]
    side = _side_range(layout, rows_list, pages[0]["size"]) if columns == "two" else None
    if side is not None and _text_both_sides(rows_list, side):
        columns, side = "three", None
    footer_rows = [r for r in (by_id[i] for i in _ids(answer.get("footers"), by_id, "the footers"))
                   if _in_foot_or_head(r, pages)]
    footers = all(any(r["page"] == n for r in footer_rows) for n in range(1, len(pages) + 1))
    contacts = _contacts(answer.get("contacts"), by_id)
    body = _body_style(rows_list)
    headings = []
    for i in ids:
        row = by_id[i]
        column = _column_of(row, side)
        text, bbox = row["text"], list(row["bbox"])
        second = _continues(row, [r for r in rows_list if r["id"] not in ids and r["id"] != name and r["id"] not in entries],
                            column, side)
        if second is not None and row["style"].rstrip("*") != body:
            text = f"{text} {second['text']}"
            bbox = [min(bbox[0], second["bbox"][0]), min(bbox[1], second["bbox"][1]),
                    max(bbox[2], second["bbox"][2]), max(bbox[3], second["bbox"][3])]
        kind = next(h.get("kind") for h in given if h["id"] == i)
        if kind not in KINDS:
            raise _fail(f'"{row["text"][:40]}" has no section kind')
        headings.append({"kind": kind, "column": column, "row": row, "text": text, "bbox": bbox})
    return {"linkedin": bool(answer.get("linkedin_export")) and footers, "columns": columns, "side_range": side,
            "name": by_id[name], "headings": headings, "entry_titles": entries,
            "contacts": contacts, "footers": footer_rows}


def _body_style(rows_list: list[dict]) -> str:
    """The id of the style most characters are set in."""
    chars: dict[str, int] = {}
    for r in rows_list:
        sid = r["style"].rstrip("*")
        chars[sid] = chars.get(sid, 0) + len(r["text"])
    return max(chars, key=chars.get) if chars else ""


# ---------- the call and its cache ----------

def _cache_dir() -> Path:
    return workspace.HOME / ".style" / "structure"


def _ask(text: str, feature: str = "style") -> dict:
    """The one model call: Haiku at low effort with no MCP servers (their tool lists would be thousands of tokens)."""
    return claude_cli.ask(SYSTEM, text, model="haiku", feature=feature, schema=SCHEMA, effort="low",
                          timeout_s=60)


def structure_for(pdf_path, feature: str = "style") -> dict | None:
    """The checked structure (`check`) of the CV in `pdf_path`: the cached answer for its sha256 when there is one for
    this `PROMPT_VERSION` and these rows, else one Haiku call (`_ask`, billed under `feature`) whose answer is checked and
    then cached; an answer that does not hold is asked once more (the model's answers vary from run to run). None for a
    scan (nothing to read: no call). A cached answer is checked again on every read; one that no
    longer holds is dropped and asked once again.

    Raises:
        StructureError: the call failed or its answer did not hold (nothing is cached then); the message is in plain
            words for the user and `detail` says what went wrong (also written to the problem log).
    """
    pdf_path = Path(pdf_path)
    pages = style_extract.read_pages(pdf_path)
    if not style_extract.scan_verdict(pages)["copyable"]:
        return None
    text, listed = rows(pages)
    return ask_cached.cached_answer(
        key=hashlib.sha256(pdf_path.read_bytes()).hexdigest(), version=PROMPT_VERSION,
        tag=hashlib.sha256(text.encode("utf-8")).hexdigest(), ask=lambda: _ask(text, feature),
        check=lambda answer: check(answer, listed, pages), error=StructureError, unreached=StructureError.unreached,
        label="cv structure", store=ask_cached.DirStore(_cache_dir(), _KEEP_CACHED))


def extract(pdf_path) -> dict:
    """`style_extract.extract` of the CV, given its structure (`structure_for`).

    Raises:
        StructureError: as `structure_for`.
    """
    return style_extract.extract(Path(pdf_path), structure=structure_for(pdf_path))

