"""The fact check (#433) as a test makes it: the model's answer is `findings`, and `check` writes `facts.json` as the
tailor's `check_facts` would. `finding("97%", "Cut churn by 97%")` is one a model would list."""

from door.tailoring import facts


def finding(value, context, kind="number", file="cv"):
    return {"kind": kind, "value": value, "context": context, "file": file}


def checked(monkeypatch, out, profile_dir, findings=(), **kw):
    """Run `facts.check` on `out` with the model answering `findings`; returns what it found."""
    monkeypatch.setattr(facts, "_ask", lambda inputs: {"findings": list(findings)})
    return facts.check(out, profile_dir, **kw)
