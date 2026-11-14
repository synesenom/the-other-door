"""Tailoring module — generates tailored CV bullets and cover letters."""

from __future__ import annotations

import os
import re
from pathlib import Path

from door.core import migrations

__all__ = ["StoryBank"]

_REQUIRED_FIELDS = ("title", "context", "action", "result", "learning")


def _slug(title: str) -> str:
    """Return a normalized slug for deduplication: lowercase, alphanumeric + hyphens."""
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s


class StoryBank:
    """Persistent store of reusable CARL (context, action, result, learning) stories.

    Stories are stored in a Markdown file at ``path`` using ``##``-headed blocks.
    Deduplication is performed by normalized title slug.

    Typical usage::

        sb = StoryBank(Path("<profile dir>/story_bank.md"))
        sb.append({
            "title": "Led the Data Migration Project",
            "context": "...",
            "action": "...",
            "result": "...",
            "learning": "...",
        })
        sb.save()
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._stories: list[dict] = self._load()
        # A file that exists with content but parsed to nothing is not ours to overwrite.
        self._unparsed = not self._stories and self._has_content()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def stories(self) -> list[dict]:
        """Return the current list of stories (read-only copy)."""
        return list(self._stories)

    def append(self, story: dict) -> None:
        """Add *story* to the bank unless its title slug is already present.

        Raises:
            ValueError: If any required field is missing from *story*.
        """
        missing = [f for f in _REQUIRED_FIELDS if f not in story]
        if missing:
            raise ValueError(
                f"Story is missing required fields: {', '.join(missing)}"
            )
        slug = _slug(story["title"])
        existing_slugs = {_slug(s["title"]) for s in self._stories}
        if slug not in existing_slugs:
            self._stories.append(dict(story))

    def replace(self, old_title: str, story: dict) -> None:
        """Swap the story titled *old_title* for *story*, keeping its position.

        Raises:
            ValueError: unknown title, missing fields, or the new title's slug
                belongs to another story.
        """
        missing = [f for f in _REQUIRED_FIELDS if f not in story]
        if missing:
            raise ValueError(f"Story is missing required fields: {', '.join(missing)}")
        old = _slug(old_title)
        idx = next((i for i, s in enumerate(self._stories) if _slug(s["title"]) == old), None)
        if idx is None:
            raise ValueError(f"No story titled {old_title!r}")
        new = _slug(story["title"])
        if any(i != idx and _slug(s["title"]) == new for i, s in enumerate(self._stories)):
            raise ValueError(f"Another story already has the title {story['title']!r}")
        self._stories[idx] = dict(story)

    def remove(self, title: str) -> None:
        """Remove the story whose title slug matches *title*.

        Raises:
            ValueError: no such story.
        """
        slug = _slug(title)
        for i, s in enumerate(self._stories):
            if _slug(s["title"]) == slug:
                del self._stories[i]
                return
        raise ValueError(f"No story titled {title!r}")

    def save(self) -> None:
        """Serialize stories to Markdown and write atomically to ``self._path``.

        Raises:
            ValueError: the file exists with content but held no readable story.
        """
        if self._unparsed:
            raise ValueError(
                f"{self._path.name} has content but no readable story; not overwriting it"
            )
        migrations.ensure_folder(self._path.parent, "profile")
        tmp_path = self._path.with_suffix(".md.tmp")
        try:
            content = self._serialize()
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(tmp_path, self._path)
        finally:
            # Remove the temp file if the atomic replace failed.
            if tmp_path.exists():
                tmp_path.unlink()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _has_content(self) -> bool:
        try:
            return self._path.exists() and bool(self._path.read_text(encoding="utf-8").strip())
        except Exception:
            return True

    def _load(self) -> list[dict]:
        """Parse the Markdown file and return a list of story dicts."""
        if not self._path.exists():
            return []
        try:
            text = self._path.read_text(encoding="utf-8")
            return self._parse(text)
        except Exception:
            return []

    @staticmethod
    def _parse(text: str) -> list[dict]:
        """Parse Markdown text into a list of story dicts."""
        stories: list[dict] = []
        # Split on ## headings (level-2 only)
        blocks = re.split(r"(?m)^## ", text)
        for block in blocks[1:]:  # [0] is whatever precedes the first heading
            if not block.strip():
                continue
            lines = block.splitlines()
            title = lines[0].strip()
            if not title:
                continue
            story: dict = {"title": title}
            for line in lines[1:]:
                m = re.match(
                    r"^\*\*(Context|Action|Result|Learning)\*\*:\s*(.*)",
                    line,
                    re.IGNORECASE,
                )
                if m:
                    key = m.group(1).lower()
                    value = m.group(2).strip()
                    story[key] = value
                    continue
            stories.append(story)
        return stories

    def _serialize(self) -> str:
        """Serialize the stories list to a Markdown string."""
        parts: list[str] = []
        for story in self._stories:
            block = f"## {story['title']}\n\n"
            for field in ("context", "action", "result", "learning"):
                label = field.capitalize()
                block += f"**{label}**: {story.get(field, '')}\n"
            parts.append(block)
        return "\n".join(parts)
