"""The discovery sources reach only public addresses and read no system proxy, as the boards and feeds do."""
import pytest
import requests.adapters

from door.scrapers import http_client
from door.scrapers.discovery import linkedin


_REAL_SEND = requests.adapters.HTTPAdapter.send  # before tests/conftest.py's guard replaces it


@pytest.fixture
def real_network(monkeypatch):
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _REAL_SEND)


def _linkedin_get(url):
    return linkedin._open_session().goto(url)


def _paged_get(url):
    return http_client.public_session().get(url, timeout=5)


@pytest.mark.parametrize("get", [_linkedin_get, _paged_get], ids=["linkedin", "paged"])
@pytest.mark.parametrize("host", ["169.254.169.254", "10.0.0.5", "127.0.0.1:8099", "localhost"])
def test_a_discovery_request_to_a_private_address_is_refused(get, host, real_network):
    with pytest.raises(http_client.NotPublicAddress):
        get(f"http://{host}/latest/meta-data/")


@pytest.mark.parametrize("make", [lambda: linkedin._open_session()._http, http_client.public_session],
                         ids=["linkedin", "paged"])
def test_a_discovery_session_reads_no_system_proxy(make):
    session = make()
    assert session.trust_env is False
    assert session.headers["User-Agent"] == http_client.USER_AGENT
