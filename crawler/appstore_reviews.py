"""Fetch Garmin Connect reviews from Apple's public App Store review feed.

Apple serves each country's most recent reviews (at most 10 pages of 50) as
JSON. Every run merges new reviews into a JSONL file keyed by review id, so
running it regularly builds up history across app versions.

    python -m crawler.appstore_reviews fetch --out data/appstore_reviews.jsonl
    python -m crawler.appstore_reviews export --src data/appstore_reviews.jsonl > data/corpus.txt

Reviewer names are not stored.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

from crawler.records import read_records, timestamp, validate_review, write_records

GARMIN_CONNECT_APP_ID = "583446403"
DEFAULT_COUNTRIES = ("us", "gb", "ca", "au", "nz", "ie")
MAX_PAGES = 10  # Apple never serves more than 10 pages per country.
FEED_URL = (
    "https://itunes.apple.com/{country}/rss/customerreviews/"
    "page={page}/id={app_id}/sortby=mostrecent/json"
)
# The feed returns empty pages for some countries unless the agent starts with
# "Mozilla/5.0"; the "(compatible; ...)" form still names this project.
USER_AGENT = "Mozilla/5.0 (compatible; release-impact-analyzer/0.1; CS410 course project, UIUC)"


def parse_feed(payload: dict, country: str) -> list[dict]:
    """Turns one feed page into review dicts."""
    entries = payload.get("feed", {}).get("entry", [])
    if isinstance(entries, dict):  # a lone entry is not wrapped in a list
        entries = [entries]

    reviews = []
    for entry in entries:
        if "im:rating" not in entry:  # older feeds lead with app metadata
            continue
        reviews.append(
            {
                "id": entry["id"]["label"],
                "country": country,
                "date": entry["updated"]["label"],
                "rating": int(entry["im:rating"]["label"]),
                "app_version": entry["im:version"]["label"],
                "title": entry["title"]["label"],
                "text": entry["content"]["label"],
            }
        )
    return reviews


def fetch_json(url: str, retries: int = 3, backoff: float = 2.0) -> dict:
    """GETs a JSON URL, retrying on rate limits, server errors and timeouts."""
    if type(retries) is not int or retries < 0:
        raise ValueError("retries must be a nonnegative integer")
    if not math.isfinite(backoff) or backoff < 0:
        raise ValueError("backoff must be finite and nonnegative")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as err:
            retryable = err.code == 429 or err.code >= 500
            if not retryable or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
        time.sleep(backoff * 2**attempt)
    raise AssertionError("unreachable")


def fetch_country(
    country: str, app_id: str = GARMIN_CONNECT_APP_ID, delay: float = 1.5
) -> Iterator[dict]:
    """Yields a country's reviews page by page until the feed runs out."""
    if not math.isfinite(delay) or delay < 0:
        raise ValueError("delay must be finite and nonnegative")
    for page in range(1, MAX_PAGES + 1):
        url = FEED_URL.format(country=country, page=page, app_id=app_id)
        reviews = parse_feed(fetch_json(url), country)
        if not reviews:
            return
        yield from reviews
        time.sleep(delay)  # stay polite between requests


def load_reviews(path: Path, *, missing_ok: bool = False) -> dict[str, dict]:
    return {r["id"]: r for r in read_records(path, validate_review, "id", missing_ok=missing_ok)}


def save_reviews(path: Path, reviews: dict[str, dict]) -> None:
    """Writes reviews oldest first, via a temp file so a crash never
    leaves a half-written dataset behind."""
    rows = sorted(reviews.values(), key=lambda r: (timestamp(r["date"]), r["id"]))
    write_records(path, rows, validate_review)


def to_corpus_line(review: dict) -> str:
    """Title and text on one line, as the C++ search CLI expects."""
    return " ".join(f"{review['title']}. {review['text']}".split())


def cmd_fetch(args: argparse.Namespace) -> None:
    if not math.isfinite(args.delay) or args.delay < 0:
        raise ValueError("delay must be finite and nonnegative")
    reviews = load_reviews(args.out, missing_ok=True)
    before = len(reviews)
    for country in args.countries:
        count = 0
        for review in fetch_country(country, args.app_id, args.delay):
            reviews[review["id"]] = review
            count += 1
        print(f"{country}: {count} reviews", file=sys.stderr)
    save_reviews(args.out, reviews)
    print(
        f"{len(reviews)} reviews in {args.out} ({len(reviews) - before} new)",
        file=sys.stderr,
    )


def cmd_export(args: argparse.Namespace) -> None:
    for review in load_reviews(args.src).values():
        print(to_corpus_line(review))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="download reviews and merge into a JSONL file")
    fetch.add_argument("--out", type=Path, default=Path("data/appstore_reviews.jsonl"))
    fetch.add_argument("--countries", nargs="+", default=list(DEFAULT_COUNTRIES))
    fetch.add_argument("--app-id", default=GARMIN_CONNECT_APP_ID)
    fetch.add_argument("--delay", type=float, default=1.5, help="seconds between requests")
    fetch.set_defaults(func=cmd_fetch)

    export = sub.add_parser("export", help="print one review per line for the search CLI")
    export.add_argument("--src", type=Path, default=Path("data/appstore_reviews.jsonl"))
    export.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
