"""Offline check of a tailored CV and cover letter against the candidate's own sources.

Every number, year, employer, skill or tool, certification and degree in ``cv.tex`` /
``cover_letter.tex`` should appear in ``profile/cv.md`` or the story bank (the letter may
also echo the ad's figures and skills). What does not is *reported*, never blocked: the tailor is told not to invent, this checks it
did not. Pure and deterministic: no model call, no network, never raises out of `check`.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from door import i18n
from door.core import skill_aliases, workspace
from door.matching import integrity

FACTS_FILE = "facts.json"

_MACROS = {
    "cvheader": 5, "letterheader": 5, "recipient": 3, "closing": 1, "renewcommand": 2,
    "href": 2, "url": 1, "vspace": 1, "hspace": 1, "setlength": 2, "fontsize": 2,
    "definecolor": 3, "color": 1, "textcolor": 1, "includegraphics": 1,
}
_MACRO_RE = re.compile(r"\\(" + "|".join(_MACROS) + r")(?![a-zA-Z])\*?")
# A figure: digits with ``.`` / ``,`` groups, or French groups of three after a (narrow, non-breaking) space
# ("45 000"); a ``%`` (a space before it allowed) or a ``k`` / ``m`` / ``b`` / ``x`` suffix, a ``k`` also after a
# space when a currency sign follows ("45 k€").
_GROUP = "[ \u00a0\u202f]"
_NUM_RE = re.compile(
    rf"(?<![\w.,])(?:\d{{1,3}}(?:{_GROUP}\d{{3}}(?!\d))+|\d+)(?:[.,]\d+)*"
    rf"(?:\s?%|[kKmMbBx](?![a-zA-Z])|{_GROUP}?[kK](?=\s?€))?(?![\w])"
)
_SCALE = {"k": 3, "m": 6, "b": 9}
_THOUSANDS_RE = re.compile(r"\d{1,3}([.,]\d{3})+")
_DASHES_RE = re.compile(r"---|--|–|—")
_CONTEXT_CHARS = 100
_TODO_RE = re.compile(r"\bTODO\b")


@lru_cache(maxsize=1)
def _date_res() -> tuple[re.Pattern, re.Pattern]:
    """The day before a month name ("29 octobre", "1er oct.") and a numeric month before a year
    ("10/2026", "29/10/2026"): a date's day and month are not figures to check, its year still is."""
    names = sorted((re.escape(n) for n in i18n.month_numbers()), key=len, reverse=True)
    month = re.compile(rf"(?<![\w.,])\d{{1,2}}(?:er|re|e)?\.?[ \u00a0\u202f]*(?=(?:{'|'.join(names)})(?!\w))", re.I) if names else re.compile(r"(?!)")
    numeric = re.compile(r"(?<![\w.,/])(?:(?:0?[1-9]|[12]\d|3[01])/)?(?:0?[1-9]|1[0-2])/(?=(?:19|20)\d\d(?!\d))")
    return month, numeric


def _strip_dates(line: str) -> str:
    month, numeric = _date_res()
    return numeric.sub("", month.sub("", line))


def _strip_comments(tex: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*", "", line) for line in tex.splitlines())


def _unescape(text: str) -> str:
    text = text.replace("\\%", "%").replace("\\&", "&").replace("\\$", "$").replace("~", " ")
    text = text.replace("\\,", " ").replace("{,}", ",")  # LaTeX thin space (thousands) and braced decimal comma
    return _DASHES_RE.sub(" - ", text)


def _group_end(text: str, start: int) -> int | None:
    """Index just past the brace group opening at ``text[start]``, or None."""
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _drop_macros(text: str) -> str:
    """Remove the macros whose arguments are not content (with those arguments)."""
    out, pos = [], 0
    while True:
        match = _MACRO_RE.search(text, pos)
        if not match:
            out.append(text[pos:])
            break
        out.append(text[pos:match.start()])
        i = match.end()
        opt = re.compile(r"\s*\[[^\]]*\]").match(text, i)
        if opt:
            i = opt.end()
        for _ in range(_MACROS[match.group(1)]):
            j = i
            while j < len(text) and text[j].isspace():
                j += 1
            if j >= len(text) or text[j] != "{":
                break
            end = _group_end(text, j)
            if end is None:
                i = len(text)
                break
            i = end
        out.append(" ")
        pos = i
    return "".join(out)


def _plain(text: str) -> str:
    text = _drop_macros(text)
    text = re.sub(r"\\\\\[[^\]]*\]", " ", text)
    text = re.sub(r"\\begin\{[^}]*\}(\[[^\]]*\])?", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)
    return re.sub(r"[{}]", " ", text)


def _canon(token: str) -> str:
    """One spelling per figure: ``1,200`` = ``1.200`` = ``1200``, ``3,5`` = ``3.5``,
    ``40k`` = ``40,000``, ``2.5M`` = ``2,500,000``; ``%`` and a multiplier ``x`` stay."""
    pct = token.endswith("%")
    token = re.sub(r"\s", "", token.rstrip("%"))
    suffix = token[-1].lower() if token[-1].isalpha() else ""
    token = token.rstrip("kKmMbBx")
    if _THOUSANDS_RE.fullmatch(token):
        token = re.sub(r"[.,]", "", token)
    else:
        token = token.replace(",", ".")
    if suffix in _SCALE:
        token, suffix = format(Decimal(token).scaleb(_SCALE[suffix]).normalize(), "f"), ""
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token + ("%" if pct else suffix)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _window(line: str, raw: str) -> str:
    line = _squash(line.replace("\\item", " "))
    idx = line.find(_squash(raw))
    if len(line) <= 2 * _CONTEXT_CHARS or idx < 0:
        return line[: 2 * _CONTEXT_CHARS + 1] if len(line) > 2 * _CONTEXT_CHARS + 1 and idx < 0 else line
    lo = max(0, idx - _CONTEXT_CHARS // 2)
    hi = min(len(line), idx + len(raw) + _CONTEXT_CHARS // 2)
    return ("…" if lo else "") + line[lo:hi] + ("…" if hi < len(line) else "")


def extract_claims(tex: str, file: str) -> list[dict]:
    """The checkable claims of one document: numbers, years, (CV only) employers, skills, certifications and
    degrees, and each `TODO`, a gap of cv.md's that must not reach a document."""
    text = _unescape(_strip_comments(tex))
    text = text.partition("\\begin{document}")[2] or text  # the template's preamble holds no claims (\hbadness=99999)
    claims: list[dict] = [
        # Read off the source, not `_plain`: the macros it drops include \cvheader's contact details.
        {"kind": "placeholder", "value": "TODO", "context": _window(line, "TODO"), "file": file}
        for line in map(_squash, text.splitlines()) if _TODO_RE.search(line)
    ]
    if file == "cv":
        pos = 0
        while True:
            at = text.find("\\workexperience", pos)
            if at < 0:
                break
            pos = at + 1
            brace = text.find("{", at)
            if brace < 0:
                continue
            end = _group_end(text, brace)
            if end is None:
                continue
            head = _squash(_plain(text[brace + 1:end - 1]))
            if " | " not in head:
                continue
            company = re.split(r"\s[-–—]{1,3}\s", head.split(" | ", 1)[1], maxsplit=1)[0].strip()
            if company:
                claims.append({"kind": "employer", "value": company, "context": head, "file": file})
    for line in _plain(text).splitlines():
        shown = line
        line = _strip_dates(line)
        for match in _NUM_RE.finditer(line):
            raw = match.group(0)
            value = _canon(raw)
            if re.fullmatch(r"\d", value):
                continue
            kind = "year" if re.fullmatch(r"(19|20)\d\d", value) else "number"
            claims.append({"kind": kind, "value": value, "context": _window(shown, raw), "file": file})
    return claims + extract_term_claims(text, file)


# --- skills, tools, certifications and degrees --------------------------------

_SENTINEL = "\x00SECTION "
_SECTION_RE = re.compile(r"\\section\*?\s*\{((?:[^{}]|\{[^{}]*\})*)\}")
_PAREN_RE = re.compile(r"\([^)]*\)")
_SPLIT_RE = re.compile(r"[,;•|]")
_SKILL_MAX_WORDS = 4
_TEXT_MAX_WORDS = 10
_TERM_SPLIT_RE = re.compile(r"[\s,;:()\[\]{}\"“”‘’*|•<>=!?]+")
_ABBREV_RE = re.compile(r"(?:[A-Za-z]\.){1,}[A-Za-z]?")


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _term_tokens(text: str) -> list[str]:
    """Normalised tokens of a term or a source text: casefolded, hyphens as spaces, edge
    punctuation and simple plurals removed; ``+ # . /`` inside a token stay (``c++``,
    ``.net``, ``s/4hana``)."""
    out = []
    for raw in _TERM_SPLIT_RE.split(text.replace("\\&", "&").replace("\u2019s", "").casefold()):
        for tok in re.split(r"[-_–—]+", raw):
            tok = tok.rstrip(".'/")
            if not tok.startswith(".") or not re.match(r"\.[a-z]", tok):  # keep ".net"
                tok = tok.lstrip(".'/&")
            if re.search(r"\w", tok):
                out.append(_singular(tok))
    return out


def _term_key(term: str) -> str:
    return " ".join(_term_tokens(term))


def _stop_keys() -> set[str]:
    return {_term_key(w) for w in i18n.skill_stop_words()}


def _bare(key: str) -> str:
    return re.sub(r"[./]", "", key)


def _legal_keys() -> set[str]:
    """The company forms of every country ("ApS", "GmbH", "S.A.S."), dots and slashes dropped: a form is no skill."""
    return {_bare(_term_key(s)) for s in i18n.legal_suffixes()} - {""}


def _filler() -> set[str]:
    return {_singular(w) for w in i18n.stop_words()}


def _section_kind(title: str) -> str:
    key = _squash(_plain(title)).casefold().strip(" :")
    for kind in ("skills", "education", "certifications"):
        if key in i18n.cv_section(kind):
            return kind
    return "other"


def _is_technical(tok: str) -> bool:
    """A word that looks like a tool, language or standard: ``C++``, ``Node.js``, ``CI/CD``,
    ``S/4HANA``, ``PostgreSQL``, ``SQL``. Plain and capitalised words are not."""
    if not re.search(r"[A-Za-z]", tok) or "@" in tok or tok.lower().startswith(("http", "www")):
        return False
    if sum(c.isdigit() for c in tok) > 2 or _ABBREV_RE.fullmatch(tok):
        return False
    if re.search(r"[A-Za-z0-9][+#]", tok):
        return True
    if re.fullmatch(r"[A-Z0-9]+", tok):
        return sum(c.isalpha() for c in tok) >= 2
    if re.search(r"[a-z][A-Z]", tok):
        return True
    if any(c.isupper() for c in tok) and ("." in tok or "/" in tok):
        parts = [p for p in re.split(r"[./]", tok) if p]
        need = 3 if "." in tok else 2
        return any(sum(c.isalpha() for c in p) >= need for p in parts)
    return False


def _technical_tokens(line: str) -> list[str]:
    out = []
    for raw in re.split(r"[\s,;:()\[\]{}\"“”*|•<>=!?]+", line):
        for tok in re.split(r"[-–—]+", raw):
            tok = tok.strip("'’_/&").rstrip(".") if not tok.startswith(".") else tok.rstrip(".")
            if tok and _is_technical(tok):
                out.append(tok)
    return out


def _list_items(line: str) -> list[str]:
    items = []
    for part in _SPLIT_RE.split(line):
        part = _squash(_PAREN_RE.sub(" ", part))
        head, colon, rest = part.partition(":")
        if colon and len(head.split()) <= 3:
            part = rest
        part = part.strip(" .:*-")
        if part:
            items.append(part)
    return items


def _entries(line: str, kind: str) -> list[str]:
    """The claim texts of one line of a certifications / education section."""
    if kind == "education":
        head = re.split(r"\s[|-]\s|,", line)[0]
        parts = [head]
    else:
        parts = [re.split(r"\s[|-]\s|,\s*(?:19|20)\d\d", seg)[0] for seg in re.split(r"[;,](?![^()]*\))", line)]
    out = []
    for part in parts:
        part = _squash(part).strip(" .:*-")
        if re.search(r"[^\W\d_]", part) and len(part.split()) <= _TEXT_MAX_WORDS:
            out.append(part)
    return out


def extract_term_claims(text: str, file: str) -> list[dict]:
    """Skills, certifications and degrees of one document (``text`` already uncommented and
    unescaped). Section-aware: every item of a Skills, Certifications or Education section is a
    claim; elsewhere (bullets, profile, letter) only technical-looking words are."""
    text = text.replace("\\#", "#").replace("\\_", "_")
    text = re.sub(r"\\end\{[^}]*\}", " ", text)
    text = re.sub(r"\\\\(\[[^\]]*\])?", "\n", text)  # a LaTeX line break is not part of a term
    text = _SECTION_RE.sub(lambda m: f"\n{_SENTINEL}{m.group(1)}\n", text)
    stop = _stop_keys()
    legal = _legal_keys()
    claims: list[dict] = []
    section = "other"
    for line in _plain(text).splitlines():
        if line.startswith(_SENTINEL):
            section = _section_kind(line[len(_SENTINEL):])
            continue
        if not line.strip():
            continue
        if section == "skills":
            found = [("skill", v) for v in _list_items(line) if len(v.split()) <= _SKILL_MAX_WORDS]
        elif section == "certifications":
            found = [("certification", v) for v in _entries(line, section)]
        elif section == "education":
            found = [("degree", v) for v in _entries(line, section)]
        else:
            found = [("skill", v) for v in _technical_tokens(line)]
        for kind, value in found:
            if _term_key(value) in stop or not _term_key(value) or _TODO_RE.search(value):
                continue
            if kind == "skill" and _bare(_term_key(value)) in legal:
                continue
            claims.append({"kind": kind, "value": value, "context": _window(line, value), "file": file})
    return claims


def source_tokens(*texts: str) -> set[str]:
    """Every canonical number token of the given source texts."""
    tokens: set[str] = set()
    for text in texts:
        for match in _NUM_RE.finditer(_strip_dates(text.replace("\\%", "%"))):
            tokens.add(_canon(match.group(0)))
    return tokens


def _norm_name(text: str) -> str:
    return _squash(text.replace("\\&", "&")).casefold()


_TERM_KINDS = ("skill", "certification", "degree")


class _TermSources:
    """The terms of the source texts, for the skill / certification / degree claims."""

    def __init__(self, texts: list[str], aliases: dict):
        self.filler = _filler()
        tokens = _term_tokens("\n".join(texts))
        self.tokens = {t for t in tokens if t not in self.filler}
        self.phrase = " " + " ".join(t for t in tokens if t not in self.filler) + " "
        self.canon: dict[str, list[str]] = {}
        self.dropped: set[str] = set()
        for variant, canonical in aliases.items():
            vkey = _term_key(variant)
            if not vkey:
                continue
            if canonical is None:
                self.dropped.add(vkey)
                continue
            ckey = _term_key(canonical)
            self.canon.setdefault(vkey, []).append(ckey)
            self.canon.setdefault(ckey, []).append(vkey)

    def _words(self, value: str) -> list[str]:
        return [t for t in _term_tokens(value) if t not in self.filler and not t.isdigit()]

    def _has(self, kind: str, words: list[str]) -> bool:
        if kind == "certification":
            return " " + " ".join(words) + " " in self.phrase
        return set(words) <= self.tokens

    def supports(self, kind: str, value: str) -> bool:
        key = _term_key(value)
        if key in self.dropped:
            return True
        variants = [self._words(value)]
        if kind == "certification":
            variants.append(self._words(_PAREN_RE.sub(" ", value)))
            variants += [self._words(m) for m in re.findall(r"\(([^)]*)\)", value)]
        variants += [self._words(alt) for alt in self.canon.get(key, [])]
        return any(not words or self._has(kind, words) for words in variants)


def unsupported(
    claims: list[dict],
    cv_sources: list[str],
    letter_sources: list[str] | None = None,
    *,
    current_year: int | None = None,
    aliases: dict | None = None,
) -> list[dict]:
    """The claims no source supports, deduplicated, in document order.

    ``aliases`` is ``jobs/skill_aliases.json`` (``{variant: canonical | None}``): a skill and its
    alias count as one, and a ``None`` one is not a skill."""
    year = str(current_year or date.today().year)
    cv_tokens = source_tokens(*cv_sources)
    letter_tokens = source_tokens(*(cv_sources if letter_sources is None else letter_sources))
    haystack = _norm_name("\n".join(cv_sources))
    cv_terms = _TermSources(cv_sources, aliases or {})
    letter_terms = _TermSources(cv_sources if letter_sources is None else letter_sources, aliases or {})
    out, seen = [], set()
    for claim in claims:
        value = claim["value"]
        if claim["kind"] == "placeholder":
            pass  # cv.md says TODO too, and that backs nothing
        elif claim["kind"] in _TERM_KINDS:
            terms = letter_terms if claim["file"] == "cover_letter" else cv_terms
            if terms.supports(claim["kind"], value):
                continue
        elif claim["kind"] == "employer":
            if claim["file"] != "cv" or _norm_name(value) in haystack:
                continue
        else:
            if claim["kind"] == "year" and value == year:
                continue
            tokens = letter_tokens if claim["file"] == "cover_letter" else cv_tokens
            if value in tokens or (value.endswith("%") and value[:-1] in tokens):
                continue
        key = (claim["kind"], value, claim["file"], claim["context"])
        if key not in seen:
            seen.add(key)
            out.append(claim)
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


_REASON_MAX = 200


def _clean_reason(value: object) -> str | None:
    """A reason as one short line of plain text, or None when it is not a non-empty string."""
    if not isinstance(value, str):
        return None
    text = _squash("".join(" " if ch.isspace() or not ch.isprintable() else ch for ch in value))
    return text[:_REASON_MAX].rstrip() or None


def _item_key(item: dict) -> tuple:
    return (item.get("kind"), item.get("value"), item.get("file"))


def _with_reasons(found: list[dict], saved: list | None, keep: list[dict] | None) -> None:
    """Put on each flagged item (not a placeholder) the reason recorded for it before, then the ``keep`` ones."""
    reasons: dict[tuple, str] = {}
    for source in (saved or [], keep or []):
        for item in source:
            if isinstance(item, dict) and (reason := _clean_reason(item.get("reason"))):
                reasons[_item_key(item)] = reason
    for item in found:
        if item.get("kind") != "placeholder" and (reason := reasons.get(_item_key(item))):
            item["reason"] = reason


def check(
    output_dir: Path,
    profile_dir: Path,
    *,
    write: bool = True,
    current_year: int | None = None,
    keep: list[dict] | None = None,
) -> list[dict] | None:
    """Check ``output_dir``'s CV and letter against the profile; None when it cannot be known.

    ``[]`` is clean. Writes ``facts.json`` (best effort) unless ``write`` is False. Never raises.
    An item still flagged keeps the ``reason`` recorded for it (by kind, value and file); ``keep``
    (``[{kind, value, file, reason}]``) records new ones. A TODO never takes one.
    """
    try:
        cv_md = profile_dir / "cv.md"
        cv_tex = output_dir / "cv.tex"
        if not cv_md.is_file() or not cv_tex.is_file():
            return None
        cv_sources = [cv_md.read_text(encoding="utf-8"), _read(profile_dir / "story_bank.md")]
        try:
            posting = json.loads(_read(output_dir / "posting.json") or "{}")
        except ValueError:
            posting = {}
        if not isinstance(posting, dict):
            posting = {}
        integrity.ensure(posting)
        try:
            aliases, _ = skill_aliases.load_for(workspace.JOBS_DIR)
        except Exception:  # noqa: BLE001 - the alias file only widens what counts as supported
            aliases = {}
        ad = f"{posting.get('title') or ''}\n{posting.get('description') or ''}"
        claims = extract_claims(cv_tex.read_text(encoding="utf-8"), "cv")
        letter = output_dir / "cover_letter.tex"
        if letter.is_file():
            claims += extract_claims(letter.read_text(encoding="utf-8"), "cover_letter")
        found = unsupported(claims, cv_sources, cv_sources + [ad], current_year=current_year, aliases=aliases)
        _with_reasons(found, load(output_dir), keep if isinstance(keep, list) else None)
    except Exception:  # noqa: BLE001 - a check that cannot run is "not checked", never a failure
        return None
    if write:
        try:
            payload = {"checked_at": datetime.now(timezone.utc).isoformat(), "unsupported": found}
            tmp = output_dir / (FACTS_FILE + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, output_dir / FACTS_FILE)
        except OSError:
            pass
    return found


def load(output_dir: Path) -> list[dict] | None:
    """The unsupported list `check` last wrote, or None when missing or unreadable."""
    try:
        data = json.loads((output_dir / FACTS_FILE).read_text(encoding="utf-8"))
        items = data["unsupported"]
        return items if isinstance(items, list) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
