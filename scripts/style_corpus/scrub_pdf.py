"""Scrub a real CV PDF for the test corpus: every word of its text becomes a French word of about the same
width, never one of the original, and every number other digits with none of the original's numbers inside;
icons, rules, colours and positions stay as they are.

Made for pdfTeX PDFs (words placed by kerns, no space glyphs), Quartz ones (Apple Pages: subset TrueType fonts in
MacRoman, real space glyphs; a glyph of width 0 is not in the subset, so no word is written with
it), and Word, Google Docs and Canva ones (Type0 fonts, Identity-H, and Skia's Type3 fallback fonts, glyphs placed one
by one or in TJ arrays), whose tagged structure (StructTreeRoot, ActualText, Alt) goes too. One path for all of them,
the page's and every form's text alike (rewrite_content). Every image becomes a flat grey box of its size (a photo, a
logo). Every colour turns round the colour wheel by one random angle, greys kept
(turn_colour). Links, outlines, forms, XMP and the document info but its Creator and Producer go.
Needs pikepdf, which is not a project dependency: run it from its own venv (`python -m venv v && v/bin/pip install pikepdf`).

usage: scrub_pdf.py <in.pdf> <out.pdf> <words.json>   (words.json from `scrub_check.py words <in.pdf>`, plus the
words and numbers of the original's links and document info, which the text does not show)
Then check with `scrub_check.py check <in.pdf> <out.pdf> <words.json>` and look at the render.
Never commit the original or words.json: they hold the person's text.
"""
from __future__ import annotations

import colorsys
import json
import random
import re
import sys
import unicodedata
import zlib
from numbers import Number
from typing import NamedTuple

FRENCH = """
à a ô y au de du la le les un une et ou en il on ni si sa se ce ne
été âge air ami art bas bel bon cas ciel col cou cri dos eau élan fil fin fou gaz île jeu lac lit loi
mer mot nez nid nuit oie ours pain pied pré rue sel sol son thé toit vent vie voix
arbre autre avoir blanc bleue bois bruit calme chant chose clair coeur corps côté danse doigt douce
école encre étoile étude faire fleur forêt froid fruit genou glace grâce herbe heure hiver image jardin
jaune jouer large lampe lèvre livre loin lourd lune maison marché matin merle midi monde montre neige
noire nuage ombre orage pâle papier parler passer pêche petit pierre place plage pluie plume poème
pomme porte poule prendre rêve rivière robe rouge saison salle sable sapin soleil sourire table temps
terre tigre toile train trésor vague valise verre village ville violet voyage
abeille ardoise automne bateau bougie cabane caillou campagne cerise chemin cheval chemise citron
colline couleur couteau crayon cuisine dentelle désert dimanche écharpe enfance épaule escalier
étrange fenêtre feuille fontaine fraise fromage gâteau grenier guitare horizon hirondelle journée
lumière lointain marelle matinée mélodie mémoire minuit montagne musique nuageux océan olivier
orange oreiller panier papillon parapluie paysage pinceau plafond prairie printemps promenade
quartier raisin rideau rivage ruisseau sentier silence soirée sorcière tableau tempête théâtre
tilleul tiroir tonnerre tortue tranquille trottoir vacances vallée velours verger vitrail
aquarelle arrosoir bibliothèque bicyclette boulangerie cerisier champignon chocolat cheminée
coquillage crépuscule escargot étincelle feuillage framboise grenouille marronnier moissonneur
nénuphar parfumerie pâquerette perroquet rossignol sauterelle tournesol vagabondage
balançoire chuchotement émerveillement ensoleillement éparpillement gribouillage marchandise
majestueusement merveilleusement renouvellement tourbillonnement silencieusement
""".split()
ACCENTS = {
    "é": "eacute", "è": "egrave", "ê": "ecircumflex", "ë": "edieresis", "à": "agrave", "â": "acircumflex",
    "ç": "ccedilla", "ö": "odieresis", "œ": "oe", "î": "icircumflex", "ï": "idieresis", "ô": "ocircumflex", "ù": "ugrave", "û": "ucircumflex",
    "É": "Eacute", "È": "Egrave", "Ê": "Ecircumflex", "À": "Agrave", "Â": "Acircumflex", "Ç": "Ccedilla",
    "Î": "Icircumflex", "Ô": "Ocircumflex", "Û": "Ucircumflex",
    "ß": "germandbls", "æ": "ae", "Æ": "AE", "ø": "oslash", "Ø": "Oslash", "Œ": "OE",
}
MARKS = {"0301": "acute", "0300": "grave", "0302": "circumflex", "0308": "dieresis", "0303": "tilde",
         "030A": "ring", "0327": "cedilla", "030C": "caron", "030B": "hungarumlaut"}
BASE_CODECS = {"/MacRomanEncoding": "mac_roman", "/WinAnsiEncoding": "cp1252"}
DIGIT_NAMES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
INFO_KEPT = ("/Creator", "/Producer")
GREY = 0xB4

rng = random.Random(154)


LIGATURES = {n: "f" for n in ("ff", "fi", "fl", "ffi", "ffl", "uniFB00", "uniFB01", "uniFB02", "uniFB03", "uniFB04")}


def glyph_name(ch: str) -> str | None:
    """The PostScript name of a Latin letter: 'a', 'eacute', 'Aring'; None for anything else."""
    if ch.isascii():
        return ch if ch.isalpha() else None
    if ch in ACCENTS:
        return ACCENTS[ch]
    parts = unicodedata.decomposition(ch).split()
    if len(parts) == 2 and parts[1] in MARKS and chr(int(parts[0], 16)).isascii():
        return chr(int(parts[0], 16)) + MARKS[parts[1]]
    return None


NAME_TO_CHAR = {glyph_name(ch): ch for codec in BASE_CODECS.values() for ch in bytes(range(128, 256)).decode(codec, "ignore")
                if glyph_name(ch)} | {v: k for k, v in ACCENTS.items()}


def glyph_char(name: str) -> str | None:
    if len(name) == 1 and name.isascii() and name.isalpha():
        return name
    return NAME_TO_CHAR.get(name) or LIGATURES.get(name)


def encoding_names(base: str | None) -> dict[int, str]:
    """Code to glyph name of a simple font's base encoding: ASCII letters and digits always; the space and the
    accented letters of a named one (MacRoman, WinAnsi). Without one (a TeX font's own), code 32 is no space."""
    names: dict[int, str] = {}
    for c in range(32, 127):
        ch = chr(c)
        if ch.isalpha():
            names[c] = ch
        elif "0" <= ch <= "9":
            names[c] = DIGIT_NAMES[int(ch)]
    if base in BASE_CODECS or base == "/StandardEncoding":
        names[32] = "space"
    if base in BASE_CODECS:
        for c in range(128, 256):
            ch = bytes([c]).decode(BASE_CODECS[base], "ignore")
            if ch == "ﬁ" or ch == "ﬂ":
                names[c] = "fi" if ch == "ﬁ" else "fl"
            elif ch and glyph_name(ch):
                names[c] = glyph_name(ch)
    return names


def kept_info(info: dict) -> dict:
    """What stays of the document info: the names of the programs that made the PDF, nothing about its author."""
    return {k: v for k, v in info.items() if k in INFO_KEPT}


class Font:
    """A simple font's codes: which are letters (char_of), digits and spaces, and which letters can be written
    (code_for_char: in the font's CharSet when it has one, else of a width above 0, as a subset font gives the
    glyphs it left out)."""

    def __init__(self, names: dict[int, str], widths, first: int = 0, charset: set[str] | None = None,
                 code_len: int = 1, codes: set[int] | None = None):
        """*widths*: a list from code *first*, or a function of the code; *code_len* the bytes of a code; *codes*
        the codes of a Type0 font's subset (its /W)."""
        self.code_len = code_len
        self.width = widths if callable(widths) else lambda c: widths[c - first] if 0 <= c - first < len(widths) else 0.0
        if charset is not None:
            have = lambda c, n: n in charset  # noqa: E731
        elif codes is not None:
            have = lambda c, n: c in codes  # noqa: E731
        else:
            have = lambda c, n: self.width(c) > 0  # noqa: E731
        self.char_of = {c: glyph_char(n) for c, n in names.items() if glyph_char(n)}
        self.digit_of = {c: n for c, n in names.items() if n in DIGIT_NAMES}
        self.space_codes = {c for c, n in names.items() if n == "space"}
        self.code_for_char = {glyph_char(n): c for c, n in names.items()
                              if glyph_char(n) and n not in LIGATURES and have(c, n)}
        self.code_for_digit = [c for c, n in names.items() if n in DIGIT_NAMES and have(c, n)]

    @classmethod
    def from_unicode(cls, chars: dict[int, str], width, code_len: int, codes: set[int] | None = None) -> "Font":
        """A font known by what its ToUnicode says each code is (Type0, Type3). A value of several letters is a
        ligature: read as an f, never written."""
        names, extra = {}, {}
        for c, u in chars.items():
            if u in (" ", "\u00a0"):
                names[c] = "space"
            elif len(u) == 1 and "0" <= u <= "9":
                names[c] = DIGIT_NAMES[int(u)]
            elif len(u) > 1 and u.isalpha():
                names[c] = "ff"
            elif len(u) == 1 and glyph_name(u) and glyph_char(glyph_name(u)):
                names[c] = glyph_name(u)
            elif len(u) == 1 and u.isalpha() and unicodedata.name(u, "").startswith("LATIN"):
                extra[c] = u  # ő, ř, ł...: a letter of a word, read as one (replaced with it), never written
        font = cls(names, width, code_len=code_len, codes=codes)
        font.char_of.update(extra)
        return font

    def kind(self, code: int) -> str | None:
        return "char_of" if code in self.char_of else "digit_of" if code in self.digit_of else None

    @classmethod
    def from_pdf(cls, font) -> "Font":
        import pikepdf

        if font.get("/Subtype") in ("/Type0", "/Type3"):
            chars = parse_tounicode(font.ToUnicode.read_bytes().decode("latin-1")) if "/ToUnicode" in font else {}
            if font.Subtype == "/Type3":
                first, scale = int(font.get("/FirstChar", 0)), float(font.FontMatrix[0]) * 1000
                widths = [float(w) * scale for w in font.get("/Widths", [])]
                return cls.from_unicode(chars, lambda c: widths[c - first] if 0 <= c - first < len(widths) else 0.0, 1)
            desc = font.DescendantFonts[0]
            w = parse_w([[float(y) for y in x] if isinstance(x, pikepdf.Array) else float(x) for x in desc.get("/W", [])])
            dw = float(desc.get("/DW", 1000))
            return cls.from_unicode(chars, lambda c: w.get(c, dw), 2, set(w))
        enc = font.get("/Encoding")
        base = str(enc) if isinstance(enc, pikepdf.Name) else (
            str(enc.get("/BaseEncoding")) if isinstance(enc, pikepdf.Dictionary) and "/BaseEncoding" in enc else None)
        names = encoding_names(base)
        if isinstance(enc, pikepdf.Dictionary) and "/Differences" in enc:
            code = 0
            for item in enc.Differences:
                if isinstance(item, int):
                    code = int(item)
                else:
                    names[code] = str(item)[1:]
                    code += 1
        fd = font.get("/FontDescriptor")
        charset = {n for n in str(fd.CharSet).split("/") if n} if fd is not None and "/CharSet" in fd else None
        return cls(names, [float(w) for w in font.get("/Widths", [])], int(font.get("/FirstChar", 0)), charset)

    def word_width(self, word: str, pattern: list[bool]) -> float:
        return sum(self.width(self.code_for_char[ch.upper() if up else ch]) for ch, up in zip(word, pattern))

    def can_write(self, word: str, pattern: list[bool]) -> bool:
        return all((ch.upper() if up else ch) in self.code_for_char for ch, up in zip(word, pattern))


def case_of(pattern: list[bool]) -> str:
    if all(pattern):
        return "upper"
    return "title" if pattern and pattern[0] else "lower"


def styled(word: str, case: str) -> str:
    return word.upper() if case == "upper" else word[:1].upper() + word[1:] if case == "title" else word


def pick(font: Font, target: float, case: str, banned: set[str], letters: int, spacing: float = 0.0) -> str:
    """A French word (or two run together) in this case whose width is closest to the original's; too wide counts
    three times as much as too narrow, since a wider word eats the space after it. A one-letter word stays one
    letter, of the width nearest its own: "à", "a", "y" or a letter of the font in its case, else in the other (a
    narrow "I" becomes an "l", not "Il", "A" or "J", which would run into the word after it). *spacing*: what the
    character spacing (Tc) adds after each letter, counted in every width."""
    wide = lambda w: font.word_width(w, [False] * len(w)) + spacing * len(w)  # noqa: E731
    pool = [styled(w, case) for w in FRENCH if w not in banned and font.can_write(styled(w, case), [False] * len(w))]
    if letters == 1:
        own = [ch for ch in font.code_for_char if ch.isalpha() and ch.lower() not in banned]
        pool = [w for w in pool if len(w) == 1] + [ch for ch in own if ch.islower() == (case == "lower")]
        if not any(abs(wide(w) - target) <= 0.25 * target for w in pool):
            pool += [ch for ch in own if ch.islower() != (case == "lower")]
        pool = sorted(set(pool))
    elif letters == 2:
        short = [w for w in pool if len(w) <= 2]
        pool = short or pool
    if not pool:
        return made_up(font, case, banned, letters)
    off = lambda w: 3 * (w - target) if w > target else target - w  # noqa: E731
    width = {w: wide(w) for w in pool}
    best = sorted(pool, key=lambda w: off(width[w]))[:2]
    if letters == 1:  # among letters, one far off the best is no choice
        best = [w for w in best if off(width[w]) <= off(width[best[0]]) + 0.1 * target]
    word = rng.choice(best)
    if abs(width[word] - target) > 0.08 * target and letters > 6:
        tail_case = "upper" if case == "upper" else "lower"
        tails = [styled(w, tail_case) for w in FRENCH if w not in banned and len(w) > 2
                 and font.can_write(styled(w, tail_case), [False] * len(w))]
        tw = {w: wide(w) for w in tails}
        pairs = sorted(((a, b) for a in pool if len(a) > 2 for b in tails),
                       key=lambda ab: off(width[ab[0]] + tw[ab[1]]))[:3]
        if pairs and off(width[pairs[0][0]] + tw[pairs[0][1]]) < off(width[word]):
            a, b = rng.choice(pairs)
            word = a + b
    return word


def made_up(font: Font, case: str, banned: set[str], letters: int) -> str:
    """When a subset font cannot write any French word in this case: as many of its own letters, never a banned word."""
    have = [ch for ch in font.code_for_char if ch.isalpha()]
    upper = [ch for ch in have if ch.isupper()] or have
    lower = [ch for ch in have if ch.islower()] or have
    if not have:
        return ""
    for _ in range(50):
        word = "".join(rng.choice(upper if case == "upper" or (case == "title" and k == 0) else lower)
                       for k in range(letters))
        if word.lower() not in banned:
            break
    return word


def new_number(length: int, digits: list[int], banned: set[str]) -> str:
    """*length* random digits of these, with no banned number of two digits or more inside them."""
    numbers = [b for b in banned if b.isdigit() and len(b) >= 2]
    for _ in range(500):
        number = "".join(str(rng.choice(digits)) for _ in range(length))
        if not any(b in number for b in numbers):
            return number
    raise SystemExit(f"no {length}-digit number avoids the original's")


def _hex_chars(h: str) -> str:
    return bytes.fromhex(h).decode("utf-16-be", "replace")


def parse_tounicode(cmap: str) -> dict[int, str]:
    """A ToUnicode CMap's code to text: bfchar pairs, bfrange with a start or an array of values."""
    found: dict[int, str] = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            found[int(src, 16)] = _hex_chars(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", cmap, re.S):
        for lo, hi, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])", block):
            if dst.startswith("["):
                values = [_hex_chars(v) for v in re.findall(r"<([0-9A-Fa-f]*)>", dst)]
            else:
                start = _hex_chars(dst[1:-1])
                values = [start[:-1] + chr(ord(start[-1]) + k) for k in range(int(hi, 16) - int(lo, 16) + 1)]
            found.update({int(lo, 16) + k: v for k, v in enumerate(values)})
    return found


def parse_w(array: list) -> dict[int, float]:
    """A CIDFont's /W as code to width: `c [w1 w2 ...]` and `c1 c2 w`."""
    found, i = {}, 0
    while i < len(array):
        if isinstance(array[i + 1], list):
            found.update({int(array[i]) + k: float(w) for k, w in enumerate(array[i + 1])})
            i += 2
        else:
            found.update({c: float(array[i + 2]) for c in range(int(array[i]), int(array[i + 1]) + 1)})
            i += 3
    return found


class Glyph(NamedTuple):
    """Text drawn in one font and size from (x, y) of the text matrix *tm*, with the character and word spacing in
    force; *data* is one code, or a replaced word's."""
    tm: tuple | None
    font: str
    size: float
    x: float
    y: float
    data: bytes
    tc: float = 0.0
    tw: float = 0.0


WORD_GAP = 0.15  # of the font size: a wider gap between two glyphs ends a word (pdfTeX's glue is 0.22-0.33)


def advance(f: Font, size: float, tc: float, tw: float, data: bytes) -> float:
    """How far these codes move the pen: each glyph's width, the character spacing after each, and the word spacing
    after a single-byte code 32."""
    codes = [int.from_bytes(data[k:k + f.code_len], "big") for k in range(0, len(data), f.code_len)]
    return sum(f.width(c) * size / 1000 + tc + (tw if c == 32 and f.code_len == 1 else 0.0) for c in codes)


def glyphs_of(ops: list, fonts: dict) -> list:
    """A page's operators with every text block read into Glyphs at their positions in the text matrix's space
    (one per code); the operators that only place text (Tf, Tm, Td, TD, T*, ' and ") go, the writer puts the glyphs
    back; the rest stay where they were. Tz and Ts are refused: nothing here would move for them."""
    out, text, saved = [], False, []
    tm, font, size, lx, ly, x, tc, tw, tl = None, None, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    for op, operands in ops:
        if op == "q":
            saved.append((tc, tw, tl, font, size))
        elif op == "Q":
            tc, tw, tl, font, size = saved.pop() if saved else (0.0, 0.0, 0.0, None, 1.0)
        elif op == "Tc":
            tc = float(operands[0])
        elif op == "Tw":
            tw = float(operands[0])
        elif op == "TL":
            tl = float(operands[0])
        if op == "BT":
            tm, lx, ly, x, text = None, 0.0, 0.0, 0.0, True
        elif op == "ET":
            text = False
        if not text or op in ("BT", "ET"):
            out.append((op, operands))
            continue
        if op == '"':
            tw, tc = float(operands[0]), float(operands[1])
            out += [("Tw", [tw]), ("Tc", [tc])]
        if op == "TD":
            tl = -float(operands[1])
        if op == "Tf":
            font, size = str(operands[0]), float(operands[1])
        elif op == "Tm":
            tm, lx, ly, x = tuple(float(v) for v in operands), 0.0, 0.0, 0.0
        elif op in ("Td", "TD", "T*", "'", '"'):
            dx, dy = (float(operands[0]), float(operands[1])) if op in ("Td", "TD") else (0.0, -tl)
            lx, ly = lx + dx, ly + dy
            x = lx
        elif op in ("Tz", "Ts"):
            raise SystemExit(f"unhandled text operator {op}")
        elif op not in ("Tj", "TJ"):
            out.append((op, operands))
        if op in ("Tj", "TJ", "'", '"'):
            f = fonts[font]
            for item in operands[0] if op == "TJ" else [operands[-1]]:
                if not isinstance(item, bytes):
                    x -= float(item) * size / 1000
                    continue
                for k in range(0, len(item), f.code_len):
                    data = item[k:k + f.code_len]
                    out.append(Glyph(tm, font, size, x, ly, data, tc, tw))
                    x += advance(f, size, tc, tw, data)
    return out


def rewrite_content(ops: list, fonts: dict, banned: set[str]) -> list:
    """The page's operators with each word of its text replaced: a run of letters, or of digits, in one font drawn one
    after the other (follows), by a French word of about its width (pick), or as many other digits with none of the
    original's numbers inside them. The rest of a token (the marks and words joined to it: an email, a URL, a bracket
    set in a block of its own) moves with the new word's end; the next token starts where it did."""
    stream, runs_out = glyphs_of(ops, fonts), []
    i, shift, prev, prev_end = 0, 0.0, None, 0.0  # shift: in page space
    while i < len(stream):
        g = stream[i]
        if not isinstance(g, Glyph):
            runs_out.append(g)
            i += 1
            continue
        f = fonts[g.font]
        width = lambda glyph: advance(f, g.size, g.tc, g.tw, glyph.data)  # noqa: E731
        kind = lambda glyph: f.kind(int.from_bytes(glyph.data, "big"))  # noqa: E731
        if int.from_bytes(g.data, "big") in f.space_codes or prev is None or not follows(prev, g, prev_end):
            shift = 0.0
        k, j, end = kind(g), i + 1, g.x + width(g)
        while k and j < len(stream) and follows(g, stream[j], end) and stream[j][:3] == g[:3] and kind(stream[j]) == k:
            end = stream[j].x + width(stream[j])
            j += 1
        run = [int.from_bytes(x.data, "big") for x in stream[i:j]]
        data = g.data
        if k == "char_of":
            original = "".join(f.char_of[c] for c in run)
            word = pick(f, (end - g.x) * 1000 / g.size, case_of([ch.isupper() for ch in original]),
                        banned | {original.lower()}, len(run), g.tc * 1000 / g.size)
            data = b"".join(f.code_for_char[ch].to_bytes(f.code_len, "big") for ch in word) or data
        elif k == "digit_of" and f.code_for_digit:
            digit_code = {DIGIT_NAMES.index(f.digit_of[c]): c for c in f.code_for_digit}
            data = b"".join(digit_code[int(d)].to_bytes(f.code_len, "big") for d in new_number(len(run), sorted(digit_code), banned))
        scale = (g.tm or (1.0,))[0]
        runs_out.append(g._replace(x=g.x + shift / scale, data=data))
        shift += (width(g._replace(data=data)) - (end - g.x)) * scale
        i, prev, prev_end = j, stream[j - 1], end
    return _written(runs_out, fonts)


def _on_page(g: Glyph, x: float) -> tuple[float, float]:
    """Where a point at *x* on *g*'s line lies on the page (its text matrix applied)."""
    a, b, c, d, e, f = g.tm or (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    return a * x + c * g.y + e, b * x + d * g.y + f


def follows(a: Glyph, b, end: float) -> bool:
    """Whether glyph *b* is drawn right after glyph *a* (which ends at *end*), in whatever block: on the same line of
    the page, with no gap over WORD_GAP of a's size between them."""
    if not isinstance(b, Glyph):
        return False
    (ax, ay), (bx, by) = _on_page(a, end), _on_page(b, b.x)
    size = a.size * (a.tm or (1.0,))[0]
    return abs(by - ay) < 0.1 * size and -0.1 * size <= bx - ax <= WORD_GAP * size


def _written(stream: list, fonts: dict) -> list:
    """Glyphs back as operators: Tf and Tm at each block's first glyph and when they change, a Td to each line, the
    line as one TJ whose kerns put each glyph at its x (a reader finds pdfTeX's word breaks in those kerns)."""
    unset = object()
    out, tm, font, size, px, py, end = [], unset, None, None, 0.0, 0.0, None
    for g in stream:
        if not isinstance(g, Glyph):
            out.append(g)
            end = None
            if g[0] == "BT":  # a new block starts from the identity matrix, and a Q before it may have dropped the font
                tm, font, px, py = unset, None, 0.0, 0.0
            continue
        if (g.font, g.size) != (font, size):
            font, size, end = g.font, g.size, None
            out.append(("Tf", [font, size]))
        if g.tm != tm:
            tm, px, py, end = g.tm, 0.0, 0.0, None
            out.append(("Tm", list(tm or (1.0, 0, 0, 1.0, 0, 0))))
        if end is None or g.y != py:
            out += [("Td", [round(g.x - px, 4), round(g.y - py, 4)]), ("TJ", [[]])]
            px, py, end = g.x, g.y, g.x
        line = out[-1][1][0]
        kern = round((end - g.x) * 1000 / g.size, 3)
        if abs(kern) > 0.01:
            line.append(kern)
        if line and isinstance(line[-1], bytes):
            line[-1] += g.data
        else:
            line.append(g.data)
        end = g.x + advance(fonts[g.font], g.size, g.tc, g.tw, g.data)
    return [("Tj", [args[0][0]]) if op == "TJ" and len(args[0]) == 1 else (op, args) for op, args in out]


COLOUR_OPS = ("rg", "RG", "sc", "SC", "scn", "SCN")


def luminance(rgb: tuple) -> float:
    """How light a colour looks (WCAG relative luminance), what its contrast with the page is worked out from."""
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def turn_colour(rgb: tuple, turn: float) -> tuple:
    """An RGB colour turned `turn` degrees round the colour wheel, its saturation and how light it looks kept: the
    CV's own colours go, its contrast and which colour is its accent stay. A grey (black and white too) stays."""
    if max(rgb) - min(rgb) < 0.01:
        return rgb
    h, _, s = colorsys.rgb_to_hls(*rgb)
    h, target, low, high = (h + turn / 360) % 1, luminance(rgb), 0.0, 1.0
    for _ in range(30):
        mid = (low + high) / 2
        low, high = (mid, high) if luminance(colorsys.hls_to_rgb(h, mid, s)) < target else (low, mid)
    return tuple(round(c, 3) for c in colorsys.hls_to_rgb(h, (low + high) / 2, s))


def recolour_ops(ops: list, turn: float) -> list:
    """Content operators with each three-number fill or stroke colour turned (turn_colour); everything else kept."""
    return [(list(turn_colour(tuple(float(x) for x in operands), turn)), op)
            if str(op) in COLOUR_OPS and len(operands) == 3
            else (operands, op) for operands, op in ops]


def colours_left(ops: list) -> int:
    """The colours recolour_ops leaves as they are: CMYK (k, K, four numbers), a shading painted (sh), a pattern's."""
    return sum(1 for operands, op in ops
               if str(op) in ("k", "K", "sh") or (str(op) in COLOUR_OPS and len(operands) != 3
                                                  and not (len(operands) == 1 and isinstance(operands[0], Number))))


def recolour(pdf, turn: float) -> int:
    """Every page's and form's colours turned by the same angle (recolour_ops); returns colours_left over them."""
    import pikepdf

    left = 0

    def redo(obj):
        nonlocal left
        ops = list(pikepdf.parse_content_stream(obj))
        left += colours_left(ops)
        return pikepdf.unparse_content_stream(recolour_ops(ops, turn))

    seen = set()
    for page in pdf.pages:
        page.Contents = pdf.make_stream(redo(page))
        stack = [page.Resources]
        while stack:
            for _, x in (stack.pop().get("/XObject") or {}).items():
                if x.get("/Subtype") == "/Form" and x.objgen not in seen:
                    seen.add(x.objgen)
                    x.write(redo(x))
                    if "/Resources" in x:
                        stack.append(x.Resources)
    return left


def grey_images(resources) -> int:
    """Every image of these resources (and of their forms) becomes a flat grey box of its size: a photo of the
    person or an employer's logo would name them. Returns how many."""
    import pikepdf

    count = 0
    for _, x in (resources.get("/XObject") or {}).items():
        if x.get("/Subtype") == "/Form" and "/Resources" in x:
            count += grey_images(x.Resources)
        elif x.get("/Subtype") == "/Image":
            w, h = int(x.Width), int(x.Height)
            for key in list(x.keys()):
                if key not in ("/Type", "/Subtype", "/Width", "/Height", "/Length"):
                    del x[key]
            x.write(zlib.compress(bytes([GREY]) * (w * h)), filter=pikepdf.Name.FlateDecode)
            x.ColorSpace, x.BitsPerComponent = pikepdf.Name.DeviceGray, 8
            count += 1
    return count


def page_ops(page, fonts: dict, banned: set[str]) -> list:
    """A page's (or form's) content as pikepdf operators: rewrite_content over its plain operands. Marked content
    keeps only its /MCID: /ActualText and /Alt are the CV's text again."""
    import pikepdf

    ops = []
    for operands, op in pikepdf.parse_content_stream(page):
        o = str(op)
        if o == "BI" or not isinstance(op, pikepdf.Operator):
            raise SystemExit(f"unhandled operator {o}")
        if o == "BDC" and len(operands) == 2 and isinstance(operands[1], pikepdf.Dictionary):
            operands = [operands[0], pikepdf.Dictionary({k: v for k, v in operands[1].items() if k == "/MCID"})]
        elif o in ("Tj", "'"):
            operands = [bytes(operands[0])]
        elif o == '"':
            operands = [float(operands[0]), float(operands[1]), bytes(operands[2])]
        elif o == "TJ":
            operands = [[bytes(x) if isinstance(x, pikepdf.String) else float(x) for x in operands[0]]]
        elif o in ("Tf", "Tm", "Td", "TD", "Tc", "Tw", "TL"):
            operands = [str(operands[0]), *map(float, operands[1:])] if o == "Tf" else [float(x) for x in operands]
        ops.append((o, list(operands)))

    def back(x):
        if isinstance(x, bytes):
            return pikepdf.String(x)
        if isinstance(x, list):
            return pikepdf.Array([back(y) for y in x])
        return pikepdf.Name(x) if isinstance(x, str) else x

    return [([back(x) for x in operands], pikepdf.Operator(o)) for o, operands in rewrite_content(ops, fonts, banned)]


def fonts_of(resources) -> dict:
    """Each font of these resources by its name; an icon font's codes are none of them letters or digits (FontAwesome's
    own encoding puts its icons on the codes of ASCII letters)."""
    fonts = {}
    for name, f in (resources.get("/Font") or {}).items():
        if f.get("/Subtype") not in ("/Type1", "/TrueType", "/MMType1", "/Type0", "/Type3"):
            raise SystemExit(f"unhandled font {f.get('/Subtype')} {f.get('/BaseFont')}")
        fonts[name] = Font.from_pdf(f)
        if "fontawesome" in str(f.get("/BaseFont", "")).lower():
            fonts[name].char_of, fonts[name].digit_of = {}, {}
    return fonts


def scrub_resources(resources, banned: set[str], seen: set | None = None) -> None:
    """Named marked-content property lists keep only their /MCID, and the text of each form XObject (recursively,
    with the form's own fonts, else these) is rewritten as the page's is."""
    import pikepdf

    seen = set() if seen is None else seen
    for _, props in (resources.get("/Properties") or {}).items():
        for key in [k for k in props.keys() if k != "/MCID"]:
            del props[key]
    for _, x in (resources.get("/XObject") or {}).items():
        if x.get("/Subtype") != "/Form" or x.objgen in seen:
            continue
        seen.add(x.objgen)
        res = x.get("/Resources", resources)
        data = pikepdf.unparse_content_stream(page_ops(x, fonts_of(res), banned))
        x.write(data)
        scrub_resources(res, banned, seen)


def _drop_page_keys(page) -> None:
    for key in ("/Annots", "/PieceInfo", "/Metadata", "/Thumb", "/StructParents"):
        if key in page:
            del page[key]


def main(src: str, dst: str, words_json: str) -> None:
    import pikepdf

    banned = {w.lower() for w in json.loads(open(words_json).read())}
    pdf = pikepdf.open(src)
    images = 0
    for page in pdf.pages:
        images += grey_images(page.Resources)
        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(page_ops(page, fonts_of(page.Resources), banned)))
        scrub_resources(page.Resources, banned)
        _drop_page_keys(page)
    for key in ("/StructTreeRoot", "/MarkInfo", "/Lang", "/Outlines", "/Names", "/Metadata", "/PageLabels", "/AcroForm", "/OpenAction", "/Threads", "/PieceInfo"):
        if key in pdf.Root:
            del pdf.Root[key]
    for obj in pdf.objects:  # XMP left on a font, an image or a form
        if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)) and "/Metadata" in obj:
            del obj["/Metadata"]
    if "/Info" in pdf.trailer:
        info = kept_info(dict(pdf.trailer.Info.items()))
        del pdf.trailer["/Info"]
        if info:
            pdf.trailer["/Info"] = pdf.make_indirect(pikepdf.Dictionary(info))
    left = recolour(pdf, random.SystemRandom().uniform(120, 240))  # never written down
    pdf.remove_unreferenced_resources()
    pdf.save(dst, compress_streams=True)
    print("done:", images, "image(s) greyed,", left, "colour(s) not turned (CMYK, shading, pattern: look at them)")


if __name__ == "__main__":
    main(*sys.argv[1:4])
