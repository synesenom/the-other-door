"""Salary estimate (#371), the pure parts: what the model is asked, and whether its answer can be trusted.

`build_input` condenses the ad and the CV's experience into the text of one question (no name, email or
phone); `parse` accepts an answer only when it has a sane range, a currency code and a source with a URL;
`years_of_experience` does the overlap arithmetic over the role years `core.cv_read` read, so the model need not guess. No network, no model call:
`commands/salary.py` asks.
"""

import re
from datetime import date

from door import i18n

_MAX_AD_LINES = 6
_MAX_CV_CHARS = 6000
_CODE = re.compile(r"[A-Z]{3}")
_PERIODS = ("month", "year")
_POSITIONS = ("below", "within", "above")


def _squash(text: str) -> str:
    return " ".join(str(text).split()).casefold()


def years_of_experience(reading: dict, cv_text: str, *, now_year: int | None = None) -> int | None:
    """Years covered by the CV's dated roles, overlaps counted once: the `###` entries under a section the reading
    calls `experience`, each with the start and end year the reading gave (an end it left out runs to `now_year`).
    A year the entry's dates do not contain is not trusted and the entry does not count.

    ``None`` when no role has a usable date range."""
    now_year = now_year or date.today().year
    kinds = [s.get("kind") for s in reading.get("sections") or []]
    unused = list(reading.get("entries") or [])
    spans, section = [], -1
    for line in (cv_text or "").splitlines():
        if line.startswith("## "):
            section += 1
        elif line.startswith("### ") and 0 <= section < len(kinds):
            heading = _squash(line[4:])
            entry = next((e for e in unused if _squash(e.get("heading") or "") == heading), None)
            if entry is None:
                continue
            unused.remove(entry)
            if kinds[section] != "experience":
                continue
            first, last = entry.get("start_year"), entry.get("end_year")
            dates = str(entry.get("dates") or "")
            if first is None or str(first) not in dates or (last is not None and str(last) not in dates):
                continue
            last = now_year if last is None else last
            if last >= first:
                spans.append((first, min(last, now_year)))
    if not spans:
        return None
    total, (cur_start, cur_end) = 0, (None, None)
    for first, last in sorted(spans):
        if cur_end is None or first > cur_end:
            total += (cur_end - cur_start) if cur_end is not None else 0
            cur_start, cur_end = first, last
        else:
            cur_end = max(cur_end, last)
    return total + (cur_end - cur_start)


def _salary_lines(description: str) -> list[str]:
    pattern = i18n.compile_words(i18n.marker_words("salary") + i18n.currency_words())
    lines = [ln.strip().lstrip("•*-").strip() for ln in (description or "").splitlines()]
    return [ln for ln in lines if ln and len(ln) <= 300 and pattern.search(ln)][:_MAX_AD_LINES]


def _experience_lines(description: str) -> list[str]:
    pattern = i18n.compile_words(i18n.marker_words("requirement") + list(i18n.seniority_words()))
    lines = [ln.strip().lstrip("•*-").strip() for ln in (description or "").splitlines()]
    found = [ln for ln in lines if ln and len(ln) <= 300 and re.search(r"\d", ln) and pattern.search(ln)]
    return found[:_MAX_AD_LINES]


def _anonymous_cv(cv_text: str, profile: dict, reading: dict) -> str:
    """The CV from its first `## ` line (the title and contact header never go), without the profile's name, email and
    phone, nor the name, email and contact details the reading found, each taken out as the literal text."""
    private = [str(profile.get(k)) for k in ("name", "email", "phone") if profile.get(k)]
    private += [part for part in str(profile.get("name") or "").split() if len(part) > 1]
    private += [str(reading.get(k)) for k in ("name", "email") if reading.get(k)]
    private += [str(c["value"]) for c in reading.get("contacts") or [] if c.get("value")]
    lines = (cv_text or "").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    text = "\n".join(lines[start:])
    for value in sorted(set(private), key=len, reverse=True):
        text = re.sub(re.escape(value), "", text, flags=re.IGNORECASE)
    return text.strip()[:_MAX_CV_CHARS]


def build_input(posting: dict, cv_text: str, profile: dict, reading: dict, *, now_year: int | None = None) -> str:
    """The question's text: the ad (title, company, place, country and currency, the ad's own salary
    and experience lines) and the candidate's experience (years counted from the reading `reading` of the CV, the CV without contact details)."""
    place = posting.get("location") or profile.get("location") or ""
    country = i18n.country_for_location(place) or i18n.country_for_location(str(profile.get("location") or ""))
    out = ["# The job", f"Title: {posting.get('title', '')}", f"Company: {posting.get('company', '')}",
           f"Location: {place}"]
    if country:
        out.append(f"Country: {country.name} (currency written as: {', '.join(country.currency)})")
    ad_salary = _salary_lines(posting.get("description", ""))
    out.append("The ad's own salary lines:" + ("" if ad_salary else " none"))
    out += [f"- {ln}" for ln in ad_salary]
    asked = _experience_lines(posting.get("description", ""))
    if asked:
        out.append("What the ad asks for:")
        out += [f"- {ln}" for ln in asked]
    years = years_of_experience(reading, cv_text, now_year=now_year)
    out += ["", "# The candidate",
            f"Years of experience counted from the dated roles: {years} years" if years is not None
            else "Years of experience: not countable from the CV"]
    cv = _anonymous_cv(cv_text, profile, reading)
    if cv:
        out += ["CV (contact details removed):", cv]
    return "\n".join(out)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value) if isinstance(value, float) else value


def parse(answer) -> dict | None:
    """The model's answer, checked: ``{"low", "high", "currency", "period", "gross", "position", "basis",
    "sources", "ad_salary"}``, or ``None`` when it found nothing or cannot be trusted (``low`` above
    ``high``, no currency code, an unknown period, no source with an http(s) URL)."""
    if not isinstance(answer, dict) or answer.get("found") is False:
        return None
    low, high = _number(answer.get("low")), _number(answer.get("high"))
    currency, period = answer.get("currency"), answer.get("period")
    if low is None or high is None or low > high:
        return None
    if not isinstance(currency, str) or not _CODE.fullmatch(currency) or period not in _PERIODS:
        return None
    sources = []
    for item in answer.get("sources") or []:
        url = item.get("url") if isinstance(item, dict) else None
        if isinstance(url, str) and re.match(r"https?://\S+$", url):
            sources.append({"title": str(item.get("title") or url).strip(), "url": url})
    if not sources:
        return None
    position, ad_salary = answer.get("position"), answer.get("ad_salary")
    return {
        "low": low, "high": high, "currency": currency, "period": period,
        "gross": answer.get("gross") is not False,
        "position": position if position in _POSITIONS else None,
        "basis": str(answer.get("basis") or "").strip(),
        "sources": sources,
        "ad_salary": ad_salary.strip() if isinstance(ad_salary, str) and ad_salary.strip() else None,
    }
