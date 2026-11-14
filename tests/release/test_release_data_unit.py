"""The release gate's comparison (#57): what counts as a difference, what a step may list, how a snapshot is normalised."""

from pathlib import Path

from door.core.migrations import Step
from release_gate_utils import release_data as rd

BEFORE = {
    "list_companies": {"companies": [{"name": "A", "status": "followed"}, {"name": "B", "status": "dormant"}]},
    "show_profile": {"config": {"cv_template": "<home>/profile/cv.template.tex", "min_score": 0.6}},
}


def after(**edits):
    import copy

    data = copy.deepcopy(BEFORE)
    for path, value in edits.items():
        node = data
        *parents, last = path.split("/")
        for part in parents:
            node = node[int(part)] if isinstance(node, list) else node[part]
        if value is rd:
            del node[last]
        else:
            node[int(last) if isinstance(node, list) else last] = value
    return data


def test_equal_data_has_no_difference():
    assert rd.differences(BEFORE, after()) == []


def test_a_new_key_is_not_a_difference():
    new = after()
    new["show_profile"]["config"]["preferences"] = {"sectors": []}
    new["something_new"] = 1
    new["list_companies"]["companies"][0]["collect_problem"] = None
    assert rd.differences(BEFORE, new) == []


def test_a_dropped_key_is_a_difference_naming_its_path():
    found = rd.differences(BEFORE, after(**{"show_profile/config/min_score": rd}))
    assert found == ["show_profile.config.min_score: missing (was 0.6)"]


def test_a_changed_value_a_shorter_list_and_a_changed_type_are_differences():
    assert rd.differences(BEFORE, after(**{"show_profile/config/min_score": 0.7}))
    assert rd.differences(BEFORE, after(**{"list_companies/companies/1/status": "followed"}))
    shorter = after()
    shorter["list_companies"]["companies"].pop()
    assert "list_companies.companies: 2 items before, 1 now" in rd.differences(BEFORE, shorter)
    assert rd.differences(BEFORE, after(**{"show_profile/config": []}))


def test_a_listed_change_is_not_reported_and_its_children_are_covered():
    found = rd.differences(BEFORE, after(**{"show_profile/config/cv_template": rd}))
    assert found and rd.unlisted(found, ["show_profile.config.cv_template"]) == []
    assert rd.unlisted(found, ["show_profile.config"]) == []
    assert rd.unlisted(found, ["show_profile.*.cv_template"]) == []


def test_a_change_the_step_does_not_list_stays_reported():
    found = rd.differences(BEFORE, after(**{"show_profile/config/cv_template": rd, "show_profile/config/min_score": 0.9}))
    left = rd.unlisted(found, ["show_profile.config.cv_template"])
    assert [line.split(":")[0] for line in left] == ["show_profile.config.min_score"]


def test_a_listed_path_covers_the_items_of_a_list():
    found = rd.differences(BEFORE, after(**{"list_companies/companies/1/status": "followed"}))
    assert rd.unlisted(found, ["list_companies.companies[1]"]) == []
    assert rd.unlisted(found, ["list_companies.companies[0]"]) == found


def test_a_step_that_drops_a_value_is_not_excused_by_changes_that_name_other_paths():
    found = rd.differences(BEFORE, after(**{"list_companies/companies/1/status": rd}))
    assert rd.unlisted(found, ["show_profile.config.*"]) == found


def test_a_step_carries_its_listed_changes_and_defaults_to_none():
    assert Step("x", lambda folder: None).changes == ()
    assert Step("x", lambda folder: None, changes=("a.b",)).changes == ("a.b",)


def test_normalise_masks_the_data_folder_and_every_time(tmp_path):
    home = tmp_path / "home"
    data = {"path": f"{home}/profile/cv.md", "at": "2026-03-20T09:00:00+00:00", "n": 3, "list": ["x 2026-03-20 09:15:30.5Z y"]}
    assert rd.normalise(data, home) == {"path": "<home>/profile/cv.md", "at": "<time>", "n": 3, "list": ["x <time> y"]}


def test_the_saved_data_holds_no_address_but_example_com():
    import re

    from release_gate_utils import SAMPLES_DIR

    found = set()
    for path in SAMPLES_DIR.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".md", ".tex", ".log", ".html"}:
            found |= set(re.findall(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", path.read_text(encoding="utf-8", errors="ignore")))
    assert {a for a in found if not a.endswith("@example.com")} == set()
