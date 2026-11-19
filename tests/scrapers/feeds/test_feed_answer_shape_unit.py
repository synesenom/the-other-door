"""A feed answer with no job list is a recorded error, not a quiet day (#434); an empty list is a quiet day."""

import importlib

import pytest

from door.scrapers import drain_answered, drain_errors

# (module, config key, the answer's list key; None = the answer is the list itself)
_FEEDS = [
    ("greenhouse", "greenhouse_boards", "jobs"),
    ("ashby", "ashby_companies", "jobs"),
    ("pinpoint", "pinpoint_companies", "data"),
    ("recruitee", "recruitee_companies", "offers"),
    ("teamtailor", "teamtailor_companies", "items"),
    ("lever", "lever_companies", None),
]


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.text = ""
        self.status_code = 200
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _scrape(monkeypatch, name, key, payload):
    monkeypatch.setattr("door.scrapers.http_client.PoliteSession.get", lambda self, *a, **k: _Resp(payload))
    mod = importlib.import_module(f"door.scrapers.feeds.{name}")
    drain_errors()
    drain_answered(name)
    return mod.scrape({key: ["acme"]})


@pytest.mark.parametrize("name,key,list_key", _FEEDS)
@pytest.mark.parametrize("payload", [{}, {"error": "moved"}, "nope", None])
def test_an_answer_without_the_job_list_is_an_error_not_answered(monkeypatch, name, key, list_key, payload):
    if list_key and not isinstance(payload, dict):
        payload = {list_key: "nope"}
    assert _scrape(monkeypatch, name, key, payload) == []
    assert drain_errors()[name]
    assert drain_answered(name) is False


@pytest.mark.parametrize("name,key,list_key", _FEEDS)
def test_an_empty_job_list_is_answered(monkeypatch, name, key, list_key):
    assert _scrape(monkeypatch, name, key, {list_key: []} if list_key else []) == []
    assert not drain_errors().get(name)
    assert drain_answered(name) is True
