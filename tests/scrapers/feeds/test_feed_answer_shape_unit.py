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
    ("hr_manager", "hr_manager_aliases", "Items"),
    ("workable", "workable_companies", "jobs"),
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


class _Text(_Resp):
    def __init__(self, text):
        super().__init__(None)
        self.text = text


@pytest.mark.parametrize("text,answered", [
    ("<html>login</html", False),
    ("<html><body>login</body></html>", False),
    ("<rss><channel><title>Acme</title></channel></rss>", True),
])
def test_successfactors_reads_a_feed_without_a_channel_as_an_error(monkeypatch, text, answered):
    from door.scrapers.feeds import successfactors

    monkeypatch.setattr("door.scrapers.http_client.PoliteSession.get", lambda self, *a, **k: _Text(text))
    drain_errors()
    drain_answered("successfactors")
    assert successfactors.scrape({"successfactors_companies": ["jobs.acme.com"]}) == []
    assert bool(drain_errors().get("successfactors")) is not answered
    assert drain_answered("successfactors") is answered


def test_smartrecruiters_probe_without_a_content_list_is_not_ok(monkeypatch):
    from door.scrapers.feeds import smartrecruiters

    monkeypatch.setattr("door.scrapers.http_client.PoliteSession.get", lambda self, *a, **k: _Text('{"x": 1}'))
    result = smartrecruiters.probe({"smartrecruiters_companies": ["acme"]})
    assert result["structure_ok"] is False and "content" in result["reason"]


def test_the_jobsearch_message_names_its_key():
    from door.scrapers.boards import arbetsformedlingen

    with pytest.raises(ValueError, match="hits"):
        arbetsformedlingen._parse_response('{"x": 1}')


def test_emply_scrape_without_a_vacancies_list_is_not_answered(monkeypatch):
    from door.scrapers.feeds import emply

    resp = _Resp({"error": "x"})
    resp.is_redirect = False
    monkeypatch.setattr("door.scrapers.http_client.PoliteSession.post", lambda self, *a, **k: resp)
    drain_errors()
    drain_answered("emply")
    assert emply.scrape({"emply_tenants": ["acme"]}) == []
    assert drain_errors()["emply"]
    assert drain_answered("emply") is False


def test_taleez_scrape_without_a_jobs_list_is_not_answered(monkeypatch):
    from door.scrapers.feeds import taleez

    monkeypatch.setattr("door.scrapers.http_client.PoliteSession.get", lambda self, *a, **k: _Text('{"x": 1}'))
    drain_errors()
    drain_answered("taleez")
    assert taleez.scrape({"taleez_companies": ["acme"]}) == []
    assert drain_errors()["taleez"]
    assert drain_answered("taleez") is False
