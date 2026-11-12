"""The last resort of `follow`: ask Claude Haiku (with web search) where an employer's careers page is.

One question through `claude_cli.ask` (the Claude plan's quota, never an API key). The answer is only a
URL: `follow` feeds it back into its own checks and follows an employer only when a feed is confirmed.
"""

from __future__ import annotations

from urllib.parse import urlparse

from door.core import claude_cli

MODEL = "haiku"
MAX_PARALLEL = 4  # `claude -p` calls in flight at once (each takes 30 to 60 s)
_SCHEMA = {"type": "object", "properties": {"careers_url": {"type": ["string", "null"]}},
           "required": ["careers_url"], "additionalProperties": False}
_SYSTEM = (
    "You find the official careers page of an employer. Use web search. Answer with the URL of the page on the "
    "employer's own site or its applicant system that lists its open jobs, or null when you are not sure it is "
    "that employer's (never a job board such as LinkedIn or Jobindex). JSON only."
)


def parse_url(answer: object) -> str | None:
    """The http(s) URL in a model answer ``{"careers_url": ...}``, else None. Pure."""
    url = answer.get("careers_url") if isinstance(answer, dict) else None
    if not isinstance(url, str):
        return None
    url = url.strip()
    parsed = urlparse(url)
    return url if parsed.scheme in ("http", "https") and parsed.netloc else None


def ask_careers_url(name: str, title: str | None, location: str, *, profile_dir=None) -> str | None:
    """The careers URL the model finds for employer *name* (it hired for *title* in *location*), or None
    when it finds none or the call fails."""
    prompt = f"Employer: {name}\nA job it advertised: {title or 'unknown'}\nWhere I am looking: {location or 'unknown'}"
    try:
        answer = claude_cli.ask(_SYSTEM, prompt, model=MODEL, feature="careers_lookup", schema=_SCHEMA, allowed_tools=("WebSearch",),
                                timeout_s=120, profile_dir=profile_dir)
    except claude_cli.ClaudeError:
        return None
    return parse_url(answer)
