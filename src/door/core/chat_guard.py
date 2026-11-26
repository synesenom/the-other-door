"""What a tool answer may carry into a Claude Code chat (and any model that calls the tools).

An ad is written by a stranger, and a chat can run commands on the user's computer, so in a chat no tool
answer carries an ad's text: `show` gives the summary of `matching/ad_summary` and opens the ad for the user
(`open_ad`), and `guard` leaves the description and the integrity excerpts out of every answer and cuts every
other string to a bound and wraps it in a marker ``<ad-TOKEN>…</ad-TOKEN>`` (default deny: only the keys of
`_KEEP`, whose texts the code makes, stay as they are), a token drawn at random for each call, so text inside it cannot close it early or
pass for the server's own words. The desktop app (its main process sets `path_scope.ENV`) and the phone are not
chats and get answers as they are.
"""

from __future__ import annotations

import html
import re
import secrets
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from door.core import utils, workspace

VIEW_DIR = ".view"
ASK_CHARS = 1500
TEXT_CHARS = 300
MAX_ITEMS = 50

# Bounds of the fields that have their own (everything else wrapped is cut at TEXT_CHARS); the skills are lists of
# strings, each cut, at most `_MAX_SKILLS` of them, and any other list at MAX_ITEMS.
_BOUNDS = {"title": 120, "title_en": 120, "company": 80, "location": 80, "score_reason": 240,
           "matching_skills": 40, "missing_skills": 40}
_SKILLS = ("matching_skills", "missing_skills")
_MAX_SKILLS = 20
_AD_TEXT = ("description", "description_condensed")

# Default deny: in a chat every string in an answer is cut and wrapped, whatever its key, because ad text reaches
# answers by routes no list of keys can foresee (an error quoting a title, a note read from a material, a progress
# line, an employer's name). Only the values of these keys stay as they are, each a text the code itself makes and
# no ad can choose; when unsure, a key is not here.
_KEEP = frozenset({
    "id", "job_id", "ids",  # `<site>.<platform id>`, the key of every ledger (an id a site would have to guess to forge)
    "status", "kind", "verdict", "outcome", "stage", "feature",  # members of fixed lists the code picks from
    "currency", "period", "position",  # the salary estimate's fixed words (`salary.py`)
    "work_mode",  # `onsite|hybrid|remote` or null: `ad_summary.clean` drops any other value
    "pdfs", "pngs", "pdf", "png", "path", "paths", "dir",  # files the code writes under `jobs/output/<id>/`
    "at", "as_of", "start", "end",  # timestamps the code stamps (an event's time, a window's ends)
})
# Answers that are a dict from an ad's text to a count: its keys are wrapped too (the only ones, a test runs every tool).
_NAMED_BY_AD = frozenset({"by_company"})
_KEEP_SUFFIX = ("_at", "_path", "_dir")  # `scraped_at`, `updated_at`, `output_path`, ...: stamps and paths the code builds (but `posted_at` is the site's)


_OPENED: set[str] = set()  # the jobs whose ad this server already opened


# Tools whose answers hold only the user's own data or the code's own words, never a posting's or an employer's
# text, so a chat gets them whole (the CV a draft returns goes straight to `save_cv`). Read from each core's answer;
# a tool whose answer can include any posting or employer text is not here (a test places every tool).
OWN_DATA_TOOLS = frozenset({
    "infer_basics", "keywords", "suggest_titles",  # the user's CV, their own pages and profile
    "show_profile", "init_profile", "save_cv", "save_photo", "remove_photo", "cv_style_sample",  # the profile and CV
    "list_stories", "draft_stories", "save_story", "remove_story",  # the user's story bank
    "doctor", "setup",  # checks and installs of this computer
    "export_data", "import_data", "report_problem",  # archives and reports: paths and counts
    "connect_drive", "sync_data", "disconnect_drive",  # the Drive link and its sync state
    "phone_start", "phone_stop", "phone_status", "pair_phone", "unpair_phone",  # the phone server
    "cancel_job",  # stops a run: the code's own answer
})

# Tools whose answers must come back whole (the CV a draft returns goes to `save_cv`, a proposal's text is shown to the
# user) but are written by a model from pages a stranger may have written: every string stays uncut and with its
# lines, inside the call's marker. `save_cv` takes the marker tags off the text it is given (`unmark`).
WHOLE_TEXT_TOOLS = frozenset({"draft_cv", "enrich"})
_TAG = re.compile(r"</?ad-[0-9a-f]{8}>")


def _marker() -> tuple[str, str]:
    token = secrets.token_hex(4)
    return f"<ad-{token}>", f"</ad-{token}>"


def _wrap(value: str, limit: int, marker: tuple[str, str]) -> str:
    text = " ".join(value.split())[:limit]
    return f"{marker[0]}{text}{marker[1]}"


def unmark(text: str) -> str:
    """``text`` without any marker tag a chat's answer put in it, wherever it sits (a draft edited around its marker,
    two marked pieces joined)."""
    return _TAG.sub("", text)


def wrap_text(value: str) -> str:
    """One text (a progress line) as a chat may read it: cut and in a marker of its own."""
    return _wrap(value, TEXT_CHARS, _marker())


def _is_ad(node: dict) -> bool:
    """A dict that describes a posting: a title with a company or link or id, or a company with a place."""
    return ("title" in node and any(k in node for k in ("company", "url", "id", "job_id"))) or (
        "company" in node and "location" in node)


def _kept(key) -> bool:
    return isinstance(key, str) and (key in _KEEP or key.endswith(_KEEP_SUFFIX) and key != "posted_at")


def _walk(node, key, kept, marker, tool):
    """``node`` (the value of ``key``) with every string wrapped unless ``kept`` (under a key of `_KEEP`)."""
    if isinstance(node, str):
        if kept:
            return node
        if tool in WHOLE_TEXT_TOOLS:
            return f"{marker[0]}{node}{marker[1]}"
        if tool == "ask" and key == "answer":
            return f"{marker[0]}{node.strip()[:ASK_CHARS]}{marker[1]}"
        return _wrap(node, _BOUNDS.get(key, TEXT_CHARS), marker)
    if isinstance(node, list):
        return [_walk(item, key, kept, marker, tool) for item in node[:_MAX_SKILLS if key in _SKILLS else MAX_ITEMS]]
    if isinstance(node, dict):
        ad = _is_ad(node)
        out = {}
        for name, value in node.items():
            if name in _AD_TEXT and ad:
                continue
            if name == "excerpt" and "kind" in node:  # an integrity finding's quote of the ad
                continue
            shown = _wrap(name, _BOUNDS.get(key, TEXT_CHARS), marker) if key in _NAMED_BY_AD and not kept else name
            out[shown] = _walk(value, name, kept or _kept(name), marker, tool)
        return out
    return node


def guard(tool: str, answer: dict) -> dict:
    """``answer`` as a chat may read it: no description, every string cut and wrapped but those of `_KEEP`."""
    return answer if tool in OWN_DATA_TOOLS else _walk(answer, None, False, _marker(), tool)


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
    job = str(posting.get("id") or "")
    if job in _OPENED:  # once per job for the server's life: a chat that asks again must not open a tab each time
        return {"opened": target}
    if not webbrowser.open(target):
        return {"opened": None, "open_failed": target}
    _OPENED.add(job)
    return {"opened": target}
