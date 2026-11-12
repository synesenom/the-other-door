#!/usr/bin/env python3
"""How many logged-out LinkedIn search requests does THIS IP allow at a given pace?

Pages one keyword (default "Head of Data", Denmark, last 7 days) at ``--pace`` seconds between
requests until the first non-200 answer or ``--max`` requests, then prints the count and any
Retry-After. Run it from the machine that runs ``./door find``; it makes at most ``--max``
requests (150) and stops at the first refusal, without retrying.

    poetry run python scripts/probe_linkedin.py [--keyword K] [--location L] [--pace 3] [--max 150]
"""

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import requests  # noqa: E402

from door.scrapers.discovery import linkedin  # noqa: E402
from door.scrapers.http_client import USER_AGENT  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--keyword", default="Head of Data")
    ap.add_argument("--location", default="Denmark")
    ap.add_argument("--pace", type=float, default=3.0, help="seconds between requests (jittered +-30%%)")
    ap.add_argument("--max", type=int, default=150)
    args = ap.parse_args()
    http = requests.Session()
    http.headers["User-Agent"] = USER_AGENT
    started, cards, n = time.monotonic(), 0, 0
    # Page one keyword to its end, then start again: the point is the request count, not the cards.
    while n < args.max:
        for start in range(0, 1000, 10):
            if n >= args.max:
                break
            resp = http.get(linkedin._SEARCH_URL, params={
                "keywords": f'"{args.keyword}"', "location": args.location, "start": start,
                "sortBy": "DD", "f_TPR": "r604800"}, timeout=30)
            n += 1
            if resp.status_code != 200:
                print(f"HTTP {resp.status_code} on request {n} after {time.monotonic() - started:.0f} s "
                      f"(Retry-After: {resp.headers.get('Retry-After')}); {cards} cards read before it")
                return 1
            page = linkedin._parse_cards(resp.text)
            cards += len(page)
            if len(page) < 10:
                break
            time.sleep(random.uniform(args.pace * 0.7, args.pace * 1.3))
    print(f"no refusal in {n} requests, {time.monotonic() - started:.0f} s, {cards} cards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
