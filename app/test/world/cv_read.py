"""What the stand-in `claude` answers the call that reads a CV (#430, `door.core.cv_read`): the CV comes on stdin as
`CV:\n<<<\n...\n>>>\n` and the answer is a plain reading of it, as `tests/cv_read_utils.plain` makes for the unit tests:
the name is the `# ` line, the email the first address, the contact details the `**Label:** value` parts of the header
(their kind by the shape of the value), the sections the `## ` lines (their kind from the world's table, `reading.kinds`,
else `other`), the skills the items of a skills section, the entries the `### ` lines with the years of their first date
range, the languages the world's (`reading.languages`, as the CV writes them). Every value is a stretch of the CV, so
`cv_read.check` holds it. Run as `python cv_read.py` with the input on stdin and the world's `reading` block as the first
argument (JSON); stdlib only, no `door` import (it is the double of a model, never a rule of the app)."""

import json
import re
import sys

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RANGE = re.compile(r"\b((?:19|20)\d\d)\s*[-–—]\s*((?:19|20)\d\d|[^\W\d_]+)", re.UNICODE)


def split_skills(line: str) -> list[str]:
    """The items of a skills line, split on commas and semicolons outside brackets."""
    items, depth, cur = [], 0, ""
    for ch in line.lstrip("-*• ").strip():
        depth += ch == "("
        depth -= ch == ")" and depth > 0
        if ch in ",;" and depth == 0:
            items.append(cur.strip(" ."))
            cur = ""
        else:
            cur += ch
    items.append(cur.strip(" ."))
    return [i for i in items if i]


def contact_kind(value: str) -> str:
    if "@" in value:
        return "email"
    if "linkedin." in value:
        return "linkedin"
    if "github." in value:
        return "github"
    if re.fullmatch(r"[+\d][\d\s().-]{5,}", value):
        return "phone"
    return "web" if "." in value and " " not in value else "location"


def read(md: str, reading: dict) -> dict:
    kinds = reading.get("kinds", {})
    out = {"name": None, "email": None, "city": None, "country": None, "languages": [], "sections": [], "contacts": [],
           "skills": [], "levels": [], "entries": []}
    kind = None
    for line in md.split("\n"):
        if line.startswith("# ") and out["name"] is None:
            out["name"] = line[2:].strip()
        elif line.startswith("## "):
            heading = re.sub(r"\s*<!--.*?-->\s*$", "", line[3:]).strip()
            kind = kinds.get(heading, "other")
            out["sections"].append({"heading": heading, "kind": kind})
        elif line.startswith("### "):
            heading = line[4:].strip()
            m = RANGE.search(heading)
            out["entries"].append({
                "heading": heading, "role": None, "org": None, "dates": m.group(0) if m else None, "place": None,
                "start_year": int(m.group(1)) if m else None,
                "end_year": int(m.group(2)) if m and m.group(2).isdigit() else None})
        elif kind is None and line.startswith("**"):
            for part in line.split("|"):
                m = re.match(r"\s*\*\*([^*]+?)\s*:\*\*\s*(.+?)\s*$", part)
                if m:
                    ckind = contact_kind(m.group(2))
                    out["contacts"].append({"kind": ckind, "label": m.group(1), "value": m.group(2)})
                    if ckind == "location" and out["city"] is None:
                        out["city"] = m.group(2)
        elif kind == "skills" and line.strip():
            for item in split_skills(line):
                if item not in out["skills"]:
                    out["skills"].append(item)
    out["email"] = next((m.group(0) for line in md.split("\n") if not line.startswith(">") and (m := EMAIL.search(line))), None)
    out["languages"] = [x for x in reading.get("languages", []) if x["language"] in md]
    return out


if __name__ == "__main__":
    text = sys.stdin.read()
    body = text.split("<<<\n", 1)[-1].rsplit("\n>>>", 1)[0]
    print(json.dumps(read(body, json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}), ensure_ascii=False))
