"""Previews of a CV and a letter in a style (#207, epic #144): the user's own `cv.md` and one sample letter, printed in
the rebuilt template (`profile/style.next/`, the candidate, else `profile/style/`: "like") and in the default one ("default"), with no model and nothing copied
from the uploaded PDF.

`show(home, profile_dir, config)` makes what is stale and returns the page images. A set lives in
`HOME/.style/preview/<default|like>/` (`cv.pdf`, `letter.pdf`, `cv_page_N.png`, `letter_page_N.png`, `meta.json`) and is
made again only when its key, in `meta.json`, differs: the sha256 of the CV, the photo, the style's templates and
manifest, the fonts and icons it serves, the CV's language and the program's version. It is written in a staging
folder of the call's own and moved in whole, so calls at once do not meet. A set that cannot be printed (no Chromium)
is left out.

The CV is `cv_body.body(cv.md, reading)` (`cv_read.read`: one cached model call, #431) with the photo as a prepare places it (the profile's rule, `page.profile_photo`);
the letter is `sample_letter`, in English. `page.print_page` is the one place a body is placed in a template and printed,
shared with the style build's own renders.
"""

from __future__ import annotations

import hashlib
import html
import json
import shutil
from pathlib import Path

import pypdfium2

from door import i18n, version
from door.core import cv_read, templates, utils, workspace
from door.style import cv_body
from door.render import html_pdf, pdf_render
from door.render import page as page_mod

_SAMPLE_DATE = "1 January 2026"
_LETTER = """{header}
<div class="recipient"><p>Hiring team</p><p>Example Company</p><p>Copenhagen</p></div>
<p class="date"><<date>></p>
<p>Dear hiring team, this is a sample letter that shows how your cover letters will look in this style. It holds a few short paragraphs, as a real letter does.</p>
<p>A second paragraph is here to show the spacing between paragraphs and how the lines break across the page. The words are filler and say nothing about you.</p>
<p>Thank you for your time. Your own letters are written for each job you prepare.</p>
<div class="closing"><p class="signoff">Kind regards,</p><p>{name}</p></div>"""


def sample_letter(cv_md: str, reading: dict) -> str:
    """The sample letter, its date filled: the header and signature are the name and contact details in `cv_md` (none
    for a CV with no name). The paragraphs are fixed English that claim nothing about anyone."""
    header, name = cv_body.letter_header(cv_md, reading)
    return _LETTER.format(header=header, name=html.escape(name, quote=False)).replace("<<date>>", _SAMPLE_DATE)


def cv_text(profile_dir: Path, config: dict) -> str:
    """The CV the previews and the style build's stress renders are made from: the one `config`'s `cv_content` names
    (the profile's `cv.md` by default), else the example CV."""
    path = workspace.cv_path(config, profile_dir)
    return (path if path.is_file() else workspace.PROFILE_EXAMPLE_DIR / "cv.md").read_text(encoding="utf-8")


def _language(cv_md: str) -> str:
    return i18n.language_code(i18n.detect_language(cv_md) or "") or "en"


def _sha(*parts: bytes) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(hashlib.sha256(part).digest())
    return digest.hexdigest()


def _bytes(path: Path | None) -> bytes:
    try:
        return path.read_bytes() if path else b""
    except OSError:
        return b""


def _paths(style: str, profile_dir: Path) -> tuple[Path, Path]:
    """The CV template and the letter template of `style`."""
    if style == "like":
        folder = templates.liked(profile_dir)
        return folder / templates.FILES["cv_template"], folder / templates.FILES["cover_letter_template"]
    return (templates.resolve("cv_template", {}, profile_dir), templates.resolve("cover_letter_template", {}, profile_dir))


def _key(cv_md: str, lang: str, photo: Path | None, cv_template: Path, letter_template: Path) -> str:
    """What a set is made from. Raises ValueError for a manifest that cannot be used."""
    served = [f for files in templates.assets(cv_template).values() for f in files]
    manifests = (cv_template.parent / templates.MANIFEST_FILE, letter_template.parent / templates.MANIFEST_FILE)
    return _sha(version.VERSION.encode(), cv_md.encode(), lang.encode(), _bytes(photo), _bytes(cv_template), _bytes(letter_template),
                *(_bytes(m) for m in manifests), *(_bytes(f) for f in served))


def _fresh(folder: Path, key: str) -> list[str] | None:
    """The image names of the set in `folder` when it is whole and made from `key`, else None."""
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        images = meta["images"]
    except (OSError, ValueError, KeyError):
        return None
    if meta.get("key") != key or not images or not all((folder / name).is_file() for name in images):
        return None
    return images


def _make(stage: Path, cv_md: str, reading: dict, lang: str, photo: Path | None, cv_template: Path, letter_template: Path) -> list[str]:
    """Print the CV and the letter into `stage` and the pages of both to images; the file names of the images."""
    manifest = templates.manifest(cv_template) or templates.Manifest()
    pdf, _, picture = page_mod.print_page(
        cv_body.body(cv_md, reading), cv_template.read_text(encoding="utf-8"), cv_template, lang, stage, "cv",
        manifest=manifest, photo=photo)
    images = [p.name for p in pdf_render.render_pdf_pages(pdf, stage)]
    # the letter is printed with the CV template's fonts and icons, as `style_build` checks it
    letter = page_mod.print_page(
        sample_letter(cv_md, reading), letter_template.read_text(encoding="utf-8"), cv_template, "en", stage, "letter")
    images += [p.name for p in pdf_render.render_pdf_pages(letter[0], stage)]
    if picture:
        (stage / picture).unlink(missing_ok=True)
    return images


def _set(root: Path, folder: Path, key: str, cv_md: str, reading: dict, lang: str, photo: Path | None, cv_template: Path,
         letter_template: Path) -> list[str] | None:
    """Make the set in a staging folder of this call and move it in as `folder`; its image names, None when it could
    not be printed. A call that meets another's set already moved in (the same key, the same files) uses that."""
    try:
        with utils.staging(root, f".{folder.name}.") as stage:
            images = _make(stage, cv_md, reading, lang, photo, cv_template, letter_template)
            (stage / "meta.json").write_text(json.dumps({"key": key, "images": images}), encoding="utf-8")
            shutil.rmtree(folder, ignore_errors=True)
            try:
                stage.rename(folder)
            except OSError:
                return _fresh(folder, key)
            return images
    except (html_pdf.PrintError, ValueError, OSError, pypdfium2.PdfiumError):
        return None


def show(home: Path, profile_dir: Path, config: dict) -> dict:
    """The previews, made again where stale: ``{"styles": {"default": {"cv": [png], "letter": [png], "version": key,
    "two_column": bool}, "like": {...}}}`` (absolute paths, page order; `version` changes with the images, for a cache
    buster). `like` is there only when a style is built (`profile/style.next/` or `profile/style/` has `cv.template.html`); a set that could not be printed is left
    out. Nothing is raised for a print that fails. A CV that cannot be read (`cv_read.CvReadError`) is
    ``{"styles": {}, "warning": words}`` (not an `error`: the caller keeps the rest of its answer) and nothing is written."""
    root = Path(home) / ".style" / "preview"
    cv_md = cv_text(Path(profile_dir), config)
    try:
        reading = cv_read.read(cv_md)
    except cv_read.CvReadError as exc:
        return {"styles": {}, "warning": str(exc)}
    lang = _language(cv_md)
    photo = page_mod.profile_photo(config, {})  # no posting: the profile's own country decides
    out: dict[str, dict] = {}
    for style in ("default", "like"):
        folder = root / style
        cv_template, letter_template = _paths(style, Path(profile_dir))
        if style == "like" and not cv_template.is_file():
            shutil.rmtree(folder, ignore_errors=True)
            continue
        try:
            key = _key(cv_md, lang, photo, cv_template, letter_template)
            two_column = bool((templates.manifest(cv_template) or templates.Manifest()).columns)
        except (ValueError, OSError):
            continue
        images = _fresh(folder, key) or _set(root, folder, key, cv_md, reading, lang, photo, cv_template, letter_template)
        if images:
            out[style] = {kind: [str(folder / n) for n in images if n.startswith(f"{kind}_page_")] for kind in ("cv", "letter")}
            out[style].update(version=key, two_column=two_column)
    return {"styles": out}
