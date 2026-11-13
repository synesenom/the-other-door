"""`check_facts`: the tailor agent's offline fact check of the finished CV and letter, so it can fix what
is unsupported before it ends. There is no command. A call is one round, two at most per prepare run
(`prepare` clears the counter before the tailor starts); `keep` records why an item stays."""

from pathlib import Path

from door.commands import _common as common
from door.core import workspace
from door.tailoring import facts as facts_mod

MAX_ROUNDS = 2
ROUNDS_FILE = ".facts_rounds"


def _rounds_used(output_dir: Path) -> int:
    try:
        return int((output_dir / ROUNDS_FILE).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _check_facts_core(job_id: str, keep: list[dict] | None = None, jobs_dir: Path | None = None) -> dict:
    """Check a job's CV and letter against `profile/cv.md` and the story bank.

    Args:
        job_id: The job: its id, or words from its company and title.
        keep: ``[{kind, value, file, reason}]``: why an item still listed is true (plain text, 200
            characters at most). A TODO never takes one.
        jobs_dir: Directory containing ``output/<job_id>/`` (default `workspace.JOBS_DIR`).

    Returns:
        ``{"job_id", "round", "rounds_left", "unsupported"}`` (``unsupported`` as `facts.check`: None when
        the check cannot run, which uses no round), or ``{"error"}`` once the rounds are spent.

    Raises:
        ValueError: `job_id` is not a valid slug.
        FileNotFoundError: the job has no output folder.
    """
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    job_id = common._resolve_job_ref(job_id, jobs_dir)
    output_dir = jobs_dir / "output" / job_id
    if not output_dir.exists():
        raise FileNotFoundError(f"output directory not found: {output_dir}")
    used = _rounds_used(output_dir)
    if used >= MAX_ROUNDS:
        return {"error": f"the fact check ran {MAX_ROUNDS} times already: finish with what is left"}
    found = facts_mod.check(output_dir, workspace.PROFILE_DIR, keep=keep)
    if found is None:
        return {"job_id": job_id, "round": used, "rounds_left": MAX_ROUNDS - used, "unsupported": None}
    try:
        (output_dir / ROUNDS_FILE).write_text(str(used + 1), encoding="utf-8")
    except OSError:
        pass
    return {"job_id": job_id, "round": used + 1, "rounds_left": MAX_ROUNDS - used - 1, "unsupported": found}
