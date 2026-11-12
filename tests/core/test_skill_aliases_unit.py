"""Unit tests for core/skill_aliases.py: the tolerant reader of jobs/skill_aliases.json."""

import json

from door.core import skill_aliases


def test_missing_file_is_empty_without_warning(tmp_path):
    assert skill_aliases.load(tmp_path / "skill_aliases.json") == ({}, None)


def test_valid_file_lowercases_keys_and_keeps_null(tmp_path):
    path = tmp_path / "skill_aliases.json"
    path.write_text(json.dumps({" K8s ": " Kubernetes ", "Teamwork": None}))
    aliases, warning = skill_aliases.load(path)
    assert aliases == {"k8s": "Kubernetes", "teamwork": None} and warning is None


def test_corrupt_file_is_empty_with_warning_and_not_rewritten(tmp_path):
    path = tmp_path / "skill_aliases.json"
    path.write_text("{nope")
    aliases, warning = skill_aliases.load(path)
    assert aliases == {} and warning and "skill_aliases.json" in warning
    assert path.read_text() == "{nope"


def test_non_dict_and_non_text_values_are_refused(tmp_path):
    path = tmp_path / "skill_aliases.json"
    for body in ('["a"]', '{"a": 3}'):
        path.write_text(body)
        aliases, warning = skill_aliases.load(path)
        assert aliases == {} and warning
        assert path.read_text() == body


def test_load_for_reads_the_jobs_dir(tmp_path):
    (tmp_path / skill_aliases.FILE).write_text('{"k8s": "Kubernetes"}')
    assert skill_aliases.load_for(tmp_path)[0] == {"k8s": "Kubernetes"}
