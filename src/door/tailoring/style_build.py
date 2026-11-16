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

import json
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image
from pypdfium2 import PdfiumError

from door import i18n
from door.core import claude_cli, fonts, progress as progress_mod, templates, workspace
from door.tailoring import cv_body, font_measure, html_guard, html_pdf, pdf_render, readability, style_compare, style_extract

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


# ---------- the loop ----------

CAP = style_compare.CAP
TIMEOUT_S = 900  # one stylist call
_CV_FILE, _LETTER_FILE = templates.FILES["cv_template"], templates.FILES["cover_letter_template"]
_NAME = re.compile(r"^#\s+(.+)$", re.M)
_STRESS_PHOTO = {"location": "Copenhagen"}  # a country whose CVs may carry a photo: the photo variant places it
_SAMPLE_LETTER = """<header class="letter-header"><h1>Jane Doe</h1>
<p class="contact"><span class="phone">+45 1234 5678</span><span class="email"><a href="mailto:jane@example.com">jane@example.com</a></span><span class="location">Aarhus</span></p></header>
<div class="recipient"><p>Hiring team</p><p>Example Company</p><p>Copenhagen</p></div>
<p class="date"><<date>></p>
<p>Dear hiring team, I am writing to apply for the role you advertise. My eight years of work on data platforms taught me to plan in small steps and to keep the people who use a system informed of what changes and when.</p>
<p>At my last employer I led a team of four through a migration that ran without a single hour of downtime, and I cut a nightly job from three hours to twenty-five minutes. I would bring the same habits to your team.</p>
<p>Thank you for your time. I would be glad to tell you more in an interview.</p>
<div class="closing"><p class="signoff">Kind regards,</p><p>Jane Doe</p></div>"""
_SAMPLE_DATE = "1 January 2026"


class _Stop(Exception):
    """The build cannot go on: what is said is a problem of the result."""


def _task(files: str, feedback: str | None, reply: str) -> str:
    return f"{files}\n\n{feedback + chr(10) + chr(10) if feedback else ''}{reply}"


def _ask(run, task: str, work: Path, profile_dir: Path | None) -> str:
    """One stylist call (a `claude -p` session in `work`, read-only: the agent's own tools, `--restricted`) and its
    reply text."""
    definition = agent()
    entry = {"description": definition["description"], "prompt": definition["prompt"], "tools": definition["tools"],
             "model": definition["model"]}
    args = ["--restricted", "--agents", json.dumps({STYLIST: entry}), "--agent", STYLIST,
            "--allowedTools", ",".join(definition["tools"]), "--no-session-persistence", *claude_cli.STREAM_ARGS]
    envelope = run(args, feature="style", input=task, timeout_s=TIMEOUT_S, profile_dir=profile_dir, cwd=work)
    return str(claude_cli.envelope_result(envelope))


def _shipped_plan(style_fonts: list[dict], font_dir: Path) -> list[dict]:
    """What stands in for the fonts when none could be fetched: the TrueType fonts the code ships
    (`profile.example/fonts/`: Figtree for a sans, Young Serif for a serif), copied into `font_dir`."""
    shipped = workspace.PROFILE_EXAMPLE_DIR / "fonts"
    faces = {"Regular": (400, False), "Italic": (400, True), "SemiBold": (600, False), "SemiBoldItalic": (600, True),
             "Bold": (700, False), "BoldItalic": (700, True)}
    by_family: dict[str, list[dict]] = {}
    for path in sorted(shipped.glob("*.ttf")):
        stem, _, face = path.stem.partition("-")
        if face in faces:
            family = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)
            by_family.setdefault(family, []).append({"name": path.name, "weight": faces[face][0], "italic": faces[face][1]})
    font_dir.mkdir(parents=True, exist_ok=True)
    plan: list[dict] = []
    for original in (f for f in style_fonts if f.get("family") and not f.get("icon")):
        if any(e["family"] == original["family"] for e in plan):
            continue
        resolved = "Young Serif" if original.get("serif") and "Young Serif" in by_family else next(iter(by_family))
        files = by_family[resolved]
        uses = sorted({(f["weight"], f["italic"]) for f in style_fonts if f.get("family") == original["family"]})
        faked = [[w, i] for w, i in uses if not any(f["italic"] == i and abs(f["weight"] - w) <= 100 for f in files)]
        for f in files:
            shutil.copyfile(shipped / f["name"], font_dir / f["name"])
        for licence in shipped.glob(f"{resolved.replace(' ', '')}-OFL.txt"):
            shutil.copyfile(licence, font_dir / licence.name)
        plan.append({"family": original["family"], "source": "shipped", "resolved": resolved, "faked": faked,
                     "reason": f"{original['family']}: its free copy could not be fetched; the shipped {resolved} stands in",
                     "files": files, "licence": None, "alternatives": [], "uses": [list(u) for u in uses]})
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


def _font_names(plan: list[dict]) -> list[str]:
    return list(dict.fromkeys(f["name"] for e in plan for f in e["files"]))


def _agent_style(style: dict) -> dict:
    """`style` as the stylist reads and `profile/style/style.json` keeps it: the icons' traced paths are in the SVG files."""
    return {**style, "icons": [{k: v for k, v in icon.items() if k not in ("d", "viewBox", "fill_rule")} for icon in style["icons"]]}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _print(template: str, body: str, lang: str, folder: Path, name: str, work: Path) -> Path:
    """`body` placed in `template` and printed to `folder/<name>.pdf` with the pinned Chromium, the fonts and icons the
    manifest next to the template in `work` names served.

    Raises:
        html_pdf.PrintError: the print failed.
        ValueError: the manifest names a file that is not there.
    """
    from door.commands import compile as compile_cmd

    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / f"{name}.pdf"
    html_pdf.print_html(folder, compile_cmd._wrap(template, body, lang), pdf, assets=templates.assets(work / _CV_FILE))
    return pdf


class _Session:
    """One build's state: the original's style and page images, the folder it works in, the manifest and the model seam."""

    def __init__(self, style: dict, pdf: Path, work: Path, manifest: templates.Manifest, run, profile_dir: Path | None) -> None:
        self.style, self.work, self.manifest, self.run, self.profile_dir = style, work, manifest, run, profile_dir
        self.images = style_compare.page_images(pdf, work)  # also leaves original_page_N.png beside the files it reads
        self.rounds = 0

    def ask(self, task: str, *, count: bool = True) -> str:
        """One stylist call; the letter's (`count` False) are not rounds of the CV template."""
        self.rounds += count
        return _ask(self.run, task, self.work, self.profile_dir)

    def sample(self, template: str, body: str) -> tuple[dict, float, float]:
        """The sample `body` printed in `template`, read back and compared with the original: the diffs, the blurred
        score and the worst offset in points.

        Raises:
            _Stop: the print has no text to read back.
        """
        from door.commands import compile as compile_cmd

        placed = compile_cmd._place_columns(compile_cmd._with_photo(body, template, self.work, {}, {})[0], self.manifest.columns, "en")
        pdf = _print(template, placed, "en", self.work, "render", self.work)
        render = style_extract.extract(pdf)
        if not render["verdict"]["copyable"]:
            raise _Stop("the print has no text to read back")
        diffs = style_compare.match(self.style, render)
        score = style_compare.pages_score(self.images, style_compare.page_images(pdf, self.work))
        return diffs, score, style_compare.worst_offset_pt(diffs)

    def guard(self, template: str, kind: str = "cv") -> list[str]:
        return html_guard.template_problems(template, self.manifest, kind)


_REPLY_FIRST = ("Reply with one line on what you see (layout, colours), then the ```template block and the ```body block, "
                "nothing after them.")
_REPLY_NEXT = "Reply with one line on what you changed and the whole new template in one ```template block, nothing after it."
_REPLY_LETTER = "Reply with one line and the whole letter template in one ```letter block, nothing after it."
MAX_PAGES = 3  # the most a template may name (`templates.Manifest.max_pages`)
_LIMIT = 12  # problems one message to the stylist names


def _files_text(s: _Session, notes: str, icon_files: dict[str, str]) -> str:
    pages = len(s.images)
    icons = ", ".join(f"{kind} -> /icons/{name}" for kind, name in icon_files.items()) or "none"
    columns = ", ".join(s.manifest.columns.side) if s.manifest.columns else "none: one column, no .main or .side"
    return (
        f"Rebuild the look of the CV in this folder as a template. Files here: original_page_1.png to original_page_{pages}.png "
        f"(the CV; look at them with the Read tool), style.json, text.txt, fonts.css, template.json. "
        f"Your last template, when there is one, is cv.template.html and the print of the last one that printed is "
        f"render_page_1.png and on (render_page_N.png for the other pages).\n"
        f"Fonts (use only these; the @font-face rules are in fonts.css):\n{notes or '- none: use generic families'}\n"
        f"Icons you may draw, by kind: {icons}.\nSide column sections: {columns}. Page limit: {s.manifest.max_pages}."
    )


def _list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items[:_LIMIT])


def _draft(s: _Session, files: str, cap: int) -> tuple[str | None, str | None, list[float], str | None]:
    """The comparison rounds: the stylist writes a template (and, in the first round that has one, the sample body),
    the guard reads it, it is printed and compared. Returns the best template (None when none ever printed), the
    sample body, the blurred scores of the rounds that printed and the last feedback."""
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
            else:
                body = sample
                _write(s.work / "sample_body.html", body)
            if body is None:
                continue
        _write(s.work / _CV_FILE, template)
        if problems := s.guard(template):
            feedback = "The guard refused your template, so it was not printed. Fix these:\n" + _list(problems)
            continue
        try:
            diffs, score, worst = s.sample(template, body)
        except (html_pdf.PrintError, _Stop, ValueError) as exc:
            feedback = f"Printing your template failed: {exc}"
            continue
        kept.append(template)
        scores.append(score)
        feedback = style_compare.feedback(diffs, score)
        if style_compare.should_stop(scores, worst, cap):
            break
    return (kept[style_compare.best_round(scores)] if scores else None), body, scores, feedback


def _stress(s: _Session, template: str, cv_md: str) -> list[str]:
    """The failures of the template printed with the variants of `cv_md` (`stress_variants`), through the same placing
    and photo steps `compile` takes, no model: a print that fails, text lost off the page (`readability`'s checks,
    a last page nearly empty excepted), a photo not placed, too many pages (the compact variant must fit the
    manifest's `max_pages`, the rest `MAX_PAGES`)."""
    from door.commands import compile as compile_cmd

    name = (_NAME.search(cv_md) or [None, None])[1]
    picture = s.work / "stress-photo.jpg"
    Image.new("RGB", (350, 450), "tan").save(picture, "JPEG")
    failures: list[str] = []
    for variant, v in stress_variants(cv_md).items():
        progress_mod.report(f"stress render: {variant}", stage="style")
        folder = s.work / "stress" / variant
        folder.mkdir(parents=True, exist_ok=True)
        placed = compile_cmd._place_columns(cv_body.body(v["md"], v["lang"]), s.manifest.columns, v["lang"])
        config = {**_STRESS_PHOTO, "photo": str(picture)} if v["photo"] else {}
        built, photo = compile_cmd._with_photo(placed, template, folder, _STRESS_PHOTO, config)
        if v["photo"] and photo is None:
            failures.append(f"{variant}: the photo was not placed")
            continue
        try:
            pdf = _print(template, built, v["lang"], folder, "cv", s.work)
            found = [f"{p['kind']}: {p['detail']}" for p in readability.check_pdf(pdf, built, name, cv=True) if p["kind"] != "sparse"]
            pages = pdf_render.get_page_count(pdf)
        except (html_pdf.PrintError, ValueError) as exc:
            failures.append(f"{variant}: printing failed: {exc}")
            continue
        limit = s.manifest.max_pages if variant == "fewer" else MAX_PAGES
        if pages > limit:
            found.append(f"{pages} pages, at most {limit}")
        failures += [f"{variant}: {f}" for f in found]
    return failures


def _letter(s: _Session, template: str) -> tuple[str | None, list[str]]:
    """The letter template for the final CV `template`: a second stylist call given the CV template and the default
    letter template, its page guarded, printed with a sample letter (readable, one page); one more call when it fails."""
    shutil.copyfile(workspace.PROFILE_EXAMPLE_DIR / _LETTER_FILE, s.work / f"default.{_LETTER_FILE}")
    _write(s.work / _CV_FILE, template)
    files = (f"Write the cover letter template that matches the CV template. Files here: cv.template.html (the CV template "
             f"you wrote: its fonts, colours, margins and header), default.{_LETTER_FILE} (the default letter template: its "
             f"building blocks and structure), template.json, fonts.css. Read the first two with the Read tool.")
    body = _SAMPLE_LETTER.replace("<<date>>", _SAMPLE_DATE)
    feedback, problems = None, []
    for _ in range(2):
        progress_mod.report("building the letter template", stage="style")
        candidate = blocks(s.ask(_task(files, feedback, _REPLY_LETTER), count=False)).get("letter")
        if candidate is None:
            problems = ["no ```letter block: the whole page in one fenced block named letter"]
        elif not (problems := s.guard(candidate, "letter")):
            try:
                pdf = _print(candidate, body, "en", s.work / "letter", "letter", s.work)
                problems = [f"{p['kind']}: {p['detail']}" for p in readability.check_pdf(pdf, body, None)]
                if (pages := pdf_render.get_page_count(pdf)) != 1:
                    problems.append(f"the sample letter prints on {pages} pages, it must be one")
            except (html_pdf.PrintError, ValueError) as exc:
                problems = [f"printing failed: {exc}"]
        if not problems:
            return candidate, []
        feedback = "Problems with your letter template. Fix these:\n" + _list(problems)
    return None, [f"letter template: {p}" for p in problems]


def _publish(profile_dir: Path, work: Path, pdf: Path, style: dict, cv: str, letter: str) -> None:
    """Write `profile_dir/style/` whole: staged beside it and moved in, an earlier one set aside and put back when the
    move fails. No ledger lock (nothing else writes there).

    Raises:
        OSError: the files could not be written or moved.
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    dest, old = profile_dir / "style", profile_dir / ".style.old"
    staging = Path(tempfile.mkdtemp(prefix=".style.", suffix=".part", dir=profile_dir))
    try:
        _write(staging / _CV_FILE, cv)
        _write(staging / _LETTER_FILE, letter)
        _write(staging / "style.json", json.dumps(_agent_style(style), ensure_ascii=False, indent=1))
        shutil.copyfile(work / templates.MANIFEST_FILE, staging / templates.MANIFEST_FILE)
        shutil.copyfile(pdf, staging / "source.pdf")
        for folder in ("fonts", "icons"):
            if (work / folder).is_dir():
                shutil.copytree(work / folder, staging / folder, ignore=shutil.ignore_patterns("*.part"))
        shutil.rmtree(old, ignore_errors=True)
        if dest.exists():
            dest.rename(old)
        try:
            staging.rename(dest)
        except OSError:
            if old.exists() and not dest.exists():
                old.rename(dest)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)


def _stress_cv(profile_dir: Path) -> str:
    """The CV the stress renders are made from: the profile's, else the example one."""
    for folder in (profile_dir, workspace.PROFILE_EXAMPLE_DIR):
        try:
            return (folder / "cv.md").read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


def _build(pdf_path: Path, work: Path, profile_dir: Path, run, fonts_fetch, cap: int, result: dict) -> None:
    refused = style_extract.not_pdf(pdf_path)
    if refused:
        raise _Stop(refused["detail"])
    style = style_extract.extract(pdf_path)
    if not style["verdict"]["copyable"]:
        raise _Stop(style["verdict"]["detail"] or f"no style to copy ({style['verdict']['reason']})")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    pdf = work / "original.pdf"
    shutil.copyfile(pdf_path, pdf)
    progress_mod.report("reading the CV's style", stage="style")
    _write(work / "text.txt", "\n".join(pdf_render.page_texts(pdf)))
    _write(work / "style.json", json.dumps(_agent_style(style), ensure_ascii=False, indent=1))
    progress_mod.report("fetching the fonts", stage="style")
    plan, result["font_error"] = _get_fonts(pdf, style, work / "fonts", fonts_fetch)
    result["fonts"] = font_results(plan)
    _write(work / "fonts.css", font_face_css(plan))
    icon_files, result["dropped_icons"] = write_icons(style["icons"], work / "icons")
    data = manifest_data(style, _font_names(plan), icon_files)
    _write(work / templates.MANIFEST_FILE, json.dumps(data, indent=1))
    s = _Session(style, pdf, work, templates.Manifest(**data), run, profile_dir)
    try:
        _rounds(s, plan, icon_files, pdf, style, profile_dir, cap, result)
    finally:
        result["rounds"] = s.rounds


def _rounds(s: _Session, plan: list[dict], icon_files: dict[str, str], pdf: Path, style: dict, profile_dir: Path, cap: int,
            result: dict) -> None:
    files = _files_text(s, font_notes(plan), icon_files)
    template, body, scores, feedback = _draft(s, files, cap)
    result["scores"], result["score"] = scores, max(scores, default=None)
    if template is None:
        raise _Stop(f"no template of the stylist's passed the guard and printed in {s.rounds} rounds: {feedback}")
    cv_md = _stress_cv(profile_dir)
    if failures := _stress(s, template, cv_md):
        progress_mod.report("one more round for the stress renders", stage="style")
        _write(s.work / _CV_FILE, template)
        reply = blocks(s.ask(_task(files, "Printed with other texts, your template fails:\n" + _list(failures), _REPLY_NEXT)))
        template = reply.get("template") or ""
        if problems := (s.guard(template) if template else ["no ```template block in the reply"]):
            raise _Stop("the stress renders failed and the extra round's template was refused: " + "; ".join(problems[:3]))
        if failures := _stress(s, template, cv_md):
            raise _Stop("the stress renders still fail after the extra round: " + "; ".join(failures[:_LIMIT]))
        try:
            result["score"] = s.sample(template, body)[1]
            result["scores"] = [*scores, result["score"]]
        except (html_pdf.PrintError, _Stop, ValueError):
            pass
    letter, problems = _letter(s, template)
    if letter is None:
        raise _Stop("; ".join(problems))
    _publish(profile_dir, s.work, pdf, style, template, letter)
    result["state"] = "ready"


def build(pdf_path, *, work_dir, profile_dir=None, run=None, fonts_fetch=None, progress=None, cap: int = CAP) -> dict:
    """Build a CV template from the CV PDF at `pdf_path` (see the module's docstring) and write it to
    `profile_dir/style/` (default the profile) when it is ready; a failed build writes nothing there.

    `work_dir` is the build's own folder (emptied first): the files the stylist reads, its drafts and the stress
    prints. `run` is the model call (default `claude_cli.run`: tests give a stand-in), `fonts_fetch(plan, dest)` the font
    download (default `fonts.fetch`), `progress` a `progress.Reporter`; `cap` bounds the comparison rounds.

    Returns ``{"state": "ready" | "failed", "rounds", "score", "fonts": [{family, source, reason, faked, resolved}],
    "dropped_icons": [{near, reason}], "font_error", "scores", "problems": [str]}``: ``font_error`` is why the fonts
    were not fetched (the shipped fonts stood in), ``problems`` why it failed. A model, print or file error is a
    failed result, not an exception.
    """
    result: dict = {"state": "failed", "rounds": 0, "score": None, "fonts": [], "dropped_icons": [], "font_error": None,
                    "scores": [], "problems": []}
    with progress_mod.activate(progress):
        try:
            _build(Path(pdf_path), Path(work_dir), Path(profile_dir) if profile_dir else workspace.PROFILE_DIR,
                   run or claude_cli.run, fonts_fetch, cap, result)
        except _Stop as exc:
            result["problems"] = [str(exc)]
        except (claude_cli.ClaudeError, html_pdf.PrintError, OSError, ValueError, PdfiumError) as exc:
            result["problems"] = [f"{type(exc).__name__}: {exc}"]
    return result
