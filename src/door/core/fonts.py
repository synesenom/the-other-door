"""Free fonts for a CV's fonts (#199): which pinned family stands in for each font a CV names, and the fetch of it.

`fonts_pin.json` (written by `scripts/pin_fonts.py`) pins each family at the last google/fonts commit where it was
still static, with the sha256 of every file and of its licence, so a file is fetched once, checked, and never
partly written. Static only: Chromium prints a variable font as nameless Type 3 text. `plan` is pure: the pin, the
fonts `style_extract` found and, if there are any, their measurements (`tailoring.font_measure`); it picks per
family, in this order, the family of the same name, a metric-compatible stand-in (Calibri to Carlito, Arial to
Arimo, ...), the nearest pinned family of the same class by measured width, x-height and stem, else the class
default with `source: "none"`. Icon fonts are skipped (#148 traces their glyphs); a symbol font gets nothing.
The embedded subset in a PDF is only measured, never shipped.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import statistics
import tempfile
import urllib.request
from pathlib import Path

_PIN = Path(__file__).with_name("fonts_pin.json")
ADVANCE_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "


class FontsError(Exception):
    pass


def pin() -> dict:
    return json.loads(_PIN.read_text(encoding="utf-8"))


def key(name: str) -> str:
    """A font name as the pin writes it: lowercase letters and digits only (`Nimbus Sans L` is `nimbussansl`)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def file_url(family: str, name: str, data: dict | None = None) -> str:
    data = data or pin()
    fam = data["families"][family]
    return data["url"].format(commit=fam["commit"], dir=fam["dir"], name=name)


def licence_url(family: str, data: dict | None = None) -> str:
    data = data or pin()
    return file_url(family, data["families"][family]["licence"]["name"], data)


# ---------- plan ----------

CLASS_DEFAULT = {"sans": "Arimo", "serif": "Tinos", "fixed": "Cousine"}
MAX_WIDTH_ERROR = 0.06    # past this median error in a run's width no pinned family is called near
TIE = 0.005               # widths this close are a tie, settled by x-height, then stem
MIN_RUNS = 3              # runs of the regular face needed to say anything of its widths
BEARING = 0.08            # em: the ink of a run is this much narrower than the sum of its advances (side bearings)
ALTERNATIVES = 2
_SYMBOL = re.compile(r"^(cm(sy|mi|ex|bsy)|msam|msbm|symbol|wingdings|webdings|zapfdingbats|mtextra)", re.I)


def _lookup(family: str, data: dict) -> tuple[str, str] | None:
    """(source, pinned family) for a font family named as a CV writes it: the pin's own name, else the stand-in
    the aliases give, trying the name without a trailing PostScript `MT`/`PS` too."""
    k = key(family)
    names = {key(n): n for n in data["families"]}
    for candidate in dict.fromkeys((k, re.sub(r"(mt|ps)+$", "", k))):
        if candidate in names:
            return "name", names[candidate]
        if candidate in data["aliases"]:
            return "standin", data["aliases"][candidate]
    return None


def _class_of(group: list[dict]) -> str:
    if any(f["fixed"] for f in group):
        return "fixed"
    return "serif" if any(f["serif"] for f in group) else "sans"


def _pick(files: list[dict], weight: int, italic: bool) -> dict:
    """The pinned file nearest a weight and style: the right slant when the family has one, then the closest weight
    (the heavier of two equally near)."""
    same = [f for f in files if f["italic"] == italic] or [f for f in files if not f["italic"]] or files
    return min(same, key=lambda f: (abs(f["weight"] - weight), -f["weight"]))


def _files(family: str, uses: list[tuple[int, bool]], data: dict) -> list[dict]:
    chosen: dict[str, dict] = {}
    for weight, italic in uses:
        file = _pick(data["families"][family]["files"], weight, italic)
        entry = chosen.setdefault(file["name"], {**file, "url": file_url(family, file["name"], data), "for": []})
        entry["for"].append([weight, italic])
    return list(chosen.values())


def _licence(family: str, data: dict) -> dict:
    lic = data["families"][family]["licence"]
    return {"name": f"{family.replace(' ', '')}-{lic['name']}", "url": licence_url(family, data), "sha256": lic["sha256"]}


def _width_error(runs: list, advance: list[int]) -> float:
    table = dict(zip(ADVANCE_CHARS, advance))
    mean = statistics.fmean(advance)
    errors = []
    for text, width, size in runs:
        if width > 0:
            predicted = (sum(table.get(c, mean) for c in text) / 1000 - BEARING) * size
            errors.append(abs(predicted - width) / width)
    return statistics.median(errors)


def _own_measure(group: list[dict], measured: dict) -> dict | None:
    """The measurement of the family's regular face (else the nearest to it) with enough runs to go by."""
    have = [f for f in group if f["font"] in measured and len(measured[f["font"]]["runs"]) >= MIN_RUNS]
    if not have:
        return None
    best = min(have, key=lambda f: (f["italic"], abs(f["weight"] - 400)))
    return measured[best["font"]]


def _rank(klass: str, own: dict, data: dict) -> list[dict]:
    """Every pinned family of the class by how near it is to the measured font: width first, a tie by x-height,
    then stem."""
    scored = []
    for name, fam in data["families"].items():
        if fam["class"] != klass:
            continue
        m = fam["metrics"]
        gap = lambda a, b: abs(a - b) / b if a and b else 0.0   # noqa: E731 - a measure that is missing counts for nothing
        scored.append({"family": name, "error": _width_error(own["runs"], m["advance"]),
                       "x": gap(m["x_height"], own["x_height"]), "stem": gap(m["stem"], own["stem"])})
    if not scored:
        return []
    best = min(s["error"] for s in scored)
    tied = sorted((s for s in scored if s["error"] - best <= TIE), key=lambda s: (s["x"], s["stem"]))
    rest = sorted((s for s in scored if s["error"] - best > TIE), key=lambda s: s["error"])
    return tied + rest


def _entry(family: str, source: str, resolved: str | None, reason: str, uses, data: dict, alternatives=()) -> dict:
    return {"family": family, "source": source, "resolved": resolved, "reason": reason,
            "files": _files(resolved, uses, data) if resolved else [],
            "licence": _licence(resolved, data) if resolved else None,
            "alternatives": [{"family": a["family"], "error": round(a["error"], 3)} for a in alternatives],
            "uses": [list(u) for u in uses]}


def _resolve(family: str, group: list[dict], measured: dict | None, data: dict) -> dict:
    uses = sorted({(f["weight"], f["italic"]) for f in group})
    if any(_SYMBOL.match(f["font"]) for f in group):
        return _entry(family, "none", None, f"{family}: a symbol font, nothing to fetch", uses, data)
    found = _lookup(family, data)
    if found:
        source, resolved = found
        reason = (f"{family}: the pinned {resolved}" if source == "name"
                  else f"{family}: {resolved} has the same widths and is free")
        return _entry(family, source, resolved, reason, uses, data)
    klass = _class_of(group)
    default = CLASS_DEFAULT[klass] if CLASS_DEFAULT[klass] in data["families"] else None
    own = _own_measure(group, measured or {})
    if own is None:
        return _entry(family, "none", default,
                      f"{family}: no free copy, and no measurement of it to compare; {default or 'nothing'} stands in", uses, data)
    ranked = _rank(klass, own, data)
    if ranked and ranked[0]["error"] <= MAX_WIDTH_ERROR:
        best = ranked[0]
        return _entry(family, "nearest", best["family"],
                      f"{family}: no free copy; nearest is {best['family']} (width within {best['error']:.1%})",
                      uses, data, ranked[1:1 + ALTERNATIVES])
    near = f"nearest {ranked[0]['family']}, width off by {ranked[0]['error']:.0%}" if ranked else "no family of its kind"
    return _entry(family, "none", default, f"{family}: no free copy is close enough ({near}); {default or 'nothing'} stands in",
                  uses, data, ranked[:ALTERNATIVES])


def plan(fonts: list[dict], measured: dict | None = None, *, data: dict | None = None) -> list[dict]:
    """One entry per font family of `fonts` (what `style_extract.extract` returns), in order of use: ``family`` as the
    CV names it, ``source`` (`name`, `standin`, `nearest`, `none`), ``resolved`` (the pinned family, or None),
    ``reason``, ``files`` (name, weight, italic, size, sha256, url, `for`: the weights and styles the CV uses),
    ``licence``, ``alternatives`` (the next nearest) and ``uses``. Icon fonts and fonts with no name are left out."""
    data = data or pin()
    groups: dict[str, list[dict]] = {}
    for f in fonts:
        if f.get("icon") or not f.get("family"):
            continue
        groups.setdefault(f["family"], []).append(f)
    return [_resolve(family, group, measured, data) for family, group in groups.items()]


# ---------- fetch ----------

def _http_get(url: str, to: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, open(to, "wb") as out:  # noqa: S310 - https, pinned
        shutil.copyfileobj(response, out)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(plan: list[dict], dest: Path, *, fetch=_http_get) -> list[Path]:
    """Download what `plan` names into `dest` (the font files and each family's licence beside them) and return the
    font files. A file there with the pinned hash is left alone; every download is checked against the pin before
    anything is moved in, so a bad one leaves `dest` as it was.

    Raises:
        FontsError: a download failed or does not match the pinned sha256.
    """
    wanted: list[tuple[str, str, str]] = []   # (url, file name in dest, sha256)
    for entry in plan:
        wanted += [(f["url"], f["name"], f["sha256"]) for f in entry["files"]]
        if entry["licence"]:
            wanted.append((entry["licence"]["url"], entry["licence"]["name"], entry["licence"]["sha256"]))
    dest = Path(dest)
    missing = [w for w in wanted if not (dest / w[1]).is_file() or _sha256(dest / w[1]) != w[2]]
    if missing:
        try:
            dest.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".fonts.", suffix=".part", dir=dest))
        except OSError as exc:
            raise FontsError(str(exc)) from exc
        try:
            for url, name, sha in missing:
                part = staging / name
                fetch(url, part)
                if _sha256(part) != sha:
                    raise FontsError(f"{name} does not match the pinned checksum; nothing was written")
            for _, name, _ in missing:
                (staging / name).replace(dest / name)
        except OSError as exc:
            raise FontsError(str(exc)) from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return [dest / f["name"] for entry in plan for f in entry["files"]]
