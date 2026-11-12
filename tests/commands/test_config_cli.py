"""Config validation when a command loads profile/config.json.

Split out of the former tests/test_door_cli.py (issue #15 onward); the shared
`cli_env` fixture is in tests/commands/conftest.py, helpers in tests/cli_utils.py.
"""

import json

import pytest
from click.testing import CliRunner

from door.cli import cli
from door.commands import find as find_cmd
from door.commands import prepare as prepare_cmd
from door.commands import scrape as scrape_cmd
from cli_utils import result_text, stub_blocks, stub_steps


# --------------------------------------------------------------------------- #
# config validation at load (issue #137)
# --------------------------------------------------------------------------- #

def _break_config(cli_env, **extra):
    config = json.loads((cli_env.profile_dir / "config.json").read_text())
    config.update(extra)
    (cli_env.profile_dir / "config.json").write_text(json.dumps(config))


def test_run_invalid_config_exits_1_naming_the_key_before_scraping(cli_env, monkeypatch):
    import door.scrapers.boards.jobindex as ji

    def _must_not_run(config, **kwargs):  # pragma: no cover — must not be called
        raise AssertionError("scraper ran despite an invalid config")

    monkeypatch.setattr(ji, "scrape", _must_not_run)
    monkeypatch.delattr(ji, "iter_scrape", raising=False)
    _break_config(cli_env, greenhouse_board=["acme"])

    result = CliRunner().invoke(cli, ["find", "search"])

    assert result.exit_code == 1
    text = result_text(result)
    assert "greenhouse_board" in text
    assert "Traceback" not in text


def test_scrape_passes_per_site_lists_to_scrapers_as_a_dict(cli_env, monkeypatch):
    import door.scrapers.feeds.greenhouse as gh

    seen = {}

    def _fake(config, **kwargs):
        seen["config"] = config
        return []

    monkeypatch.setattr(gh, "scrape", _fake)
    monkeypatch.delattr(gh, "iter_scrape", raising=False)
    from door.core import companies

    items = companies.load(cli_env.profile_dir)
    companies.record(items, "Acme", feed=("greenhouse", "acme"), status="followed", found_via="manual", reason=None)
    companies.save(cli_env.profile_dir, items)

    scrape_cmd._scrape_core(["greenhouse"], jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir, mode="collect")

    assert isinstance(seen["config"], dict)
    assert seen["config"]["greenhouse_boards"] == ["acme"]


# one command per loader: lenient (`_load_config_or_defaults`) and strict (`_load_config`)
@pytest.mark.parametrize("argv", [["jobs"], ["find"]])
def test_commands_reject_an_invalid_config(cli_env, argv):
    _break_config(cli_env, min_sore=0.5)
    result = CliRunner().invoke(cli, argv)
    assert result.exit_code == 1, result_text(result)
    text = result_text(result)
    assert "min_sore" in text
    assert "Traceback" not in text


def test_list_without_any_config_still_works(cli_env):
    (cli_env.profile_dir / "config.json").unlink()
    result = CliRunner().invoke(cli, ["jobs"])
    assert result.exit_code == 0, result_text(result)


def test_doctor_lists_every_config_error(cli_env):
    _break_config(cli_env, min_sore=0.5, dedup_similarity_threshold=1.5)
    result = CliRunner().invoke(cli, ["doctor"])
    text = result_text(result)
    assert "min_sore" in text
    assert "dedup_similarity_threshold" in text

