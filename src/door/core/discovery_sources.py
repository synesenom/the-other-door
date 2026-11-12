"""The discovery sources `discover` can read, and which of them a profile runs.

A source is a module (in `door/scrapers/discovery/`, importing `door` only through `door.scrapers.sdk`)
with ``NAME``, ``COUNTRIES`` (ISO 3166 codes it serves, lowercase; ``()`` = anywhere), ``CONFIG_KEY``
(a ``<source>_discovery`` bool in the profile; a source runs only once the user turned it on), ``VERDICT``
(``"unsure"``: its terms forbid automated access, see `door.core.sites.VERDICTS`), ``TERMS_URL`` and
``TERMS_SUMMARY`` (what the verdict rests on; the docstring quotes the terms in a "Terms" passage; the
disclaimer shown when the user turns it on is generated from them, `door.core.disclaimer`), ``run(config, **kwargs) -> DiscoveryResult``
(see `door.scrapers.sdk`), and the optional hooks ``enabled(config) -> reason | None`` (a further
reason to skip), ``extras(queue) -> dict`` (more keyword arguments for ``run``, read from the candidates
queue) and ``skip_employer(emp, state, now) -> str | None`` (a reason not to queue an employer).
`SOURCES` maps a name to its dotted module path and is read at call time, so a test can register another.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from door.core import disclaimer

SOURCES: dict[str, str] = {
    "linkedin": "door.scrapers.discovery.linkedin",
    "profession": "door.scrapers.discovery.profession",  # profession.hu, Hungary only
    "hellowork": "door.scrapers.discovery.hellowork",  # HelloWork, France only
    "jobbsafari": "door.scrapers.discovery.jobbsafari",  # Jobbsafari, Sweden only
}


def get(name: str) -> ModuleType:
    return importlib.import_module(SOURCES[name])


def _country_code(config: dict) -> str | None:
    from door import i18n

    pack = i18n.country_for_location(config.get("location") or "")
    return pack.code.lower() if pack is not None else None


def selected(config: dict) -> list[tuple[str, ModuleType, str | None]]:
    """Every registered source with the reason it does not run for *config* (None = it runs):
    ``"not for <cc>"`` (the profile's country is not one it serves; a source with countries needs a
    known one), ``"<key> not chosen"`` (the key is not set: the user was never asked, or did not
    answer), ``"<key> is off"``, or the module's own ``enabled`` reason."""
    code = _country_code(config)
    out = []
    for name in list(SOURCES):
        module = get(name)
        reason = None
        if module.COUNTRIES and code not in module.COUNTRIES:
            reason = f"not for {code}" if code else "not for an unknown country"
        elif config.get(module.CONFIG_KEY) is None:
            reason = f"{module.CONFIG_KEY} not chosen"
        elif not config[module.CONFIG_KEY]:
            reason = f"{module.CONFIG_KEY} is off"
        elif hasattr(module, "enabled"):
            reason = module.enabled(config)
        out.append((name, module, reason))
    return out


def info(name: str) -> dict:
    """One source in words: ``{"name", "key", "label", "verdict", "terms_url", "terms_summary", "disclaimer"}``,
    the disclaimer being the text every surface shows when the user turns it on."""
    module = get(name)
    label = getattr(module, "LABEL", name)
    return {
        "name": name, "key": module.CONFIG_KEY, "label": label, "verdict": module.VERDICT,
        "terms_url": module.TERMS_URL, "terms_summary": module.TERMS_SUMMARY,
        "disclaimer": disclaimer.text(label, module.TERMS_SUMMARY, module.TERMS_URL),
    }


def for_location(location: str) -> list[dict]:
    """The sources serving *location*'s country (the worldwide ones for a city in no known country),
    in registry order: their `info` each, what onboarding asks about."""
    code = _country_code({"location": location})
    out = []
    for name in list(SOURCES):
        module = get(name)
        if not module.COUNTRIES or code in module.COUNTRIES:
            out.append(info(name))
    return out


def unchosen(config: dict) -> list[dict]:
    """The sources serving *config*'s location whose key is not set: never asked, so not run."""
    return [s for s in for_location(config.get("location") or "") if config.get(s["key"]) is None]


def off_for_location(config: dict) -> list[dict]:
    """The sources serving *config*'s location that are not turned on (key unset or false)."""
    return [s for s in for_location(config.get("location") or "") if config.get(s["key"]) is not True]


def on(config: dict) -> list[dict]:
    """The `unsure` sources serving *config*'s location that the user turned on: what `doctor` and the run
    summary keep visible."""
    return [s for s in for_location(config.get("location") or "") if s["verdict"] == "unsure" and config.get(s["key"]) is True]
