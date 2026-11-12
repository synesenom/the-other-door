"""Salary estimate (#371), the pure parts: what the model is asked, and whether its answer can be trusted.

`build_input` condenses the ad and the CV's experience into the text of one question (no name, email or
phone); `parse` accepts an answer only when it has a sane range, a currency code and a source with a URL;
`years_of_experience` counts the CV's dated roles so the model need not guess. No network, no model call:
`commands/salary.py` asks.
"""

import re
from datetime import date

from door import i18n

_MAX_AD_LINES = 6
_MAX_CV_CHARS = 6000
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\d[\d ().-]{6,}\d")
_RANGE = re.compile(r"\b((?:19|20)\d\d)\s*[-–—]\s*((?:19|20)\d\d|[^\W\d_]+)", re.UNICODE)
_CODE = re.compile(r"[A-Z]{3}")
_PERIODS = ("month", "year")
_POSITIONS = ("below", "within", "above")


def _sections(cv_text: str) -> list[tuple[str, str]]:
    """``[(heading, body)]`` for each ``## `` section of the CV."""
    parts = re.split(r"^##\s+(.+)$", cv_text or "", flags=re.MULTILINE)
    return list(zip(parts[1::2], parts[2::2]))


def years_of_experience(cv_text: str, *, now_year: int | None = None) -> int | None:
    """Years covered by the CV's dated roles (``2018 - 2021``, ``2021 - present``), overlaps counted once.

    Only the sections that are not education, certifications or skills count; a word after the
    first year ("present") means the role goes on. ``None`` when no role has a date range."""
    now_year = now_year or date.today().year
    skip = {w.lower() for kind in ("education", "certifications", "skills") for w in i18n.cv_section(kind)}
    spans = []
    for heading, body in _sections(cv_text):
        if heading.strip().lower() in skip:
            continue
        for start, end in _RANGE.findall(body):
            first, last = int(start), int(end) if end.isdigit() else now_year
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


def _anonymous_cv(cv_text: str, profile: dict) -> str:
    """The CV without its title line, contact lines and the profile's name, email and phone."""
    private = [str(profile.get(k)) for k in ("name", "email", "phone") if profile.get(k)]
    private += [part for part in str(profile.get("name") or "").split() if len(part) > 1]
    lines = []
    for line in (cv_text or "").splitlines():
        if line.startswith("# ") or _EMAIL.search(line) or (_PHONE.search(line) and not _RANGE.search(line)):
            continue
        for value in private:
            line = re.sub(re.escape(value), "", line, flags=re.IGNORECASE)
        lines.append(line)
    return "\n".join(lines).strip()[:_MAX_CV_CHARS]


def build_input(posting: dict, cv_text: str, profile: dict, *, now_year: int | None = None) -> str:
    """The question's text: the ad (title, company, place, country and currency, the ad's own salary
    and experience lines) and the candidate's experience (counted years, the CV without contact details)."""
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
    years = years_of_experience(cv_text, now_year=now_year)
    out += ["", "# The candidate",
            f"Years of experience counted from the dated roles: {years} years" if years is not None
            else "Years of experience: not countable from the CV"]
    cv = _anonymous_cv(cv_text, profile)
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
