"""One-time conversion of an existing `jobs/` to the `<site>.<platform_id>` job id (#313).

Renames the posting files and their ids, `applications.json`, the `jobs/output/<id>/` folders and
the history (keyed by job id), resolves `duplicate_of` and deletes `last_list.json`. The originals
are copied to `backups/<timestamp>/jobs` first. Idempotent. Runs under the ledger lock.

Usage:  poetry run python scripts/migrate_job_ids.py [--dry-run]
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from door.commands import archive as archive_cmd  # noqa: E402
from door.core import models, utils, workspace  # noqa: E402
from door.core.lock import ledger_lock  # noqa: E402

# Platforms whose raw ids repeat across tenants: the host of the posting url joins the platform id.
_TENANT_SOURCES = frozenset({"successfactors", "teamtailor", "pinpoint"})
# What the backup copies: the files and folders that carry job ids.
_MIGRATED = ("applications.json", "history.json", "last_list.json", "output", "postings")


def _new_platform_id(source: str, platform_id: str, url: str) -> str:
    """The platform id as the scrapers now write it (idempotent)."""
    return models.tenant_platform_id(url, platform_id) if source in _TENANT_SOURCES else platform_id


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _scan_postings(jobs_dir: Path) -> list[dict]:
    """Every posting file with its target id: ``{path, data, old_id, new_id, new_pid}``."""
    found = []
    for path in sorted((jobs_dir / "postings").glob("*/*/*.json")):
        data = _read_json(path)
        if not isinstance(data, dict) or not data.get("id") or not data.get("platform_id"):
            continue
        source = str(data.get("source") or path.parent.name)
        new_pid = _new_platform_id(source, str(data["platform_id"]), str(data.get("url") or ""))
        found.append({"path": path, "data": data, "old_id": data["id"], "source": source,
                      "new_pid": new_pid, "new_id": models.make_job_id(source, new_pid)})
    return found


def _winner(group: list[dict], output_posting) -> dict:
    """Of the postings that shared an old id, the one its ledger entry and output folder follow:
    the one whose platform id the output copy holds, else the earliest scraped."""
    if isinstance(output_posting, dict) and output_posting.get("platform_id"):
        out_pid = str(output_posting["platform_id"])
        out_folded = _new_platform_id(str(output_posting.get("source") or ""), out_pid, str(output_posting.get("url") or ""))
        for item in group:
            if item["new_pid"] in (out_pid, out_folded) or str(item["data"]["platform_id"]) == out_pid:
                return item
    return min(group, key=lambda i: (str(i["data"].get("scraped_at") or ""), str(i["path"])))


def _plan_migration(jobs_dir: Path) -> dict:
    """What the migration would change, without touching anything."""
    postings = _scan_postings(jobs_dir)
    groups: dict[str, list[dict]] = {}
    for item in postings:
        groups.setdefault(item["old_id"], []).append(item)

    id_map: dict[str, str] = {}
    split = 0
    for old_id, group in groups.items():
        if len({i["new_id"] for i in group}) > 1:
            split += 1
            winner = _winner(group, _read_json(jobs_dir / "output" / old_id / "posting.json"))
        else:
            winner = group[0]
        if winner["new_id"] != old_id:
            id_map[old_id] = winner["new_id"]

    # An output folder with no posting file maps through its own copy.
    output = jobs_dir / "output"
    if output.is_dir():
        for folder in sorted(output.iterdir()):
            copy = _read_json(folder / "posting.json") if folder.is_dir() else None
            if folder.name in groups or not isinstance(copy, dict) or not copy.get("platform_id"):
                continue
            source = str(copy.get("source") or folder.name.split(".")[0])
            pid = _new_platform_id(source, str(copy["platform_id"]), str(copy.get("url") or ""))
            new_id = models.make_job_id(source, pid)
            if new_id != folder.name:
                id_map[folder.name] = new_id

    # History: old entries are keyed by platform id and carry the old job id.
    history_path = jobs_dir / "history.json"
    old_history = _read_json(history_path)
    new_history: dict[str, dict] = {}
    history_changes = 0
    if isinstance(old_history, dict):
        for key, entry in old_history.items():
            if not isinstance(entry, dict):
                new_history[key] = entry
                continue
            source = str(entry.get("source") or "")
            raw_pid = str(entry.get("platform_id") or key)
            if entry.get("platform_id") and key == models.make_job_id(source, entry["platform_id"]):
                new_history.setdefault(key, entry)  # already migrated
                continue
            pid = _new_platform_id(source, raw_pid, str(entry.get("url") or ""))
            new_id = models.make_job_id(source, pid)
            old_job_id = entry.get("job_id")
            if old_job_id and old_job_id not in id_map and old_job_id not in groups and old_job_id != new_id:
                id_map.setdefault(old_job_id, new_id)  # a ledger entry may name a job only the history knows
            migrated = {"job_id": new_id, "platform_id": pid, **{k: v for k, v in entry.items() if k not in ("job_id", "platform_id")}}
            if new_id in new_history:
                new_history[new_id]["last_seen"] = max(str(new_history[new_id].get("last_seen") or ""),
                                                       str(migrated.get("last_seen") or ""))
            else:
                new_history[new_id] = migrated
            history_changes += 1

    applications = _read_json(jobs_dir / "applications.json")
    renamed_apps = (
        sum(1 for k in applications if id_map.get(k, k) != k) if isinstance(applications, dict) else 0
    )
    output_dirs = (
        [d for d in sorted(output.iterdir()) if d.is_dir() and id_map.get(d.name, d.name) != d.name]
        if output.is_dir() else []
    )
    return {
        "postings": postings, "id_map": id_map, "split": split, "history": new_history,
        "history_changes": history_changes, "applications": applications, "applications_renamed": renamed_apps,
        "output_dirs": output_dirs,
    }


def _backup_ledgers(jobs_dir: Path, backups_dir: Path) -> Path:
    backup = archive_cmd._new_backup_dir(backups_dir)
    target = backup / "jobs"
    target.mkdir()
    for name in _MIGRATED:
        src = jobs_dir / name
        if src.is_dir():
            shutil.copytree(src, target / name)
        elif src.is_file():
            shutil.copy2(src, target / name)
    return backup


def _migrate_unlocked(dry_run: bool = False, *, jobs_dir: Path | None = None, backups_dir: Path | None = None) -> dict:
    """Re-key `jobs/` to the ``<site>.<platform_id>`` job id: posting files and their ``id``,
    ``duplicate_of``, ``applications.json``, ``output/<id>/``, ``history.json`` (keyed by job id) and
    ``last_list.json`` (deleted). Idempotent; the originals go to ``backups/<timestamp>/jobs`` first.
    Never prints.

    Two postings that shared an old id are split; the ledger entry and output folder follow the one
    whose platform id ``output/<id>/posting.json`` holds, else the earliest scraped. The platform id
    of SuccessFactors, Teamtailor and Pinpoint postings gets its host folded in (as the scrapers do).

    Returns:
        ``{"renamed", "split", "history", "applications", "outputs", "backup_dir", "dry_run"}``:
        counts of posting files changed, old ids split, history entries re-keyed, ledger entries
        and output folders renamed; ``backup_dir`` is None on a dry run or when nothing changes.
    """
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    if backups_dir is None:
        backups_dir = workspace.BACKUPS_DIR
    jobs_dir = Path(jobs_dir)

    plan = _plan_migration(jobs_dir)
    id_map = plan["id_map"]

    changes = []  # (item, new_data, new_path)
    claimed: set[Path] = set()
    for item in plan["postings"]:
        data = dict(item["data"])
        data["id"], data["platform_id"] = item["new_id"], item["new_pid"]
        if data.get("duplicate_of"):
            data["duplicate_of"] = id_map.get(data["duplicate_of"], data["duplicate_of"])
        new_path = item["path"].with_name(f"{item['new_id']}.json")
        if new_path != item["path"] and (new_path in claimed or new_path.exists()):
            new_path = item["path"]  # another posting of this day already holds that name: leave it be
            data["id"] = item["old_id"]
        claimed.add(new_path)
        if data != item["data"] or new_path != item["path"]:
            changes.append((item, data, new_path))

    stale_last_list = (jobs_dir / "last_list.json").exists()
    history_changed = plan["history_changes"] > 0
    result = {
        "renamed": len(changes), "split": plan["split"],
        "history": plan["history_changes"], "applications": plan["applications_renamed"],
        "outputs": len(plan["output_dirs"]), "backup_dir": None, "dry_run": dry_run,
    }
    anything = bool(changes or history_changed or plan["applications_renamed"] or plan["output_dirs"] or stale_last_list)
    if dry_run or not anything:
        return result

    result["backup_dir"] = str(_backup_ledgers(jobs_dir, backups_dir))

    for item, data, new_path in changes:
        utils.write_json_atomic(new_path, data)
        if new_path != item["path"]:
            item["path"].unlink(missing_ok=True)

    if history_changed:
        utils.write_json_atomic(jobs_dir / "history.json", plan["history"])

    applications = plan["applications"]
    if plan["applications_renamed"]:
        renamed = {}
        for key, entry in applications.items():
            new_key = id_map.get(key, key)
            if new_key in renamed or (new_key != key and new_key in applications):
                new_key = key  # the new id is taken (a partly migrated tree): keep this entry as it is
            renamed[new_key] = entry
        utils.write_json_atomic(jobs_dir / "applications.json", renamed)

    for folder in plan["output_dirs"]:
        target = folder.with_name(id_map[folder.name])
        if target.exists():
            continue  # a partly migrated tree already has it: keep both
        folder.rename(target)
        copy = _read_json(target / "posting.json")
        if isinstance(copy, dict):
            copy["id"] = target.name
            if copy.get("platform_id"):
                copy["platform_id"] = _new_platform_id(
                    str(copy.get("source") or ""), str(copy["platform_id"]), str(copy.get("url") or ""))
            if copy.get("duplicate_of"):
                copy["duplicate_of"] = id_map.get(copy["duplicate_of"], copy["duplicate_of"])
            utils.write_json_atomic(target / "posting.json", copy)

    (jobs_dir / "last_list.json").unlink(missing_ok=True)
    return result


def migrate(dry_run: bool = False, *, jobs_dir: Path | None = None, backups_dir: Path | None = None) -> dict:
    """Run the migration under the ledger lock (purpose ``migrate``); see `_migrate_unlocked`."""
    jobs_dir = Path(jobs_dir or workspace.JOBS_DIR)
    with ledger_lock(jobs_dir, "migrate"):
        return _migrate_unlocked(dry_run, jobs_dir=jobs_dir, backups_dir=backups_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-key jobs/ to <site>.<platform_id> job ids (once; safe to rerun).")
    parser.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    args = parser.parse_args(argv)
    try:
        result = migrate(args.dry_run)
    except Exception as exc:  # lock held, unreadable files: say so plainly
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not any(result[k] for k in ("renamed", "history", "applications", "outputs")):
        print("Job ids are already <site>.<platform_id>: nothing to change")
        return 0
    print(("Would change" if args.dry_run else "Migrated") + f" {result['renamed']} postings to <site>.<platform_id> ids")
    print(f"  postings {result['renamed']}, split {result['split']} shared ids, history {result['history']}, "
          f"ledger {result['applications']}, output {result['outputs']}")
    if result["backup_dir"]:
        print(f"  backup   {result['backup_dir']}")
    if args.dry_run:
        print("Run again without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
