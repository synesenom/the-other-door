"""What a tool answer may carry into a Claude Code chat (and any model that calls the tools).

An ad is written by a stranger, and a chat can run commands on the user's computer, so in a chat no tool
answer carries an ad's text: `show` gives the summary of `matching/ad_summary` and opens the ad for the user
(`open_ad`), and `guard` leaves the description and the integrity excerpts out of every answer and cuts the
short ad-derived fields (title, company, the score's reason, skills) to a bound and wraps each in a marker
``<ad-TOKEN>…</ad-TOKEN>``, a token drawn at random for each call, so text inside it cannot close it early or
pass for the server's own words. The desktop app (its main process sets `path_scope.ENV`) and the phone are not
chats and get answers as they are.
"""

from __future__ import annotations

import html
import secrets
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from door.core import utils, workspace

VIEW_DIR = ".view"
ASK_CHARS = 1500

# key -> bound; list keys hold strings each cut to the bound, at most `_MAX_SKILLS` of them
_TEXT = {"title": 120, "title_en": 120, "company": 80, "location": 80, "score_reason": 240}
_SKILLS = ("matching_skills", "missing_skills")
_SKILL_CHARS, _MAX_SKILLS = 40, 20
_AD_TEXT = ("description", "description_condensed")


def _marker() -> tuple[str, str]:
    token = secrets.token_hex(4)
    return f"<ad-{token}>", f"</ad-{token}>"


def _wrap(value: str, limit: int, marker: tuple[str, str]) -> str:
    text = " ".join(value.split())[:limit]
    return f"{marker[0]}{text}{marker[1]}"


def _is_ad(node: dict) -> bool:
    """A dict that describes a posting: a title with a company or link or id, or a company with a place."""
    return ("title" in node and any(k in node for k in ("company", "url", "id", "job_id"))) or (
        "company" in node and "location" in node)


def _walk(node, marker):
    if isinstance(node, list):
        return [_walk(item, marker) for item in node]
    if not isinstance(node, dict):
        return node
    ad = _is_ad(node)
    out = {}
    for key, value in node.items():
        if ad and key in _AD_TEXT:
            continue
        if key == "excerpt" and "kind" in node:  # an integrity finding's quote of the ad
            continue
        if key == "score_reason" and isinstance(value, str) or ad and key in _TEXT and isinstance(value, str):
            out[key] = _wrap(value, _TEXT[key], marker)
        elif key in _SKILLS and isinstance(value, list):
            out[key] = [_wrap(s, _SKILL_CHARS, marker) for s in value if isinstance(s, str)][:_MAX_SKILLS]
        else:
            out[key] = _walk(value, marker)
    return out


def guard(tool: str, answer: dict) -> dict:
    """``answer`` as a chat may read it. `ask`'s answer, a model's reading of ads, is capped and wrapped whole."""
    marker = _marker()
    if tool == "ask" and isinstance(answer.get("answer"), str):
        answer = {**answer, "answer": _wrap_long(answer["answer"], marker)}
    return _walk(answer, marker)


def _wrap_long(text: str, marker: tuple[str, str]) -> str:
    return f"{marker[0]}{text.strip()[:ASK_CHARS]}{marker[1]}"


def view_page(posting: dict) -> str:
    """The saved ad as a plain HTML page: its text escaped, no script, no link, no style from the ad."""
    def esc(key):
        return html.escape(str(posting.get(key) or ""))

    body = html.escape(str(posting.get("description") or ""))
    return ("<!doctype html>\n<html><head><meta charset=\"utf-8\"><meta name=\"referrer\" content=\"no-referrer\">"
            f"<title>{esc('title')} - {esc('company')}</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;"
            "line-height:1.5}pre{white-space:pre-wrap;font:inherit}</style></head><body>"
            f"<h1>{esc('title')}</h1><p>{esc('company')} - {esc('location')}</p><pre>{body}</pre></body></html>\n")


def open_ad(posting: dict) -> dict:
    """Open the ad for the user: its own address when it is http(s), else the saved text as a page under the data
    folder. ``{"opened": url_or_path}``, or ``{"opened": None, "open_failed": url_or_path}`` when the browser
    could not be started (the caller gives the user that link)."""
    url = str(posting.get("url") or "")
    if urlparse(url).scheme in ("http", "https") and urlparse(url).netloc:
        target = url
    else:
        page = workspace.HOME / VIEW_DIR / f"{posting.get('id') or 'ad'}.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        utils.write_atomic(page, view_page(posting))
        target = page.as_uri()
    try:
        ok = webbrowser.open(target)
    except Exception:  # a browser that cannot start is not a failure of the tool
        ok = False
    return {"opened": target} if ok else {"opened": None, "open_failed": target}
