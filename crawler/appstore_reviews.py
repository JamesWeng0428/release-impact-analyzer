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
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

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
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as err:
            retryable = err.code == 429 or err.code >= 500
            if not retryable or attempt == retries:
                raise
        except urllib.error.URLError:
            if attempt == retries:
                raise
        time.sleep(backoff * 2**attempt)
    raise AssertionError("unreachable")


def fetch_country(
    country: str, app_id: str = GARMIN_CONNECT_APP_ID, delay: float = 1.5
) -> Iterator[dict]:
    """Yields a country's reviews page by page until the feed runs out."""
    for page in range(1, MAX_PAGES + 1):
        url = FEED_URL.format(country=country, page=page, app_id=app_id)
        reviews = parse_feed(fetch_json(url), country)
        if not reviews:
            return
        yield from reviews
        time.sleep(delay)  # stay polite between requests


def load_reviews(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {r["id"]: r for r in map(json.loads, f) if r}


def save_reviews(path: Path, reviews: dict[str, dict]) -> None:
    """Writes reviews oldest first, via a temp file so a crash never
    leaves a half-written dataset behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for review in sorted(reviews.values(), key=lambda r: (r["date"], r["id"])):
            f.write(json.dumps(review, ensure_ascii=False) + "\n")
    tmp.replace(path)


def to_corpus_line(review: dict) -> str:
    """Title and text on one line, as the C++ search CLI expects."""
    return " ".join(f"{review['title']}. {review['text']}".split())


def cmd_fetch(args: argparse.Namespace) -> None:
    reviews = load_reviews(args.out)
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
    args.func(args)


if __name__ == "__main__":
    main()
