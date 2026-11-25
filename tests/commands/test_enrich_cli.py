"""`enrich`: propose additions to profile/cv.md from public URLs, then apply the
ones the user picks — the core behind `/expand`, usable from a shell.

Offline: `claude_cli.run` is replaced; nothing is fetched.
"""

import json
import types

import pytest
import responses
from click.testing import CliRunner

from door.cli import cli
from door.commands import enrich as enrich_cmd
from door.commands import _common as common
from door.core import claude_cli, workspace
from door.scrapers import http_client
from cli_utils import result_text
from profile_utils import write_config

CV = """# Jane Doe

## Profile

Data scientist.

## Skills

Python, SQL.

## Projects

- Built a churn model.
"""

PROPOSALS = [
    {"section": "Skills", "text": "Rust (used in github.com/jane/kv)", "source": "https://github.com/jane"},
    {"section": "Projects", "text": "Built a distributed key-value store in Go (github.com/jane/kv)", "source": "https://github.com/jane"},
    {"section": "Talks", "text": "Spoke at PyData Copenhagen 2025", "source": "https://jane.example"},
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    write_config(profile_dir, {"role_targets": ["Data Scientist"], "enrich_sources": ["https://github.com/jane"]})
    cv_path = profile_dir / "cv.md"
    cv_path.write_text(CV)
    config = json.loads((profile_dir / "config.json").read_text())
    config["cv_content"] = str(cv_path)
    (profile_dir / "config.json").write_text(json.dumps(config))
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(http_client.PoliteSession, "redirect_target", lambda self, url: None)
    monkeypatch.setattr(common, "_page_links", lambda url: [])
    return types.SimpleNamespace(profile_dir=profile_dir, cv_path=cv_path, proposals_path=profile_dir / ".enrich_proposals.json")


def _answer(monkeypatch, proposals=PROPOSALS, unreachable=(), calls=None):
    def fake_run(args, *, input=None, timeout_s=None, profile_dir=None, **_):
        if calls is not None:
            calls.append({"args": args, "input": input, "profile_dir": profile_dir})
        return json.dumps({"result": json.dumps({"proposals": proposals, "unreachable": list(unreachable)})})
    monkeypatch.setattr(claude_cli, "run", fake_run)


# --------------------------------------------------------------------------- #
# propose
# --------------------------------------------------------------------------- #

def test_propose_asks_claude_with_webfetch_the_cv_and_the_urls(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls, unreachable=["https://down.example"])
    result = enrich_cmd._enrich_core(["https://github.com/jane", "https://down.example"], profile_dir=env.profile_dir)

    assert result["outcome"] == "proposed"
    assert result["urls"] == ["https://github.com/jane", "https://down.example"]
    assert result["unreachable"] == ["https://down.example"]
    assert [p["n"] for p in result["proposals"]] == [1, 2, 3]
    assert result["proposals"][0] == {"n": 1, **PROPOSALS[0]}
    assert result["proposals_path"] == str(env.proposals_path)
    assert json.loads(env.proposals_path.read_text())["proposals"] == result["proposals"]
    assert env.cv_path.read_text() == CV  # nothing written yet

    args = calls[0]["args"]
    assert args[args.index("--allowedTools") + 1].split(",") == [
        "WebFetch(domain:github.com)", "WebFetch(domain:www.github.com)", "WebFetch(domain:api.github.com)",
        "WebFetch(domain:down.example)", "WebFetch(domain:www.down.example)"]
    assert args[args.index("--system-prompt") + 1] == claude_cli.prompt("cv-enricher", webfetch_rules=common._WEBFETCH_RULES)
    assert "never fabricate" in claude_cli.prompt("cv-enricher", webfetch_rules=common._WEBFETCH_RULES).lower() or "never invent" in claude_cli.prompt("cv-enricher", webfetch_rules=common._WEBFETCH_RULES).lower()
    assert json.loads(args[args.index("--json-schema") + 1]) == enrich_cmd._SCHEMA
    assert args[args.index("--model") + 1] == claude_cli.model_of("cv-enricher")
    assert "Built a churn model" in calls[0]["input"]
    assert "Data Scientist" in calls[0]["input"]
    assert "https://github.com/jane\nhttps://down.example" in calls[0]["input"]
    assert calls[0]["profile_dir"] == env.profile_dir


def _rules(call):
    args = call["args"]
    return args[args.index("--allowedTools") + 1].split(",") if "--allowedTools" in args else []


def test_enrich_with_a_url_allows_webfetch_on_that_host_only(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls)
    monkeypatch.setattr(http_client.PoliteSession, "redirect_target", lambda self, url: "https://jane.pages.example/home")
    enrich_cmd._enrich_core(["https://jane.example/"], profile_dir=env.profile_dir)
    args = calls[0]["args"]
    assert "--restricted" in args and args[args.index("--tools") + 1] == "WebFetch"
    assert _rules(calls[0]) == ["WebFetch(domain:jane.example)", "WebFetch(domain:www.jane.example)",
                                "WebFetch(domain:jane.pages.example)", "WebFetch(domain:www.jane.pages.example)"]


def test_a_linkedin_or_indeed_page_gets_no_webfetch_rule(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls)
    enrich_cmd._enrich_core(["https://www.linkedin.com/in/jane", "https://dk.indeed.com/x", "https://jane.example"], profile_dir=env.profile_dir)
    assert _rules(calls[0]) == ["WebFetch(domain:jane.example)", "WebFetch(domain:www.jane.example)"]
    calls.clear()
    enrich_cmd._enrich_core(["https://linkedin.com/in/jane"], profile_dir=env.profile_dir)
    assert _rules(calls[0]) == [] and calls[0]["args"][calls[0]["args"].index("--tools") + 1] == ""
    assert "Never fetch a LinkedIn or Indeed URL" in calls[0]["args"][calls[0]["args"].index("--system-prompt") + 1]


def test_a_page_given_without_a_scheme_is_fetched_over_https(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls)
    result = enrich_cmd._enrich_core(["github.com/jane"], profile_dir=env.profile_dir)
    assert _rules(calls[0]) == ["WebFetch(domain:github.com)", "WebFetch(domain:www.github.com)", "WebFetch(domain:api.github.com)"]
    assert "https://github.com/jane" in calls[0]["input"] and result["urls"] == ["https://github.com/jane"]


def test_a_page_that_redirects_to_linkedin_gets_no_rule_for_it(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls)
    monkeypatch.setattr(http_client.PoliteSession, "redirect_target", lambda self, url: "https://www." + "linked" + "in.com/in/jane")
    enrich_cmd._enrich_core(["https://jane.example"], profile_dir=env.profile_dir)
    assert _rules(calls[0]) == ["WebFetch(domain:jane.example)", "WebFetch(domain:www.jane.example)"]


def test_a_redirect_that_cannot_be_read_leaves_only_the_given_hosts(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls)

    def refuse(self, url):
        raise http_client.RobotsBlocked(url)
    monkeypatch.setattr(http_client.PoliteSession, "redirect_target", refuse)
    enrich_cmd._enrich_core(["https://jane.example"], profile_dir=env.profile_dir)
    assert _rules(calls[0]) == ["WebFetch(domain:jane.example)", "WebFetch(domain:www.jane.example)"]


def test_propose_from_a_cv_file_reads_its_text_and_fetches_nothing(env, monkeypatch, tmp_path):
    calls = []
    _answer(monkeypatch, calls=calls)
    new_cv = tmp_path / "new-cv.md"
    new_cv.write_text("# Jane Doe\n\n## Talks\n\n- Spoke at PyData Copenhagen 2025\n")
    result = enrich_cmd._enrich_core(files=[str(new_cv)], profile_dir=env.profile_dir)

    assert result["outcome"] == "proposed"
    assert result["files"] == [str(new_cv)] and result["urls"] == []
    assert env.cv_path.read_text() == CV  # proposed only, as from a page
    sent = calls[0]["input"]
    assert "Spoke at PyData Copenhagen 2025" in sent and "Built a churn model" in sent
    assert "https://github.com/jane" not in sent  # the remembered pages are not read with a file
    assert "--allowedTools" not in calls[0]["args"] and calls[0]["args"][calls[0]["args"].index("--tools") + 1] == ""  # nothing to fetch
    # the rules say what a CV file is and what its proposals' source is
    rules = calls[0]["args"][calls[0]["args"].index("--system-prompt") + 1]
    assert "CV file" in rules and "file name" in rules
    assert "CV file new-cv.md:" in sent


def test_propose_from_pages_and_a_cv_file_fetches_the_pages_and_reads_the_file(env, monkeypatch, tmp_path):
    calls = []
    _answer(monkeypatch, calls=calls)
    new_cv = tmp_path / "new-cv.md"
    new_cv.write_text("# Jane\n")
    result = enrich_cmd._enrich_core(["https://jane.example"], files=[str(new_cv)], profile_dir=env.profile_dir)
    assert result["urls"] == ["https://jane.example"] and result["files"] == [str(new_cv)]
    args = calls[0]["args"]
    assert args[args.index("--allowedTools") + 1] == "WebFetch(domain:jane.example),WebFetch(domain:www.jane.example)"
    assert "CV file new-cv.md:" in calls[0]["input"] and "https://jane.example" in calls[0]["input"]


def test_files_with_apply_is_an_error(env, monkeypatch, tmp_path):
    _answer(monkeypatch)
    with pytest.raises(ValueError, match="not both"):
        enrich_cmd._enrich_core(files=[str(tmp_path / "cv.md")], apply=[1], profile_dir=env.profile_dir)


def test_cli_a_missing_file_says_so_and_fails(env, monkeypatch, tmp_path, prompts):
    _answer(monkeypatch)
    result = CliRunner().invoke(cli, ["cv", "enrich", "--file", str(tmp_path / "gone.pdf")])
    assert result.exit_code == 1
    assert "gone.pdf: no such file" in result_text(result)


def test_propose_from_a_file_of_another_type_is_an_error(env, monkeypatch, tmp_path):
    _answer(monkeypatch)
    odd = tmp_path / "cv.exe"
    odd.write_text("x")
    with pytest.raises(ValueError, match="PDF, DOCX, Markdown"):
        enrich_cmd._enrich_core(files=[str(odd)], profile_dir=env.profile_dir)


def test_cli_reads_a_cv_file_given_with_file(env, monkeypatch, tmp_path, prompts):
    _answer(monkeypatch)
    new_cv = tmp_path / "new-cv.md"
    new_cv.write_text("# Jane\n")
    result = CliRunner().invoke(cli, ["cv", "enrich", "--file", str(new_cv)])
    assert result.exit_code == 0, result_text(result)
    assert "Spoke at PyData Copenhagen 2025" in result_text(result)


def test_propose_defaults_to_enrich_sources(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls)
    assert enrich_cmd._enrich_core(profile_dir=env.profile_dir)["urls"] == ["https://github.com/jane"]


def test_propose_without_urls_is_an_error(env, monkeypatch):
    _answer(monkeypatch)
    write_config(env.profile_dir, {"role_targets": ["x"], "cv_content": str(env.cv_path)})
    with pytest.raises(ValueError, match="enrich_sources"):
        enrich_cmd._enrich_core(profile_dir=env.profile_dir)


def test_propose_without_a_cv_is_an_error(env, monkeypatch):
    _answer(monkeypatch)
    env.cv_path.unlink()
    with pytest.raises(FileNotFoundError, match="cv.md"):
        enrich_cmd._enrich_core(profile_dir=env.profile_dir)


def test_propose_with_nothing_new(env, monkeypatch):
    _answer(monkeypatch, proposals=[])
    result = enrich_cmd._enrich_core(profile_dir=env.profile_dir)
    assert result["outcome"] == "nothing_new" and result["proposals"] == []
    assert not env.proposals_path.exists()


def test_propose_drops_malformed_and_duplicate_proposals(env, monkeypatch):
    _answer(monkeypatch, proposals=[
        {"section": "Skills", "text": "Rust", "source": "u"},
        {"section": "Skills", "text": " Rust ", "source": "u"},
        {"section": "Skills", "text": "", "source": "u"},
        {"text": "no section", "source": "u"},
        {"section": "## Projects", "text": "Built a churn model.", "source": "u"},  # already in the CV
        {"section": "## Projects", "text": "New thing", "source": "u"},
    ])
    result = enrich_cmd._enrich_core(profile_dir=env.profile_dir)
    assert [(p["section"], p["text"]) for p in result["proposals"]] == [("Skills", "Rust"), ("Projects", "New thing")]


def test_propose_drops_what_the_cv_already_says_in_other_punctuation_or_markup(env, monkeypatch):
    _answer(monkeypatch, proposals=[
        {"section": "Projects", "text": "Built a churn-model", "source": "u"},  # "- Built a churn model."
        {"section": "Skills", "text": "**Python**, SQL", "source": "u"},  # "Python, SQL."
        {"section": "Projects", "text": "Built a churn model in Python and served it to 3 teams", "source": "u"},  # says more: kept
    ])
    result = enrich_cmd._enrich_core(profile_dir=env.profile_dir)
    assert [p["text"] for p in result["proposals"]] == ["Built a churn model in Python and served it to 3 teams"]


def test_reading_the_pages_again_after_adding_proposes_none_of_it_again(env, monkeypatch):
    _proposed(env, monkeypatch)
    enrich_cmd._enrich_core(all=True, profile_dir=env.profile_dir)
    # the second read words the same things a little differently
    _answer(monkeypatch, proposals=[
        {"section": "Skills", "text": "Rust, used in github.com/jane/kv", "source": "https://github.com/jane"},
        {"section": "Projects", "text": "Built a distributed key value store in Go (github.com/jane/kv).", "source": "https://github.com/jane"},
        {"section": "Talks", "text": "Spoke at PyData Copenhagen, 2025", "source": "https://jane.example"},
    ])
    before = env.cv_path.read_text()
    result = enrich_cmd._enrich_core(profile_dir=env.profile_dir)
    assert result["outcome"] == "nothing_new" and result["proposals"] == []
    assert env.cv_path.read_text() == before


def test_propose_rejects_an_answer_without_proposals(env, monkeypatch):
    monkeypatch.setattr(claude_cli, "run", lambda *a, **k: json.dumps({"result": "{}"}))
    with pytest.raises(claude_cli.ClaudeError, match="proposals"):
        enrich_cmd._enrich_core(profile_dir=env.profile_dir)


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #

def _proposed(env, monkeypatch):
    _answer(monkeypatch)
    return enrich_cmd._enrich_core(profile_dir=env.profile_dir)


def test_apply_inserts_under_the_section_and_appends_new_sections(env, monkeypatch):
    _proposed(env, monkeypatch)
    result = enrich_cmd._enrich_core(apply=[1, 3], profile_dir=env.profile_dir)

    assert result["outcome"] == "applied"
    assert [a["n"] for a in result["added"]] == [1, 3]
    assert result["cv_path"] == str(env.cv_path)
    assert result["backup"] == str(env.cv_path) + ".bak"
    text = env.cv_path.read_text()
    assert "## Skills\n\nPython, SQL.\n\n- Rust (used in github.com/jane/kv)\n\n## Projects" in text
    assert text.endswith("## Projects\n\n- Built a churn model.\n\n## Talks\n\n- Spoke at PyData Copenhagen 2025\n")
    assert (env.cv_path.with_name("cv.md.bak")).read_text() == CV
    assert not env.proposals_path.exists()


def test_apply_after_the_last_bullet_of_a_section(env, monkeypatch):
    _proposed(env, monkeypatch)
    enrich_cmd._enrich_core(apply=[2], profile_dir=env.profile_dir)
    assert "## Projects\n\n- Built a churn model.\n- Built a distributed key-value store in Go (github.com/jane/kv)\n" in env.cv_path.read_text()


def test_apply_all(env, monkeypatch):
    _proposed(env, monkeypatch)
    result = enrich_cmd._enrich_core(all=True, profile_dir=env.profile_dir)
    assert [a["n"] for a in result["added"]] == [1, 2, 3]


def test_apply_rejects_bad_numbers_and_leaves_the_proposals(env, monkeypatch):
    _proposed(env, monkeypatch)
    with pytest.raises(ValueError, match="1-3"):
        enrich_cmd._enrich_core(apply=[4], profile_dir=env.profile_dir)
    assert env.proposals_path.exists()
    assert env.cv_path.read_text() == CV


def test_apply_without_proposals_is_an_error(env, monkeypatch):
    with pytest.raises(FileNotFoundError, match="no proposals"):
        enrich_cmd._enrich_core(apply=[1], profile_dir=env.profile_dir)


def test_apply_and_urls_together_is_an_error(env, monkeypatch):
    with pytest.raises(ValueError, match="not both"):
        enrich_cmd._enrich_core(["https://x"], apply=[1], profile_dir=env.profile_dir)


def test_apply_refuses_stale_proposals_after_the_cv_changed(env, monkeypatch):
    _proposed(env, monkeypatch)
    env.cv_path.write_text(CV + "\n## Extra\n\n- changed\n")
    with pytest.raises(ValueError, match="changed"):
        enrich_cmd._enrich_core(apply=[1], profile_dir=env.profile_dir)


# --------------------------------------------------------------------------- #
# CLI and tool
# --------------------------------------------------------------------------- #

def test_cli_proposes_then_asks_which_to_add(env, monkeypatch, prompts):
    _answer(monkeypatch, unreachable=["https://down.example"])
    monkeypatch.setattr(enrich_cmd.common, "_stdout_is_tty", lambda: True)
    prompts.answers["apply"] = "1 3"
    result = CliRunner().invoke(cli, ["cv", "enrich", "https://github.com/jane", "https://down.example"])
    assert result.exit_code == 0, result_text(result)
    out = result_text(result)
    assert "Could not fetch https://down.example" in out
    assert "1. [Skills] Rust (used in github.com/jane/kv)" in out
    assert "Source: https://github.com/jane" in out
    assert "Added 2 item(s) to" in out
    assert "- Rust (used in github.com/jane/kv)" in env.cv_path.read_text()
    assert "Spoke at PyData" in env.cv_path.read_text()
    assert "key-value" not in env.cv_path.read_text()


def test_cli_none_makes_no_changes(env, monkeypatch, prompts):
    _answer(monkeypatch)
    monkeypatch.setattr(enrich_cmd.common, "_stdout_is_tty", lambda: True)
    prompts.answers["apply"] = "none"
    result = CliRunner().invoke(cli, ["cv", "enrich"])
    assert result.exit_code == 0, result_text(result)
    assert "No changes made" in result_text(result)
    assert env.cv_path.read_text() == CV
    assert env.proposals_path.exists()  # `enrich --apply 2` can still pick them up


def test_cli_not_a_tty_prints_and_hints(env, monkeypatch, prompts):
    _answer(monkeypatch)
    monkeypatch.setattr(enrich_cmd.common, "_stdout_is_tty", lambda: False)
    result = CliRunner().invoke(cli, ["cv", "enrich"])
    assert result.exit_code == 0, result_text(result)
    assert prompts.order == []
    assert "enrich --apply 1,3" in result_text(result) and "enrich --all" in result_text(result)


def test_cli_apply_and_all_use_the_saved_proposals(env, monkeypatch, prompts):
    _proposed(env, monkeypatch)
    result = CliRunner().invoke(cli, ["cv", "enrich", "--apply", "2"])
    assert result.exit_code == 0, result_text(result)
    assert prompts.order == []
    assert "Added 1 item(s)" in result_text(result)

    _proposed(env, monkeypatch)  # proposal 2 is now in the CV, so only 1 and 3 come back
    result = CliRunner().invoke(cli, ["cv", "enrich", "--all"])
    assert result.exit_code == 0, result_text(result)
    assert "Added 2 item(s)" in result_text(result)


def test_cli_nothing_new(env, monkeypatch, prompts):
    _answer(monkeypatch, proposals=[])
    result = CliRunner().invoke(cli, ["cv", "enrich"])
    assert result.exit_code == 0, result_text(result)
    assert "Nothing new found" in result_text(result)


def test_cli_errors_are_one_line(env, monkeypatch, prompts):
    def boom(*a, **k):
        raise claude_cli.ClaudeError("claude exited 1: x")
    monkeypatch.setattr(claude_cli, "run", boom)
    result = CliRunner().invoke(cli, ["cv", "enrich"])
    assert result.exit_code == 1 and "Error: claude exited 1: x" in result_text(result)
    result = CliRunner().invoke(cli, ["cv", "enrich", "--apply", "1"])
    assert result.exit_code == 1 and "no proposals" in result_text(result)
    result = CliRunner().invoke(cli, ["cv", "enrich", "--apply", "x"])
    assert result.exit_code != 0




def test_insert_finds_a_section_whose_heading_records_its_kind():
    cv = "## Tools I use <!-- kind: skills -->\n\n- Python\n"
    assert enrich_cmd._insert(cv, "Tools I use", "SQL") == "## Tools I use <!-- kind: skills -->\n\n- Python\n- SQL\n"


def test_a_new_section_is_written_with_its_title_alone_and_the_rules_ask_for_no_kind_marker():
    assert enrich_cmd._insert("## Profile\n\nHi\n", "Toolbox", "SQL").endswith("\n## Toolbox\n\n- SQL\n")
    assert "<!-- kind" not in claude_cli.prompt("cv-enricher", webfetch_rules=common._WEBFETCH_RULES)


def test_clean_keeps_the_title_when_the_model_wrote_a_marker_anyway():
    [p] = enrich_cmd._clean_proposals([{"section": "Toolbox <!-- kind: skills -->", "text": "SQL", "source": "x"}], "")
    assert p["section"] == "Toolbox" and "kind" not in p


def test_a_linked_page_on_another_host_is_said_to_need_giving(env, monkeypatch):
    # The call reads only the hosts the user gave; a page it was pointed to elsewhere is skipped, and the line says how to have it read.
    _answer(monkeypatch, unreachable=["https://api.github.com/users/jane/repos?per_page=100", "https://jane.example/down"])
    result = CliRunner().invoke(cli, ["cv", "enrich", "https://jane.example"])
    out = result_text(result)
    assert result.exit_code == 0, out
    assert "Not read: https://api.github.com/users/jane/repos?per_page=100 is not one of the pages you gave; give it too to have it read." in out
    assert "Could not fetch https://jane.example/down" in out


def test_a_personal_site_may_be_walked_to_its_subdomains_and_the_profiles_it_links(env, monkeypatch):
    # Code reads the links of the given page, before the model sees anything: its own subdomains and GitHub or ORCID
    # get a rule; any other site it links to, or a host that only ends like it, does not.
    calls = []
    _answer(monkeypatch, calls=calls)
    links = ["https://blog.jane.example/posts", "https://www.blog.jane.example/", "/research", "https://www.github.com/jane",
             "https://orcid.org/0000-0002-1825-0097", "https://linkedin.jane.example/", "https://evil.example/x",
             "https://jane.example.evil.example/", "https://notjane.example/"]
    monkeypatch.setattr(common, "_page_links", lambda url: links)
    enrich_cmd._enrich_core(["https://jane.example"], profile_dir=env.profile_dir)
    assert _rules(calls[0]) == [
        "WebFetch(domain:jane.example)", "WebFetch(domain:www.jane.example)", "WebFetch(domain:blog.jane.example)",
        "WebFetch(domain:www.blog.jane.example)", "WebFetch(domain:github.com)", "WebFetch(domain:api.github.com)",
        "WebFetch(domain:orcid.org)", "WebFetch(domain:pub.orcid.org)",
    ]


def test_a_link_whose_host_is_not_a_plain_name_gets_no_rule(env, monkeypatch):
    # The page writes these hosts; one with a comma or other text in it would break the rule list the call is given.
    calls = []
    _answer(monkeypatch, calls=calls)
    links = ["https://x),webfetch,websearch,(.jane.example/", "https://a b.jane.example/", "https://attacker.com%23.jane.example/",
             "https://evil.com\uff0e.jane.example/"]
    monkeypatch.setattr(common, "_page_links", lambda url: links)
    enrich_cmd._enrich_core(["https://jane.example"], profile_dir=env.profile_dir)
    assert _rules(calls[0]) == ["WebFetch(domain:jane.example)", "WebFetch(domain:www.jane.example)"]


def test_a_page_deeper_than_a_home_page_gets_no_subdomains(env, monkeypatch):
    # A profile on a shared site (medium.com/@jane) is not the user's own site: its subdomains are other people's.
    calls = []
    _answer(monkeypatch, calls=calls)
    monkeypatch.setattr(common, "_page_links", lambda url: ["https://attacker.medium.com/", "https://github.com/jane"])
    enrich_cmd._enrich_core(["https://medium.com/@jane"], profile_dir=env.profile_dir)
    assert _rules(calls[0]) == ["WebFetch(domain:medium.com)", "WebFetch(domain:www.medium.com)",
                                "WebFetch(domain:github.com)", "WebFetch(domain:api.github.com)"]


def test_a_given_profile_site_gets_its_data_host_and_is_not_walked(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls)
    monkeypatch.setattr(common, "_page_links", lambda url: pytest.fail("a profile site's own page is not read for links"))
    enrich_cmd._enrich_core(["https://orcid.org/0000-0002-1825-0097"], profile_dir=env.profile_dir)
    assert _rules(calls[0]) == ["WebFetch(domain:orcid.org)", "WebFetch(domain:www.orcid.org)", "WebFetch(domain:pub.orcid.org)"]


@responses.activate
def test_the_links_of_a_page_are_read_from_its_html(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    responses.add(responses.GET, "https://jane.example/", body='<a href="/cv">CV</a> <a href="https://github.com/jane">gh</a> <a>none</a>')
    assert common._page_links("https://jane.example/") == ["https://jane.example/cv", "https://github.com/jane"]


@responses.activate
def test_a_page_whose_links_cannot_be_read_has_none(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)
    responses.add(responses.GET, "https://jane.example/", status=500)
    assert common._page_links("https://jane.example/") == []
