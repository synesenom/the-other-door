"""Scrub a real CV PDF for the test corpus: every word of its text becomes a French word of about the same
width, never one of the original; icons, rules, colours and positions stay as they are.

Made for pdfTeX PDFs (words placed by kerns, no space glyphs); a Word or Canva PDF needs changes first.
Needs pikepdf, which is not a project dependency: run it from its own venv (`python -m venv v && v/bin/pip install pikepdf`).

usage: scrub_pdf.py <in.pdf> <out.pdf> <words.json>   (words.json from `scrub_check.py words <in.pdf>`)
Then check with `scrub_check.py check <in.pdf> <out.pdf> <words.json>` and look at the render.
Never commit the original or words.json: they hold the person's text.
"""
from __future__ import annotations

import json
import random
import sys

import pikepdf

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
}
NAME_TO_CHAR = {v: k for k, v in ACCENTS.items()}
DIGIT_NAMES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
SPACE_KERN = -150

rng = random.Random(154)


LIGATURES = {n: "f" for n in ("ff", "fi", "fl", "ffi", "ffl", "uniFB00", "uniFB01", "uniFB02", "uniFB03", "uniFB04")}


def glyph_char(name: str) -> str | None:
    if len(name) == 1 and name.isascii() and name.isalpha():
        return name
    return NAME_TO_CHAR.get(name) or LIGATURES.get(name)


class Font:
    def __init__(self, font):
        names: dict[int, str] = {}
        for c in range(32, 127):
            ch = chr(c)
            if ch.isalpha():
                names[c] = ch
            elif "0" <= ch <= "9":
                names[c] = DIGIT_NAMES[int(ch)]
        enc = font.get("/Encoding")
        if isinstance(enc, pikepdf.Dictionary) and "/Differences" in enc:
            code = 0
            for item in enc.Differences:
                if isinstance(item, int):
                    code = int(item)
                else:
                    names[code] = str(item)[1:]
                    code += 1
        fd = font.get("/FontDescriptor")
        have = None
        if fd is not None and "/CharSet" in fd:
            have = {n for n in str(fd.CharSet).split("/") if n}
        self.char_of = {c: glyph_char(n) for c, n in names.items() if glyph_char(n)}
        self.digit_of = {c: n for c, n in names.items() if n in DIGIT_NAMES}
        self.code_for_char = {glyph_char(n): c for c, n in names.items()
                              if glyph_char(n) and n not in LIGATURES and (have is None or n in have)}
        self.code_for_digit = [c for c, n in names.items() if n in DIGIT_NAMES and (have is None or n in have)]
        first = int(font.get("/FirstChar", 0))
        widths = [float(w) for w in font.get("/Widths", [])]
        self.width = lambda c: widths[c - first] if 0 <= c - first < len(widths) else 0.0

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
    """A French word (or two run together) in this case whose width is closest to the original's."""
    pool = [styled(w, case) for w in FRENCH if w not in banned and font.can_write(styled(w, case), [False] * len(w))]
    if letters <= 2:
        short = [w for w in pool if len(w) <= 2]
        pool = short or pool
    if not pool:
        return ""
    width = {w: font.word_width(w, [False] * len(w)) for w in pool}
    best = sorted(pool, key=lambda w: abs(width[w] - target))[:2]
    word = rng.choice(best)
    if abs(width[word] - target) > 0.08 * target and letters > 6:
        tail_case = "upper" if case == "upper" else "lower"
        tails = [styled(w, tail_case) for w in FRENCH if w not in banned and len(w) > 2
                 and font.can_write(styled(w, tail_case), [False] * len(w))]
        tw = {w: font.word_width(w, [False] * len(w)) for w in tails}
        pairs = sorted(((a, b) for a in pool if len(a) > 2 for b in tails),
                       key=lambda ab: abs(width[ab[0]] + tw[ab[1]] - target))[:3]
        if pairs and abs(width[pairs[0][0]] + tw[pairs[0][1]] - target) < abs(width[word] - target):
            a, b = rng.choice(pairs)
            word = a + b
    return word


def scrub_op(font: Font, items: list, banned: set[str]) -> list:
    """items: a TJ array as a list of bytes and numbers. Each word is replaced whole (any length) where its
    first letter was; its width difference is added back at the next word break, so words start where they did."""
    positions = []
    for i, item in enumerate(items):
        if isinstance(item, bytes):
            for j, b in enumerate(item):
                positions.append((i, j) if b in font.char_of else None)
        elif item < SPACE_KERN:
            positions.append(None)
    words, cur = [], []
    for p in positions + [None]:
        if p is None:
            if cur:
                words.append(cur)
            cur = []
        else:
            cur.append(p)
    first_of, in_word = {}, set()
    for word in words:
        pattern = [font.char_of[items[i][j]].isupper() for i, j in word]
        target = sum(font.width(items[i][j]) for i, j in word)
        fr = pick(font, target, case_of(pattern), banned, len(word))
        first_of[word[0]] = bytes(font.code_for_char[ch] for ch in fr)
        in_word.update(word)
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
            if (i, j) in first_of:
                buf += first_of[(i, j)]
                owed += sum(font.width(c) for c in first_of[(i, j)])
            elif (i, j) not in in_word and b in font.digit_of and font.code_for_digit:
                buf.append(rng.choice(font.code_for_digit))
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


def main(src: str, dst: str, words_json: str) -> None:
    banned = {w.lower() for w in json.loads(open(words_json).read())}
    pdf = pikepdf.open(src)
    for page in pdf.pages:
        fonts = {name: Font(f) for name, f in page.Resources.get("/Font", {}).items()
                 if "fontawesome" not in str(f.get("/BaseFont", "")).lower()}
        cur, size, new_ops, carry_pt = None, 1.0, [], 0.0
        for operands, op in pikepdf.parse_content_stream(page):
            o = str(op)
            if o == "Tf":
                cur, size = str(operands[0]), float(operands[1])
            if o in ("Td", "TD", "Tm", "T*", "BT", "ET", "'", '"'):
                carry_pt = 0.0
            font = fonts.get(cur)
            if font and o in ("'", '"'):
                raise SystemExit(f"unhandled text operator {o}")
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
        if "/Annots" in page:
            del page.Annots
    for key in ("/Outlines", "/Names", "/Metadata", "/PageLabels"):
        if key in pdf.Root:
            del pdf.Root[key]
    if "/Info" in pdf.trailer:
        del pdf.trailer["/Info"]
    pdf.remove_unreferenced_resources()
    pdf.save(dst, compress_streams=True)
    print("done")


if __name__ == "__main__":
    main(*sys.argv[1:4])
