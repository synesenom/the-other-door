"""Time zones resolve without the system's database (#33: Windows has none, and a board that names
Europe/Stockholm at import crashed `find` there): the `tzdata` package carries them."""

import zoneinfo


def test_a_zone_resolves_with_no_system_database():
    zoneinfo.reset_tzpath(to=[])
    zoneinfo.ZoneInfo.clear_cache()
    try:
        assert zoneinfo.ZoneInfo("Europe/Stockholm").key == "Europe/Stockholm"
    finally:
        zoneinfo.reset_tzpath()
        zoneinfo.ZoneInfo.clear_cache()
