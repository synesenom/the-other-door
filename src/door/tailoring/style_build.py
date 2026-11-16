"""Build a CV template from an uploaded CV (#149, epic #144): the builder core.

`build(pdf_path, ...)` reads the style of a CV PDF (`style_extract`), fetches the free fonts for it (`fonts`), writes its
icons as SVG files, and runs the stylist agent (`.claude/agents/stylist.md`) round by round: the agent writes a template
page, the builder checks it (`html_guard.template_problems`), prints a sample body in it with the pinned Chromium, reads
the print back and compares it with the original (`style_compare`) until the loop's rule says stop. The best round is
then stress-rendered with `profile/cv.md` made shorter, longer, French and with a photo (no model: `cv_body`), one more
round when that fails, and a second call writes the matching letter template. Only a build that passes is written, whole,
to `profile/style/`; a failed one writes nothing there.
"""

from __future__ import annotations

import re
from pathlib import Path

from door import i18n
from door.core import templates, workspace

STYLIST = "stylist"
_BLOCK = re.compile(r"^```(\w+)[ \t]*\n(.*?)\n```[ \t]*$", re.S | re.M)


def agent() -> dict:
    """The stylist agent's definition from `.claude/agents/stylist.md`: ``description``, ``model``, ``tools`` and its
    body as the ``prompt``."""
    text = (workspace.REPO_ROOT / ".claude" / "agents" / f"{STYLIST}.md").read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    entry: dict = {"prompt": body.strip(), "tools": []}
    key = None
    for line in front.splitlines():
        if line.lstrip().startswith("- ") and key == "tools":
            entry["tools"].append(line.strip()[2:].strip())
        elif ":" in line and not line.startswith(" "):
            key, value = (part.strip() for part in line.split(":", 1))
            if key in ("description", "model"):
                entry[key] = value
    return entry


def blocks(reply: str) -> dict[str, str]:
    """The fenced blocks of a stylist's reply by their name (```` ```template ````, ``body``, ``letter``): the first of
    each name. A block cut off before its closing fence is not one."""
    found: dict[str, str] = {}
    for name, text in _BLOCK.findall(reply):
        found.setdefault(name, text.strip())
    return found


# ---------- what the stylist is given: fonts, icons, manifest ----------

def font_face_css(plan: list[dict]) -> str:
    """One `@font-face` rule per file of each entry of `fonts.plan`, under the family the file belongs to, served as
    `/fonts/<file>`; an entry with no files (no free copy of its kind) has none."""
    rules = []
    for entry in plan:
        for f in entry["files"]:
            style = "italic" if f["italic"] else "normal"
            rules.append(f'@font-face {{ font-family: "{entry["resolved"]}"; font-weight: {f["weight"]}; font-style: {style}; '
                         f'src: url(/fonts/{f["name"]}) format("truetype"); }}')
    return "\n".join(rules)


def font_notes(plan: list[dict]) -> str:
    """What the stylist is told of each font the CV uses: which family stands for it and which faces are faked."""
    lines = []
    for entry in plan:
        if not entry["resolved"]:
            lines.append(f'- {entry["family"]}: no font for it; use a generic family ({entry["reason"]})')
            continue
        faked = "; ".join(f'weight {w}{" italic" if i else ""}' for w, i in entry["faked"])
        lines.append(f'- {entry["family"]} -> use "{entry["resolved"]}"' + (f" (no file for: {faked}; do not use)" if faked else ""))
    return "\n".join(lines)


def font_results(plan: list[dict]) -> list[dict]:
    """The result's font entries: the family the CV names, how it was resolved and why, what is faked."""
    return [{"family": e["family"], "source": e["source"], "reason": e["reason"], "faked": e["faked"],
             "resolved": e["resolved"]} for e in plan]


_URL = re.compile(r"(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?")
_PHONE = re.compile(r"[\d\s()+.\-]{7,}")
_YEAR = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")
_PATH = re.compile(r"[MLHVCSQTAZmlhvcsqtaz\d\s.,\-]+")
_VIEWBOX = re.compile(r"[\d\s.\-]+")
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_NOT_RECOGNISED = "no kind of contact detail or date recognised beside it"
_NEAR = 30  # characters of the text beside a dropped icon the result names


def icon_kind(near: str | None) -> str | None:
    """The kind of icon (one of `templates.ICON_KINDS`) that belongs beside `near`: a contact label in any supported
    language, else what the text looks like (an address, a number, a link, a date); None when it is none of them."""
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
        label = near[:_NEAR] if near else None
        if kind is None:
            dropped.append({"near": label, "reason": _NOT_RECOGNISED})
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


def side_kinds(style: dict) -> list[str]:
    """The section kinds of the side column: those whose headings in the original sit in its side band, in reading
    order (a heading no section kind names stays in the main column). Empty for a CV with no side band."""
    bands = [b for b in style["columns"]["bands"] if b["kind"] == "side"]
    kinds: list[str] = []
    for heading in style["headings"]:
        x = (heading["bbox"][0] + heading["bbox"][2]) / 2
        if any(b["x0"] - 2 <= x <= b["x1"] + 2 for b in bands):
            kind = i18n.cv_section_kind(heading["text"], templates.SECTION_KINDS)
            if kind and kind not in kinds:
                kinds.append(kind)
    return kinds


def manifest_data(style: dict, font_files: list[str], icon_files: dict[str, str]) -> dict:
    """The `template.json` of a build: its fonts and icons, the side column's kinds and the page limit (the original's
    page count within the 1 to 3 a template may name)."""
    data: dict = {"version": 1, "fonts": list(font_files), "icons": dict(icon_files),
                  "max_pages": min(3, max(1, style.get("page_count", 1)))}
    if side := side_kinds(style):
        data["columns"] = {"side": side}
    return data


# ---------- the stress variants ----------

_LONG_ROLE = "Senior Principal Engineering Manager for Distributed Data Platforms and Cross-Functional Delivery Programmes"
_FRENCH = ("Professionnel polyvalent, fort de huit années d'expérience dans des environnements exigeants, attaché à des plans "
           "clairs, à des étapes régulières et à une communication ouverte avec les équipes, les clients et les partenaires, "
           "capable de conduire des projets complexes de leur cadrage jusqu'à leur mise en production, en tenant les délais "
           "comme les budgets et en formant les collègues qui rejoignent l'équipe en cours de route.")


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


def stress_variants(cv_md: str) -> dict[str, dict]:
    """The CV in `cv_md` made into the texts a template must hold (no model): ``base``, ``photo`` (the same, printed with
    a photo), ``fewer`` (one entry a section), ``long_title`` (a very long job title), ``extra_section`` (one more
    section) and ``french`` (a long French paragraph first, `lang` "fr"). Each is ``{"md", "lang", "photo"}``."""
    lines = cv_md.rstrip("\n").splitlines()
    at = _section_at(lines)
    variants = {
        "base": lines, "photo": lines, "fewer": _fewer(lines), "long_title": _long_title(lines),
        "extra_section": [*lines, "", "## Publications", "", "- A study of nightly pipelines (2021)", "- Notes on small steady steps (2019)"],
        "french": [*lines[:at], "## Profil", "", _FRENCH, "", *lines[at:]],
    }
    return {name: {"md": cv_md if name in ("base", "photo") else "\n".join(v) + "\n", "lang": "fr" if name == "french" else "en",
                   "photo": name == "photo"} for name, v in variants.items()}
