"""Guard (issue #367): no real person's email address or phone number in the saved test data, example
data or demo files. Saved job ads name their contact people; those are replaced with made-up ones
(`Rikke Holm`, `kontakt@example.com`, `00 00 00 00`) before a fixture is committed."""

import re
import subprocess
from pathlib import Path

from paths import REPO_ROOT

# The tracked text files this guard reads: saved payloads, golden files, test code, the example
# profile and the demo and design material.
_ROOTS = ("tests", "profile.example", "docs/demo", "docs/design", "scripts/demo", "app/demo-record", "app/src", "app/test", "app/journeys", "app/e2e", "app/e2e-web", "app/e2e-install")
_BINARY = re.compile(r"\.(png|gif|jpe?g|svg|ico|woff2?|pdf|tar\.gz|zip)$", re.I)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
# Made-up domains only: example.com/org/net, the one-letter x.* ones, acme.*, and the reserved TLDs.
_FAKE_DOMAIN = re.compile(r"(?i)(^|\.)(example\.(com|org|net|dk)|x\.(com|org|dk)|acme\.\w+|[a-z0-9-]+\.(test|invalid|example|localhost))$")
_FAKE_ADDRESSES = {"ada@gmail.com"}  # a sign-in in the app's tests
# The project's own contact, where a problem report is sent (pyproject's author): public on purpose.
_PROJECT_CONTACT = set(re.findall(r'email = "([^"]+)"', (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")))
# A Danish or Hungarian number after a word that introduces one ("tlf. 11 22 33 44", "på 55667788"),
# or with a country code on its own ("+45 99 88 77 66").
_PHONE = re.compile(
    r"(?i)(?:(?:\b(?:tlf|telefon|phone|mobil|mobile|tel|på|on|eller|or)\b\.?:?\s*|tel:)(?:\+\s?(?:45|36)\s?)?"
    r"|\+\s?(?:45|36)[\s.-]?)(\d{2}\s?\d{2}\s?\d{2}\s?\d{2})\b"
)
# Spaced in pairs with nothing around it ("<span>11 22 33 44</span>"), or a tel: link, its "+" and spaces
# possibly encoded ("tel:&#x2B;4511223344", "tlf:11%2022 33 44").
_PHONE_BARE = re.compile(
    r"(?i)(?<![\d.:/+-])(?<!\+ )(\d{2} \d{2} \d{2} \d{2})(?![\d.:/-])"
    r"|(?:tel|tlf):(?:\+|&#x2B;|%2B)?(?:45|36)?((?:\d|%20| ){8,12})"
)
# A Hungarian mobile: +36, a mobile prefix, then seven digits ("+36 30 123 4567").
_PHONE_HU_MOBILE = re.compile(r"\+\s?36[\s.-]?(?:20|30|31|50|70)[\s.-]?(\d{3}[\s.-]?\d{4})\b")
_FAKE_PHONES = {"00000000", "12345678", "0000000", "1234567"}


def _files() -> list:
    listed = subprocess.run(["git", "ls-files", *_ROOTS], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    own = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()  # its own examples are made up
    return [REPO_ROOT / f for f in listed.stdout.splitlines() if not _BINARY.search(f) and f != own]


def _text(path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def test_no_real_email_address_in_test_example_or_demo_data():
    found = []
    for path in _files():
        for m in _EMAIL.finditer(_text(path)):
            if m.group(0).lower() not in _FAKE_ADDRESSES | _PROJECT_CONTACT and not _FAKE_DOMAIN.search(m.group(1)):
                found.append(f"{path.relative_to(REPO_ROOT)}: {m.group(0)}")
    assert found == []


def test_no_real_phone_number_in_test_example_or_demo_data():
    found = []
    for path in _files():
        text = _text(path).replace("&#x2B;", "+").replace("&#43;", "+")
        # A bare number is only looked for in saved payloads: elsewhere (an SVG path) digit runs are not phones.
        bare = _PHONE_BARE.finditer(text) if "/fixtures/" in path.as_posix() else ()
        for m in [*_PHONE.finditer(text), *bare]:
            number = next(g for g in m.groups() if g)
            digits = re.sub(r"\D", "", number.replace("%20", ""))[-8:]
            if len(digits) == 8 and digits not in _FAKE_PHONES:
                found.append(f"{path.relative_to(REPO_ROOT)}: {number}")
        for m in _PHONE_HU_MOBILE.finditer(text):
            if re.sub(r"\D", "", m.group(1)) not in _FAKE_PHONES:
                found.append(f"{path.relative_to(REPO_ROOT)}: {m.group(0)}")
    assert found == []


def test_the_guard_catches_what_it_is_for():
    assert _EMAIL.search("kontakt mette.berg@firma.dk") and not _FAKE_DOMAIN.search("firma.dk")
    assert _FAKE_DOMAIN.search("example.com") and _FAKE_DOMAIN.search("jobs.example.org")
    assert _PHONE.search("på tlf. 11 22 33 44").group(1) == "11 22 33 44"
    assert _PHONE.search("på 55667788 eller").group(1) == "55667788"
    assert _PHONE.search("Manager +45 99 88 77 66").group(1) == "99 88 77 66"
    assert _PHONE.search("job 2026 10 30 12") is None
    assert _PHONE_BARE.search("<span>11 22 33 44</span>").group(1) == "11 22 33 44"
    assert _PHONE_HU_MOBILE.search("**Phone:** +36 30 123 4567 |").group(1) == "123 4567"
    assert _PHONE_HU_MOBILE.search("+36-20-1234567").group(1) == "1234567"
    assert _PHONE_BARE.search('href="tel:&#x2B;4511223344"').group(2) == "11223344"
    assert _PHONE_BARE.search('href="tlf:11%2022 33 44"').group(2) == "11%2022 33 44"
    assert _PHONE_BARE.search("v1.20 30 40 50") is None


# Credentials that a saved page can carry (a site's own Maps key, a token) and a secret scanner flags.
_SECRET = re.compile(
    r"(sk-ant-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{35}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[bap]-[A-Za-z0-9-]{10,}|ya29\.[A-Za-z0-9_-]{20,})"
)
_FAKE_SECRET = re.compile(r"^AIza0+$")


def test_no_credential_in_test_example_or_demo_data():
    found = [f"{path.relative_to(REPO_ROOT)}: {m.group(0)[:12]}…" for path in _files()
             for m in _SECRET.finditer(_text(path)) if not _FAKE_SECRET.match(m.group(0))]
    assert found == []
