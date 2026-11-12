"""Every Claude call reports its usage (#575): each `claude_cli.run`/`ask` call under `src/door/`
names a known `feature=`, and the modules that run `claude` themselves call `usage.record`."""

import ast
import json
import types

from door.core import usage
from door.matching import language, scorer
from paths import REPO_ROOT

SRC = REPO_ROOT / "src" / "door"
# Modules that start `claude -p` with their own subprocess.run (retry, backoff, fallback model).
OWN_SUBPROCESS = ("matching/scorer.py", "matching/language.py", "core/scraper_fix.py")


def _calls(tree, names):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in names
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "claude_cli"):
            yield node


def test_every_claude_cli_call_names_a_known_feature():
    seen = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _calls(tree, {"run", "ask"}):
            kw = {k.arg: k.value for k in call.keywords}
            where = f"{path.relative_to(SRC)}:{call.lineno}"
            assert "feature" in kw, f"{where} calls claude_cli.{call.func.attr} without feature="
            assert isinstance(kw["feature"], ast.Constant), f"{where}: feature= must be a literal"
            assert kw["feature"].value in usage.FEATURES, f"{where}: unknown feature {kw['feature'].value!r}"
            seen.append(kw["feature"].value)
    assert len(seen) >= 12


def test_modules_running_claude_themselves_record_usage():
    for rel in OWN_SUBPROCESS:
        text = (SRC / rel).read_text(encoding="utf-8")
        assert "usage.record(" in text, f"{rel} runs claude without usage.record"
        assert "STREAM_ARGS" in text or "build_claude_argv" in text, f"{rel} asks for no stream"


# --------------------------------------------------------------------------- what the call sites record
def _envelope(result, out=100):
    return json.dumps({"type": "result", "is_error": False, "result": result, "total_cost_usd": 0.01,
                       "modelUsage": {"claude-haiku": {"inputTokens": 50, "outputTokens": out}}})


def test_scoring_records_one_line_per_chunk_with_its_postings_as_units():
    postings = [{"id": f"s.{i}", "title": "t", "company": "c", "description": "d"} for i in range(3)]
    answer = {"results": [{"job_id": p["id"], "score": 0.5, "score_reason": "r", "matching_skills": [],
                           "missing_skills": [], "flags": [], "language_requirement": "none"} for p in postings]}

    def run(argv, **kw):
        return types.SimpleNamespace(returncode=0, stdout=_envelope(json.dumps(answer)), stderr="")

    scorer.score_postings(postings, system_prompt="s", chunk=3, workers=1, run_fn=run, sleep_fn=lambda s: None)
    [line] = usage.read()
    assert (line["feature"], line["units"]) == ("match_scoring", 3)


def test_title_translation_records_each_batch(tmp_path):
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"id": "s.1", "title": "Udvikler", "description": "Vi søger en udvikler", "language": "da"}))
    answer = json.dumps({"titles": [{"id": "s.1", "title_en": "Developer"}]})
    language.filter_languages([path], {"languages": ["English", "Danish"]}, run_fn=lambda argv, stdin: _envelope(answer))
    [line] = usage.read()
    assert line["feature"] == "title_translation"


def test_the_tailor_run_asks_for_the_envelope(tmp_path):
    from door.commands import prepare
    argv = prepare._tailor_args("s.1", tmp_path / "posting.json")
    assert argv[argv.index("--output-format") + 1] == "stream-json"
