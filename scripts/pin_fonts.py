#!/usr/bin/env python3
"""Write `src/door/style/fonts_pin.json`: the free font families The other door can fetch for a CV (#199).

A developer tool, not run in CI, and the only place that decides which families are pinned (`FAMILIES`: add one
there). For each family it finds the newest google/fonts commit whose folder still holds static TrueType files and
a licence, downloads them, hashes them (sha256) and measures the regular face with Pillow (x-height,
the width of an `l`, and the advance of 63 characters, in em fractions of 1000) so that `door.style.fonts.plan` can
pick the nearest family to a CV's own font without a font file at hand. Static only: variable files print as
nameless Type 3 text, and making statics would need a modified font. A family that was never static, or whose
folder has no licence file, is left out and named. Needs `gh` (signed in) and the network; Pillow is a dependency.

    poetry run python scripts/pin_fonts.py [--cache DIR] [--only "Lato" ... | --tables-only]

No option pins every family afresh at google/fonts' current commits. `--only` pins the named families and keeps every
other entry as it is; `--tables-only` rewrites just `aliases` and `lookalikes`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from door.style import fonts  # noqa: E402
from door.style import style_extract  # noqa: E402

OUT = ROOT / "src" / "door" / "style" / "fonts_pin.json"
REPO = "google/fonts"
RAW = "https://raw.githubusercontent.com/google/fonts/{commit}/{dir}/{name}"
LICENCES = ("OFL.txt", "LICENSE.txt")

# (family, class, folders to try in order). A family is under `ofl/<name without spaces>` and, for an older static
# copy, `apache/<same>`; the Croscore ones (Arimo, Tinos, Cousine) and Roboto Slab sit under apache/ only.
_SANS = [
    "Carlito", "Lato", "Open Sans", "Roboto", "Montserrat", "Source Sans Pro", "Raleway", "Poppins", "Nunito",
    "Nunito Sans", "PT Sans", "Work Sans", "DM Sans", "Fira Sans", "Karla", "Rubik", "Jost", "Mulish", "Muli",
    "Quicksand", "IBM Plex Sans", "Libre Franklin", "Questrial", "Cabin", "Inter", "Figtree", "Barlow", "Hind",
    "Titillium Web", "Josefin Sans", "Archivo", "Oxygen", "Asap", "Catamaran",
]
_SERIF = [
    "Caladea", "Young Serif", "Lora", "EB Garamond", "Playfair Display", "Merriweather", "PT Serif", "Crimson Text",
    "Crimson Pro", "Source Serif Pro", "Libre Baskerville", "Cormorant Garamond", "Spectral", "IBM Plex Serif",
    "Gelasio", "Libre Caslon Text", "Bitter", "Alegreya", "Cardo", "Arvo", "Lusitana", "Marcellus", "Noto Serif",
    "Vollkorn", "Domine", "Zilla Slab", "Cormorant", "Neuton", "Old Standard TT", "Libre Bodoni", "Gentium Book Basic",
]
_FIXED = [
    "Roboto Mono", "Source Code Pro", "IBM Plex Mono", "Fira Mono", "Inconsolata", "Space Mono", "PT Mono",
    "Courier Prime", "JetBrains Mono", "Anonymous Pro", "Oxygen Mono",
]
_APACHE_ONLY = [("Arimo", "sans"), ("Tinos", "serif"), ("Cousine", "fixed"), ("Roboto Slab", "serif")]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


FAMILIES: list[tuple[str, str, tuple[str, ...]]] = (
    [(n, c, (f"ofl/{_slug(n)}", f"apache/{_slug(n)}"))
     for c, names in (("sans", _SANS), ("serif", _SERIF), ("fixed", _FIXED)) for n in names]
    + [(n, c, (f"apache/{_slug(n)}",)) for n, c in _APACHE_ONLY]
)

# Each name a CV may give a font that a pinned family replaces at the same widths: a metric-compatible clone (Carlito,
# Arimo, ...) or the same family under a newer name.
ALIASES = {
    "Carlito": ["calibri"],
    "Caladea": ["cambria"],
    "Arimo": ["arial", "arialmt", "helvetica", "liberationsans", "nimbussansl", "nimbussans", "texgyreheros", "freesans"],
    "Tinos": ["times", "timesnewroman", "timesnewromanps", "timesnewromanpsmt", "liberationserif", "nimbusromno9l",
              "nimbusroman", "texgyretermes", "freeserif"],
    "Cousine": ["courier", "couriernew", "couriernewps", "liberationmono", "nimbusmonol", "nimbusmono", "texgyrecursor"],
    "Gelasio": ["georgia"],
    "Source Sans Pro": ["sourcesans3", "sourcesans"],
    "Source Serif Pro": ["sourceserif4"],
    "Muli": ["mulish"],
}
# A free family that only looks like the font: its line widths may differ.
LOOKALIKES = {
    "Arimo": ["helveticaneue", "aptos"],
    "Asap": ["optima"],
    "EB Garamond": ["garamond"],
    "Lato": ["avenir", "avenirnext"],
    "Libre Baskerville": ["baskerville"],
    "Libre Franklin": ["franklingothic"],
    "Open Sans": ["segoeui"],
    "Questrial": ["centurygothic"],
    "Spectral": ["palatino", "palatinolinotype", "bookantiqua"],
    "Work Sans": ["verdana"],
}


def gh(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if out.returncode:
        return None
    return json.loads(out.stdout)


def static_files(listing) -> list[dict]:
    return [f for f in listing if f["type"] == "file" and f["name"].endswith(".ttf") and "[" not in f["name"]
            and re.fullmatch(r"[A-Za-z0-9_.-]+", f["name"])]


def find_static(folder: str):
    """(commit, files, licence name) of the newest commit that touched `folder` and left static TrueType files and
    a licence in it, or why not."""
    reason = "no commits"
    for page in (1, 2, 3):
        commits = gh(f"repos/{REPO}/commits?path={folder}&per_page=100&page={page}")
        if not commits:
            break
        for c in commits:
            listing = gh(f"repos/{REPO}/contents/{folder}?ref={c['sha']}")
            if not isinstance(listing, list):
                continue
            files = static_files(listing)
            licence = next((n for n in LICENCES if any(f["name"] == n for f in listing)), None)
            if files and any(weight_italic(f["name"]) == (400, False) for f in files) and licence:
                return c["sha"], files, licence, [f for f in listing if f["name"] == licence][0]
            reason = "variable only" if not files else "no licence file" if not licence else "no regular file"
    return reason


_SHORT_STYLE = re.compile(r"[A-Za-z]+[a-z](BI|B|I|R)")   # GenBkBasB, GenBkBasBI: no hyphen, a style letter or two


def weight_italic(name: str) -> tuple[int, bool]:
    stem = name.removesuffix(".ttf")
    short = _SHORT_STYLE.fullmatch(stem)
    if short:
        stem = "X-" + {"BI": "BoldItalic", "B": "Bold", "I": "Italic", "R": "Regular"}[short.group(1)]
    facts = style_extract.font_facts_from_name(stem)
    return facts["weight"], facts["italic"]


def download(url: str, cache: Path) -> bytes:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / hashlib.sha256(url.encode()).hexdigest()
    if not target.is_file():
        with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 - https
            target.write_bytes(r.read())
    return target.read_bytes()


def _ink_width(font, ch: str) -> int:
    """The width of the pixels a character draws (`getbbox` is as wide as its advance at least)."""
    box = font.getmask(ch).getbbox()
    return box[2] - box[0] if box else 0


def measure_font(path: Path) -> dict:
    """x-height and the ink width of `l` as fractions of the em, and the advance of each of
    `fonts.ADVANCE_CHARS` in 1/1000 em, all at size 1000 with Pillow (the ink boxes the PDF side reads too)."""
    from PIL import ImageFont

    font = ImageFont.truetype(str(path), 1000)

    def ink(ch: str):
        return font.getbbox(ch, anchor="ls")

    return {
        "x_height": round(statistics.median(-ink(c)[1] for c in "xzvw") / 1000, 3),
        "stem": round(_ink_width(font, "l") / 1000, 3),
        "advance": [round(font.getlength(c)) for c in fonts.ADVANCE_CHARS],
    }


def pin_family(name: str, klass: str, folders: tuple[str, ...], cache: Path):
    found = None
    for folder in folders:
        found = find_static(folder)
        if not isinstance(found, str):
            break
    if isinstance(found, str):
        return None, found
    commit, files, licence, licence_item = found
    entries = []
    regular = None
    for f in sorted(files, key=lambda f: f["name"]):
        data = download(RAW.format(commit=commit, dir=folder, name=f["name"]), cache)
        if len(data) != f["size"]:
            return None, f"{f['name']}: size differs from the API's"
        weight, italic = weight_italic(f["name"])
        entries.append({"name": f["name"], "weight": weight, "italic": italic, "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})
        if (weight, italic) == (400, False):
            regular = cache / f["name"]
            regular.write_bytes(data)
    lic = download(RAW.format(commit=commit, dir=folder, name=licence), cache)
    try:
        metrics = measure_font(regular)
    except OSError as exc:   # FreeType cannot read some fonts
        return None, f"cannot be measured: {exc}"
    finally:
        regular.unlink()
    return {"commit": commit, "dir": folder, "class": klass,
            "licence": {"name": licence, "sha256": hashlib.sha256(lic).hexdigest()},
            "files": entries, "metrics": metrics}, None


def write(pin: dict, out: Path) -> None:
    text = json.dumps(pin, indent=1, ensure_ascii=False)
    text = re.sub(r"\[\s+([\d,\s.\-]+?)\s+\]", lambda m: "[" + re.sub(r"\s+", " ", m.group(1)) + "]", text)
    out.write_text(text + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path("/tmp/door-fonts-cache"))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--only", nargs="+", metavar="FAMILY",
                      help="pin just these families into the existing pin; the others stay as they are")
    mode.add_argument("--tables-only", action="store_true",
                      help="pin nothing; rewrite `aliases` and `lookalikes` from the families already pinned")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    known = {name for name, _, _ in FAMILIES}
    unknown = [n for n in args.only or [] if n not in known]
    if unknown:
        ap.error(f"not in FAMILIES: {', '.join(unknown)}")
    partial = args.tables_only or args.only is not None
    families = dict(json.loads(args.out.read_text(encoding="utf-8"))["families"]) if partial else {}
    to_pin = [] if args.tables_only else [f for f in FAMILIES if args.only is None or f[0] in args.only]
    skipped = {}
    for name, klass, folders in to_pin:
        pinned, why = pin_family(name, klass, folders, args.cache)
        if pinned:
            families[name] = pinned
            print(f"pinned  {name}: {pinned['dir']}@{pinned['commit'][:10]} {len(pinned['files'])} files")
        else:
            skipped[name] = why
            print(f"skipped {name}: {why}")
    # `aliases` and `lookalikes`: each name to its target, for the targets that are pinned.
    tables = {name: dict(sorted({a: target for target, keys in table.items() if target in families for a in keys}.items()))
              for name, table in (("aliases", ALIASES), ("lookalikes", LOOKALIKES))}
    write({"version": 1, "url": RAW, "families": dict(sorted(families.items())), **tables}, args.out)
    print(f"{len(families)} families, {len(tables['aliases'])} aliases, {len(tables['lookalikes'])} look-alikes; skipped: {', '.join(skipped) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
