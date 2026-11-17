"""Free fonts for a CV's fonts (#199): which pinned family stands in for each font a CV names, and the fetch of it.

`fonts_pin.json` (written by `scripts/pin_fonts.py`) pins each family at the last google/fonts commit where it was
still static, with the sha256 of every file and of its licence, so a file is fetched once, checked, and never
partly written. Static only: Chromium prints a variable font as nameless Type 3 text. `plan` is pure: the pin, the
fonts `style_extract` found and, if there are any, their measurements (`tailoring.font_measure`); it picks per
family, in this order, the family of the same name, a metric-compatible stand-in (Calibri to Carlito, Arial to
Arimo, ...; `aliases`), the nearest pinned family of the same class by measured width, x-height and stem (within `MAX_WIDTH_ERROR`), a free look-alike
whose widths may differ (`lookalikes`), else the class default with `source: "none"`. Icon fonts are skipped (#148 traces their glyphs); a symbol font gets nothing.
The embedded subset in a PDF is only measured, never shipped.
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

from door.core import pinned, utils

_PIN = Path(__file__).with_name("fonts_pin.json")
ADVANCE_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "


class FontsError(Exception):
    pass


def pin() -> dict:
    return json.loads(_PIN.read_text(encoding="utf-8"))


def key(name: str) -> str:
    """A font name as the pin writes it: lowercase letters and digits only (`Nimbus Sans L` is `nimbussansl`)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def file_url(family: str, name: str, data: dict) -> str:
    fam = data["families"][family]
    return data["url"].format(commit=fam["commit"], dir=fam["dir"], name=name)


# ---------- plan ----------

CLASS_DEFAULT = {"sans": "Arimo", "serif": "Tinos", "fixed": "Cousine"}
MAX_WIDTH_ERROR = 0.06    # past this median error in a run's width no pinned family is called near
TIE = 0.005               # widths this close are a tie, settled by x-height, then stem
MIN_RUNS = 3              # runs of the regular face needed to say anything of its widths
BEARING = 0.08            # em: the ink of a run is this much narrower than the sum of its advances (side bearings)
ALTERNATIVES = 2
_SYMBOL = re.compile(r"^(cm(sy|mi|ex|bsy)|msam|msbm|symbol|wingdings|webdings|zapfdingbats|mtextra)", re.I)


_MARKERS = re.compile(r"(mt|ps|ltstd|ltpro|lt|std|pro|display)$")


def _candidates(family: str) -> list[str]:
    """The pin's spellings of a family name, the name as written first, then with the PostScript `MT`/`PS`, a foundry
    or edition marker (`LT`, `Std`, `Pro`, `Display`) and a style after a hyphen taken off, then those without Adobe's
    `Adobe` or `A` prefix (`AGaramondPro`: a capital A before another capital). Not `Narrow`: that is another width."""
    out = [key(family)]
    stem = key(family.split("-")[0])
    while stem:
        out.append(stem)
        stem = _MARKERS.sub("", stem)
        if stem == out[-1]:
            break
    stem = re.sub(r"^adobe", "", out[-1])
    out += [stem, stem[1:] if re.match(r"A[A-Z]", family) else ""]
    return [c for c in dict.fromkeys(out) if c]


def _lookup(family: str, data: dict) -> tuple[str, str] | None:
    """(source, pinned family) for a font family named as a CV writes it: the pin's own name, else the stand-in
    its aliases give; a stand-in the pin does not hold (the shipped fonts alone) is none."""
    names = {key(n): n for n in data["families"]}
    for candidate in _candidates(family):
        if candidate in names:
            return "name", names[candidate]
        if data["aliases"].get(candidate) in data["families"]:
            return "standin", data["aliases"][candidate]
    return None


def _lookalike(family: str, data: dict) -> str | None:
    """The free look-alike for a font family named as a CV writes it, if the pin holds it."""
    for candidate in _candidates(family):
        if data["lookalikes"].get(candidate) in data["families"]:
            return data["lookalikes"][candidate]
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


def _faked(files: list[dict], uses) -> list[list]:
    """The (weight, italic) of `uses` that Chromium would have to synthesise from the file `_pick` gives (an italic
    from an upright file, a bold from a lighter one), which it prints as nameless Type 3 text."""
    out = []
    for weight, italic in uses:
        got = _pick(files, weight, italic)
        if (italic and not got["italic"]) or (weight >= 600 and got["weight"] < 600):
            out.append([weight, italic])
    return out


def _files(family: str, uses: list[tuple[int, bool]], data: dict) -> list[dict]:
    chosen: dict[str, dict] = {}
    for weight, italic in uses:
        file = _pick(data["families"][family]["files"], weight, italic)
        entry = chosen.setdefault(file["name"], {**file, "url": file_url(family, file["name"], data), "for": []})
        entry["for"].append([weight, italic])
    return list(chosen.values())


def _licence(family: str, data: dict) -> dict:
    lic = data["families"][family]["licence"]
    return {"name": f"{family.replace(' ', '')}-{lic['name']}", "url": file_url(family, lic["name"], data),
            "sha256": lic["sha256"]}


def _width_error(runs: list, advance: list[int]) -> float:
    table = dict(zip(ADVANCE_CHARS, advance))
    mean = statistics.fmean(advance)
    errors = []
    for text, width, size in runs:
        if width > 0:
            predicted = (sum(table.get(c, mean) for c in text) / 1000 - BEARING) * size
            errors.append(abs(predicted - width) / width)
    return statistics.median(errors) if errors else 1.0   # no run to go by: as far off as can be


def _own_measure(group: list[dict], measured: dict) -> dict | None:
    """The measurement of the family's regular face (else the nearest to it) with enough runs to go by."""
    have = [f for f in group if f["font"] in measured
            and sum(1 for run in measured[f["font"]]["runs"] if run[1] > 0) >= MIN_RUNS]
    if not have:
        return None
    best = min(have, key=lambda f: (f["italic"], abs(f["weight"] - 400)))
    return measured[best["font"]]


def _rank(klass: str, own: dict, uses, data: dict) -> list[dict]:
    """Every pinned family of the class by how near it is to the measured font: width first; families tied on width
    go by how few of the faces the CV uses they would have to fake, then x-height, then stem."""
    scored = []
    for name, fam in data["families"].items():
        if fam["class"] != klass:
            continue
        m = fam["metrics"]
        gap = lambda a, b: abs(a - b) / b if a and b else 0.0   # noqa: E731 - a measure that is missing counts for nothing
        scored.append({"family": name, "error": _width_error(own["runs"], m["advance"]),
                       "x": gap(m["x_height"], own["x_height"]), "stem": gap(m["stem"], own["stem"]),
                       "faked": len(_faked(fam["files"], uses))})
    if not scored:
        return []
    best = min(s["error"] for s in scored)
    tied = sorted((s for s in scored if s["error"] - best <= TIE), key=lambda s: (s["faked"], s["x"], s["stem"]))
    rest = sorted((s for s in scored if s["error"] - best > TIE), key=lambda s: s["error"])
    return tied + rest


def _entry(family: str, source: str, resolved: str | None, reason: str, uses, data: dict, alternatives=()) -> dict:
    faked = _faked(data["families"][resolved]["files"], uses) if resolved else []
    if faked:
        reason += "; " + ", ".join(f"{'italic' if i else 'bold'} ({w})" for w, i in faked) + " faked: the family has no such file"
    return {"family": family, "source": source, "resolved": resolved, "reason": reason, "faked": faked,
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
        reason = {"name": f"{family}: the pinned {resolved}",
                  "standin": f"{family}: {resolved} has the same widths and is free"}[source]
        return _entry(family, source, resolved, reason, uses, data)
    klass = _class_of(group)
    default = CLASS_DEFAULT[klass] if CLASS_DEFAULT[klass] in data["families"] else None
    like = _lookalike(family, data)
    like_entry = like and _entry(family, "lookalike", like,
                                 f"{family}: {like} looks alike and is free; line widths may differ", uses, data)
    own = _own_measure(group, measured or {})
    if own is None:
        if like:
            return like_entry
        return _entry(family, "none", default,
                      f"{family}: no free copy, and no measurement of it to compare; {default or 'nothing'} stands in", uses, data)
    ranked = _rank(klass, own, uses, data)
    if ranked and ranked[0]["error"] <= MAX_WIDTH_ERROR:
        best = ranked[0]
        return _entry(family, "nearest", best["family"],
                      f"{family}: no free copy; nearest is {best['family']} (width within {best['error']:.1%})",
                      uses, data, ranked[1:1 + ALTERNATIVES])
    if like:
        return like_entry
    near = f"nearest {ranked[0]['family']}, width off by {ranked[0]['error']:.0%}" if ranked else "no family of its kind"
    return _entry(family, "none", default, f"{family}: no free copy is close enough ({near}); {default or 'nothing'} stands in",
                  uses, data, ranked[:ALTERNATIVES])


def plan(fonts: list[dict], measured: dict | None = None, *, data: dict | None = None) -> list[dict]:
    """One entry per font family of `fonts` (what `style_extract.extract` returns), in order of use: ``family`` as the
    CV names it, ``source`` (`name`, `standin`, `lookalike`, `nearest`, `none`), ``resolved`` (the pinned family, or None),
    ``reason``, ``faked`` (the weights and styles the family has no file for, which Chromium would synthesise), ``files`` (name,
    weight, italic, sha256, url, `for`: the weights and styles the CV uses), ``licence``, ``alternatives`` (the next nearest) and ``uses``. Icon fonts and fonts with no name are left out."""
    data = data or pin()
    groups: dict[str, list[dict]] = {}
    for f in fonts:
        if f.get("icon") or not f.get("family"):
            continue
        groups.setdefault(f["family"], []).append(f)
    return [_resolve(family, group, measured, data) for family, group in groups.items()]


# ---------- fetch ----------

def fetch(plan: list[dict], dest: Path) -> list[Path]:
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
    missing = [w for w in wanted if not (dest / w[1]).is_file() or pinned.sha256(dest / w[1]) != w[2]]
    if missing:
        try:
            with utils.staging(dest, ".fonts.") as staging:
                pinned.download(missing, staging)
                for _, name, _ in missing:
                    (staging / name).replace(dest / name)
        except (OSError, pinned.ChecksumError) as exc:
            raise FontsError(str(exc)) from exc
    return [dest / f["name"] for entry in plan for f in entry["files"]]
