"""Per-company feeds fetch entries on different hosts side by side (issue #254), and give
the serial run's result: same postings in config order, each host's requests in config order.

Recruitee stands in for the four feeds that use the shared pool (career_sites, successfactors,
teamtailor, recruitee): its entries are a slug on the provider's domain or a careers host.
"""

import json

import pytest
import responses

from door.scrapers.feeds import recruitee
from paths import TESTS_DIR

_ENTRIES = ["careers.alpha.example", "x", "careers.beta.example", "y", "careers.gamma.example"]
_HOSTS = ["careers.alpha.example", "x.recruitee.com", "careers.beta.example", "y.recruitee.com",
          "careers.gamma.example"]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


def _offers_for(host: str) -> str:
    fixture = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "recruitee" / "famly.json"
    offers = json.loads(fixture.read_text(encoding="utf-8"))["offers"]
    for n, offer in enumerate(offers):
        offer["id"] = f"{host}-{n}"
        offer["title"] = f"{host} job {n}"
    return json.dumps({"offers": offers})


def _scrape(workers: int):
    with responses.RequestsMock() as rsps:
        for host in _HOSTS:
            rsps.add(responses.GET, f"https://{host}/api/offers/", body=_offers_for(host))
        postings = recruitee.scrape({"recruitee_companies": _ENTRIES, "scrape_workers": workers})
        requested = [c.request.url for c in rsps.calls]
    return [{k: v for k, v in p.items() if k != "scraped_at"} for p in postings], requested


def test_entries_on_three_hosts_give_the_serial_result_in_config_order():
    serial, serial_requests = _scrape(1)
    parallel, parallel_requests = _scrape(8)

    assert parallel == serial
    assert [p["platform_id"].rsplit("-", 1)[0] for p in serial[::2]] == _HOSTS
    # scrape_workers=1 is today's loop: one request after the other, in config order.
    assert serial_requests == [f"https://{h}/api/offers/" for h in _HOSTS]
    # Hosts on one provider's domain may run side by side (up to `PER_PROVIDER`), in any
    # order; each is still asked once, and the result above stays in config order.
    on_provider = [u for u in parallel_requests if ".recruitee.com" in u]
    assert sorted(on_provider) == ["https://x.recruitee.com/api/offers/", "https://y.recruitee.com/api/offers/"]


def test_hosts_of_a_feed_are_in_flight_together():
    import threading

    barrier = threading.Barrier(3, timeout=3)  # passes only if the three custom hosts overlap

    def meet(request):
        barrier.wait()
        return 200, {}, _offers_for(request.url.split("/")[2])

    with responses.RequestsMock() as rsps:
        for host in _HOSTS:
            if host.startswith("careers."):
                rsps.add_callback(responses.GET, f"https://{host}/api/offers/", callback=meet)
            else:
                rsps.add(responses.GET, f"https://{host}/api/offers/", body=_offers_for(host))
        postings = recruitee.scrape({"recruitee_companies": _ENTRIES, "scrape_workers": 3})

    assert len(postings) == 2 * len(_HOSTS)
