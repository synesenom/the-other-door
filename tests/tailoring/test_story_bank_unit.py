"""Unit tests for StoryBank class in tailoring/__init__.py."""

import pytest

from door.tailoring import StoryBank

VALID_STORY = {
    "title": "Led the Data Migration Project",
    "context": "The legacy database was failing under load, and 5TB had to move with zero downtime.",
    "action": "Designed a phased migration plan with dual-write and cut-over.",
    "result": "Migrated successfully with 0 incidents and 15% cost reduction.",
    "learning": "Learned to plan for rollback before starting any migration.",
}

VALID_STORY_2 = {
    "title": "Built the ML Pipeline From Scratch",
    "context": "No existing ML infrastructure, and a production-ready pipeline due in 3 months.",
    "action": "Chose MLflow + Airflow, containerised, and trained the team.",
    "result": "Pipeline shipped on time; team adopted it across 4 projects.",
    "learning": "Early investment in monitoring saved weeks of debugging later.",
}


def test_load_missing_file_returns_empty_list(tmp_path):
    """StoryBank initialized with a non-existent file should have no stories."""
    sb = StoryBank(tmp_path / "story_bank.md")
    assert sb.stories == []


def test_load_existing_bank_parses_all_fields(tmp_path):
    """StoryBank should parse all 4 CARL fields."""
    story_file = tmp_path / "story_bank.md"
    story_file.write_text(
        "## My Story\n\n"
        "**Context**: Context text.\n"
        "**Action**: Action text.\n"
        "**Result**: Result text.\n"
        "**Learning**: Learning text.\n",
        encoding="utf-8",
    )
    sb = StoryBank(story_file)
    assert len(sb.stories) == 1
    story = sb.stories[0]
    assert story["title"] == "My Story"
    assert story["context"] == "Context text."
    assert story["action"] == "Action text."
    assert story["result"] == "Result text."
    assert story["learning"] == "Learning text."


def test_append_deduplicates_by_title_slug_case_insensitive(tmp_path):
    """Title slug dedup should be case-insensitive."""
    sb = StoryBank(tmp_path / "story_bank.md")
    sb.append(VALID_STORY)
    story_upper = dict(VALID_STORY)
    story_upper["title"] = VALID_STORY["title"].upper()
    sb.append(story_upper)
    assert len(sb.stories) == 1


def test_append_different_slug_adds_both(tmp_path):
    """Appending two stories with different titles should yield two stories."""
    sb = StoryBank(tmp_path / "story_bank.md")
    sb.append(VALID_STORY)
    sb.append(VALID_STORY_2)
    assert len(sb.stories) == 2


def test_save_load_round_trip(tmp_path):
    """Saving then loading should preserve both stories."""
    path = tmp_path / "story_bank.md"
    sb = StoryBank(path)
    sb.append(VALID_STORY)
    sb.append(VALID_STORY_2)
    sb.save()

    sb2 = StoryBank(path)
    assert len(sb2.stories) == 2
    titles = {s["title"] for s in sb2.stories}
    assert VALID_STORY["title"] in titles
    assert VALID_STORY_2["title"] in titles


def test_save_atomic_no_tmp_left_behind(tmp_path):
    """After save(), the .md.tmp file must not exist."""
    path = tmp_path / "story_bank.md"
    sb = StoryBank(path)
    sb.append(VALID_STORY)
    sb.save()
    assert not (tmp_path / "story_bank.md.tmp").exists()


def test_load_corrupt_file_falls_back_to_empty(tmp_path):
    """A corrupt or unreadable markdown file should yield an empty story list."""
    story_file = tmp_path / "story_bank.md"
    story_file.write_bytes(b"\xff\xfe garbage \x00\x01")
    sb = StoryBank(story_file)
    assert sb.stories == []


def test_save_creates_parent_directory(tmp_path):
    """save() must create the parent directory if it doesn't exist."""
    path = tmp_path / "nested" / "story_bank.md"
    sb = StoryBank(path)
    sb.append(VALID_STORY)
    sb.save()
    assert path.exists()


def test_story_format_requires_all_carl_fields(tmp_path):
    """append() must raise ValueError if any CARL field is missing."""
    sb = StoryBank(tmp_path / "story_bank.md")
    for field in ("context", "action", "result", "learning"):
        story_missing = {k: v for k, v in VALID_STORY.items() if k != field}
        with pytest.raises(ValueError, match=field):
            sb.append(story_missing)


def test_replace_swaps_in_place_and_renames(tmp_path):
    sb = StoryBank(tmp_path / "story_bank.md")
    sb.append(VALID_STORY)
    sb.append(VALID_STORY_2)
    sb.replace(VALID_STORY["title"], {**VALID_STORY, "title": "Renamed", "result": "New."})
    assert [s["title"] for s in sb.stories] == ["Renamed", VALID_STORY_2["title"]]
    assert sb.stories[0]["result"] == "New."


def test_replace_unknown_title_raises(tmp_path):
    sb = StoryBank(tmp_path / "story_bank.md")
    sb.append(VALID_STORY)
    with pytest.raises(ValueError):
        sb.replace("Nope", VALID_STORY)


def test_replace_slug_collision_raises(tmp_path):
    sb = StoryBank(tmp_path / "story_bank.md")
    sb.append(VALID_STORY)
    sb.append(VALID_STORY_2)
    with pytest.raises(ValueError):
        sb.replace(VALID_STORY["title"], {**VALID_STORY, "title": VALID_STORY_2["title"]})


def test_remove_by_slug_and_miss(tmp_path):
    sb = StoryBank(tmp_path / "story_bank.md")
    sb.append(VALID_STORY)
    sb.append(VALID_STORY_2)
    sb.remove("led the DATA migration project")
    assert [s["title"] for s in sb.stories] == [VALID_STORY_2["title"]]
    with pytest.raises(ValueError):
        sb.remove("missing")


def test_serialized_file_is_carl_only(tmp_path):
    path = tmp_path / "story_bank.md"
    sb = StoryBank(path)
    sb.append(VALID_STORY)
    sb.save()
    text = path.read_text(encoding="utf-8")
    for label in ("Context", "Action", "Result", "Learning"):
        assert text.count(f"**{label}**:") == 1
    for gone in ("Situation", "Task", "Reflection", "Skills"):
        assert f"**{gone}**" not in text


def test_a_skills_line_is_not_part_of_a_story(tmp_path):
    path = tmp_path / "story_bank.md"
    path.write_text("## A\n\n**Context**: c\n**Action**: a\n**Result**: r\n**Learning**: x\n**Skills**: Go\n")
    assert "skills" not in StoryBank(path).stories[0]


def test_save_refuses_to_overwrite_unparsed_file(tmp_path):
    path = tmp_path / "story_bank.md"
    path.write_text("just some notes, no story headings\n", encoding="utf-8")
    sb = StoryBank(path)
    assert sb.stories == []
    sb.append(VALID_STORY)
    with pytest.raises(ValueError):
        sb.save()
    assert path.read_text(encoding="utf-8") == "just some notes, no story headings\n"
