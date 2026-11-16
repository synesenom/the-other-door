"""Scrub a real CV PDF for the test corpus: every word of its text becomes a French word of about the same
width, never one of the original, and every number other digits with none of the original's numbers inside;
icons, rules, colours and positions stay as they are.

Made for pdfTeX PDFs (words placed by kerns, no space glyphs) and Quartz ones (Apple Pages: subset TrueType
fonts in MacRoman, real space glyphs; a glyph of width 0 is not in the subset, so no word is written with it);
a Word or Canva PDF (Type0 fonts, Identity-H) needs changes first. Every image becomes a flat grey box of its
size (a photo, a logo); links, outlines, forms, XMP and the document info but its Creator and Producer go.
Needs pikepdf, which is not a project dependency: run it from its own venv (`python -m venv v && v/bin/pip install pikepdf`).

usage: scrub_pdf.py <in.pdf> <out.pdf> <words.json>   (words.json from `scrub_check.py words <in.pdf>`, plus the
words and numbers of the original's links and document info, which the text does not show)
Then check with `scrub_check.py check <in.pdf> <out.pdf> <words.json>` and look at the render.
Never commit the original or words.json: they hold the person's text.
"""
from __future__ import annotations

import json
import random
import sys
import unicodedata
import zlib

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
SPACE_KERN = -150
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

    def __init__(self, names: dict[int, str], widths: list[float], first: int = 0, charset: set[str] | None = None):
        self.width = lambda c: widths[c - first] if 0 <= c - first < len(widths) else 0.0
        have = (lambda c, n: n in charset) if charset is not None else (lambda c, n: self.width(c) > 0)
        self.char_of = {c: glyph_char(n) for c, n in names.items() if glyph_char(n)}
        self.digit_of = {c: n for c, n in names.items() if n in DIGIT_NAMES}
        self.space_codes = {c for c, n in names.items() if n == "space"}
        self.code_for_char = {glyph_char(n): c for c, n in names.items()
                              if glyph_char(n) and n not in LIGATURES and have(c, n)}
        self.code_for_digit = [c for c, n in names.items() if n in DIGIT_NAMES and have(c, n)]

    @classmethod
    def from_pdf(cls, font) -> "Font":
        import pikepdf

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


def pick(font: Font, target: float, case: str, banned: set[str], letters: int) -> str:
    """A French word (or two run together) in this case whose width is closest to the original's; too wide counts
    three times as much as too narrow, since a wider word eats the space after it."""
    pool = [styled(w, case) for w in FRENCH if w not in banned and font.can_write(styled(w, case), [False] * len(w))]
    if letters <= 2:
        short = [w for w in pool if len(w) <= 2]
        pool = short or pool
    if not pool:
        return made_up(font, case, banned, letters)
    off = lambda w: 3 * (w - target) if w > target else target - w  # noqa: E731
    width = {w: font.word_width(w, [False] * len(w)) for w in pool}
    best = sorted(pool, key=lambda w: off(width[w]))[:2]
    word = rng.choice(best)
    if abs(width[word] - target) > 0.08 * target and letters > 6:
        tail_case = "upper" if case == "upper" else "lower"
        tails = [styled(w, tail_case) for w in FRENCH if w not in banned and len(w) > 2
                 and font.can_write(styled(w, tail_case), [False] * len(w))]
        tw = {w: font.word_width(w, [False] * len(w)) for w in tails}
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


def runs(items: list, member: dict) -> list[list[tuple[int, int]]]:
    """The (item, byte) positions of each unbroken run of codes in *member* through a TJ array; a wide kern breaks one."""
    positions = []
    for i, item in enumerate(items):
        if isinstance(item, bytes):
            positions += [(i, j) if b in member else None for j, b in enumerate(item)]
        elif item < SPACE_KERN:
            positions.append(None)
    found, cur = [], []
    for p in positions + [None]:
        if p is None:
            if cur:
                found.append(cur)
            cur = []
        else:
            cur.append(p)
    return found


def new_number(length: int, digits: list[int], banned: set[str]) -> str:
    """*length* random digits of these, with no banned number of two digits or more inside them."""
    numbers = [b for b in banned if b.isdigit() and len(b) >= 2]
    for _ in range(500):
        number = "".join(str(rng.choice(digits)) for _ in range(length))
        if not any(b in number for b in numbers):
            return number
    raise SystemExit(f"no {length}-digit number avoids the original's")


def scrub_op(font: Font, items: list, banned: set[str]) -> list:
    """items: a TJ array as a list of bytes and numbers. Each word is replaced whole (any length) where its
    first letter was; its width difference is added back at the next word break (a wide kern, or a space glyph),
    so words start where they did. A number becomes as many other digits, none of the original's numbers in it."""
    first_of, in_word = {}, set()
    for word in runs(items, font.char_of):
        pattern = [font.char_of[items[i][j]].isupper() for i, j in word]
        target = sum(font.width(items[i][j]) for i, j in word)
        fr = pick(font, target, case_of(pattern), banned, len(word))
        first_of[word[0]] = bytes(font.code_for_char[ch] for ch in fr)
        in_word.update(word)
    digit_code = {DIGIT_NAMES.index(font.digit_of[c]): c for c in font.code_for_digit}
    new_digit = {}
    for number in runs(items, font.digit_of) if digit_code else []:
        digits = new_number(len(number), sorted(digit_code), banned)
        new_digit.update({p: digit_code[int(d)] for p, d in zip(number, digits)})
    out, owed = [], 0.0
    for i, item in enumerate(items):
        if not isinstance(item, bytes):
            if item < SPACE_KERN and abs(owed) > 1e-6:
                # at a word space: what the words before it gained or lost is given back here,
                # so punctuation moves with its word and the next word starts where it did
                out.append(round(owed, 3))
                owed = 0.0
            out.append(item)
            continue
        buf = bytearray()
        for j, b in enumerate(item):
            if b in font.space_codes and abs(owed) > 1e-6:
                out += [bytes(buf), round(owed, 3)]  # a real space: given back before it, as at a wide kern
                buf, owed = bytearray(), 0.0
            if (i, j) in first_of:
                buf += first_of[(i, j)]
                owed += sum(font.width(c) for c in first_of[(i, j)])
            elif (i, j) in new_digit:
                buf.append(new_digit[(i, j)])
                owed += font.width(buf[-1])
            elif (i, j) not in in_word:
                buf.append(b)
                owed += font.width(b)
            owed -= font.width(b)
        out.append(bytes(buf))
    # tidy: no empty strings, adjacent numbers merged, a trailing number carried out of the run
    # (pdfium applies a number only before a string that draws something)
    tidy = []
    for x in out:
        if isinstance(x, bytes):
            if x:
                tidy.append(x)
        elif tidy and not isinstance(tidy[-1], bytes):
            tidy[-1] += x
        else:
            tidy.append(x)
    while tidy and not isinstance(tidy[-1], bytes):
        owed += tidy.pop()
    return tidy, owed


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


def main(src: str, dst: str, words_json: str) -> None:
    import pikepdf

    banned = {w.lower() for w in json.loads(open(words_json).read())}
    pdf = pikepdf.open(src)
    images = 0
    for page in pdf.pages:
        fonts = {}
        for name, f in page.Resources.get("/Font", {}).items():
            if "fontawesome" in str(f.get("/BaseFont", "")).lower():
                continue
            if f.get("/Subtype") not in ("/Type1", "/TrueType", "/MMType1"):
                raise SystemExit(f"unhandled font {f.get('/Subtype')} {f.get('/BaseFont')}")
            fonts[name] = Font.from_pdf(f)
        images += grey_images(page.Resources)
        cur, size, new_ops, carry_pt = None, 1.0, [], 0.0
        for operands, op in pikepdf.parse_content_stream(page):
            o = str(op)
            if o == "Tf":
                cur, size = str(operands[0]), float(operands[1])
            if o in ("Td", "TD", "Tm", "T*", "BT", "ET", "'", '"'):
                carry_pt = 0.0
            font = fonts.get(cur)
            if (font and o in ("'", '"')) or o == "BI":
                raise SystemExit(f"unhandled operator {o}")
            if font and o in ("Tj", "TJ"):
                src_items = [bytes(operands[0])] if o == "Tj" else [
                    bytes(x) if isinstance(x, pikepdf.String) else float(x) for x in operands[0]]
                items, owed = scrub_op(font, src_items, banned)
                if carry_pt:
                    items = [carry_pt * 1000 / size, *items]
                carry_pt = owed * size / 1000
                arr = pikepdf.Array([pikepdf.String(x) if isinstance(x, bytes) else round(x, 3) for x in items])
                operands, op = [arr], pikepdf.Operator("TJ")
            elif o in ("Tj", "TJ") and carry_pt:
                src_items = [operands[0]] if o == "Tj" else list(operands[0])
                operands, op = [pikepdf.Array([round(carry_pt * 1000 / size, 3), *src_items])], pikepdf.Operator("TJ")
                carry_pt = 0.0
            new_ops.append((operands, op))
        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(new_ops))
        for key in ("/Annots", "/PieceInfo", "/Metadata", "/Thumb"):
            if key in page:
                del page[key]
    for key in ("/Outlines", "/Names", "/Metadata", "/PageLabels", "/AcroForm", "/OpenAction", "/Threads", "/PieceInfo"):
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
    pdf.remove_unreferenced_resources()
    pdf.save(dst, compress_streams=True)
    print("done:", images, "image(s) greyed")


if __name__ == "__main__":
    main(*sys.argv[1:4])
