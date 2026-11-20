"""What the stand-in `claude` answers the call that reads a CV's structure (#343): the CV's text lines come on stdin as
`door.style.style_structure.rows` writes them, and the answer is a plain rule's, as in `tests/style_structure_utils`:
the name is the largest text of the first page, the headings are the lines of at most six words set unlike the body
text that a section kind names, one column, not LinkedIn; the contact lines are those that look like an email, a link,
a phone number or a period of years the footers the lines that are a page number or `Page N of M`. Run as `python structure.py` with the input on stdin; needs
`door` importable."""

import json
import re
import sys

# The stand-in's own few titles of the sections a column can hold (a test world's, not a language table).
TITLES = {
    "skills": ("skills", "kompetencer", "compétences"),
    "education": ("education", "uddannelse", "formation"),
    "certifications": ("certifications", "certificeringer"),
    "languages": ("languages", "sprog", "langues"),
    "interests": ("interests", "interesser", "loisirs", "centres d'intérêt", "érdeklődési kör", "intressen"),
}
_FOOTER = re.compile(r"\d+|page \d+ of \d+", re.I)
_PHONE = re.compile(r"[\d\s()+.\-]{7,}")
_PERIOD = re.compile(r"(19|20)\d\d\s*[-\u2013]\s*((19|20)\d\d|\w+)")


def section_kind(title: str) -> str | None:
    key = " ".join(title.split()).casefold().strip(" :")
    return next((kind for kind, titles in TITLES.items() if key in titles), None)


def contact_kind(text: str) -> str | None:
    """The kind of contact detail a line looks like, for a test's stand-in only: no language."""
    text = text.strip()
    low = text.lower()
    if "@" in text:
        return "email"
    if "linkedin." in low:
        return "linkedin"
    if "github." in low:
        return "github"
    if _PERIOD.fullmatch(text):
        return "date"
    if _PHONE.fullmatch(text) and sum(c.isdigit() for c in text) >= 7:
        return "phone"
    if re.fullmatch(r"(https?://)?(www\.)?[\w-]+(\.[\w-]+)+(/\S*)?", text):
        return "web"
    return None


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
    heads = [r for r in short if section_kind(r["text"])] or short[:3]
    return {
        "linkedin_export": False, "layout": {"columns": "one"}, "name": name["id"],
        "headings": [{"id": r["id"], "kind": section_kind(r["text"]) or "other"} for r in heads],
        "entry_titles": [],
        "contacts": [{"id": r["id"], "kind": kind} for r in lines if (kind := contact_kind(r["text"]))],
        "footers": [r["id"] for r in lines if _FOOTER.fullmatch(r["text"].strip())]}


if __name__ == "__main__":
    sys.stdout.write(json.dumps(answer(sys.stdin.read())))
