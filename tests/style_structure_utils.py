"""The model's reading of a CV's structure (#343), for tests: no test reaches a model.

`recorded(name)` is an answer recorded for a style corpus case (`tests/tailoring/fixtures/styles/structure/<name>.json`,
ids and kinds only; `scripts/record_structure.py` records them again) and `fake_ask(text)` the stand-in the autouse
fixture of `tests/conftest.py` puts where `style_structure` asks: it reads the same input the model gets and answers by
a plain rule (the name is the largest text of the first page, the headings are the lines of at most six words set
unlike the body that a section kind names, one column, not LinkedIn), so a test that reads any PDF finds the
structure it expects without a model; the corpus CVs get their recorded answers.
"""

import functools
import json

from paths import TESTS_DIR

from door import i18n

RECORDED = TESTS_DIR / "tailoring" / "fixtures" / "styles" / "structure"
_KINDS = tuple(i18n.CvSections.model_fields)


def recorded(name: str) -> dict:
    return json.loads((RECORDED / f"{name}.json").read_text(encoding="utf-8"))


def parse(text: str) -> tuple[dict, list[dict]]:
    """The styles (id to size, weight, characters) and the lines (id, page, y, x0, x1, style, text) of a model input."""
    styles, lines, part = {}, [], None
    for raw in text.splitlines():
        if raw.startswith("styles ("):
            part = "styles"
        elif raw.startswith("lines ("):
            part = "lines"
        elif part == "styles":
            sid, *rest = raw.split(" ")
            # family may hold spaces: the last five fields are size, weight, italic, colour, chars
            size, weight, _, _, chars = rest[-5:]
            styles[sid] = {"size": float(size), "weight": int(weight), "chars": int(chars)}
        elif part == "lines":
            i, page, y, x0, x1, style, *words = raw.split(" ")
            lines.append({"id": int(i), "page": int(page), "x0": int(x0), "x1": int(x1), "style": style.rstrip("*"),
                          "text": " ".join(words)})
    return styles, lines


@functools.cache
def _corpus() -> dict[str, dict]:
    """The recorded answers by the model input of the PDF they were recorded for."""
    from door.tailoring import style_extract, style_structure

    pdfs = RECORDED.parent
    return {style_structure.rows(style_extract.read_pages(pdfs / f"{f.stem}.pdf"))[0]: recorded(f.stem)
            for f in sorted(RECORDED.glob("*.json")) if (pdfs / f"{f.stem}.pdf").is_file()}


def fake_ask(text: str) -> dict:
    """The recorded answer when `text` is the input of a corpus CV, else a plain rule's."""
    if text in _corpus():
        return _corpus()[text]
    styles, lines = parse(text)
    body = max(styles, key=lambda s: styles[s]["chars"])
    first = [r for r in lines if r["page"] == 1] or lines
    name = max(first, key=lambda r: (styles[r["style"]]["size"], -r["id"]))
    short = [r for r in lines if r is not name and len(r["text"].split()) <= 6 and r["style"] != body]
    heads = [r for r in short if i18n.cv_section_kind(r["text"], _KINDS)] or short
    heads = heads[:3] if len(heads) < 2 else heads
    return {"linkedin_export": False, "layout": {"columns": "one", "side": "none"}, "name": name["id"],
            "headings": [{"id": r["id"], "kind": i18n.cv_section_kind(r["text"], _KINDS) or "other", "column": "main"}
                         for r in heads], "entry_titles": []}


def structure_of(pdf, answer: dict) -> dict:
    """`answer` held to `style_structure.check` over the PDF's own lines."""
    from door.tailoring import style_extract, style_structure

    pages = style_extract.read_pages(pdf)
    return style_structure.check(answer, style_structure.rows(pages)[1], pages)


def extract_with(pdf, answer: dict) -> dict:
    """`style_extract.extract` of the PDF given the structure `answer` makes (a recorded answer, say)."""
    from door.tailoring import style_extract

    return style_extract.extract(pdf, structure=structure_of(pdf, answer))
