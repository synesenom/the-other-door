"""What the stand-in `claude` answers the call that reads a CV's structure (#343): the CV's text lines come on stdin as
`door.style.style_structure.rows` writes them, and the answer is a plain rule's, as in `tests/style_structure_utils`:
the name is the largest text of the first page, the headings are the lines of at most six words set unlike the body
text that a section kind names, one column, not LinkedIn. Run as `python structure.py` with the input on stdin; needs
`door` importable."""

import json
import sys

from door import i18n

KINDS = tuple(i18n.CvSections.model_fields)


def answer(text: str) -> dict:
    """The plain rule's answer to a model input."""
    styles, lines, part = {}, [], None
    for raw in text.splitlines():
        if raw.startswith("styles ("):
            part = "styles"
        elif raw.startswith("lines ("):
            part = "lines"
        elif part == "styles":
            sid, *rest = raw.split(" ")
            size, weight, _, _, chars = rest[-5:]  # the family may hold spaces
            styles[sid] = {"size": float(size), "chars": int(chars)}
        elif part == "lines":
            i, page, _, x0, x1, style, *words = raw.split(" ")
            lines.append({"id": int(i), "page": int(page), "style": style.rstrip("*"), "text": " ".join(words)})
    body = max(styles, key=lambda s: styles[s]["chars"])
    first = [r for r in lines if r["page"] == 1] or lines
    name = max(first, key=lambda r: (styles[r["style"]]["size"], -r["id"]))
    short = [r for r in lines if r is not name and len(r["text"].split()) <= 6 and r["style"] != body]
    heads = [r for r in short if i18n.cv_section_kind(r["text"], KINDS)] or short[:3]
    return {
        "linkedin_export": False, "layout": {"columns": "one"}, "name": name["id"],
        "headings": [{"id": r["id"], "kind": i18n.cv_section_kind(r["text"], KINDS) or "other"} for r in heads],
        "entry_titles": []}


if __name__ == "__main__":
    sys.stdout.write(json.dumps(answer(sys.stdin.read())))
