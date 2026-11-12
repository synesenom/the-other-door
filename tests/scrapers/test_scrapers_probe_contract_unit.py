"""Every scraper exposes the side-effect-free `probe(config)` (issue #178)."""

import importlib
import socket

import pytest

from door.core.sites import ALL_SITES, SITES

_PROBE_KEYS = {"raw", "ext", "postings", "structure_ok"}


@pytest.fixture
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("probe touched the network without any configuration")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.mark.parametrize("site", ALL_SITES)
def test_probe_with_empty_config_is_none_or_a_probe_result_and_stays_offline(site, _no_network):
    module = importlib.import_module(SITES[site].module)
    result = module.probe({})
    assert result is None or _PROBE_KEYS <= set(result)
