"""The detached-process helpers (`core/process.py`): started in a session of their own, ended with their tree,
and the run.json a long-lived process leaves. Nothing real is started or killed."""

import signal

from door.core import process


def test_stopping_ends_each_process_group_not_just_its_first_process(monkeypatch):
    # Python on a Mac starts through a launcher: the server is a child in the launcher's group
    sent = []
    monkeypatch.setattr(process.os, "killpg", lambda pgid, sig: sent.append(("group", pgid)), raising=False)
    monkeypatch.setattr(process.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(process.sys, "platform", "darwin")
    process.kill_tree(4242)
    assert sent == [("group", 4242)]


def test_a_process_that_leads_no_group_is_ended_alone(monkeypatch):
    # not every pid is a group leader: never take down a group that is somebody else's
    sent = []
    monkeypatch.setattr(process.os, "killpg", lambda pgid, sig: sent.append(("group", pgid)), raising=False)
    monkeypatch.setattr(process.os, "getpgid", lambda pid: 1, raising=False)
    monkeypatch.setattr(process.os, "kill", lambda pid, sig: sent.append(("pid", pid)))
    monkeypatch.setattr(process.sys, "platform", "darwin")
    process.kill_tree(4242)
    assert sent == [("pid", 4242)]


def test_on_windows_the_whole_tree_is_ended_with_taskkill(monkeypatch):
    calls = []
    monkeypatch.setattr(process.sys, "platform", "win32")
    monkeypatch.setattr(process.subprocess, "run", lambda argv, **kw: calls.append(argv))
    process.kill_tree(4242)
    assert calls == [["taskkill", "/T", "/F", "/PID", "4242"]]


def _spawn_flags(monkeypatch, tmp_path, platform, **kwargs):
    seen = {}
    monkeypatch.setattr(process.sys, "platform", platform)
    monkeypatch.setattr(process.subprocess, "Popen", lambda argv, **kw: seen.update(kw))
    process.spawn_detached(["x"], log=tmp_path / "x.log", **kwargs)
    return seen


def test_on_windows_a_server_is_detached_from_the_console(monkeypatch, tmp_path):
    assert _spawn_flags(monkeypatch, tmp_path, "win32")["creationflags"] == 0x00000008 | 0x00000200


def test_a_signal_can_be_chosen_for_the_group(monkeypatch):
    sent = []
    monkeypatch.setattr(process.os, "killpg", lambda pgid, sig: sent.append((pgid, sig)), raising=False)
    monkeypatch.setattr(process.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(process.sys, "platform", "darwin")
    process.kill_tree(4242, signal.SIGKILL)
    assert sent == [(4242, signal.SIGKILL)]


def test_a_run_file_is_read_back_as_written_and_a_missing_or_broken_one_is_none(tmp_path):
    path = tmp_path / "deep" / "run.json"
    assert process.read_run(path) is None
    process.write_run(path, {"state": "building", "name": "Zoë"})
    assert process.read_run(path) == {"state": "building", "name": "Zoë"}
    assert "Zoë" in path.read_text(encoding="utf-8")
    path.write_text("{", encoding="utf-8")
    assert process.read_run(path) is None


def test_is_alive_is_true_for_this_process_and_false_for_a_gone_one():
    import os

    assert process.is_alive(os.getpid())
    assert not process.is_alive(2**22 + 12345)


def test_a_group_is_killed_by_its_id_even_when_its_leader_is_gone(monkeypatch):
    sent = []
    monkeypatch.setattr(process.os, "killpg", lambda pgid, sig: sent.append((pgid, sig)), raising=False)
    monkeypatch.setattr(process.os, "getpgid", lambda pid: (_ for _ in ()).throw(ProcessLookupError()), raising=False)
    monkeypatch.setattr(process.sys, "platform", "darwin")
    process.kill_tree(4242, signal.SIGKILL, group=True)
    assert sent == [(4242, signal.SIGKILL)]


def test_a_group_nobody_may_signal_is_left_alone(monkeypatch):
    def refuse(pgid, sig):
        raise PermissionError

    monkeypatch.setattr(process.os, "killpg", refuse, raising=False)
    monkeypatch.setattr(process.sys, "platform", "darwin")
    process.kill_tree(4242, group=True)
