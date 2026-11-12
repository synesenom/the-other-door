"""`add`: bring an ad found elsewhere into the pipeline as an ordinary posting."""

import json
import re
import sys
from pathlib import Path

import click

from door.commands import _common as common
from door.commands import _progress
from door.commands import matches as matches_cmd
from door.commands import match as match_cmd
from door.core import progress as progress_mod
from door.core import workspace
from door.core.profile_loader import ConfigError
from door.core.utils import _validate_job_id
from door.matching import integrity
from door.core import utils

_ONE_SOURCE = "give the ad as a file, text or a URL (exactly one of them)"


def _page_text(html: str) -> str:
    """The readable text of an HTML page: scripts, styles and tags gone, one
    line per block, blank lines collapsed."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    lines = [" ".join(line.split()) for line in soup.get_text("\n").splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _fetch_ad(url: str) -> tuple[str, str]:
    """The ad at `url` as ``(readable text, html)``, through the scrapers' polite client.

    Raises:
        ValueError: the page could not be fetched, or has no text.
    """
    from door.scrapers.http_client import PoliteSession

    try:
        response = PoliteSession(min_delay=0, max_delay=0, max_retries=1).get(url)
        response.raise_for_status()
    except Exception as exc:  # requests errors, robots, timeouts: one message for the user
        raise ValueError(f"could not fetch {url}: {exc}") from None
    text = _page_text(response.text)
    if not text:
        raise ValueError(f"could not fetch {url}: the page has no readable text")
    return text, response.text


_READ_MODEL = "haiku"
_READ_MAX_CHARS = 30_000

_READ_RULES = (
    "You read a job ad. The user gives you the readable text of a web page showing one job ad. "
    "Answer with its job title, the hiring company (the employer, not the job board or recruiter "
    "platform) and the location as the ad states it. Empty strings for what the page does not "
    "say. Answer with the JSON only."
)

_READ_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "company": {"type": "string"}, "location": {"type": "string"}},
    "required": ["title", "company", "location"],
}


def _read_ad(text: str, url: str) -> dict:
    """The ad's ``title``, ``company`` and ``location`` as Haiku reads them from
    the page ``text`` (one `claude -p` call); empty strings for what it could not tell.

    Raises:
        ValueError: the call failed.
    """
    from door.core import claude_cli

    try:
        answer = claude_cli.ask(_READ_RULES, text[:_READ_MAX_CHARS], model=_READ_MODEL, feature="import_posting",
                                schema=_READ_SCHEMA, timeout_s=120)
    except claude_cli.ClaudeError as exc:
        raise ValueError(f"could not read the title and company from {url} ({exc}) — pass --title and --company") from None
    return {k: " ".join(str(answer.get(k) or "").split()) for k in ("title", "company", "location")}


def _step(message: str, outcome: str | None = None) -> None:
    """One of `add`'s steps: running (no ``outcome``), or done ("ok"/"failed")."""
    progress_mod.report(message, stage="add", outcome=outcome)


# --------------------------------------------------------------------------- #
# add (issue #166)
# --------------------------------------------------------------------------- #
@common._with_progress
def _add_core(
    path: Path | str | None,
    *,
    text: str | None = None,
    title: str | None = None,
    company: str | None = None,
    url: str | None = None,
    location: str | None = None,
    force: bool = False,
    jobs_dir: Path | None = None,
    profile_dir: Path | None = None,
    progress=None,
) -> dict:
    """Turn a job ad found outside the scraped boards into an ordinary posting.

    The ad comes from a file (plain text / Markdown, or a JSON `JobPosting`),
    as pasted ``text``, or — with neither — from the web page at ``url``,
    fetched and reduced to its readable text ("here's a link"); a title,
    company or location not given is then read off the page by Haiku.
    Text becomes the ``description`` of a new posting
    with ``source="manual"``; a JSON posting is validated and kept as given
    (``title``/``company``/``url``/``location`` override its fields). It is
    saved to ``jobs/postings/<today>/manual/<job_id>.json`` and scored right away
    (`_match_core` on that one file, Haiku like `find`), so it is a posting
    like any other: `list`, `show`, `prepare` and `status` work on it
    unchanged; `scrape`'s filters never touch it. A failed scoring keeps the
    posting (the next `find` scores it). Never prints: each step (fetch,
    read, save, score) is reported to ``progress`` (stage ``"add"``) as it
    starts and, with an ``outcome``, as it ends.

    Args:
        force: Replace a posting already stored under the same id.
        progress: A `door.core.progress.Reporter` for the steps, or None.

    Returns:
        ``{"job_id", "path", "replaced": bool, "score": float | None,
        "score_reason": str | None, "score_error"?: str}``.

    Raises:
        ValueError: neither/both of path and text, missing title/company for
            text, an empty ad, an invalid JSON posting, or the id exists
            without ``force``.
        FileNotFoundError: ``path`` does not exist.
    """
    import hashlib
    from datetime import date, datetime, timezone

    from pydantic import ValidationError

    from door.core.models import JobPosting, make_job_id
    from door.core.selection import find_posting_path

    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    fetched = path is None and text is None and bool(url)
    gated: dict | None = None
    if fetched:
        from urllib.parse import urlparse

        host = urlparse(url).netloc or url
        _step(f"fetching {host}")
        try:
            text, html = _fetch_ad(url)
            gated = integrity.check(text, html=html)
            text = gated["clean_text"]
            if not text:
                raise ValueError(f"could not fetch {url}: the page has no readable text")
        except ValueError:
            _step(f"could not fetch {host}", "failed")
            raise
        _step(f"fetched {host}", "ok")
        if not (title and company):
            _step("reading the title and company (Haiku)")
            try:
                read = _read_ad(text, url)
            except ValueError:
                _step("could not read the title and company", "failed")
                raise
            title, company, location = title or read["title"], company or read["company"], location or read["location"]
            if title and company:
                _step(f"read {title} at {company}", "ok")
            else:
                _step(f"could not read the {'title' if not title else 'company'}", "failed")
    if (path is None) == (text is None):
        raise ValueError(_ONE_SOURCE)

    posting: dict | None = None
    if path is not None:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"ad file not found: {path}")
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(raw)
                posting = JobPosting.model_validate(data).model_dump(mode="json")
            except (ValueError, ValidationError) as exc:
                raise ValueError(f"{path} is not a valid posting JSON: {exc}") from None
            _validate_job_id(posting["id"])
            posting["integrity"] = None  # a file's own verdict is not trusted
    else:
        raw = text

    overrides = {k: v for k, v in (("title", title), ("company", company), ("url", url), ("location", location)) if v}
    if posting is None:
        description = (raw or "").strip()
        if not description:
            raise ValueError("the ad is empty")
        for name, value in (("title", title), ("company", company)):
            if not (value and value.strip()):
                raise ValueError(f"could not read the {name} from {url} — pass --{name}" if fetched
                                 else f"--{name} is required when importing an ad as text")
        platform_id = hashlib.sha1(description.encode("utf-8")).hexdigest()[:12]
        posting = JobPosting(
            id=make_job_id("manual", platform_id),
            title=title.strip(),
            company=company.strip(),
            location=(location or "").strip(),
            url=(url or "").strip(),
            description=description,
            integrity=integrity.stored(gated) if gated else None,
            source="manual",
            scraped_at=datetime.now(timezone.utc),
            platform_id=platform_id,
        ).model_dump(mode="json")
    else:
        posting.update(overrides)

    if not posting.get("integrity"):
        integrity.apply(posting)
    job_id = posting["id"]
    existing = find_posting_path(jobs_dir, job_id)
    if existing is not None and not force:
        raise ValueError(f"a posting with id {job_id!r} is already stored at {existing} — pass force to replace it")
    target = existing or (workspace.day_dir(jobs_dir, date.today().isoformat()) / "manual" / f"{job_id}.json")
    utils.write_json_atomic(target, posting)

    result = {"job_id": job_id, "path": str(target), "replaced": existing is not None}
    _step(f"saved {posting['title']} at {posting['company']}", "ok")
    _step("scoring (Haiku)")
    try:
        failed = match_cmd._match_core(jobs_dir=jobs_dir, profile_dir=profile_dir, paths=[target])["failed"]
        error = "scoring failed" if failed else None
    except (FileNotFoundError, ConfigError) as exc:  # no usable profile: the posting is stored all the same
        error = str(exc)
    scored = json.loads(target.read_text(encoding="utf-8"))
    result.update(score=scored.get("score"), score_reason=scored.get("score_reason"))
    if error:
        result["score_error"] = f"{error}; the next `find` scores it"
        _step("scoring failed", "failed")
    else:
        _step(f"scored {result['score']:.2f}", "ok")
    return result


@click.command("add")
@click.argument("source")
@click.option("--title", default=None, help="Job title (required for a text/Markdown ad; read by Haiku for a URL).")
@click.option("--company", default=None, help="Company (required for a text/Markdown ad; read by Haiku for a URL).")
@click.option("--url", default=None, help="Where the ad lives (optional).")
@click.option("--location", default=None, help="Job location (optional).")
@click.option("--force", is_flag=True, default=False, help="Replace a posting already stored under the same id.")
def add(source, title, company, url, location, force):
    """Add a job ad found outside the scraped boards.

    SOURCE is usually the ad's URL: the page is fetched, and the title,
    company and location you leave out are read off it by Haiku. It can also
    be a text/Markdown file with the ad (then --title and --company are
    required), a JSON posting, or `-` to read the ad from stdin. It is stored as
    jobs/postings/<today>/manual/<job_id>.json and scored right away, so list, show,
    prepare and status work on it like on any scraped posting.
    """
    kwargs = dict(title=title, company=company, url=url, location=location, force=force, jobs_dir=workspace.JOBS_DIR)
    if common._is_url(source):
        source, kwargs["url"] = None, source
    interactive = common._stdout_is_tty()
    try:
        with _progress.live_progress(enabled=interactive) as reporter:
            if source == "-":
                result = _add_core(None, text=click.get_text_stream("stdin").read(), progress=reporter, **kwargs)
            else:
                result = _add_core(source, progress=reporter, **kwargs)
    except (ValueError, FileNotFoundError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    _render_added(result, interactive=interactive)


def _render_added(result: dict, *, interactive: bool) -> None:
    """`show`'s card for the added posting (without the ad itself), where it
    was saved, and what to do next."""
    posting = matches_cmd._show_core(result["job_id"], jobs_dir=workspace.JOBS_DIR)
    console = common._console()
    if interactive:
        console.print()
    matches_cmd._render_posting_detail(posting, posting["status"], console, description=False)
    console.print()
    from door.core.selection import find_posting

    words = common.job_words(find_posting(workspace.JOBS_DIR, result["job_id"]) or {"id": result["job_id"]}, workspace.JOBS_DIR)
    # soft_wrap: a path or a command is never broken across lines, so it stays copyable.
    console.print(f"  [dim]{'Replaced' if result['replaced'] else 'Saved':<8}[/] [green]{common._display_path(result['path'])}[/]", soft_wrap=True)
    if result.get("score_error"):
        console.print(f"  [dim]{'Score':<8}[/] [yellow]not scored: {result['score_error']}[/]", soft_wrap=True)
    common._next_steps(console, [
        (f"./door jobs prepare {words}", "tailor a CV and cover letter"),
        (f"./door jobs show {words}", "the whole ad"),
    ])
